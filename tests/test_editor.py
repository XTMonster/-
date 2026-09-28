"""§7.1 阶段 B1（Editor）的纯计算测试。"""

from __future__ import annotations

import json

import pytest

from block_director.contracts.enums import Purpose, ToolChoice
from block_director.contracts.messages import ChatReply, FunctionCall, ToolCall
from block_director.contracts.plan import Plan, ShotPlan
from block_director.layer5_orchestrator.editor import (
    EDITOR_TOOL_NAME,
    EMIT_SHOT_DRAFT_PARAMETERS,
    ShotDraft,
    build_editor_payload,
    extract_draft,
    find_draft_call,
    merge_draft,
)
from block_director.layer5_orchestrator.tool_schema import validate_args


def plan() -> Plan:
    return Plan.from_dict({
        "scene_heading": "INT. 公寓 - 夜",
        "shots": [
            {"shot_id": "shot_001", "order": 1, "intent": "建立",
             "shot_type": "MLS", "duration_frames": 72,
             "characters": ["char_001", "char_002"],
             "prompt": "雨夜客厅"},
            {"shot_id": "shot_002", "order": 2, "intent": "反应",
             "shot_type": "MCU", "duration_frames": 96,
             "characters": ["char_001"]},
        ]})


def draft(**overrides) -> dict:
    payload = {"shot_id": "shot_001",
               "actions": [{"character_id": "char_001",
                            "action_type": "nod",
                            "start_frame": 1, "end_frame": 40}],
               "dialogues": [{"character_id": "char_001", "text": "你好",
                              "start_frame": 10, "end_frame": 40}],
               "camera": {"side": "left", "lens": 35},
               "prompt": "雨夜客厅，中远景"}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# §18.2 的提示
# --------------------------------------------------------------------------- #
def test_editor_payload_carries_everything_the_prompt_needs():
    payload = build_editor_payload(plan().shots[0], plan(), shot_order=1,
                                   scene_state="（场景）", continuity="（台账）",
                                   characters=["char_001", "char_002"],
                                   props=["chair"], scene_text="林可坐下。")
    system = payload.messages[0].content
    assert payload.purpose is Purpose.EDITOR
    assert payload.tool_choice is ToolChoice.REQUIRED
    assert payload.tools[0]["function"]["name"] == EDITOR_TOOL_NAME
    for fragment in ("shot_001", "72", "MLS", "（场景）", "（台账）",
                     "char_001", "chair", "林可坐下。", "相对描述"):
        assert fragment in system, fragment
    assert "不要给坐标" in system


def test_editor_payload_uses_the_retriever_when_given():
    class FakeRetriever:
        def block_for_shot(self, shot_type, intent, action_types=(), limit=800):
            return f"知识：{shot_type}/{intent}"

    payload = build_editor_payload(plan().shots[1], plan(),
                                   retriever=FakeRetriever())
    assert "知识：MCU/反应" in payload.messages[0].content


def test_editor_payload_says_when_knowledge_is_off():
    payload = build_editor_payload(plan().shots[0], plan())
    assert "未启用知识库" in payload.messages[0].content


# --------------------------------------------------------------------------- #
# 草案 schema 与解析
# --------------------------------------------------------------------------- #
def test_draft_schema_is_strict():
    good = draft()
    assert validate_args(EMIT_SHOT_DRAFT_PARAMETERS, good) == []
    bad = draft(unknown_field=1)
    assert any("不允许出现字段" in item
               for item in validate_args(EMIT_SHOT_DRAFT_PARAMETERS, bad))
    wrong_action = draft(actions=[{"character_id": "char_001"}])
    assert any("action_type" in item for item in
               validate_args(EMIT_SHOT_DRAFT_PARAMETERS, wrong_action))


def test_extract_draft_round_trips_the_tool_arguments():
    reply = ChatReply(tool_calls=[ToolCall(
        id="c", function=FunctionCall(name=EDITOR_TOOL_NAME,
                                      arguments=json.dumps(draft())))] )
    parsed = extract_draft(reply, "shot_001")
    assert parsed.shot_id == "shot_001"
    assert parsed.actions[0]["action_type"] == "nod"
    assert parsed.camera["lens"] == 35
    assert find_draft_call(reply) is not None


def test_extract_draft_rejects_the_wrong_shot():
    reply = ChatReply(tool_calls=[ToolCall(
        id="c", function=FunctionCall(name=EDITOR_TOOL_NAME,
                                      arguments=json.dumps(draft(
                                          shot_id="shot_002"))))])
    with pytest.raises(ValueError) as excinfo:
        extract_draft(reply, "shot_001")
    assert "不一致" in str(excinfo.value)


def test_extract_draft_rejects_a_missing_call_or_bad_json():
    empty = ChatReply(content="我不干了", tool_calls=[])
    with pytest.raises(ValueError):
        extract_draft(empty, "shot_001")
    broken = ChatReply(tool_calls=[ToolCall(
        id="c", function=FunctionCall(name=EDITOR_TOOL_NAME,
                                      arguments="{不是 json"))])
    with pytest.raises(ValueError):
        extract_draft(broken, "shot_001")


def test_missing_shot_id_falls_back_to_the_requested_one():
    reply = ChatReply(tool_calls=[ToolCall(
        id="c", function=FunctionCall(name=EDITOR_TOOL_NAME,
                                      arguments=json.dumps(draft(shot_id=""))))])
    assert extract_draft(reply, "shot_001").shot_id == "shot_001"


# --------------------------------------------------------------------------- #
# 合并
# --------------------------------------------------------------------------- #
def test_merge_only_touches_the_target_shot():
    merged = merge_draft(plan(), ShotDraft.from_dict(draft()))
    first, second = merged.shots
    assert first.actions and first.dialogues
    assert first.camera == {"side": "left", "lens": 35}
    assert first.prompt == "雨夜客厅，中远景"
    assert second.actions == [] and second.dialogues == []
    assert second.prompt == ""


def test_merge_keeps_the_plan_as_the_source_of_timing():
    """镜头时长与顺序是计划的唯一真源（§10.2 的排片依赖它）。"""
    original = plan()
    merged = merge_draft(original, ShotDraft.from_dict(draft()))
    assert [shot.duration_frames for shot in merged.shots] == \
        [shot.duration_frames for shot in original.shots]
    assert [shot.shot_id for shot in merged.shots] == ["shot_001", "shot_002"]
    assert merged.scene_heading == original.scene_heading


def test_merge_replaces_previous_draft_content():
    once = merge_draft(plan(), ShotDraft.from_dict(draft()))
    twice = merge_draft(once, ShotDraft.from_dict(draft(
        actions=[], dialogues=[], prompt="改过的描述")))
    assert twice.shots[0].actions == []
    assert twice.shots[0].prompt == "改过的描述"


def test_merge_ignores_an_unknown_shot():
    merged = merge_draft(plan(), ShotDraft.from_dict(draft(shot_id="shot_999")))
    assert merged.to_dict() == plan().to_dict()


def test_empty_fields_do_not_erase_plan_values():
    """草案里没写的字段不该把计划里的内容抹掉（景别、提示词）。"""
    merged = merge_draft(plan(), ShotDraft.from_dict(
        {"shot_id": "shot_001", "actions": []}))
    assert str(merged.shots[0].shot_type) == "MLS"
    assert merged.shots[0].prompt == "雨夜客厅"
