"""Local character revisions are isolated by shot staging overlays."""

from __future__ import annotations

import copy

from block_director.cinema.coarse_revision import apply_coarse_prescriptions
from block_director.cinema.shot_staging import effective_character_position


def _reference():
    return {
        "schema_version": "coarse-world-reference/v1",
        "scene_id": "scene",
        "characters": [{
            "name": "米迦尔",
            "position": {"x": 0.0, "y": 0.0, "z": 0.0},
            "facing": [0.0, 1.0, 0.0],
        }],
        "props": [],
        "anchors": [],
        "camera_intents": [
            {
                "shot_id": "shot_001",
                "position": [0.0, 3.0, 1.5],
                "target": [0.0, 0.0, 1.0],
                "lens": 35.0,
                "movement": None,
            },
            {
                "shot_id": "shot_002",
                "position": [3.0, 0.0, 1.5],
                "target": [0.0, 0.0, 1.0],
                "lens": 35.0,
                "movement": None,
            },
        ],
        "shots": [
            {
                "shot_id": "shot_001",
                "order": 1,
                "duration_frames": 24,
                "shot_type": "MS",
                "characters": ["米迦尔"],
                "actions": [],
            },
            {
                "shot_id": "shot_002",
                "order": 2,
                "duration_frames": 24,
                "shot_type": "MS",
                "characters": ["米迦尔"],
                "actions": [],
            },
        ],
        "revisions": [],
        "notes": [],
    }


def test_local_character_move_does_not_change_global_or_neighbor_shot():
    initial = _reference()
    shot_two_camera = copy.deepcopy(initial["camera_intents"][1])

    revised, records = apply_coarse_prescriptions(initial, [{
        "prescription_id": "agent_local_move",
        "scope": "character",
        "shot_id": "shot_001",
        "entity": "米迦尔",
        "component": "character_position",
        "target_value": {"x": 1.25, "y": 0.5, "z": 0.0},
        "derived_from": {"check_id": "composition", "verdict": "fail"},
    }])

    assert records[0]["applied"] is True
    assert initial["characters"][0]["position"] == {
        "x": 0.0,
        "y": 0.0,
        "z": 0.0,
    }
    assert revised["characters"][0]["position"] == {
        "x": 0.0,
        "y": 0.0,
        "z": 0.0,
    }
    assert effective_character_position(
        revised, "shot_001", "米迦尔") == {
            "x": 1.25,
            "y": 0.5,
            "z": 0.0,
        }
    assert effective_character_position(
        revised, "shot_002", "米迦尔") == {
            "x": 0.0,
            "y": 0.0,
            "z": 0.0,
        }
    assert revised["shot_staging"]["shot_001"]["米迦尔"][
        "provenance"] == "agent_local_revision"
    assert revised["camera_intents"][1] == shot_two_camera
    shot_one_target = revised["camera_intents"][0]["target"]
    assert abs(shot_one_target[0] - 1.25) < 0.5
    assert abs(shot_one_target[1] - 0.5) < 0.5

