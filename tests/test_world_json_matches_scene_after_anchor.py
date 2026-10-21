"""R2 Ticket 06（S1）：锚点解析结果落入 runtime_world_state.json 并与场景 1e-4 一致。

纯层验收（不 import bpy）：
- ``divergence_report`` 必须把 ``anchors`` 表纳入四表比对（characters /
  cameras / props / anchors）；
- 无锚点（空表）不产生任何 finding（零形状差）；
- 锚点坐标差 ≤1e-4 一致、>1e-4 逐条给出带路径的 finding。
"""

from __future__ import annotations

from block_director.contracts.world_state import divergence_report
from block_director.cinema.staging import solve_anchor_positions


CAST = {
    "米迦尔": {"position": (0.0, 0.0, 0.0), "facing": (1.0, 0.0, 0.0)},
}


def _runtime_payload(anchor_position):
    """与 ``layer3_engine/world_state.collect_world_state`` 同形状的 payload。"""
    return {
        "schema_version": "runtime-world/v1",
        "characters": {
            "米迦尔": {"position": [0.0, 0.0, 0.0],
                       "facing": [1.0, 0.0, 0.0]},
        },
        "cameras": {},
        "props": {},
        "anchors": {"生蚝摊": {"position": list(anchor_position)}},
    }


def test_anchor_positions_flow_into_runtime_payload():
    """验收 3：求解器坐标可直接落进 runtime_world_state.json 的 anchors 表。"""
    positions, problems = solve_anchor_positions(
        [{"name": "生蚝摊", "relation": "米迦尔旁 2 米"}], CAST)
    assert problems == []
    payload = _runtime_payload(positions["生蚝摊"])
    assert payload["anchors"]["生蚝摊"]["position"] == [0.0, 2.0, 0.0]


def test_anchor_solution_matches_live_scene_within_tolerance():
    """场景读数与 JSON 差 ≤1e-4 ⇒ 空 finding（一致）。"""
    payload = _runtime_payload([0.0, 2.0, 0.0])
    live = _runtime_payload([0.00001, 2.0, 0.0])   # 1e-5 差，容差内
    assert divergence_report(payload, live) == []


def test_anchor_drift_beyond_tolerance_is_reported():
    """差 2e-4 超容差 ⇒ 给出带路径的 finding（anchors.<name>.position）。"""
    payload = _runtime_payload([0.0, 2.0, 0.0])
    live = _runtime_payload([0.0, 2.0002, 0.0])    # 2e-4 差，超容差
    report = divergence_report(payload, live)
    assert len(report) == 1
    assert report[0]["path"] == "anchors.生蚝摊.position"
    assert report[0]["max_delta"] > 1e-4


def test_no_anchors_is_zero_shape_difference():
    """两侧都没有 anchors ⇒ 空 finding，不产生噪音。"""
    base = {
        "schema_version": "runtime-world/v1",
        "characters": {}, "cameras": {}, "props": {},
    }
    assert divergence_report(base, base) == []


def test_missing_anchor_on_one_side_is_reported():
    """JSON 有、场景缺（或反之）⇒ 逐键比对必须发现差异。"""
    payload = _runtime_payload([0.0, 2.0, 0.0])
    live = {
        "schema_version": "runtime-world/v1",
        "characters": {}, "cameras": {}, "props": {}, "anchors": {},
    }
    report = divergence_report(payload, live)
    assert any(item["path"] == "anchors.生蚝摊.position"
               for item in report)
