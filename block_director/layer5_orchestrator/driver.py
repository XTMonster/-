"""预演驱动器：与 Blender 解耦的状态机（执行文档 v1.2 §3.2 / §3.3）。

设计红线：
- 本模块 **不得 import bpy**（§2.4）。它只编排，不碰场景。
- ``step()`` 每次只做一件小事并立即返回，绝不阻塞（LLM 调用在后台线程）。
- ``step()`` 必须在主线程调用（用 threading_guard 强制），因为它接下来会
  调用触碰 bpy 的工具。
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ..contracts.enums import Purpose
from ..contracts.messages import (
    ChatPayload,
    ChatReply,
    Message,
    assistant_message,
    new_request_id,
    tool_message,
    validate_conversation,
)
from ..contracts.plan import Plan
from ..layer6_audit.audit_logger import AuditLogger
from ..utils.logger import get_logger
from ..utils.threading_guard import assert_main_thread
from .planner import EMIT_PLAN_TOOL_PARAMETERS, PLAN_TOOL_NAME, build_plan_payload
from .states import TERMINAL_STATES, DriverState
from .tool_registry import ToolRegistry

log = get_logger("driver")


@dataclass
class DriverLimits:
    """运行护栏（§12.6）。"""

    max_steps: int = 4000
    max_llm_calls: int = 8
    llm_timeout_s: float = 120.0
    plan_attempts: int = 2
    max_tool_calls: int = 200


@dataclass
class DriverEvent:
    """给 UI / 日志的事件。"""

    kind: str
    message: str
    state: DriverState
    data: Dict[str, Any] = field(default_factory=dict)


def default_registry() -> ToolRegistry:
    """Phase 0 的最小工具集：只有阶段 A 的 emit_plan。"""
    registry = ToolRegistry()
    registry.add(
        name=PLAN_TOOL_NAME,
        description="提交白模预演的分镜计划（阶段 A 的唯一合法产出）",
        parameters=EMIT_PLAN_TOOL_PARAMETERS,
        handler=lambda **kwargs: f"计划已接收：{len(kwargs.get('shots', []))} 个镜头",
    )
    return registry


def _default_thread_factory(target: Callable[[], None],
                            name: str) -> threading.Thread:
    return threading.Thread(target=target, daemon=True, name=name)


class PrevisDriver:
    """一次预演生成运行的状态机。"""

    def __init__(
        self,
        *,
        transport,
        audit: AuditLogger,
        script: str = "",
        config=None,
        limits: Optional[DriverLimits] = None,
        registry: Optional[ToolRegistry] = None,
        observers: Optional[List[Callable[[DriverEvent], None]]] = None,
        clock: Callable[[], float] = time.monotonic,
        thread_factory: Callable[..., Any] = _default_thread_factory,
    ) -> None:
        self.transport = transport
        self.audit = audit
        self.script = script
        self.config = config
        self.limits = limits or DriverLimits()
        self.registry = registry or default_registry()
        self.clock = clock
        self.thread_factory = thread_factory

        self.state = DriverState.IDLE
        self.plan: Optional[Plan] = None
        self.error: str = ""
        self.messages: List[Message] = []

        self._observers: List[Callable[[DriverEvent], None]] = list(observers or [])
        self._steps = 0
        self._llm_calls = 0
        self._tool_calls = 0
        self._plan_attempts = 0
        self._reply_q: "queue.Queue[tuple]" = queue.Queue()
        self._cancel = threading.Event()
        self._call_started = 0.0
        self._pending_request_id = ""
        self._plan_problem = ""

    # ------------------------------------------------------------ 对外接口
    def add_observer(self, observer: Callable[[DriverEvent], None]) -> None:
        self._observers.append(observer)

    def cancel(self) -> None:
        """请求取消（协作式，§3.4）：不杀线程，只置标志并尽力通知对端。"""
        self._cancel.set()
        if self._pending_request_id:
            try:
                self.transport.cancel(self._pending_request_id)
            except Exception as exc:  # noqa: BLE001 - 取消失败不阻断
                log.debug("取消请求失败: %s", exc)

    @property
    def finished(self) -> bool:
        return self.state in TERMINAL_STATES

    def snapshot(self) -> Dict[str, Any]:
        """给 UI 的只读快照。"""
        return {
            "run_id": self.audit.run_id,
            "state": self.state.value,
            "steps": self._steps,
            "llm_calls": self._llm_calls,
            "tool_calls": self._tool_calls,
            "shots": len(self.plan.shots) if self.plan else 0,
            "total_frames": self.plan.total_frames if self.plan else 0,
            "error": self.error,
        }

    # ------------------------------------------------------------ 状态机
    def step(self) -> bool:
        """推进一小步；返回 False 表示运行已终止。"""
        assert_main_thread("PrevisDriver.step")
        if self.state in TERMINAL_STATES:
            return False

        self._steps += 1
        if self._steps > self.limits.max_steps:
            self._fail("超出最大步数（疑似死循环）")
            return False
        if self._cancel.is_set() and self.state is not DriverState.CANCELLED:
            self._transition(DriverState.CANCELLED)
            self.audit.log("run_cancelled", "运行已取消", level="warning")
            return False

        handler = getattr(self, f"_step_{self.state.value.lower()}")
        handler()
        return self.state not in TERMINAL_STATES

    def run_to_completion(self, poll_interval: float = 0.0,
                          max_wall_s: Optional[float] = None) -> DriverState:
        """headless 用：同步把状态机推到终止。"""
        started = self.clock()
        while self.step():
            if max_wall_s is not None and self.clock() - started > max_wall_s:
                self._fail(f"超出墙上时间上限 {max_wall_s}s")
                break
            if poll_interval and self.state is DriverState.CALLING_LLM:
                time.sleep(poll_interval)
        return self.state

    # ------------------------------------------------------------ 各状态
    def _step_idle(self) -> None:
        self.audit.log("run_started", "开始白模预演生成",
                       transport=type(self.transport).__name__,
                       registry=self.registry.names())
        self._emit("run_started", "开始")
        self._transition(DriverState.PLANNING)

    def _step_planning(self) -> None:
        if self._llm_calls >= self.limits.max_llm_calls:
            self._fail("LLM 调用预算耗尽")
            return
        if self._plan_attempts >= self.limits.plan_attempts:
            detail = f"：{self._plan_problem}" if self._plan_problem else ""
            self._fail(f"分镜计划生成失败（已达最大尝试次数）{detail}")
            return
        self._plan_attempts += 1
        self._start_plan_call()

    def _step_calling_llm(self) -> None:
        try:
            kind, payload = self._reply_q.get_nowait()
        except queue.Empty:
            return                                  # 仍在等待，下一 tick 再看
        duration = self.clock() - self._call_started

        if kind == "err":
            self.audit.log("llm_error", str(payload), level="error",
                           request_id=self._pending_request_id)
            self.audit.log_llm(str(Purpose.PLAN), None, duration,
                               self._pending_request_id, error=str(payload))
            self._transition(DriverState.PLANNING)   # 由 _step_planning 决定是否再试
            return

        reply: ChatReply = payload
        self.audit.log_llm(str(Purpose.PLAN), reply, duration,
                           self._pending_request_id)

        problem = self._dispatch_tool_calls(reply)
        if problem:
            self._plan_problem = problem
            self.audit.log("plan_invalid", problem, level="error")
            self._transition(DriverState.PLANNING)
            return
        self._transition(DriverState.FINISHING)

    def _step_finishing(self) -> None:
        plan = self.plan or Plan()
        # 会话结构自检（§3.4）：失败只告警，不阻断收尾
        problems = validate_conversation(self.messages)
        if problems:
            self.audit.log("conversation_invalid", "；".join(problems), level="warning")
        else:
            self.audit.log("conversation_ok",
                           f"{len(self.messages)} 条消息结构合法（§3.4）")
        self._transition(DriverState.DONE)
        self.audit.log("plan_received",
                       f"分镜计划完成：{len(plan.shots)} 个镜头",
                       shots=[shot.to_dict() for shot in plan.shots],
                       total_frames=plan.total_frames)
        self.audit.log("run_finished", "预演生成结束",
                       shots=len(plan.shots), llm_calls=self._llm_calls,
                       tool_calls=self._tool_calls, steps=self._steps)
        self._emit("run_finished", f"完成，共 {len(plan.shots)} 个镜头")

    # ------------------------------------------------------------ 内部
    def _start_plan_call(self) -> None:
        request_id = new_request_id()
        self._pending_request_id = request_id
        payload: ChatPayload = build_plan_payload(self.script, self.config,
                                                  request_id=request_id)
        self._llm_calls += 1
        self._call_started = self.clock()
        self.audit.log("llm_request", f"请求分镜计划（第 {self._plan_attempts} 次尝试）",
                       purpose=str(Purpose.PLAN), request_id=request_id,
                       tools=[tool["function"]["name"] for tool in payload.tools])
        self._transition(DriverState.CALLING_LLM)

        def worker() -> None:
            # 后台线程：只做网络 I/O，绝不触碰 bpy
            try:
                reply = self.transport.chat(payload, self.limits.llm_timeout_s)
                self._reply_q.put(("ok", reply))
            except Exception as exc:  # noqa: BLE001
                self._reply_q.put(("err", f"{type(exc).__name__}: {exc}"))

        self.thread_factory(target=worker, name="bd-llm").start()

    def _dispatch_tool_calls(self, reply: ChatReply) -> str:
        """执行回复里的工具调用；返回非空字符串表示本轮失败原因。"""
        self.messages.append(assistant_message(reply))
        if not reply.tool_calls:
            return f"回复中没有工具调用（期望 {PLAN_TOOL_NAME}）"

        errors: List[str] = []
        plan_seen = False
        for call in reply.tool_calls:
            if self._tool_calls >= self.limits.max_tool_calls:
                errors.append("工具调用次数超限")
                break
            try:
                args = call.function.parsed_arguments()
            except ValueError as exc:
                errors.append(str(exc))
                continue

            result = self.registry.execute(call.function.name, args)
            self._tool_calls += 1
            self.audit.count_tool_call()
            self.audit.log("tool_call",
                           f"{call.function.name} -> {'ok' if result.ok else result.error}",
                           tool=call.function.name, ok=result.ok, args=args)
            self.messages.append(tool_message(call, result.content))
            self._emit("tool_call", f"{call.function.name}",
                       tool=call.function.name, ok=result.ok)

            if not result.ok:
                errors.append(f"{call.function.name}: {result.content}")
                continue
            if call.function.name == PLAN_TOOL_NAME:
                try:
                    self.plan = Plan.from_dict(args)
                    plan_seen = True
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"计划解析失败: {exc}")

        if errors:
            return "；".join(errors)
        if not plan_seen:
            return f"没有收到 {PLAN_TOOL_NAME} 调用"
        return ""

    def _transition(self, new_state: DriverState) -> None:
        old = self.state
        if old is new_state:
            return
        self.state = new_state
        self.audit.log("state", f"{old.value} → {new_state.value}")
        self._emit("state", f"{old.value} → {new_state.value}", state=new_state)

    def _fail(self, message: str) -> None:
        self.error = message
        self.audit.log("run_failed", message, level="error",
                       llm_calls=self._llm_calls, tool_calls=self._tool_calls)
        self._emit("run_failed", message)
        self._transition(DriverState.ERROR)

    def _emit(self, kind: str, message: str, **data: Any) -> None:
        if not self._observers:
            return
        event = DriverEvent(kind=kind, message=message, state=self.state,
                            data=dict(data))
        for observer in self._observers:
            try:
                observer(event)
            except Exception as exc:  # noqa: BLE001 - 观察者出错不影响主流程
                log.error("观察者回调失败: %s", exc)
