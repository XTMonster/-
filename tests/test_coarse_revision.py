"""Ticket 02：粗排处方应用器 + 修正留痕（纯层，不 import bpy）。

- 修改只发生在粗编排参考 JSON，不写 Blender 场景；
- 每条应用记录含 before/after 与指纹；两次应用逐位一致（确定性）；
- 未知实体/未知轴返回显式未应用记录而不是吞错。
"""

from __future__ import annotations

from block_director.contracts.coarse_reference import (
    COARSE_REFERENCE_SCHEMA_VERSION,
    coarse_reference_content_fingerprint,
    dump_coarse_reference,
    validate_coarse_reference,
)
from block_director.cinema.coarse_revision import apply_coarse_prescriptions


def _reference(**overrides):
    doc = {
        "schema_version": COARSE_REFERENCE_SCHEMA_VERSION,
        "scene_id": "dock_fly_bomb",
        "characters": [
            {"name": "米迦尔", "position": {"x": -0.8, "y": 0.0, "z": 0.0},
             "facing": [0.0, 1.0, 0.0], "rotation": None,
             "gaze": None, "motion_by_shot": []},
        ],
        "props": [],
        "anchors": [],
        "camera_intents": [{
            "shot_id": "shot_001",
            "position": {"x": -0.5, "y": 5.5, "z": 2.0},
            "target": {"x": -0.2, "y": 0.0, "z": 0.8},
            "lens_mm": 35.0, "fov_deg": 54.4,
            "movement": None, "provenance": "script_declaration",
            "resolved": True,
        }],
        "shots": [{
            "shot_id": "shot_001", "order": 1, "duration_frames": 72,
            "intent": "飞扑建立空间", "characters": ["米迦尔"],
            "actions": [],
        }],
        "revisions": [],
        "notes": [],
    }
    doc.update(overrides)
    return doc


def test_target_prescription_rewrites_camera_target():
    ref = _reference()
    new_ref, records = apply_coarse_prescriptions(ref, [{
        "prescription_id": "p1", "scope": "camera", "shot_id": "shot_001",
        "entity": "cam_shot_001", "component": "target",
        "target_value": {"x": -0.8, "y": 0.0, "z": 0.9},
    }])
    assert new_ref["camera_intents"][0]["target"] == {
        "x": -0.8, "y": 0.0, "z": 0.9}
    assert records[0]["applied"] is True
    assert records[0]["before"]["target"] == {
        "x": -0.2, "y": 0.0, "z": 0.8}
    assert validate_coarse_reference(new_ref) == []


def test_distance_prescription_moves_position_along_sightline():
    ref = _reference()
    new_ref, records = apply_coarse_prescriptions(ref, [{
        "prescription_id": "p2", "scope": "camera", "shot_id": "shot_001",
        "entity": "cam_shot_001", "component": "distance",
        "target_value": {"position": {"x": -0.2, "y": 4.7, "z": 1.9},
                         "target": {"x": -0.2, "y": 0.0, "z": 0.8}},
    }])
    assert new_ref["camera_intents"][0]["position"] == {
        "x": -0.2, "y": 4.7, "z": 1.9}
    assert records[0]["applied"] is True


def test_position_y_prescription_raises_camera():
    ref = _reference()
    new_ref, records = apply_coarse_prescriptions(ref, [{
        "prescription_id": "p3", "scope": "camera", "shot_id": "shot_001",
        "entity": "cam_shot_001", "component": "position.y",
        "target_value": 5.9445,
    }])
    assert new_ref["camera_intents"][0]["position"]["y"] == 5.9445
    assert records[0]["applied"] is True


def test_unknown_shot_is_reported_not_applied():
    ref = _reference()
    new_ref, records = apply_coarse_prescriptions(ref, [{
        "prescription_id": "p4", "scope": "camera", "shot_id": "ghost",
        "entity": "cam_ghost", "component": "target",
        "target_value": {"x": 0.0, "y": 0.0, "z": 0.0},
    }])
    #: 实体未变（留痕写的是 revisions 元数据，不影响世界坐标内容）
    assert new_ref["camera_intents"] == ref["camera_intents"]
    assert records[0]["applied"] is False
    assert "ghost" in records[0]["reason"]
    assert len(new_ref["revisions"]) == 1


def test_unknown_component_is_reported_not_applied():
    ref = _reference()
    new_ref, records = apply_coarse_prescriptions(ref, [{
        "prescription_id": "p5", "scope": "camera", "shot_id": "shot_001",
        "entity": "cam_shot_001", "component": "lens_magic",
        "target_value": 999.0,
    }])
    assert new_ref["camera_intents"] == ref["camera_intents"]
    assert records[0]["applied"] is False
    assert "lens_magic" in records[0]["reason"]


def test_revision_history_is_written_with_fingerprints():
    ref = _reference()
    before_fp = coarse_reference_content_fingerprint(ref)
    new_ref, records = apply_coarse_prescriptions(
        ref, [{
            "prescription_id": "p6", "scope": "camera",
            "shot_id": "shot_001", "entity": "cam_shot_001",
            "component": "position.y", "target_value": 6.0,
        }],
        revision_id="rev-20261018-1", round_no=1)
    assert len(new_ref["revisions"]) == 1
    rev = new_ref["revisions"][0]
    assert rev["revision_id"] == "rev-20261018-1"
    assert rev["round"] == 1
    assert rev["fingerprint_before"] == before_fp
    assert rev["fingerprint_after"] == coarse_reference_content_fingerprint(
        new_ref)
    assert rev["prescriptions"][0]["prescription_id"] == "p6"


def test_no_prescriptions_returns_identical_reference():
    ref = _reference()
    new_ref, records = apply_coarse_prescriptions(ref, [])
    assert dump_coarse_reference(new_ref) == dump_coarse_reference(ref)
    assert records == []


def test_application_is_deterministic():
    p = [{
        "prescription_id": "p7", "scope": "camera", "shot_id": "shot_001",
        "entity": "cam_shot_001", "component": "position.y",
        "target_value": 6.25,
    }]
    a1, _ = apply_coarse_prescriptions(_reference(), p)
    a2, _ = apply_coarse_prescriptions(_reference(), p)
    assert dump_coarse_reference(a1) == dump_coarse_reference(a2)
