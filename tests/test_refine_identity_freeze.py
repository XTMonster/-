"""R2 Ticket 07 (S2)：精修不得改写镜头主体集合与景别。

缺陷 S2：修复/精修阶段重新提交的 ``emit_shot_draft`` 通过
``merge_draft`` 可以**静默改写**镜头的 ``shot_type``（景别）、
``characters``（主体集合）与 ``framing_target``（拍对象）——
spec 要求精修阶段冻结这三组字段：冲突必须报 E 类错误、保留计划原值、
不得静默改写计划（``spec_r2.md`` §S2）。

本文件钉住三层：

1. ``ShotDraft`` 能携带 ``framing_target``（草案 schema 本就暴露它，
   旧实现把它静默丢弃——连"冲突检测"的机会都没有）；
2. ``identity_conflicts(plan, draft)`` 纯函数：草案试图改
   shot_type / characters / framing_target 时给出冲突清单，没改返回空；
3. ``merge_draft(plan, draft, freeze_identity=True)`` 保留计划原值，
   只合并动作/对白等非身份字段；默认（B1 起草）行为不变。

纯层测试，不 import bpy；红线：不改判据、不改阈值、不删既有测试。
"""

from __future__ import annotations

from block_director.contracts.plan import FramingTarget, Plan, ShotPlan
from block_director.layer5_orchestrator.editor import (
    ShotDraft,
    identity_conflicts,
    merge_draft,
)


def _plan() -> Plan:
    return Plan(shots=[ShotPlan(
        shot_id="shot_001", order=1, intent="推进", shot_type="CU",
        duration_frames=72, characters=["char_001"],
        framing_target=FramingTarget(kind="character", ref="char_001",
                                     part="hand"),
    )])


def _draft(**overrides) -> ShotDraft:
    payload = {
        "shot_id": "shot_001",
        "actions": [{"character_id": "char_001", "action_type": "nod",
                     "start_frame": 1, "end_frame": 40}],
        "dialogues": [],
        "camera": {"side": "left", "lens": 35},
        "prompt": "雨夜客厅，特写",
    }
    payload.update(overrides)
    return ShotDraft.from_dict(payload)


# --------------------------------------------------------------------------- #
# ShotDraft round-trip
# --------------------------------------------------------------------------- #
def test_shot_draft_roundtrips_framing_target():
    draft = _draft(framing_target={
        "kind": "character", "ref": "char_001", "part": "hand",
        "anchor_offset": None})
    assert draft.framing_target == {
        "kind": "character", "ref": "char_001", "part": "hand",
        "anchor_offset": None}
    again = ShotDraft.from_dict(draft.to_dict())
    assert again.framing_target == draft.framing_target


def test_shot_draft_without_framing_target_is_none():
    assert _draft().framing_target is None


# --------------------------------------------------------------------------- #
# identity_conflicts
# --------------------------------------------------------------------------- #
def test_no_conflict_when_draft_matches_plan_identity():
    draft = _draft(shot_type="CU", characters=["char_001"],
                   framing_target={"kind": "character", "ref": "char_001",
                                   "part": "hand", "anchor_offset": None})
    assert identity_conflicts(_plan(), draft) == []


def test_no_conflict_when_draft_omits_identity_fields():
    assert identity_conflicts(_plan(), _draft()) == []


def test_conflict_when_draft_changes_shot_type():
    conflicts = identity_conflicts(_plan(), _draft(shot_type="MS"))
    assert len(conflicts) == 1
    assert "shot_type" in conflicts[0]


def test_conflict_when_draft_changes_characters():
    conflicts = identity_conflicts(_plan(), _draft(characters=["char_002"]))
    assert len(conflicts) == 1
    assert "characters" in conflicts[0]


def test_conflict_when_draft_changes_framing_target():
    conflicts = identity_conflicts(_plan(), _draft(framing_target={
        "kind": "character", "ref": "char_001", "part": "face",
        "anchor_offset": None}))
    assert len(conflicts) == 1
    assert "framing_target" in conflicts[0]


def test_conflicts_cover_all_three_fields_at_once():
    conflicts = identity_conflicts(_plan(), _draft(
        shot_type="MS", characters=["char_002"],
        framing_target={"kind": "prop", "ref": "银币", "part": "none",
                        "anchor_offset": None}))
    assert len(conflicts) == 3
    assert any("shot_type" in c for c in conflicts)
    assert any("characters" in c for c in conflicts)
    assert any("framing_target" in c for c in conflicts)


def test_unknown_shot_has_no_conflicts():
    assert identity_conflicts(_plan(), _draft(shot_id="shot_999",
                                              shot_type="MS")) == []


# --------------------------------------------------------------------------- #
# merge_draft freeze_identity
# --------------------------------------------------------------------------- #
def test_freeze_keeps_plan_identity_and_merges_the_rest():
    merged = merge_draft(_plan(), _draft(
        shot_type="MS", characters=["char_002"],
        framing_target={"kind": "prop", "ref": "银币", "part": "none",
                        "anchor_offset": None}),
        freeze_identity=True)
    shot = merged.shots[0]
    assert str(shot.shot_type) == "CU"
    assert shot.characters == ["char_001"]
    assert shot.framing_target.to_dict() == {
        "kind": "character", "ref": "char_001", "part": "hand",
        "anchor_offset": None}
    # 动作/对白/相机/提示词照常合并
    assert shot.actions[0]["action_type"] == "nod"
    assert shot.camera == {"side": "left", "lens": 35}
    assert shot.prompt == "雨夜客厅，特写"


def test_freeze_noop_when_identity_matches():
    merged = merge_draft(_plan(), _draft(
        shot_type="CU", characters=["char_001"],
        framing_target={"kind": "character", "ref": "char_001",
                        "part": "hand", "anchor_offset": None}),
        freeze_identity=True)
    shot = merged.shots[0]
    assert str(shot.shot_type) == "CU"
    assert shot.characters == ["char_001"]


def test_default_merge_preserves_planned_shot_type_but_applies_draft_details():
    """B1 可以补主体与拍对象，但不得覆盖计划已经确定的景别。"""
    merged = merge_draft(_plan(), _draft(
        shot_type="MS", characters=["char_002"],
        framing_target={"kind": "prop", "ref": "银币", "part": "none",
                        "anchor_offset": None}))
    shot = merged.shots[0]
    assert str(shot.shot_type) == "CU"
    assert shot.characters == ["char_002"]
    assert shot.framing_target.to_dict() == {
        "kind": "prop", "ref": "银币", "part": "none", "anchor_offset": None}


def test_freeze_only_affects_the_target_shot():
    merged = merge_draft(_plan(), _draft(
        shot_id="shot_999", shot_type="MS"), freeze_identity=True)
    assert merged.to_dict() == _plan().to_dict()
