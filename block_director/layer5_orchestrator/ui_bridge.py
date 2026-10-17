"""UI 事件桥（v1.7 TDD §2.2，卡 D1）。

把 driver 的 ``DriverEvent`` 观察流翻成 ``UIEvent``，经后台 daemon 线程
POST 给 sidecar（``/v1/ui/events``）。发送**绝不阻塞状态机**：observer 在
driver 线程里只入队；网络与重试都在后台线程做，失败/超时静默计数
（R-UI-2），进程退出前 ``flush`` 尽力清空。

纯层约束：本模块不得 import bpy（与 driver 同层，只依赖 contracts）。
"""

from __future__ import annotations

import json
import queue
import threading
import time
import urllib.request
from typing import Callable, Optional

from ..contracts.ui_events import UIEvent
from ..utils.logger import get_logger

log = get_logger("ui_bridge")


class UIBridge:
    """事件队列 ＋ 后台发送线程。

    ``enabled=False`` 时 ``enqueue`` 直接 no-op（零线程、零网络）。
    """

    def __init__(self, url: str, token: str, enabled: bool = True,
                 timeout: float = 0.5) -> None:
        self.url = str(url).rstrip("/")
        self.token = str(token)
        self.enabled = bool(enabled)
        self.timeout = float(timeout)
        self._queue: "queue.Queue[Optional[UIEvent]]" = queue.Queue()
        self._seq = 0
        self._seq_lock = threading.Lock()
        self.dropped_events = 0
        self._started = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------ 启动/收尾
    def _ensure_started(self) -> None:
        """惰性启动后台 daemon 线程（进程退出不阻塞）。"""
        if self._started or not self.enabled:
            return
        with self._lock:
            if self._started or not self.enabled:
                return
            thread = threading.Thread(target=self._sender_loop, daemon=True,
                                      name="bd-ui-bridge")
            self._started = True
            thread.start()

    def _sender_loop(self) -> None:
        """后台循环：取事件 → POST；失败/超时计数。退出哨兵是 None。"""
        while True:
            event = self._queue.get()
            if event is None:
                self._queue.task_done()
                return
            try:
                self._post(event)
            except Exception as exc:  # noqa: BLE001 - R-UI-2 静默计数
                self.dropped_events += 1
                log.debug("UI 事件投递失败: %s", exc)
            finally:
                self._queue.task_done()

    def _post(self, event: UIEvent) -> None:
        """单条事件 POST 到 sidecar（后台线程调用）。"""
        request = urllib.request.Request(
            f"{self.url}/v1/ui/events",
            data=json.dumps(event.to_dict()).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            if response.status != 200:
                raise RuntimeError(f"sidecar 返回 {response.status}")

    def flush(self, timeout: float = 1.0) -> None:
        """进程退出前 best-effort 清空队列（join，超时放弃）。"""
        if not self._started:
            return
        try:
            self._queue.join()
        except Exception:  # noqa: BLE001 - flush 失败不阻断退出
            return

    # ------------------------------------------------------------ 生产者
    def enqueue(self, event: UIEvent) -> None:
        """入队（driver 线程调用，只入队不触网）。"""
        if not self.enabled:
            return
        self._ensure_started()
        with self._seq_lock:
            self._seq += 1
            event.seq = self._seq
        self._queue.put(event)


def make_observer(bridge: UIBridge) -> Callable:
    """把 driver 观察者回调包成"翻成 UIEvent 入队"。

    DriverEvent.kind 映射（卡定义钉死）：
    - state → state_change（state 必填）
    - shot_audit / shot_finished_with_errors / shot_degraded → shot_progress
    - tool_call / self_review / repair_turn → llm_call
    - run_started / run_finished / run_failed → state（对应态）；run_failed 另发 error
    - 其余 → audit 摘要
    payload 只带摘要（shot_id/计数/状态），**不带** prompt/key/message 全文。
    """

    def observer(driver_event) -> None:
        kind = _map_kind(driver_event.kind)
        state = ""
        shot_id = ""
        payload: dict = {}
        if driver_event.kind == "state" or driver_event.kind in (
                "run_started", "run_finished", "run_failed"):
            state = _state_value(driver_event)
            payload = {"message": _truncate(driver_event.message)}
        elif driver_event.kind in ("shot_audit", "shot_finished_with_errors",
                                   "shot_degraded"):
            shot_id = str(driver_event.data.get("shot", "") or "")
            payload = {
                "passed": bool(driver_event.data.get("passed", False)),
                "message": _truncate(driver_event.message),
            }
        elif driver_event.kind in ("tool_call", "self_review", "repair_turn"):
            shot_id = str(driver_event.data.get("shot", "") or "")
            payload = {
                "tool": str(driver_event.data.get("tool", "") or ""),
                "ok": bool(driver_event.data.get("ok", False)),
                "message": _truncate(driver_event.message),
            }
        else:
            shot_id = str(driver_event.data.get("shot", "") or "")
            payload = {"message": _truncate(driver_event.message)}

        if driver_event.kind == "run_failed":
            # 失败另发一条 error 事件（卡定义）。
            bridge.enqueue(UIEvent(seq=0, ts=time.time(), kind="error",
                                   state=state, shot_id=shot_id,
                                   payload={"message": _truncate(driver_event.message)}))
        bridge.enqueue(UIEvent(seq=0, ts=time.time(), kind=kind,
                               state=state, shot_id=shot_id,
                               payload=payload))

    return observer


def _map_kind(kind: str) -> str:
    if kind == "state":
        return "state_change"
    if kind in ("shot_audit", "shot_finished_with_errors", "shot_degraded"):
        return "shot_progress"
    if kind in ("tool_call", "self_review", "repair_turn"):
        return "llm_call"
    if kind in ("run_started", "run_finished", "run_failed"):
        return "state_change"
    return "audit"


def _state_value(driver_event) -> str:
    state = getattr(driver_event, "state", None)
    if state is None:
        return ""
    value = getattr(state, "value", state)
    return str(value)


def _truncate(message: str, limit: int = 120) -> str:
    text = str(message or "")
    return text[:limit] + ("…" if len(text) > limit else "")
