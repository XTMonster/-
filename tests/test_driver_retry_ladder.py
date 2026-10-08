"""v1.6 F1（D-02）：超时重试阶梯接到驱动器（repair / react / plan）。

纯状态机（``tests/test_retry_ladder.py``）只管"下一步怎么走"，这里钉住的是
驱动器把决定变成真实行为的四条线（TDD §4.5）：

* repair 超时 → 第二次用瘦身包（去 RAG 三栏、留该镜声明与审计发现）→
  再超时 → 该镜 ``shot_degraded``，**绝无第三次调用**；
* repair 非超时错误 → 原样重试一次；重试成功则流程照常走完；
* react 超时 → 同样阶梯；降级 = 结束本次精修、该镜以降级收尾；
* plan 超时 → 重试计入既有 ``plan_attempts`` 预算，完整提示绝不原样发第三次；
* 每一步都记 ``retry_ladder`` 事件（stage / shot_id / elapsed_s 三键齐备）。
"""

from __future__ import annotations

import json

from block_director.contracts.audit import (
    AuditError,
    AuditResult,
    missing_event_fields,
)
from block_director.contracts.enums import Purpose, Severity
from block_director.contracts.messages import ChatReply, FunctionCall, ToolCall
from block_director.layer5_orchestrator.context_budget import SLIM_PLACEHOLDER
from block_director.layer5_orchestrator.driver import DriverLimits, PrevisDriver
from block_director.layer5_orchestrator.offline import demo_draft_dict, demo_plan_dict
from block_director.layer5_orchestrator.planner import EMIT_PLAN_TOOL_PARAMETERS
from block_director.layer5_orchestrator.states import DriverState
from block_director.layer5_orchestrator.tool_registry import ToolRegistry
from block_director.layer6_audit.audit_logger import AuditLogger

from stage_helpers import is_understand, understand_reply
from test_driver import InlineThread
from test_driver_repair import FakeAuditor, TrivialBuilder

SCRIPT = "INT. 咖啡馆 - 日\n\n小明坐下。\n"

#: 与 `tests/test_retry_ladder.py::KNOWLEDGE` 同一组三栏标题；只有这几个标题
#: 会被瘦身包认出来，别的【…】一律原样保留。
KNOWLEDGE_COLUMNS = (
    "【硬约束（禁/许）】\n- 禁 CU 于建立镜\n- 许 MLS\n"
    "【经验建议（软）】\n- 若对话则正反打\n"
    "【参考案例（仅参考）】\n- 案例 A\n\n"
)
SCENE_STATE_WITH_KNOWLEDGE = KNOWLEDGE_COLUMNS + "小明在桌边，相机朝北。"


def axis_finding() -> AuditError:
    return AuditError(rule="R001", code="E_AXIS_001", severity=Severity.ERROR,
                      target="shot_001",
                      message="相机位置违反 180° 轴线规则。",
                      suggestion="将相机移到轴线另一侧。")


def composition_result() -> AuditResult:
    return AuditResult(passed=False, target="shot_001", score=55.0, errors=[
        AuditError(rule="COMPOSITION", code="E_CAM_001",
                   message="构图评分 55.0 低于阈值 70",
                   severity=Severity.ERROR, target="shot_001",
                   suggestion="重新构图")])


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.add(name="emit_plan", description="plan",
                 parameters=EMIT_PLAN_TOOL_PARAMETERS,
                 handler=lambda **kwargs: "计划已接收")
    registry.add(name="setup_camera", description="fix",
                 parameters={"type": "object", "properties": {}},
                 handler=lambda: "相机已重设")
    return registry


def _fix_reply(request_id: str) -> ChatReply:
    call = ToolCall(id=f"fix_{request_id[:6]}",
                    function=FunctionCall(name="setup_camera", arguments="{}"))
    return ChatReply(tool_calls=[call], content=None, request_id=request_id)


class LadderTransport:
    """plan / editor 自动回放；repair / react 按脚本回放（``Exception`` 或 ``None``）。"""

    def __init__(self, repair_script=(), react_script=()):
        self.repair_script = list(repair_script)
        self.react_script = list(react_script)
        self._repair_i = 0
        self._react_i = 0
        self._editor_index = 0
        self.payloads = []
        self.calls = []
        self.timeouts = []

    def chat(self, payload, timeout=120.0):
        if is_understand(payload):
            # 阶段 S 不占脚本项、不计入主线计数（见 stage_helpers）
            return understand_reply(payload.request_id)
        self.calls.append(str(payload.purpose))
        self.timeouts.append(timeout)
        self.payloads.append(payload)
        if payload.purpose is Purpose.PLAN:
            call = ToolCall(id=f"plan_{len(self.calls)}",
                            function=FunctionCall(
                                name="emit_plan",
                                arguments=json.dumps(demo_plan_dict(SCRIPT))))
            return ChatReply(tool_calls=[call], request_id=payload.request_id)
        if payload.purpose is Purpose.EDITOR:
            draft = demo_draft_dict(self._editor_index)
            self._editor_index += 1
            call = ToolCall(id=f"draft_{len(self.calls)}",
                            function=FunctionCall(
                                name="emit_shot_draft",
                                arguments=json.dumps(draft, ensure_ascii=False)))
            return ChatReply(tool_calls=[call], request_id=payload.request_id)
        if payload.purpose is Purpose.REPAIR:
            item = self.repair_script[min(self._repair_i,
                                          len(self.repair_script) - 1)]
            self._repair_i += 1
            if isinstance(item, Exception):
                raise item
            return _fix_reply(payload.request_id)
        if payload.purpose is Purpose.REACT:
            item = self.react_script[min(self._react_i,
                                         len(self.react_script) - 1)]
            self._react_i += 1
            if isinstance(item, Exception):
                raise item
            return _fix_reply(payload.request_id)
        return ChatReply(content="", request_id=payload.request_id)

    def cancel(self, request_id):
        return None


class PlanTimeoutTransport:
    """plan 每次必超时；understand 走替身（阶梯只管 plan 主线）。"""

    def __init__(self):
        self.payloads = []

    def chat(self, payload, timeout=120.0):
        if is_understand(payload):
            return understand_reply(payload.request_id)
        self.payloads.append(payload)
        raise TimeoutError("The read operation timed out")

    def cancel(self, request_id):
        return None


class KnowledgeStub:
    """只实现 plan 预取所需的那一个方法（Light RAG 的替身）。"""

    def __init__(self, block: str):
        self._block = block

    def block_for_plan(self, query: str) -> str:
        return self._block


def _driver(transport, results, *, limits=None, scene_state_provider=None):
    return PrevisDriver(
        transport=transport, audit=AuditLogger(), script=SCRIPT,
        registry=_registry(), auditor=FakeAuditor(results),
        builder=TrivialBuilder(), thread_factory=InlineThread,
        limits=limits or DriverLimits(),
        scene_state_provider=scene_state_provider)


def _ladder_events(driver):
    return [event for event in driver.audit.recent()
            if event.kind == "retry_ladder"]


def test_repair_timeout_slims_then_degrades_with_exactly_two_calls():
    transport = LadderTransport(repair_script=[
        TimeoutError("The read operation timed out"),
        TimeoutError("The read operation timed out"),
    ])
    failing = AuditResult.from_findings([axis_finding()], target="shot_001")
    driver = _driver(transport, [failing, failing],
                     limits=DriverLimits(llm_timeout_s=77.5),
                     scene_state_provider=lambda: SCENE_STATE_WITH_KNOWLEDGE)

    assert driver.run_to_completion() is DriverState.DONE

    repairs = [p for p in transport.payloads if p.purpose is Purpose.REPAIR]
    assert len(repairs) == 2, "超时 → 瘦身重试 → 降级，这一镜绝不该有第三次调用"
    first, second = repairs
    assert "硬约束（禁/许）" in first.messages[0].content
    assert "R001" in first.messages[0].content            # 审计发现原样在
    assert "硬约束（禁/许）" not in second.messages[0].content
    assert SLIM_PLACEHOLDER in second.messages[0].content
    assert "R001" in second.messages[0].content           # 审计发现仍然在
    assert "小明在桌边" in second.messages[0].content      # 非知识栏的场景文本不动
    assert second.request_id != first.request_id

    events = _ladder_events(driver)
    assert [event.data["stage"] for event in events] == ["slim_retry", "degrade"]
    assert all(event.data["shot_id"] == "shot_001" for event in events)
    assert all(missing_event_fields("retry_ladder", event.data) == []
               for event in events)
    # 红线：阶梯可以重发，但**超时值本身一个字节都不许改**。
    assert transport.timeouts and set(transport.timeouts) == {77.5}
    assert [event.kind for event in driver.audit.recent()] and "shot_degraded" in [
        event.kind for event in driver.audit.recent()]


def test_repair_non_timeout_error_retries_same_payload_then_recovers():
    transport = LadderTransport(repair_script=[
        RuntimeError("HTTP 502 Bad Gateway"), None])
    failing = AuditResult.from_findings([axis_finding()], target="shot_001")
    driver = _driver(transport, [failing,
                                 AuditResult(passed=True, target="shot_001")],
                     scene_state_provider=lambda: SCENE_STATE_WITH_KNOWLEDGE)

    assert driver.run_to_completion() is DriverState.DONE

    repairs = [p for p in transport.payloads if p.purpose is Purpose.REPAIR]
    assert len(repairs) == 2, "非超时错误：原样重试一次后按脚本成功"
    first, second = repairs
    # "原样"重试：消息一个字节都不动（新 request_id 除外），知识栏仍在。
    assert [m.to_dict() for m in first.messages] == \
        [m.to_dict() for m in second.messages]
    assert "硬约束（禁/许）" in second.messages[0].content
    assert second.request_id != first.request_id

    events = _ladder_events(driver)
    assert [event.data["stage"] for event in events] == ["same_retry"]
    kinds = [event.kind for event in driver.audit.recent()]
    assert "shot_degraded" not in kinds, "重试成功后不该降级"


def test_a_success_between_failures_starts_a_fresh_ladder():
    """失败 → 成功 → 再失败：第二次失败是**新调用**的第一次失败，应重试、不降级。

    阶梯历史只描述"这一个调用"。成功之后不清零，同一镜下一次修复的首次失败
    就会被算成第二次失败而直接降级——等于少给了一次重试机会。
    """
    transport = LadderTransport(repair_script=[
        RuntimeError("HTTP 502 Bad Gateway"),   # 第 1 次修复：失败
        None,                                   # 原样重试：成功
        RuntimeError("HTTP 502 Bad Gateway"),   # 第 2 次修复：又失败
        None,                                   # 应当再得到一次原样重试
    ])
    failing = AuditResult.from_findings([axis_finding()], target="shot_001")
    driver = _driver(transport,
                     [failing, failing, AuditResult(passed=True, target="shot_001")],
                     limits=DriverLimits(max_repairs_per_shot=3))

    assert driver.run_to_completion() is DriverState.DONE

    stages = [event.data["stage"] for event in _ladder_events(driver)]
    assert stages == ["same_retry", "same_retry"], stages
    repairs = [p for p in transport.payloads if p.purpose is Purpose.REPAIR]
    assert len(repairs) == 4


def test_react_timeout_slims_then_degrades_ending_the_turn():
    transport = LadderTransport(repair_script=[None], react_script=[
        TimeoutError("The read operation timed out"),
        TimeoutError("The read operation timed out"),
    ])
    driver = _driver(transport, [composition_result()] * 3,
                     limits=DriverLimits(max_repairs_per_shot=1))

    assert driver.run_to_completion() is DriverState.DONE

    reacts = [p for p in transport.payloads if p.purpose is Purpose.REACT]
    assert len(reacts) == 2, "react 超时 → 瘦身重试 → 降级，不得第三次"
    assert reacts[1].request_id != reacts[0].request_id
    assert driver.react_history[-1]["reason"].startswith("传输错误")

    events = _ladder_events(driver)
    assert [event.data["stage"] for event in events] == ["slim_retry", "degrade"]
    assert all(event.data["shot_id"] == "shot_001" for event in events)
    assert all(missing_event_fields("retry_ladder", event.data) == []
               for event in events)


def test_plan_timeout_never_resends_the_identical_full_prompt():
    transport = PlanTimeoutTransport()
    driver = PrevisDriver(
        transport=transport, audit=AuditLogger(), script=SCRIPT,
        knowledge=KnowledgeStub(KNOWLEDGE_COLUMNS),
        limits=DriverLimits(plan_attempts=4), thread_factory=InlineThread)

    assert driver.run_to_completion() is DriverState.ERROR
    assert "分镜计划生成失败" in driver.error

    plans = [p for p in transport.payloads if p.purpose is Purpose.PLAN]
    assert len(plans) == 4, "阶梯重试计入 plan_attempts 预算，四次后按预算收尾"
    full = [p for p in plans if "硬约束（禁/许）" in p.messages[0].content]
    slim = [p for p in plans if "硬约束（禁/许）" not in p.messages[0].content]
    assert len(full) == 1, "完整提示只能在第一次出现，绝无'原样第三次'"
    assert len(slim) == 3
    assert all(SLIM_PLACEHOLDER in p.messages[0].content for p in slim)
    # 瘦身只去 RAG 三栏：计划要求与剧本原文都在。
    assert all("请基于上述剧本" in p.messages[1].content for p in slim)
    assert all(SCRIPT.strip() in p.messages[0].content for p in slim)

    events = _ladder_events(driver)
    assert [event.data["stage"] for event in events] == \
        ["slim_retry", "same_retry", "same_retry", "same_retry"]
    assert all(event.data["shot_id"] == "" for event in events)
    assert all(missing_event_fields("retry_ladder", event.data) == []
               for event in events)
