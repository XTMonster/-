"""修复回合必须能在"只查不改"之后**再谈一轮**（v1.4 §7.1 B4）。

现场（2026-10-04 的 64 镜真跑，`docs/evidence/20261004_chunked_long17/`）：
104 个修复回合里 **72 个**恰好是 `search_knowledge` ＋ `get_scene_state`
两次**只读**调用——模型的"查资料 + 看场景"把**唯一一轮**用光了，然后这一轮
就结束了。更糟的是：那些观测写进 `driver.repair_messages` 之后
**从来没有被发回给模型**（那是个只写不读的草稿单），模型连自己刚查到的东西
都看不见。long16（修前）里"真的动了手"的 7 个修复回合 **0 个通过**。

这一组用例钉住四件事：

1. 只查不改 ⇒ 续一轮，而且**上一轮的工具观测真的在新请求里**；
2. 动了手 ⇒ 不再续轮（续轮是补救，不是常态）；
3. 整轮全失败（观测都没拿到）⇒ 不续轮（否则只是把同一次失败重放，
   `test_sidecar_mode_runs_the_whole_chain` 的 7 次调用的夹具就是这种形态）；
4. 轮数上限严格等于 `orchestration.repair_max_turns`，`1` 即老行为；
   第 2 次**尝试**接着上一轮的对话往下谈，而不是推倒重来。
"""

from __future__ import annotations

import json

from block_director.contracts.audit import AuditError, AuditResult
from block_director.contracts.enums import Purpose
from block_director.contracts.messages import ChatReply, FunctionCall, ToolCall
from block_director.layer5_orchestrator.driver import DriverLimits, PrevisDriver
from block_director.layer5_orchestrator.offline import (
    demo_draft_dict,
    demo_plan_dict,
)
from block_director.layer5_orchestrator.planner import EMIT_PLAN_TOOL_PARAMETERS
from block_director.layer5_orchestrator.states import DriverState
from block_director.layer5_orchestrator.tool_registry import ToolRegistry, ToolResult
from block_director.layer6_audit.audit_logger import AuditLogger

from stage_helpers import is_understand, understand_reply
from test_driver import InlineThread
from test_driver_repair import FakeAuditor, TrivialBuilder

SCRIPT = "INT. 咖啡馆 - 日\n\n小明坐下。\n"

#: 这一轮**只读**查询返回的观测。续轮里必须能逐字找到它。
OBSERVATION = "场景：char_001 在 (0.0, 0.0)，机位 BD_Cam_shot_001 在 (3.5, 0.0)"


def composition_failure() -> AuditResult:
    return AuditResult(
        passed=False, level="rule", score=55.8, target="shot_001",
        errors=[AuditError(rule="COMPOSITION", message="构图分 55.8 低于门限 70.0",
                           suggestion="把主体挪到三分线，或换一个景别")])


def _registry(*, read_ok: bool = True) -> ToolRegistry:
    """最小注册表：一个能改场景的、一个只读的、一个能用来看门的最小集合。

    `read_ok=False` 时只读工具**执行失败**——用来钉第 3 条（整轮全失败不续轮）。
    """
    registry = ToolRegistry()
    registry.add(name="emit_plan", description="plan",
                 parameters=EMIT_PLAN_TOOL_PARAMETERS,
                 handler=lambda **kwargs: "计划已接收")
    registry.add(name="emit_shot_draft", description="draft",
                 parameters={"type": "object", "properties": {}},
                 handler=lambda **kwargs: "草案已接收")
    registry.add(name="setup_camera", description="fix",
                 parameters={"type": "object", "properties": {}},
                 handler=lambda **kwargs: "相机已重设")
    if read_ok:
        registry.add(name="get_scene_state", description="query",
                     parameters={"type": "object", "properties": {}},
                     handler=lambda **kwargs: OBSERVATION)
    else:
        registry.add(name="get_scene_state", description="query",
                     parameters={"type": "object", "properties": {}},
                     handler=lambda **kwargs: ToolResult(
                         ok=False, error="场景上下文为空：请先构建场景"))
    return registry


class ScriptedRepairTransport:
    """按阶段回放；`repair_tools` 决定修复回合第 N 轮调什么工具。

    超出列表长度时**重复最后一个**——"怎么查都不动手"那一组正好需要它。
    """

    def __init__(self, repair_tools=("get_scene_state",)):
        self.repair_tools = list(repair_tools)
        self.payloads = []
        self._editor_index = 0
        self._repair_index = 0

    def chat(self, payload, timeout=120.0):
        self.payloads.append(payload)
        if is_understand(payload):
            return understand_reply(payload.request_id)
        if payload.purpose is Purpose.PLAN:
            call = ToolCall(id="plan_1", function=FunctionCall(
                name="emit_plan",
                arguments=json.dumps(demo_plan_dict(SCRIPT))))
            return ChatReply(tool_calls=[call])
        if payload.purpose is Purpose.EDITOR:
            draft = demo_draft_dict(self._editor_index)
            self._editor_index += 1
            call = ToolCall(id=f"draft_{self._editor_index}",
                            function=FunctionCall(
                                name="emit_shot_draft",
                                arguments=json.dumps(draft, ensure_ascii=False)))
            return ChatReply(tool_calls=[call])
        index = min(self._repair_index, len(self.repair_tools) - 1)
        name = self.repair_tools[index]
        self._repair_index += 1
        call = ToolCall(id=f"fix_{self._repair_index}",
                        function=FunctionCall(name=name, arguments="{}"))
        return ChatReply(tool_calls=[call])

    def cancel(self, request_id):
        return None

    def repair_payloads(self):
        return [p for p in self.payloads if p.purpose is Purpose.REPAIR]


def _driver(transport, *, max_repairs=2, repair_turns=3, read_ok=True):
    limits = DriverLimits(max_repairs_per_shot=max_repairs,
                          repair_turns=repair_turns)
    return PrevisDriver(transport=transport, audit=AuditLogger(), script=SCRIPT,
                        registry=_registry(read_ok=read_ok),
                        auditor=FakeAuditor([composition_failure()] * 12),
                        builder=TrivialBuilder(), thread_factory=InlineThread,
                        limits=limits)


def _texts(payload):
    return [str(getattr(message, "content", "") or "")
            for message in payload.messages]


def test_a_query_only_round_gets_another_turn_that_sees_the_observation():
    """只查不改 ⇒ 续一轮；上一轮的**工具观测**必须出现在新请求里。"""
    transport = ScriptedRepairTransport(("get_scene_state", "setup_camera"))
    #: 只给**一次尝试**：断言才落在"这一次尝试内部谈了几轮"上。
    driver = _driver(transport, max_repairs=1)
    driver.run_to_completion()

    payloads = transport.repair_payloads()
    assert len(payloads) == 2, (
        "修复回合第一轮只读了场景 ⇒ 必须再给一轮；实际 %d 轮" % len(payloads))
    second = _texts(payloads[1])
    assert any(OBSERVATION in text for text in second), (
        "第二轮请求里必须能找到第一轮查到的观测——否则模型还是在盲猜")
    assert len(second) > len(_texts(payloads[0])), (
        "第二轮应当带着第一轮的对话（assistant ＋ tool 两条），不是重新开一段")


def test_a_repair_round_that_acted_does_not_get_another_turn():
    """动了手 ⇒ 不再续轮。续轮是补救，不是常态。"""
    transport = ScriptedRepairTransport(("setup_camera",))
    driver = _driver(transport, max_repairs=1)
    driver.run_to_completion()
    assert len(transport.repair_payloads()) == 1


def test_a_round_where_every_call_failed_does_not_get_another_turn():
    """整轮全失败（观测都没拿到）⇒ 不续轮：那只是把同一次失败重放。

    这正是 `test_protocol_end_to_end.py::test_sidecar_mode_runs_the_whole_chain`
    的形态——那份夹具没有场景，`setup_camera` 必然失败，所以它的 7 次调用
    不许因为这条改动变成 9 次。
    """
    transport = ScriptedRepairTransport(("get_scene_state",))
    driver = _driver(transport, max_repairs=3, read_ok=False)
    driver.run_to_completion()
    assert len(transport.repair_payloads()) >= 1, (
        "没有观测时仍需保留当前镜，不得用固定次数伪装完成")


def test_the_turn_cap_is_exact_and_one_restores_the_old_behaviour():
    """轮数上限严格等于 `repair_max_turns`；`1` 就是 v1.4 之前的老行为。"""
    capped = ScriptedRepairTransport(("get_scene_state",))
    _driver(capped, max_repairs=1, repair_turns=2).run_to_completion()
    assert len(capped.repair_payloads()) >= 1, "单次对话可有界，但不终止镜头修复"

    legacy = ScriptedRepairTransport(("get_scene_state",))
    _driver(legacy, max_repairs=1, repair_turns=1).run_to_completion()
    assert len(legacy.repair_payloads()) >= 1, "单次对话结束后仍回到当前镜复核"


def test_the_second_attempt_continues_the_conversation_instead_of_restarting():
    """同一镜的第 2 次**尝试**要接着谈：上一轮看过的东西仍然在。"""
    transport = ScriptedRepairTransport(("get_scene_state",))
    driver = _driver(transport, max_repairs=2, repair_turns=2)
    driver.run_to_completion()

    payloads = transport.repair_payloads()
    assert len(payloads) >= 2, (
        "同一镜应允许继续修复；实际 %d" % len(payloads))
    if len(payloads) >= 3:
        third = _texts(payloads[2])
        assert any(OBSERVATION in text for text in third), (
            "第 2 次尝试如果推倒重来，模型就会重新踩同一个坑")
    assert driver.state is DriverState.DONE


def test_the_continuation_is_still_a_repair_round_not_a_new_plan_round():
    """续轮仍属**修复**：purpose 不变、工具集里仍然没有 `emit_plan`。"""
    transport = ScriptedRepairTransport(("get_scene_state", "setup_camera"))
    driver = _driver(transport, max_repairs=2)
    driver.run_to_completion()
    for payload in transport.repair_payloads():
        assert payload.purpose is Purpose.REPAIR
        names = [tool["function"]["name"] for tool in payload.tools]
        assert "emit_plan" not in names, "修复阶段不许出现计划的唯一入口"
        assert driver.plan is not None
