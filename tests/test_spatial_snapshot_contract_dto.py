"""空间快照契约 DTO 与阈值同源（并行实现收口，纯层，不 import bpy）。

钉死：``DesignSnapshot`` / ``ObservationSnapshot`` 的 from_dict/to_dict 往返
逐位一致、缺必需键报错（不吞）；``DIFF_THRESHOLDS`` 与
``cinema.spatial_diff.REGISTRY`` 同源（阈值不散两处）。
"""

from __future__ import annotations

import json

import pytest

from block_director.contracts.spatial_snapshot import (
    DESIGN_SNAPSHOT_SCHEMA,
    DIFF_THRESHOLDS,
    OBSERVATION_SNAPSHOT_SCHEMA,
    DesignSnapshot,
    ObservationSnapshot,
)


def _design_data() -> dict:
    return {
        "$schema": f"blockdirector://spatial-snapshot/{DESIGN_SNAPSHOT_SCHEMA}",
        "schema_version": DESIGN_SNAPSHOT_SCHEMA,
        "run_context": {"run_id": "test-run"},
        "shot_ids": ["shot_001"],
        "characters": [],
        "props": [],
        "anchors": [],
        "camera_intents": [],
        "registry": {"diff_thresholds": dict(DIFF_THRESHOLDS)},
        "notes": ["确定性可重放"],
    }


def _observation_data() -> dict:
    return {
        "$schema": f"blockdirector://spatial-snapshot/"
                   f"{OBSERVATION_SNAPSHOT_SCHEMA}",
        "schema_version": OBSERVATION_SNAPSHOT_SCHEMA,
        "run_context": {"run_id": "obs-run"},
        "shots": [],
        "notes": ["全部来自 blender_geometry"],
    }


def test_design_snapshot_dto_round_trip():
    original = DesignSnapshot.from_dict(_design_data())
    restored = DesignSnapshot.from_dict(
        json.loads(json.dumps(original.to_dict())))
    assert restored.to_dict() == original.to_dict()
    assert restored.to_dict()["schema_version"] == DESIGN_SNAPSHOT_SCHEMA


def test_observation_snapshot_dto_round_trip():
    original = ObservationSnapshot.from_dict(_observation_data())
    restored = ObservationSnapshot.from_dict(
        json.loads(json.dumps(original.to_dict())))
    assert restored.to_dict() == original.to_dict()
    assert restored.to_dict()["schema_version"] == OBSERVATION_SNAPSHOT_SCHEMA


def test_dto_from_dict_rejects_non_mapping():
    with pytest.raises(TypeError):
        DesignSnapshot.from_dict([1, 2, 3])


def test_dto_from_dict_rejects_missing_required_keys():
    with pytest.raises(ValueError):
        DesignSnapshot.from_dict({"schema_version": DESIGN_SNAPSHOT_SCHEMA})
    with pytest.raises(ValueError):
        ObservationSnapshot.from_dict({"schema_version":
                                       OBSERVATION_SNAPSHOT_SCHEMA})


def test_diff_thresholds_matches_cinema_registry():
    from block_director.cinema.spatial_diff import REGISTRY

    assert REGISTRY == DIFF_THRESHOLDS
    assert set(REGISTRY) == {
        "camera_position_m", "character_position_m", "heading_angle_deg",
        "gaze_angle_deg", "motion_displacement_m", "speed_delta_m_s",
    }
