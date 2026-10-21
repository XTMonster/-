"""Ticket 01：粗编排参考 JSON 契约 + 粗排处方生成器。

纯层验收（不 import bpy）：

- 粗编排参考 JSON（CoarseWorldReference）读写 round-trip 逐位一致、版本化、
  指纹可复现、轻量结构守卫报 findings；
- 从 BlockoutReport 生成结构化粗排处方：{scope, shot_id, entity, component,
  axis, direction, magnitude, current_value, target_value, derived_from}；
- 无误差来源时不产出凭空处方。
"""

from __future__ import annotations

from block_director.contracts.coarse_reference import (
    COARSE_REFERENCE_SCHEMA_VERSION,
    canonical_fingerprint,
    dump_coarse_reference,
    load_coarse_reference,
    validate_coarse_reference,
)
from block_director.cinema.coarse_revision import build_coarse_prescriptions


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
            "position": [-0.5, 5.5, 2.0],
            "target": [-0.2, 0.0, 0.8],
            "lens": 35.0, "fov_deg": 54.4,
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


def _report(findings=(), checks=()):
    return {
        "schema_version": "blockout-report/v1",
        "manifest_fingerprint": "abc",
        "verdict": "fail" if findings else "pass",
        "findings": [dict(f) for f in findings],
        "checks": [dict(c) for c in checks],
        "notes": [],
    }


# ---------------------------------------------------------------------------
# 契约：round-trip / 版本 / 指纹 / 守卫

def test_dump_load_round_trip_is_byte_identical():
    doc = _reference()
    first = dump_coarse_reference(doc)
    second = dump_coarse_reference(doc)
    assert first == second
    reloaded = load_coarse_reference(first)
    assert reloaded == doc


def test_schema_version_is_pinned():
    doc = _reference()
    assert doc["schema_version"] == "coarse-world-reference/v1"
    errors = validate_coarse_reference({**doc, "schema_version": "oops"})
    assert any("schema_version" in e for e in errors)


def test_validate_flags_missing_and_bad_sections():
    errors = validate_coarse_reference({})
    for key in ("characters", "props", "anchors", "camera_intents",
                "shots", "revisions"):
        assert any(key in e for e in errors)

    bad = _reference(characters="not-a-list")
    errors = validate_coarse_reference(bad)
    assert any("characters" in e for e in errors)


def test_fingerprint_is_deterministic():
    assert canonical_fingerprint(_reference()) == canonical_fingerprint(
        _reference())


# ---------------------------------------------------------------------------
# 处方生成

def test_no_issues_produces_empty_prescriptions():
    report = _report()
    assert build_coarse_prescriptions(report=report,
                                      reference=_reference()) == []


def test_empty_wall_produces_target_prescription_towards_subject():
    report = _report(findings=[{
        "check_id": "E_BLOCKOUT_EMPTY_WALL", "shot_id": "shot_001",
        "severity": "error", "message": "主体可见比例低于阈值，疑似对空墙",
    }])
    ref = _reference()
    ps = build_coarse_prescriptions(report=report, reference=ref)
    assert len(ps) == 1
    p = ps[0]
    assert p["scope"] == "camera" and p["shot_id"] == "shot_001"
    assert p["component"] == "target" and p["direction"] == "towards_subject"
    assert p["derived_from"]["check_id"] == "E_BLOCKOUT_EMPTY_WALL"
    assert p["target_value"]["x"] == -0.8  #: 指向主体质心
    assert p["applied"] is False
    assert p["current_value"] == {"x": -0.2, "y": 0.0, "z": 0.8}


def test_composition_fail_produces_distance_prescription():
    report = _report(checks=[{
        "check_id": "composition", "shot_id": "shot_001",
        "actual": 61.7, "threshold": 80.0, "verdict": "fail",
    }])
    ps = build_coarse_prescriptions(report=report, reference=_reference())
    assert len(ps) == 1
    p = ps[0]
    assert p["component"] == "distance" and p["axis"] == "distance"
    assert p["derived_from"]["check_id"] == "composition"
    assert p["derived_from"]["actual"] == 61.7
    assert p["magnitude"] > 0
    assert "position" in p["target_value"]


def test_occlusion_fail_produces_camera_raise_prescription():
    report = _report(checks=[{
        "check_id": "occlusion", "shot_id": "shot_001",
        "actual": 0.4444, "threshold": 0.5, "verdict": "fail",
    }])
    ps = build_coarse_prescriptions(report=report, reference=_reference())
    assert len(ps) == 1
    p = ps[0]
    assert p["component"] == "position.z" and p["direction"] == "up"
    assert p["magnitude"] > 0
    assert p["target_value"] == 2.0 + p["magnitude"]  #: 世界 z=2.0 抬高
    assert p["derived_from"]["check_id"] == "occlusion"


def test_off_screen_pulls_camera_back():
    report = _report(checks=[{
        "check_id": "on_screen", "shot_id": "shot_001",
        "actual": 0.02, "threshold": 0.05, "verdict": "fail",
    }])
    ps = build_coarse_prescriptions(report=report, reference=_reference())
    assert len(ps) == 1
    p = ps[0]
    assert p["component"] == "distance" and p["direction"] == "out"
    assert p["derived_from"]["check_id"] == "on_screen"


def test_unknown_shot_is_skipped_not_guessed():
    report = _report(findings=[{
        "check_id": "E_BLOCKOUT_EMPTY_WALL", "shot_id": "ghost_shot",
        "severity": "error", "message": "主体不可见",
    }])
    ps = build_coarse_prescriptions(report=report, reference=_reference())
    assert ps == []  #: 未知镜不产凭空处方
