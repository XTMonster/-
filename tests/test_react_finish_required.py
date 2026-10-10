"""G2 判据 #8（ReAct 侧）：载荷必须 tool_choice=required 且带 finish_shot；
驱动器侧：finish_shot 正常结束 ReAct（不记 react_invalid），无工具调用照记
react_invalid（category=no_tool）。"""

from __future__ import annotations

import pytest

from block_director.contracts.audit import AuditError, AuditResult
from block_director.contracts.enums import Purpose, ToolChoice
from block_director.contracts.plan import ShotPlan
from block_director.layer5_orchestrator.control_tools import FINISH_SHOT
from block_director.layer5_orchestrator.react import build_react_payload
from block_director.layer5_orchestrator.states import DriverState
from block_director.layer5_orchestrator.tool_registry import ToolRegistry

from test_driver_react import (
    PLAN_REPLY,
    ScriptedTransport,
    StubAuditor,
    make_driver,
)


def _shot() -> ShotPlan:
    return ShotPlan.from_dict({"shot_id": "shot_001", "order": 1,
                               "intent": "精修这一镜", "shot_type": "MS",
                               "duration_frames": 48})


def _audit() -> AuditResult:
    return AuditResult(passed=False, target="shot_001", score=50.0, errors=[
        AuditError(rule="COMPOSITION", code="E_CAM_001", message="构图差",
                   target="shot_001")])


def _registry(with_finish_shot: bool = True) -> ToolRegistry:
    registry = ToolRegistry()
    registry.add(name="check_composition", description="复核构图",
                 parameters={"type": "object"}, handler=lambda **kw: "ok")
    if with_finish_shot:
        registry.add(name="finish_shot", description="声明当前镜头完成",
                     parameters={"type": "object"}, handler=lambda **kw: "ok")
    return registry


# --------------------------------------------------------------------------- #
# 载荷构造
# --------------------------------------------------------------------------- #
def test_react_payload_requires_tool_choice_and_offers_finish_shot():
    payload = build_react_payload(_shot(), _audit(), scene_state="场景",
                                  registry=_registry(), max_steps=4)
    assert payload.purpose is Purpose.REACT
    assert payload.tool_choice is ToolChoice.REQUIRED
    names = {tool["function"]["name"] for tool in payload.tools}
    assert "finish_shot" in names
    assert "emit_plan" not in names
    system = payload.messages[0].content
    assert "finish_shot" in system          # 收尾红线进了系统提示
    assert "最多 4 步" in system


def test_react_system_prompt_max_steps_bullet_matches_card():
    # 卡 G8-DF 修订 2：最多步数条目必须用卡上的原文——
    # 收尾 = finish_shot；无工具调用 = 判无效；不得再写"停止调用工具"。
    payload = build_react_payload(_shot(), _audit(), registry=_registry(),
                                  max_steps=4)
    system = payload.messages[0].content
    assert "认为已经足够好时调用 finish_shot 收尾" in system
    assert "不调用任何工具的回复会被判为无效" in system
    assert "停止调用工具" not in system


def test_react_payload_raises_when_finish_shot_is_missing():
    with pytest.raises(ValueError, match="finish_shot"):
        build_react_payload(_shot(), _audit(), registry=_registry(False))


# --------------------------------------------------------------------------- #
# 驱动器闭环（假传输）
# --------------------------------------------------------------------------- #
def test_finish_shot_ends_react_without_react_invalid():
    transport = ScriptedTransport([
        PLAN_REPLY,
        ("setup_camera", {"shot_id": "shot_001"}),      # B4 修复
        (FINISH_SHOT, {"summary": "精修完成"}),          # B5 收尾
    ])
    driver = make_driver(transport, StubAuditor(fail_times=3))
    state = driver.run_to_completion()

    kinds = [event.kind for event in driver.audit.recent(200)]
    assert state is DriverState.DONE
    assert "react_started" in kinds and "react_finished" in kinds
    assert "react_invalid" not in kinds          # finish_shot 是正常收尾
    assert driver.react_history == [
        {"shot_id": "shot_001", "steps": 1, "reason": "模型调用 finish_shot"}]
    assert "shot_finished" in kinds              # 完成声明照常落盘
    assert "shot_finished_with_errors" in kinds  # 审核仍不过，如实记账


def test_no_tool_reply_logs_react_invalid_with_no_tool_category():
    transport = ScriptedTransport([
        PLAN_REPLY,
        ("setup_camera", {"shot_id": "shot_001"}),      # B4 修复
        ("setup_camera", {"shot_id": "shot_001"}),      # B5 第 1 步
        None,                                           # 模型直接停下
    ])
    driver = make_driver(transport, StubAuditor(fail_times=3))
    driver.run_to_completion()

    events = [event for event in driver.audit.recent(200)
              if event.kind == "react_invalid"]
    assert events, "无工具调用的回复必须照记 react_invalid"
    event = events[-1]
    assert event.message == "回复中没有工具调用"
    assert event.data["reason"] == event.message
    assert event.data["category"] == "no_tool"
    assert driver.react_history[-1]["reason"] == "模型停止调用工具"
