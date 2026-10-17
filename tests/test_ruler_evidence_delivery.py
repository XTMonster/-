"""空间尺观测交付证据测试（Ticket 06 纯层）。

``block_director/delivery/ruler_evidence.py`` 把计划级处方、逐镜几何测量、
compliance 判定折成一份完整的 ``ruler_observation.json`` bundle
（契约四族：shot_specs / camera_specs / measurements / verdicts /
prescriptions），并让 ``shots.json`` 顶层引用它。纯层、无 bpy。
"""

from __future__ import annotations

from block_director.contracts.plan import Plan, ShotPlan
from block_director.contracts.spatial_ruler import validate_bundle
from block_director.delivery.manifest import build_manifest
from block_director.delivery.ruler_evidence import (
    assemble_bundle,
    camera_specs_from_results,
    map_compliance_verdicts,
    shot_specs_from_plan,
)


def _plan() -> Plan:
    plan = Plan(scene_heading="码头")
    plan.shots = [
        ShotPlan("shot_001", "建立", "ELS", 120, characters=["米迦尔"]),
        ShotPlan("shot_002", "推进", "MS", 96, characters=["伊恩"]),
    ]
    return plan


def test_bundle_assembles_and_validates() -> None:
    plan = _plan()
    bundle, findings = assemble_bundle(
        observation_id="obs_test",
        run_context={"source_run": "", "model": "test", "status": "offline"},
        plan=plan,
        measurements=[
            {"measurement_id": "m_shot_001_shot_duration_planned",
             "shot_id": "shot_001", "transition_id": None, "subject_id": None,
             "frame": None, "metric": "shot_duration_planned", "value": 5.0,
             "expected": None, "unit": "seconds", "source": "plan_intent",
             "provenance": "plan_intent"},
        ],
        verdicts=[],
        prescriptions=[],
    )
    assert findings == []
    assert validate_bundle(bundle) == []
    assert bundle["schema_version"] == "spatial-ruler-observation/v2"
    assert len(bundle["shot_specs"]) == 2
    assert bundle["shot_specs"][0]["shot_id"] == "shot_001"


def test_shot_specs_carry_declared_and_planned() -> None:
    specs = shot_specs_from_plan(_plan())
    first = specs[0]
    assert first["shot_id"] == "shot_001"
    assert first["order"] == 1                  # 按枚举顺序（1-based）
    assert first["declared"]["duration_frames"] == 120
    assert first["declared"]["characters"] == ["米迦尔"]
    assert first["planned"]["shot_type"] == "ELS"


def test_camera_specs_from_build_results() -> None:
    plan = _plan()
    build_summary = {
        "results": [
            {"shot_id": "shot_001", "camera": "BD_Cam_shot_001",
             "lens": 35.0, "camera_position": [0.0, -5.0, 1.6]},
            {"shot_id": "shot_002", "camera": "BD_Cam_shot_002",
             "lens": 50.0, "camera_position": [1.0, -3.0, 1.5]},
        ],
    }
    specs = camera_specs_from_results(plan, build_summary)
    assert specs[0]["lens"] == 35.0
    assert specs[0]["source"] == "plan_intent"
    assert specs[1]["shot_type"] == "MS"


def _finding(rule: str, severity: str, target: str = "shot_001") -> dict:
    return {"code": "E_AXIS_001", "rule": rule, "severity": severity,
            "target": target, "message": "样例", "suggestion": "建议"}


def test_compliance_verdicts_map_with_full_numeric_keys() -> None:
    compliance = {
        "ok": False,
        "findings": [_finding("R010", "warning"), _finding("SR001", "error")],
    }
    verdicts = map_compliance_verdicts(compliance)
    by_rule = {v["rule_code"]: v for v in verdicts}
    assert by_rule["R010"]["status"] == "warning"
    assert by_rule["SR001"]["status"] == "repair"
    for verdict in verdicts:
        for key in ("expected", "actual", "threshold", "unit"):
            assert key in verdict, key


def test_manifest_carries_ruler_reference_only_when_present() -> None:
    plain = build_manifest(_plan(), generated_at="t")
    assert "ruler_observation" not in plain
    enriched = build_manifest(
        _plan(), generated_at="t",
        ruler_observation={"file": "ruler_observation.json",
                           "schema_version": "spatial-ruler-observation/v2",
                           "measurement_count": 3,
                           "prescription_count": 1})
    assert enriched["ruler_observation"]["file"] == "ruler_observation.json"
    assert enriched["ruler_observation"]["measurement_count"] == 3
