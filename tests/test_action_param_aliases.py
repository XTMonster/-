"""v1.6 G2（用户裁决 2026-10-09）：无歧义动作参数别名的文档化归一。"""

from __future__ import annotations

import json

from block_director.contracts.messages import ChatReply, FunctionCall, ToolCall
from block_director.layer5_orchestrator import editor as ED
from block_director.motion import model as M


def test_unambiguous_aliases_normalise_to_canonical_keys():
    assert M.normalize_action_params(
        "turn_head", {"yaw_deg": 30}) == {"angle_deg": 30}
    assert M.normalize_action_params(
        "body_tilt", {"lean_deg": 12, "axis": "x"}) == {
            "angle_deg": 12, "axis": "x"}
    assert M.normalize_action_params(
        "look_at", {"angle_deg": 20, "pitch_deg": 5}) == {
            "yaw_deg": 20, "pitch_deg": 5}


def test_canonical_key_wins_over_the_alias():
    assert M.normalize_action_params(
        "turn_head", {"angle_deg": 10, "yaw_deg": 30}) == {"angle_deg": 10}


def test_aliases_are_unknown_to_other_actions():
    # yaw_deg 对 look_at 是规范键，对 turn_head 是别名——不能串到别的动作。
    assert M.normalize_action_params("body_tilt", {"yaw_deg": 1}) == {
        "yaw_deg": 1}
    assert M.action_param_problems("body_tilt", {"yaw_deg": 1})


def test_validation_accepts_aliases_and_still_rejects_ambiguous_words():
    assert M.action_param_problems("turn_head", {"yaw_deg": 30}) == []
    assert M.action_param_problems("body_tilt", {"lean_deg": 12}) == []
    assert M.action_param_problems("look_at", {"angle_deg": 20}) == []
    # 有歧义 / 越域的一律照旧拒绝，不静默吞。
    assert M.action_param_problems("turn_head", {"pitch_deg": 5})
    assert M.action_param_problems("turn_body", {"axis": "x"})
    assert M.action_param_problems("look_at", {"toward": "米迦尔"})
    assert M.action_param_problems("walk_to", {"speed": "slow"})


def test_draft_extraction_stores_canonical_keys():
    def reply(args):
        return ChatReply(tool_calls=[ToolCall(
            id="c1", function=FunctionCall(
                name=ED.EDITOR_TOOL_NAME,
                arguments=json.dumps(args, ensure_ascii=False)))])

    draft = ED.extract_draft(reply({
        "shot_id": "shot_006",
        "actions": [{
            "character_id": "char_001", "action_type": "turn_head",
            "start_frame": 1, "end_frame": 24,
            "params": {"yaw_deg": 20}}],
        "dialogues": [], "camera": {}, "gaze": [], "vfx": [], "prompt": ""}),
        "shot_006")
    assert draft.actions[0]["params"] == {"angle_deg": 20}
