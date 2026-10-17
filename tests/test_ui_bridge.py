"""卡 D1：ui_bridge 事件推送（v1.7 TDD §2.2）。

四个测试对应卡定义清单：
- offline 链（ui.enabled=false）零异常；
- 目标端口不通时 dropped_events 计数且不抛；
- stdlib fake server 收到三类事件（state_change/shot_progress/llm_call）；
- observer 只入队不触网（驱动线程内零 urlopen）。
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from block_director.contracts.ui_events import UIEvent
from block_director.layer5_orchestrator.driver import DriverEvent
from block_director.layer5_orchestrator.states import DriverState
from block_director.layer5_orchestrator.ui_bridge import UIBridge, make_observer


def _driver_event(kind="state", message="m", state=None, **data):
    return DriverEvent(kind=kind, message=message,
                       state=state or DriverState.IDLE, data=dict(data))


def test_offline_chain_no_exception():
    """enabled=false 时 enqueue 直接 no-op，不建线程、不触网。"""
    bridge = UIBridge(url="http://127.0.0.1:9", token="dev-token",
                      enabled=False)
    bridge.enqueue(UIEvent(seq=1, ts=time.time(), kind="state_change",
                           state="PLANNING"))
    assert bridge.dropped_events == 0
    assert not bridge._started


def test_dropped_events_counted():
    """目标端口不通：后台线程计数不抛，等待 flush 后 dropped_events > 0。"""
    bridge = UIBridge(url="http://127.0.0.1:9", token="dev-token",
                      enabled=True, timeout=0.1)
    observer = make_observer(bridge)
    observer(_driver_event(kind="state", state=DriverState.PLANNING))
    bridge.flush(timeout=2.0)
    assert bridge.dropped_events > 0


def test_fake_server_receives():
    """stdlib fake server 收到三类事件（state_change/shot_progress/llm_call）。"""
    received: list = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):                     # noqa: N802 - http.server 接口
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length))
            received.append({"path": self.path, "body": payload})
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):          # 测试静默
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        bridge = UIBridge(
            url=f"http://127.0.0.1:{server.server_port}",
            token="dev-token", enabled=True, timeout=0.5)
        observer = make_observer(bridge)
        observer(_driver_event(kind="state", state=DriverState.PLANNING))
        observer(_driver_event(kind="shot_audit", message="s1 通过",
                               shot="s1", passed=True))
        observer(_driver_event(kind="tool_call", message="emit_plan",
                               tool="emit_plan", ok=True))
        bridge.flush(timeout=3.0)
    finally:
        server.shutdown()

    assert len(received) == 3
    kinds = {item["body"]["kind"] for item in received}
    assert kinds == {"state_change", "shot_progress", "llm_call"}
    assert all(item["path"] == "/v1/ui/events" for item in received)
    state_events = [item for item in received
                    if item["body"]["kind"] == "state_change"]
    assert state_events
    assert all(item["body"]["state"] == "PLANNING" for item in state_events)
    assert all(item["body"]["shot_id"] == "s1"
               for item in received
               if item["body"]["kind"] == "shot_progress")


def test_observer_never_blocks():
    """observer 只入队不触网：驱动线程内零 urlopen。"""
    import urllib.request

    real_urlopen = urllib.request.urlopen
    calls = []

    def fake_urlopen(*args, **kwargs):
        calls.append(args)
        raise AssertionError("observer 不应发起网络请求")

    bridge = UIBridge(url="http://127.0.0.1:9", token="dev-token",
                      enabled=True, timeout=0.01)
    try:
        urllib.request.urlopen = fake_urlopen
        observer = make_observer(bridge)
        observer(_driver_event(kind="state", state=DriverState.PLANNING))
    finally:
        urllib.request.urlopen = real_urlopen
    assert calls == []
    assert bridge.dropped_events == 0
