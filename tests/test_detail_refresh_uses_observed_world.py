"""细排构图重测必须用实测世界坐标（2026-10-21 真跑：
agent 摆位写 runtime_world_state，但 reference 停在默认站位 -> 脱节）。
"""

from __future__ import annotations

from block_director.contracts.world_state import (
    merge_observed_world_into_reference,
)


def test_merge_observed_character_and_camera_into_reference():
    ref = {
        "characters": [
            {"name": "米迦尔", "position": {"x": -0.3, "y": 0.0, "z": 0.0},
             "facing": [0.0, 1.0, 0.0], "provenance": "plan_intent"},
            {"name": "伊恩", "position": {"x": -0.3, "y": 0.0, "z": 0.0},
             "facing": [0.0, 1.0, 0.0], "provenance": "plan_intent"},
        ],
        "camera_intents": [
            {"shot_id": "shot_001", "position": [-0.3, 2.9, 1.2],
             "target": [-0.3, 0.0, 1.4], "lens": 50.0},
        ],
        "props": [], "anchors": [], "notes": [],
    }
    world = {
        "characters": {
            "伊恩": {"position": [-1.6, 0.0, 0.0],
                     "facing": [1.0, 0.0, 0.0]},
            "米迦尔": {"position": [-0.3, 0.0, 0.0],
                        "facing": [0.0, 1.0, 0.0]},
        },
        "cameras": {
            "shot_001": {"position": [2.647, -2.047, 1.231],
                         "target": [0.846, 0.246, 1.231],
                         "lens_mm": 50.0},
        },
    }
    merged = merge_observed_world_into_reference(ref, world)
    chars = {c["name"]: c for c in merged["characters"]}
    assert chars["伊恩"]["position"] == {"x": -1.6, "y": 0.0, "z": 0.0}
    assert chars["伊恩"]["provenance"] == "observed_world_state"
    cam = merged["camera_intents"][0]
    assert cam["position"] == [2.647, -2.047, 1.231]
    assert cam["provenance"] == "observed_world_state"


def test_merge_preserves_unknown_entities():
    ref = {
        "characters": [
            {"name": "偷盗者", "position": {"x": 1.5, "y": 0.0, "z": 0.0},
             "facing": [0.0, 1.0, 0.0], "provenance": "plan_intent"},
        ],
        "camera_intents": [], "props": [], "anchors": [], "notes": [],
    }
    world = {"characters": {"路人甲": {"position": [9.0, 0.0, 0.0]}}}
    merged = merge_observed_world_into_reference(ref, world)
    assert merged["characters"][0]["position"]["x"] == 1.5
    assert merged["characters"][0]["provenance"] == "plan_intent"
