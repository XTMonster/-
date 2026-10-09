"""v1.6 G2：草案合入前的"无人看见的走位跨线"前置闸（纯层）。"""

from __future__ import annotations

from block_director.contracts.plan import Plan, ShotPlan
from block_director.layer5_orchestrator.driver import unseen_axis_crossing


def _shot(order, characters, walk_target=None):
    payload = {"shot_id": f"shot_{order:03d}", "order": order,
               "intent": "推进", "shot_type": "MS",
               "duration_frames": 48, "characters": list(characters)}
    if walk_target is not None:
        payload["actions"] = [{
            "character_id": "乙", "action_type": "walk_to",
            "start_frame": 1, "end_frame": 48,
            "params": {"target_position": list(walk_target)}}]
    return ShotPlan.from_dict(payload)


def _plan(*shots):
    return Plan(shots=list(shots), scene_heading="INT. 码头 - 日")


FLIP = (-4.0, 2.0, 0.0)   # 乙绕到甲的另一侧：连线掉头（≈147°）
AWAY = (1.5, -1.0, 0.0)   # 乙只是走开一点：连线只转 ≈22.6°（< 30° 阈值）


def test_a_hidden_flip_is_rejected_with_guidance():
    plan = _plan(_shot(1, ("甲", "乙")),
                 _shot(2, ("甲",), FLIP))
    problem = unseen_axis_crossing(plan, None, "shot_002")
    assert problem and "shot_002" in problem and "观众看不见" in problem


def test_a_visible_flip_passes():
    plan = _plan(_shot(1, ("甲", "乙")),
                 _shot(2, ("甲", "乙"), FLIP))
    assert unseen_axis_crossing(plan, None, "shot_002") is None


def test_a_small_walk_away_under_thirty_degrees_passes():
    plan = _plan(_shot(1, ("甲", "乙")),
                 _shot(2, ("甲",), AWAY))
    assert unseen_axis_crossing(plan, None, "shot_002") is None


def test_a_thirty_plus_degree_hidden_walk_is_rejected():
    """30–90° 带与审核同口径：≥30° 且没被同框/中性交代 ⇒ 拒绝。"""
    plan = _plan(_shot(1, ("甲", "乙")),
                 _shot(2, ("甲",), (0.9, -4.0, 0.0)))   # ≈65.8°
    problem = unseen_axis_crossing(plan, None, "shot_002")
    assert problem and "漂移" in problem


def test_no_pair_means_no_gate():
    plan = _plan(_shot(1, ("甲",)),
                 _shot(2, ("乙",), FLIP))
    assert unseen_axis_crossing(plan, None, "shot_002") is None
