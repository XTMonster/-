"""v1.6 A2 / D-11：角色表硬校验。

- 计划 characters 含表外 id（占位符如 char_a/char_b）⇒ error 并重问。
- 合法内部 id（char_001 形且已在角色表里）放行。
- 交付前自检发现表外 id 拒绝导出。
- **草案入口**（B1 单镜草案 / 修复回合的 emit_shot_draft）同样核角色表——
  v1.6 G2 真跑（GLM，run a89fa37ebdca）里 B1 幻觉出剧本中不存在的角色名，
  一路活到导出闸才被拦停；解析期拦下才是"这一镜沿用计划内容"的既有纪律。
"""

from __future__ import annotations

import json

import pytest

from block_director.contracts.audit import AuditResult
from block_director.contracts.cast import CastMember, SceneSpec
from block_director.contracts.enums import ErrorCode, Purpose, ShotType
from block_director.contracts.errors import user_message
from block_director.contracts.messages import ChatReply, FunctionCall, ToolCall
from block_director.contracts.plan import (
    Plan,
    ShotPlan,
    unknown_cast_ids,
    unknown_cast_members,
)
from block_director.layer5_orchestrator.driver import PrevisDriver
from block_director.layer5_orchestrator.editor import (
    EDITOR_TOOL_NAME,
    EMIT_SHOT_DRAFT_PARAMETERS,
    extract_draft,
)
from block_director.layer5_orchestrator.offline import (
    demo_draft_dict,
    demo_plan_dict,
)
from block_director.layer5_orchestrator.planner import EMIT_PLAN_TOOL_PARAMETERS
from block_director.layer5_orchestrator.states import DriverState
from block_director.layer5_orchestrator.tool_registry import ToolRegistry
from block_director.layer6_audit.audit_logger import AuditLogger

from test_driver import InlineThread
from test_driver_repair import (
    SCRIPT,
    FakeAuditor,
    RepairingTransport,
    TrivialBuilder,
    axis_finding,
)


def _plan_with_characters(*character_ids: str) -> Plan:
    return Plan(shots=[
        ShotPlan(shot_id=f"shot_{i:03d}",
                 intent="测试",
                 shot_type=ShotType.MS,
                 duration_frames=48,
                 characters=list(character_ids))
        for i in range(1, len(character_ids) + 1)
    ])


def test_unknown_cast_ids_flags_placeholder_ids():
    roster = ["周野", "林可"]
    plan = _plan_with_characters("周野", "char_a", "char_b")
    assert unknown_cast_ids(plan, roster) == ["char_a", "char_b"]


def test_unknown_cast_ids_allows_allocated_internal_ids():
    roster = ["周野", "林可", "char_001", "char_002"]
    plan = _plan_with_characters("char_001", "char_002", "周野")
    assert unknown_cast_ids(plan, roster) == []


def test_unknown_cast_ids_mixed_names_and_ids():
    roster = ["周野", "char_001"]
    plan = _plan_with_characters("周野", "char_001", "char_002", "char_a")
    assert unknown_cast_ids(plan, roster) == ["char_002", "char_a"]


def test_unknown_cast_ids_empty_roster_flags_everything():
    plan = _plan_with_characters("char_001")
    assert unknown_cast_ids(plan, []) == ["char_001"]


def test_unknown_cast_ids_empty_plan_passes():
    assert unknown_cast_ids(Plan(), ["周野"]) == []


def test_cast_001_user_message_format():
    msg = user_message(ErrorCode.CAST_001, ids="char_a, char_b",
                       roster="周野, 林可")
    assert "char_a, char_b" in msg
    assert "周野, 林可" in msg


def test_scene_spec_from_plan_does_not_filter():
    """SceneSpec.from_plan 保持原行为：它按 plan.characters 建 cast。

    校验在 plan 被收下之前做，因此 SceneSpec 不会收到表外 id。
    """
    plan = _plan_with_characters("周野", "char_a")
    spec = SceneSpec.from_plan(plan)
    assert [m.id for m in spec.cast] == ["周野", "char_a"]


def test_cast_member_serde_roundtrip():
    member = CastMember(id="char_001", name="周野", color="#FF0000")
    data = member.to_dict()
    restored = CastMember.from_dict(data)
    assert restored.id == "char_001"
    assert restored.name == "周野"


# --------------------------------------------------------------------------- #
# 草案入口（v1.6 G2 真跑暴露的缺口：extract_draft 从不核 draft.characters）
# --------------------------------------------------------------------------- #
def _draft_reply(arguments: dict) -> ChatReply:
    return ChatReply(tool_calls=[ToolCall(
        id="c", function=FunctionCall(
            name=EDITOR_TOOL_NAME,
            arguments=json.dumps(arguments, ensure_ascii=False)))])


def test_unknown_cast_members_matches_the_plan_level_check():
    """成员级判据与计划级判据同源——同一输入两边结论必须一致。"""
    roster = ["伊恩", "米迦尔", "char_001"]
    plan = _plan_with_characters("伊恩", "优一郎", "char_001", "char_002")
    assert unknown_cast_members(["伊恩", "优一郎", "char_001", "char_002"],
                                roster) == unknown_cast_ids(plan, roster)
    assert unknown_cast_members(["优一郎"], roster) == ["优一郎"]
    assert unknown_cast_members(["伊恩", "char_001"], roster) == []


def test_extract_draft_rejects_off_roster_characters():
    reply = _draft_reply({"shot_id": "shot_001", "characters": ["优一郎"]})
    with pytest.raises(ValueError) as excinfo:
        extract_draft(reply, "shot_001",
                      roster=["伊恩", "偷盗者", "米迦尔", "莉莉安娜"])
    assert "优一郎" in str(excinfo.value)


def test_extract_draft_allows_roster_subset_and_allocated_ids():
    """子集与已分配的 char_NNN 必须放行——不许误杀合法草案。"""
    reply = _draft_reply({"shot_id": "shot_001",
                          "characters": ["伊恩", "char_001"]})
    draft = extract_draft(reply, "shot_001",
                          roster=["伊恩", "米迦尔", "char_001"])
    assert draft.characters == ["伊恩", "char_001"]


def test_extract_draft_without_roster_keeps_the_old_behavior():
    """不给 roster = 没有角色表可查 ⇒ 跳过（与 characters/anchors 同一纪律）。"""
    reply = _draft_reply({"shot_id": "shot_001", "characters": ["优一郎"]})
    draft = extract_draft(reply, "shot_001")
    assert draft.characters == ["优一郎"]
    reply = _draft_reply({"shot_id": "shot_001", "characters": ["优一郎"]})
    draft = extract_draft(reply, "shot_001", roster=[])
    assert draft.characters == ["优一郎"]


class _OffRosterDraftTransport(RepairingTransport):
    """B1 草案里注入一个剧本中不存在的角色名（G2 真跑的"优一郎"形状）。"""

    def chat(self, payload, timeout=120.0):
        if payload.purpose is Purpose.EDITOR:
            self.chat_calls += 1
            self.payloads.append(payload)
            draft = demo_draft_dict(self._editor_index)
            self._editor_index += 1
            draft["characters"] = ["优一郎"]
            call = ToolCall(id=f"draft_{self.chat_calls}",
                            function=FunctionCall(
                                name=EDITOR_TOOL_NAME,
                                arguments=json.dumps(draft,
                                                     ensure_ascii=False)))
            return ChatReply(tool_calls=[call])
        return super().chat(payload, timeout)


def _registry_with_draft_tool() -> ToolRegistry:
    registry = ToolRegistry()
    registry.add(
        name="emit_plan", description="plan",
        parameters=EMIT_PLAN_TOOL_PARAMETERS,
        handler=lambda **kwargs: "计划已接收")
    registry.add(name="setup_camera", description="fix",
                 parameters={"type": "object", "additionalProperties": False,
                             "properties": {}},
                 handler=lambda: "相机已重设")
    registry.add(name=EDITOR_TOOL_NAME, description="draft",
                 parameters=EMIT_SHOT_DRAFT_PARAMETERS,
                 handler=lambda **kwargs: "草案已接收")
    return registry


def test_driver_rejects_off_roster_draft_and_keeps_the_plan_characters():
    """B1 草案带表外角色 ⇒ draft_invalid，这一镜沿用计划的角色表，整场不炸。"""
    transport = _OffRosterDraftTransport()
    driver = PrevisDriver(transport=transport, audit=AuditLogger(),
                          script=SCRIPT, registry=_registry_with_draft_tool(),
                          auditor=FakeAuditor([]), builder=TrivialBuilder(),
                          thread_factory=InlineThread)
    assert driver.run_to_completion() is DriverState.DONE
    expected = [list(shot["characters"])
                for shot in demo_plan_dict(SCRIPT)["shots"]]
    assert [list(shot.characters) for shot in driver.plan.shots] == expected
    events = [e for e in driver.audit.recent() if e.kind == "draft_invalid"]
    assert events, "表外角色的草案必须记 draft_invalid"
    assert any("优一郎" in e.message for e in events)


class _OffRosterRepairTransport(RepairingTransport):
    """修复回合用 emit_shot_draft 提交表外角色（第二个入口）。"""

    def chat(self, payload, timeout=120.0):
        if payload.purpose is Purpose.REPAIR:
            self.chat_calls += 1
            self.payloads.append(payload)
            draft = {"shot_id": "shot_001", "characters": ["优一郎"],
                     "actions": []}
            call = ToolCall(id=f"fix_{self.chat_calls}",
                            function=FunctionCall(
                                name=EDITOR_TOOL_NAME,
                                arguments=json.dumps(draft,
                                                     ensure_ascii=False)))
            return ChatReply(tool_calls=[call], content=None)
        return super().chat(payload, timeout)


def test_driver_repair_path_rejects_off_roster_draft():
    """修复回合的 emit_shot_draft 同样核角色表：记 repair_invalid，计划不动。"""
    transport = _OffRosterRepairTransport()
    auditor = FakeAuditor([
        AuditResult.from_findings([axis_finding()], target="shot_001"),
        AuditResult(passed=True, target="shot_001"),
    ])
    driver = PrevisDriver(transport=transport, audit=AuditLogger(),
                          script=SCRIPT, registry=_registry_with_draft_tool(),
                          auditor=auditor, builder=TrivialBuilder(),
                          thread_factory=InlineThread)
    assert driver.run_to_completion() is DriverState.DONE
    expected = [list(shot["characters"])
                for shot in demo_plan_dict(SCRIPT)["shots"]]
    assert [list(shot.characters) for shot in driver.plan.shots] == expected
    events = [e for e in driver.audit.recent() if e.kind == "repair_invalid"]
    assert any("优一郎" in e.message for e in events), \
        "修复路径的表外角色必须记进 repair_invalid"
