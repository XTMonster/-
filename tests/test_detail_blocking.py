"""Ticket 04：细排数据契约 DetailShotContract + 从冻结基准派生。

纯层验收（不 import bpy）：

- DetailShotContract 字段齐全（角色/道具/相机/节拍/音频代理），版本化可校验；
- 从冻结基准 + plan 确定性派生，两次派生逐位一致；
- 派生坐标与冻结基准一致（继承不漂移）；需改全局空间的点被标记为
  退回粗排审批而非静默修改。
"""

from __future__ import annotations

from block_director.contracts.detail_blocking import (
    DETAIL_SHOT_SCHEMA_VERSION,
    validate_detail_shots,
)
from block_director.cinema.detail_blocking import (
    E_DETAIL_SPATIAL_DRIFT,
    derive_detail_shots,
    spatial_drift_review,
)


def _baseline(**overrides):
    doc = {
        "schema_version": "coarse-baseline/v1",
        "state": "frozen",
        "checkpoint_id": "scene_01_blockout.blend",
        "produced_at": "t0", "approved_by": "test",
        "reference_fingerprint": "fp", "manifest_fingerprint": "fp2",
        "cameras_fingerprint": "fp3", "report_fingerprint": "fp4",
        "approval": {"state": "frozen"},
        "reference": {
            "schema_version": "coarse-world-reference/v1",
            "scene_id": "dock_fly_bomb",
            "characters": [
                {"name": "米迦尔", "position": {"x": -0.8, "y": 0.0, "z": 0.0},
                 "facing": [0.0, 1.0, 0.0],
                 "gaze": None, "rotation": None, "motion_by_shot": []},
                {"name": "偷盗者", "position": {"x": 1.8, "y": 0.0, "z": 0.0},
                 "facing": [0.0, -1.0, 0.0],
                 "gaze": None, "rotation": None, "motion_by_shot": []},
            ],
            "props": [{"id": "枪", "kind": "prop",
                       "position": {"x": 1.8, "y": 0.0, "z": 1.2},
                       "rotation": None, "motion": None, "owner": "偷盗者"}],
            "anchors": [],
            "camera_intents": [{
                "shot_id": "shot_001",
                "position": {"x": -0.5, "y": 5.5, "z": 2.0},
                "target": {"x": -0.2, "y": 0.0, "z": 0.8},
                "lens_mm": 35.0, "fov_deg": 54.4, "movement": None,
                "provenance": "script_declaration", "resolved": True,
            }],
            "shots": [{
                "shot_id": "shot_001", "order": 1, "duration_frames": 72,
                "intent": "飞扑建立空间", "characters": ["米迦尔", "偷盗者"],
                "actions": [{"action": "飞扑", "target": "偷盗者"}],
            }],
            "revisions": [], "notes": [],
        },
        "manifest": {"schema_version": "blockout-manifest/v1",
                     "cameras": [], "primitives": [], "shot_table": [],
                     "asset_registry": [], "scene_prop_ids": [],
                     "checkpoints": [], "notes": []},
        "report": {"schema_version": "blockout-report/v1",
                   "findings": [], "checks": [], "verdict": "pass"},
    }
    doc.update(overrides)
    return doc


def _plan():
    return {"shots": [{
        "shot_id": "shot_001", "order": 1, "duration_frames": 72,
        "intent": "飞扑建立空间", "characters": ["米迦尔", "偷盗者"],
        "actions": [{"action": "飞扑", "target": "偷盗者"}],
        "camera": {"side": "front", "lens": 35},
    }]}


def test_derive_produces_detailed_shots_from_frozen_baseline():
    shots = derive_detail_shots(baseline=_baseline(), plan=_plan())
    assert len(shots) == 1
    shot = shots[0]
    assert shot["schema_version"] == DETAIL_SHOT_SCHEMA_VERSION
    assert shot["shot_id"] == "shot_001"
    assert shot["start_frame"] == 1 and shot["end_frame"] == 72
    names = [c["name"] for c in shot["characters"]]
    assert "米迦尔" in names and "偷盗者" in names
    assert shot["camera"]["position"] == {
        "x": -0.5, "y": 5.5, "z": 2.0}
    assert shot["camera"]["target"] == {"x": -0.2, "y": 0.0, "z": 0.8}
    assert shot["props"] and shot["props"][0]["id"] == "枪"
    assert validate_detail_shots(shots) == []


def test_character_positions_inherit_baseline():
    shots = derive_detail_shots(baseline=_baseline(), plan=_plan())
    by_name = {c["name"]: c for c in shots[0]["characters"]}
    assert by_name["米迦尔"]["position"] == {
        "x": -0.8, "y": 0.0, "z": 0.0}
    assert by_name["偷盗者"]["position"] == {
        "x": 1.8, "y": 0.0, "z": 0.0}
    assert shots[0]["characters"][0]["source"] == "frozen_baseline"


def test_derivation_is_deterministic():
    import json
    a = derive_detail_shots(baseline=_baseline(), plan=_plan())
    b = derive_detail_shots(baseline=_baseline(), plan=_plan())
    assert json.dumps(a, ensure_ascii=False,
                      sort_keys=True) == json.dumps(
        b, ensure_ascii=False, sort_keys=True)


def test_spatial_drift_flags_global_space_change():
    baseline = _baseline()
    plan = _plan()
    plan["shots"][0]["characters"] = ["米迦尔", "偷盗者", "伊恩"]
    shots = derive_detail_shots(baseline=baseline, plan=plan)
    findings = spatial_drift_review(shots, baseline)
    drifts = [f for f in findings
              if f["check_id"] == E_DETAIL_SPATIAL_DRIFT]
    assert drifts, "新增角色未在冻结基准中，必须标记退回粗排审批"
    assert drifts[0]["severity"] == "error"


def test_no_drift_when_positions_match():
    shots = derive_detail_shots(baseline=_baseline(), plan=_plan())
    findings = spatial_drift_review(shots, _baseline())
    assert [f for f in findings
            if f["check_id"] == E_DETAIL_SPATIAL_DRIFT] == []
