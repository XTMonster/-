"""§10.2 排片器：唯一时间轴真源的纯计算测试。"""

from __future__ import annotations

from block_director.cinema.schedule import shot_ranges, total_frames
from block_director.contracts.plan import Plan


def plan_with(durations) -> Plan:
    return Plan.from_dict({"shots": [
        {"shot_id": f"shot_{index:03d}", "order": index, "intent": "x",
         "shot_type": "MS", "duration_frames": duration}
        for index, duration in enumerate(durations, start=1)]})


def test_ranges_are_contiguous_from_frame_one():
    ranges = shot_ranges(plan_with([72, 96, 120]))
    assert ranges == {"shot_001": (1, 72), "shot_002": (73, 168),
                      "shot_003": (169, 288)}


def test_total_frames_matches_the_last_shot():
    plan = plan_with([72, 96, 120])
    assert total_frames(plan) == 288
    assert total_frames(plan) == plan.total_frames


def test_zero_and_negative_durations_are_treated_as_one_frame():
    """坏数据不该让排片产生空区间或倒退。"""
    ranges = shot_ranges(plan_with([0, -5, 10]))
    assert ranges == {"shot_001": (1, 1), "shot_002": (2, 2),
                      "shot_003": (3, 12)}


def test_empty_plan_has_no_frames():
    plan = Plan.from_dict({"shots": []})
    assert shot_ranges(plan) == {}
    assert total_frames(plan) == 0


def test_ranges_follow_plan_order_not_shot_id():
    plan = Plan.from_dict({"shots": [
        {"shot_id": "shot_b", "order": 1, "shot_type": "MS",
         "duration_frames": 10},
        {"shot_id": "shot_a", "order": 2, "shot_type": "MS",
         "duration_frames": 10}]})
    assert shot_ranges(plan) == {"shot_b": (1, 10), "shot_a": (11, 20)}
