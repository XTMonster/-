"""P2-T2：``Plan`` / ``ShotPlan`` 的 v1.5 字段（执行文档 v1.5 TDD §3.2/§3.7）。

三条必须钉住（全是"改回去就红"的形状）：

1. **四个新字段存在且有缺省**：``ShotPlan.beats`` / ``composition`` /
   ``rule_justifications`` 与 ``Plan.environment``，缺省为空；
2. **serde 双向**：``to_dict`` → ``from_dict`` 逐字等价，且**向后兼容**——
   旧载荷（没有新键）能照常读，新键回落到缺省；
3. **既有字段只增不改**：``duration_frames`` 的"唯一时长真源"地位与既有
   字段名不变（新字段不许挤掉任何旧键）。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.contracts.plan import Plan, ShotPlan  # noqa: E402


def _shot(**overrides) -> ShotPlan:
    base = dict(shot_id="shot_001", intent="推进", shot_type="MS",
                duration_frames=72)
    base.update(overrides)
    return ShotPlan(**base)


def test_new_fields_default_to_empty():
    shot = _shot()
    assert shot.beats == []
    assert shot.composition == {}
    assert shot.rule_justifications == []
    assert Plan().environment == {}


def test_shot_plan_round_trips_with_new_fields():
    shot = _shot(
        beats=[{"t": 0.0, "subject": "char_001", "verb": "walk_to",
                "target": "door", "face_to": "camera", "pace": "slow",
                "react": "迟疑"}],
        composition={"rule": "lead_room", "subject_position": "left_third"},
        rule_justifications=[{"rule": "R001", "action": "break",
                              "reason": "表现关系破裂", "precedent": "Shining"}],
    )
    again = ShotPlan.from_dict(shot.to_dict())
    assert again.to_dict() == shot.to_dict()
    assert again.beats[0]["verb"] == "walk_to"
    assert again.composition["rule"] == "lead_room"
    assert again.rule_justifications[0]["action"] == "break"


def test_plan_round_trips_environment_host():
    plan = Plan(
        scene_heading="EXT. 码头 - 黄昏",
        # order 显式给 1：`Plan.from_dict` 会把 order==0 的镜头补成序号，
        # 那是既有行为；本用例测的是环境宿主，别把它混进来。
        shots=[_shot(order=1)],
        environment={
            "anchors": [{"name": "door", "depth": "bg", "relation": "behind 甲"}],
            "light": {"time_of_day": "dusk", "mood": "soft"},
        },
    )
    again = Plan.from_dict(plan.to_dict())
    assert again.to_dict() == plan.to_dict()
    assert again.environment["anchors"][0]["name"] == "door"
    assert again.environment["light"]["time_of_day"] == "dusk"


def test_old_payload_without_new_keys_still_loads():
    """向后兼容：v1.4 的载荷（没有新键）必须零改动地读出来。"""
    payload = {
        "scene_heading": "INT. 房间 - 日",
        "continuity_notes": ["承上"],
        "shots": [{"shot_id": "shot_002", "intent": "反应", "shot_type": "CU",
                   "duration_frames": 48, "characters": ["char_001"]}],
    }
    plan = Plan.from_dict(payload)
    assert plan.environment == {}
    assert plan.shots[0].beats == []
    assert plan.shots[0].composition == {}
    assert plan.shots[0].rule_justifications == []
    # 既有字段原样读出
    assert plan.shots[0].shot_type == "CU"
    assert plan.shots[0].duration_frames == 48


def test_no_old_field_was_removed():
    """既有字段名一个都不许丢（新字段是**追加**，不是替换）。"""
    keys = set(_shot().to_dict())
    for name in ("shot_id", "order", "intent", "shot_type", "duration_frames",
                 "characters", "dialogue_ids", "actions", "dialogues", "prompt",
                 "camera", "axis_note", "continuity_in", "gaze", "vfx",
                 "declared_duration_frames", "declared_shot_number",
                 "declared_camera_move", "intent_type", "dialogue_pins"):
        assert name in keys, name
    plan_keys = set(Plan().to_dict())
    for name in ("scene_heading", "continuity_notes", "shots"):
        assert name in plan_keys, name
