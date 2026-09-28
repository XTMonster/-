"""§7.4 控制工具：request_self_review / finish_shot / abort。"""

from __future__ import annotations

import json

from block_director.contracts.audit import AuditError, AuditResult
from block_director.contracts.enums import Severity
from block_director.layer5_orchestrator.control_tools import (
    ABORT,
    CONTROL_TOOL_NAMES,
    FINISH_SHOT,
    REQUEST_SELF_REVIEW,
    register_control_tools,
)
from block_director.layer5_orchestrator.driver import DriverLimits, PrevisDriver, default_registry
from block_director.layer5_orchestrator.offline import OfflineTransport
from block_director.layer5_orchestrator.planner import PLAN_TOOL_NAME
from block_director.layer5_orchestrator.states import DriverState
from block_director.layer5_orchestrator.tool_registry import ToolRegistry
from block_director.layer6_audit.audit_logger import AuditLogger
from block_director.contracts.messages import ChatReply, FunctionCall, ToolCall

SCRIPT = "INT. 咖啡馆 - 日\n\n小明坐下。\n"


class InlineThread:
    def __init__(self, target, name=""):
        self._target = target

    def start(self):
        self._target()


class ScriptedTransport:
    """按脚本返回工具调用（用于精确制造控制工具的调用时机）。"""

    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = 0

    def chat(self, payload, timeout=120.0):
        self.calls += 1
        item = self._replies[min(self.calls - 1, len(self._replies) - 1)]
        call = ToolCall(id=f"c{self.calls}",
                        function=FunctionCall(name=item[0],
                                              arguments=json.dumps(item[1])))
        return ChatReply(tool_calls=[call])

    def cancel(self, request_id):
        return None


class StubAuditor:
    """总是判失败的审核器：用来验证 finish_shot 会跳过修复循环。"""

    def __init__(self):
        self.audited = []

    def shot_ids(self):
        return ["shot_001", "shot_002"]

    def audit(self, shot_id):
        self.audited.append(shot_id)
        return AuditResult(passed=False, target=shot_id, errors=[
            AuditError(rule="R001", code="E_AXIS_001", message="越轴",
                       severity=Severity.ERROR, target=shot_id,
                       suggestion="挪到同侧")])


class StubBuilder:
    """满足 §4 的构建器协议：有 ``build(plan)``。"""

    def __init__(self):
        self.built = 0

    def build(self, plan):
        self.built += 1
        return {"shots": len(plan.shots)}


def make_driver(transport, **kwargs):
    return PrevisDriver(transport=transport, audit=AuditLogger(), script=SCRIPT,
                        thread_factory=InlineThread, **kwargs)


# --------------------------------------------------------------------------- #
# 注册与校验
# --------------------------------------------------------------------------- #
def test_control_tools_are_registered_with_schemas():
    registry = default_registry()
    for name in CONTROL_TOOL_NAMES:
        assert name in registry.names(), name
        assert registry.get(name).parameters.get("type") == "object"


def test_registration_is_idempotent():
    registry = ToolRegistry()
    register_control_tools(registry)
    register_control_tools(registry)
    assert set(CONTROL_TOOL_NAMES) <= set(registry.names())


def test_abort_requires_a_reason():
    registry = default_registry()
    result = registry.execute(ABORT, {})
    assert not result.ok and "参数校验失败" in result.content


def test_unknown_arguments_are_rejected():
    registry = default_registry()
    result = registry.execute(FINISH_SHOT, {"nope": 1})
    assert not result.ok and "参数校验失败" in result.content


# --------------------------------------------------------------------------- #
# abort：运行以 CANCELLED 结束，且不是"成功"
# --------------------------------------------------------------------------- #
def test_abort_stops_the_run_and_is_not_success():
    transport = ScriptedTransport([(ABORT, {"reason": "剧本不适合白模"})])
    driver = make_driver(transport)
    state = driver.run_to_completion()
    snapshot = driver.snapshot()
    assert state is DriverState.CANCELLED
    assert snapshot["abort_reason"] == "剧本不适合白模"
    assert any(event.kind == "run_aborted"
               for event in driver.audit.recent(50))


def test_abort_keeps_the_scene_and_stops_further_calls():
    transport = ScriptedTransport([(ABORT, {"reason": "停"})])
    driver = make_driver(transport)
    driver.run_to_completion()
    assert transport.calls == 1          # 放弃之后不再请求模型


# --------------------------------------------------------------------------- #
# finish_shot：跳过修复循环，但审核结论仍然落盘
# --------------------------------------------------------------------------- #
def test_finish_shot_skips_the_repair_loop():
    auditor = StubAuditor()
    transport = ScriptedTransport([
        (PLAN_TOOL_NAME, {"shots": [{"shot_id": "shot_001", "order": 1,
                                     "intent": "x", "shot_type": "MS",
                                     "duration_frames": 24}]}),
        (FINISH_SHOT, {"summary": "就这样"}),
    ])
    driver = make_driver(transport, builder=StubBuilder(),
                         auditor=auditor,
                         limits=DriverLimits(max_repairs_per_shot=2))
    state = driver.run_to_completion()

    kinds = [event.kind for event in driver.audit.recent(80)]
    assert state is DriverState.DONE
    assert driver.finish_history[0]["summary"] == "就这样"
    # 审核**每次都不通过**，但两镜都在模型声明完成之后前进：
    # 每镜被审两次（初次 + 声明完成后的复核），而不是一路修到上限。
    assert auditor.audited == ["shot_001", "shot_001",
                               "shot_002", "shot_002"]
    assert len(driver.finish_history) == 2
    assert "shot_finished_with_errors" in kinds
    assert transport.calls == 3          # 计划 1 次 + 两镜各一次往返


def test_finish_shot_without_a_current_shot_is_refused():
    driver = make_driver(ScriptedTransport([(FINISH_SHOT, {})]),
                         limits=DriverLimits(plan_attempts=1))
    driver.run_to_completion()
    assert driver.finish_history == []
    assert any(event.kind == "plan_invalid" for event in driver.audit.recent(40))


# --------------------------------------------------------------------------- #
# request_self_review：登记请求，由驱动器执行
# --------------------------------------------------------------------------- #
def test_request_self_review_registers_without_an_extra_call():
    transport = ScriptedTransport([
        (PLAN_TOOL_NAME, {"shots": [{"shot_id": "shot_001", "order": 1,
                                     "intent": "x", "shot_type": "MS",
                                     "duration_frames": 24}]}),
        (REQUEST_SELF_REVIEW, {"shot_intent": "是否表达了迟疑"}),
    ])
    driver = make_driver(transport, builder=StubBuilder())
    driver._current_shot_id = "shot_001"      # 模拟"正在处理这一镜"
    driver._dispatch_tool_calls(ChatReply(tool_calls=[
        ToolCall(id="c", function=FunctionCall(
            name=REQUEST_SELF_REVIEW,
            arguments=json.dumps({"shot_id": "shot_001",
                                  "shot_intent": "是否表达了迟疑"}))) ]))
    assert driver._pending_review == "shot_001"
    assert driver.review_requests[0]["intent"] == "是否表达了迟疑"
    assert any(event.kind == "self_review_requested"
               for event in driver.audit.recent(20))


def test_request_self_review_without_a_shot_is_reported():
    driver = make_driver(ScriptedTransport([(REQUEST_SELF_REVIEW, {})]))
    driver._dispatch_tool_calls(ChatReply(tool_calls=[
        ToolCall(id="c", function=FunctionCall(
            name=REQUEST_SELF_REVIEW, arguments="{}")) ]))
    assert driver.review_requests == []


def test_snapshot_exposes_the_control_state():
    driver = make_driver(ScriptedTransport([(ABORT, {"reason": "停"})]))
    driver.run_to_completion()
    snapshot = driver.snapshot()
    assert {"abort_reason", "finished_shots", "review_requests"} <= set(snapshot)
