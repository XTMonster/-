"""把实测世界坐标合并进粗排参考 JSON（用户 2026-10-21 裁决：
JSON 世界坐标要实时更新；2026-10-21 真跑脱节实锤）。
"""

from __future__ import annotations

from block_director.contracts.world_state import (
    merge_observed_world_into_reference,
)


def _reference():
    return {
        "schema_version": "spatial-design-snapshot/v1",
        "scene_id": "scene",
        "characters": [
            {"name": "米迦尔", "position": {"x": -0.3, "y": 0.0, "z": 0.0},
             "facing": [0.0, 1.0, 0.0], "provenance": "plan_intent"},
            {"name": "伊恩", "position": {"x": -0.3, "y": 0.0, "z": 0.0},
             "facing": [0.0, 1.0, 0.0], "provenance": "plan_intent"},
        ],
        "props": [{"id": "金子", "position": [1.5, 0.0, 0.9],
                   "provenance": "plan_intent"}],
        "anchors": [{"label": "银币摊", "position": [2.0, 0.0, 0.0],
                     "provenance": "algorithmic_measurement"}],
        "camera_intents": [
            {"shot_id": "shot_001",
             "position": [-0.3, 2.0, 1.2], "target": [-0.3, 0.0, 1.4],
             "lens": 50.0, "provenance": "algorithmic_measurement"},
        ],
        "notes": [],
    }


def test_merges_observed_character_positions():
    ref = _reference()
    world = {
        "characters": {
            "伊恩": {"position": [-1.6, 0.0, 0.0],
                     "facing": [1.0, 0.0, 0.0]},
            "米迦尔": {"position": [-0.3, 0.0, 0.0],
                        "facing": [0.0, 1.0, 0.0]},
        },
    }
    merged = merge_observed_world_into_reference(ref, world)
    by_name = {c["name"]: c for c in merged["characters"]}
    assert by_name["伊恩"]["position"] == {
        "x": -1.6, "y": 0.0, "z": 0.0}
    assert by_name["伊恩"]["facing"] == [1.0, 0.0, 0.0]
    assert by_name["伊恩"]["provenance"] == "observed_world_state"
    # 无实测的角色保持原样
    assert by_name["米迦尔"]["position"]["x"] == -0.3


def test_merges_observed_cameras():
    ref = _reference()
    world = {
        "cameras": {
            "shot_001": {
                "position": [2.647, -2.047, 1.231],
                "target": [0.846, 0.246, 1.231],
                "lens_mm": 50.0,
            }
        },
    }
    merged = merge_observed_world_into_reference(ref, world)
    cam = merged["camera_intents"][0]
    assert cam["position"] == [2.647, -2.047, 1.231]
    assert cam["target"] == [0.846, 0.246, 1.231]
    assert cam["lens"] == 50.0
    assert cam["provenance"] == "observed_world_state"


def test_merges_props_and_anchors():
    ref = _reference()
    world = {
        "props": {"金子": {"position": [1.72, 0.25, 0.911]}},
        "anchors": {"银币摊": {"position": [2.2, -0.5, 0.0]}},
    }
    merged = merge_observed_world_into_reference(ref, world)
    assert merged["props"][0]["position"] == [1.72, 0.25, 0.911]
    assert merged["anchors"][0]["position"] == [2.2, -0.5, 0.0]
    assert merged["anchors"][0]["provenance"] == "observed_world_state"


def test_unknown_entities_stay_untouched():
    ref = _reference()
    world = {"characters": {"路人甲": {"position": [9.0, 0.0, 0.0]}}}
    merged = merge_observed_world_into_reference(ref, world)
    assert merged["characters"][0]["position"]["x"] == -0.3
    assert merged["characters"][1]["position"]["x"] == -0.3


def test_does_not_mutate_input():
    ref = _reference()
    before = __import__("copy").deepcopy(ref)
    merge_observed_world_into_reference(ref, {
        "characters": {"伊恩": {"position": [-1.6, 0.0, 0.0],
                                "facing": [1.0, 0.0, 0.0]}},
    })
    assert ref == before
