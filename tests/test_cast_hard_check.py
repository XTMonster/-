"""v1.6 A2 / D-11：角色表硬校验。

- 计划 characters 含表外 id（占位符如 char_a/char_b）⇒ error 并重问。
- 合法内部 id（char_001 形且已在角色表里）放行。
- 交付前自检发现表外 id 拒绝导出。
"""

from __future__ import annotations

import pytest

from block_director.contracts.cast import CastMember, SceneSpec
from block_director.contracts.enums import ErrorCode, ShotType
from block_director.contracts.errors import user_message
from block_director.contracts.plan import Plan, ShotPlan, unknown_cast_ids


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
