"""P2-T4：emit_plan / emit_shot_draft 的 v1.5 schema 与合并。

（执行文档 v1.5 TDD §3.8；卡 P2-T4）

钉住四件事：

1. **只锁词汇与语法，不锁选择**：`beats[].verb` 的枚举**逐字等于**
   `motion/model.py::ACTION_TYPES`（红线 R-7，单一真源）；`maxItems` 上限存在；
2. **emit_plan 的 environment** 是场级声明宿主（anchors maxItems=12 + light
   三枚 enum），`additionalProperties: False`；
3. **解析期拒绝**：越界 `t`、未知 `verb`、`break` 无 `reason` 都被
   `tool_schema.validate_args` / `extract_draft` 挡住（而不是留到构建期把整轮
   打成 ERROR）；
4. **合并 + 向后兼容**：合法草案把新字段合并回 ShotPlan；旧草案（没有新键）
   行为不变。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.contracts.beats import MAX_BEATS  # noqa: E402
from block_director.contracts.messages import (  # noqa: E402
    ChatReply,
    FunctionCall,
    ToolCall,
)
from block_director.contracts.plan import Plan, ShotPlan  # noqa: E402
from block_director.motion.model import ACTION_TYPES  # noqa: E402
from block_director.layer5_orchestrator.editor import (  # noqa: E402
    EMIT_SHOT_DRAFT_PARAMETERS,
    extract_draft,
    merge_draft,
)
from block_director.layer5_orchestrator.planner import (  # noqa: E402
    EMIT_PLAN_TOOL_PARAMETERS,
)
from block_director.layer5_orchestrator.tool_schema import (  # noqa: E402
    validate_args,
)


def _reply(args: dict) -> ChatReply:
    return ChatReply(tool_calls=[ToolCall(
        id="call_1",
        function=FunctionCall(name="emit_shot_draft",
                              arguments=json.dumps(args, ensure_ascii=False)))])


def _plan() -> Plan:
    return Plan(shots=[ShotPlan(shot_id="shot_001", intent="推进",
                                shot_type="MS", duration_frames=72, order=1,
                                characters=["char_001"])],
                environment={"anchors": [{"name": "door", "depth": "bg",
                                          "relation": "behind 甲"}]})


def test_draft_schema_locks_word_lists_not_choices():
    props = EMIT_SHOT_DRAFT_PARAMETERS["properties"]
    assert set(("beats", "composition", "rule_justifications")) <= set(props)
    beats = props["beats"]
    assert beats["maxItems"] == MAX_BEATS
    assert beats["items"]["properties"]["verb"]["enum"] == list(ACTION_TYPES)
    assert props["rule_justifications"]["items"]["properties"]["action"]["enum"] == [
        "follow", "break"]
    assert props["composition"]["properties"]["rule"]["enum"]
    assert EMIT_SHOT_DRAFT_PARAMETERS["additionalProperties"] is False


def test_plan_schema_has_environment_host():
    env = EMIT_PLAN_TOOL_PARAMETERS["properties"]["environment"]
    assert env["additionalProperties"] is False
    assert env["properties"]["anchors"]["maxItems"] == 12
    assert set(env["properties"]["light"]["properties"]) == {
        "time_of_day", "mood", "key_direction"}


def test_validate_args_rejects_out_of_range_t_and_unknown_verb():
    schema = EMIT_SHOT_DRAFT_PARAMETERS
    bad_t = {"shot_id": "shot_001", "beats": [
        {"t": 1.5, "subject": "char_001", "verb": "walk_to"}]}
    assert validate_args(schema, bad_t)
    bad_verb = {"shot_id": "shot_001", "beats": [
        {"t": 0.5, "subject": "char_001", "verb": "teleport"}]}
    assert validate_args(schema, bad_verb)
    good = {"shot_id": "shot_001", "beats": [
        {"t": 0.5, "subject": "char_001", "verb": "walk_to", "target": "door"}]}
    assert validate_args(schema, good) == []


def test_extract_draft_rejects_bad_beats_and_break_without_reason():
    import pytest
    # 越界 t：validate_beats 也会拒（不只 schema）
    with pytest.raises(ValueError):
        extract_draft(_reply({"shot_id": "shot_001", "beats": [
            {"t": 2.0, "subject": "char_001", "verb": "walk_to"}]}), "shot_001")
    # break 必填 reason
    with pytest.raises(ValueError):
        extract_draft(_reply({"shot_id": "shot_001", "rule_justifications": [
            {"rule": "R001", "action": "break"}]}), "shot_001")
    # target 既不在角色表也不在锚点表
    with pytest.raises(ValueError):
        extract_draft(_reply({"shot_id": "shot_001", "beats": [
            {"t": 0.3, "subject": "char_001", "verb": "walk_to",
             "target": "nonexistent"}]}), "shot_001",
            characters=["char_001"], anchors=["door"])


def test_extract_and_merge_valid_draft():
    draft = extract_draft(_reply({
        "shot_id": "shot_001",
        "beats": [{"t": 0.0, "subject": "char_001", "verb": "walk_to",
                   "target": "door", "face_to": "camera", "pace": "slow"}],
        "composition": {"rule": "lead_room", "subject_position": "left_third"},
        "rule_justifications": [{"rule": "R001", "action": "follow"}],
    }), "shot_001", characters=["char_001"], anchors=["door"])
    merged = merge_draft(_plan(), draft)
    shot = merged.shots[0]
    assert shot.beats[0]["target"] == "door"
    assert shot.composition["rule"] == "lead_room"
    assert shot.rule_justifications[0]["rule"] == "R001"
    # actions 仍是既有字段（beats 与 actions 并存，不在契约层做有损合并）
    assert shot.actions == []


def test_old_draft_without_new_keys_merges_unchanged():
    """离线/回放兼容：没有新键的草案行为不变。"""
    draft = extract_draft(_reply({"shot_id": "shot_001"}), "shot_001",
                          characters=["char_001"], anchors=["door"])
    merged = merge_draft(_plan(), draft)
    shot = merged.shots[0]
    assert shot.beats == []
    assert shot.composition == {}
    assert shot.rule_justifications == []
    # 计划级的 environment 不受草案影响
    assert merged.environment["anchors"][0]["name"] == "door"
