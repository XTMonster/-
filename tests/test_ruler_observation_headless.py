"""空间尺观测 JSON 的 headless 落盘链路（Ticket 05/06 接线）。

钉住：
* driver snapshot 必须带出计划级空间尺证据
  （``spatial_ruler_plan_evidence``，即已应用处方与计划级测量）；
* 一次 headless 运行必须在运行目录落 ``spatial_ruler_observation.json``，
  且折出的观测文档通过结构校验（契约 v2）；
* 观测文档的 prescriptions 用**已应用**版本（不重算），计划级测量按
  measurement_id 去重合并，不丢也不覆盖几何侧测量。
"""

from __future__ import annotations

import json
from pathlib import Path

from block_director.contracts.plan import Plan, ShotPlan
from block_director.layer5_orchestrator.headless_runner import (
    run_headless,
    _write_spatial_ruler_observation,
)
from block_director.layer5_orchestrator.ruler_observation import (
    SCHEMA_VERSION,
    validate_observation,
)

SCRIPT = "INT. 码头市场 - 日\n\n米迦尔和伊恩说话。\n"


class RecordingBuilder:
    """场景构建器替身：只收计划并回一份摘要，不碰 bpy。"""

    def __init__(self, summary=None):
        self.built: list = []
        self._summary = summary or {
            "shots": 2, "characters": 2, "cameras": 2, "motions": 1,
            "keyframes": 120, "total_frames": 216,
            "results": [{"shot_id": "shot_001", "lens": 35.0,
                         "camera_position": [0.0, -5.0, 1.6]},
                        {"shot_id": "shot_002", "lens": 50.0,
                         "camera_position": [1.0, -3.0, 1.5]}],
        }

    def build(self, plan, brief=None):
        self.built.append(plan)
        return dict(self._summary)


def test_headless_snapshot_carries_ruler_plan_evidence(tmp_path):
    summary = run_headless(SCRIPT, offline=True, project_dir=tmp_path,
                           builder=RecordingBuilder(),
                           poll_interval=0.0, max_wall_s=30.0)
    assert summary["success"] is True
    evidence = summary.get("spatial_ruler_plan_evidence")
    assert isinstance(evidence, dict), evidence
    assert set(evidence) == {"prescriptions", "measurements"}
    assert isinstance(evidence["prescriptions"], list)
    assert isinstance(evidence["measurements"], list)


def test_headless_run_writes_ruler_observation_json(tmp_path):
    summary = run_headless(SCRIPT, offline=True, project_dir=tmp_path,
                           builder=RecordingBuilder(),
                           poll_interval=0.0, max_wall_s=30.0)
    target = summary.get("spatial_ruler_observation")
    assert target, summary
    path = Path(target)
    assert path.exists(), path
    assert path.parent == tmp_path
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["schema_version"] == SCHEMA_VERSION
    #: 导出直写路径的输入与运行目录落盘逐字节一致。
    assert summary.get("ruler_observation") == doc
    for key in ("observation_id", "run_context", "plugin_adapter",
                "observation_request", "registry", "shot_specs",
                "camera_specs", "measurements", "verdicts",
                "prescriptions"):
        assert key in doc, key
    assert validate_observation(doc) == []


def test_write_uses_applied_prescriptions_and_merges_measurements(tmp_path):
    """处方以 driver 实际应用的版本为准；计划级测量按 ID 去重并入。"""
    plan = Plan(scene_heading="码头市场")
    plan.shots = [
        ShotPlan("shot_001", "建立", "MS", 96, order=1,
                 characters=["米迦尔"]),
    ]
    plan_payload = plan.to_dict()
    audit_path = tmp_path / "audit_log.jsonl"
    records = [
        {"kind": "run_started", "data": {}},
        {"kind": "plan_received", "data": {"plan": plan_payload}},
        {"kind": "spatial_ruler_plan_audit", "data": {
            "findings": [], "prescriptions": [], "measurements": []}},
    ]
    audit_path.write_text("\n".join(
        json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8")
    summary = {
        "run_id": "unit-test",
        "mode": "offline",
        "success": True,
        "shots": 1,
        "audit_log": str(audit_path),
        "plan": plan_payload,
        "brief": None,
        "build": {"results": [
            {"shot_id": "shot_001", "lens": 35.0,
             "camera_position": [0.0, -5.0, 1.6]}]},
        "spatial_ruler_plan_evidence": {
            "prescriptions": [{
                "prescription_id": "p_retime_shot_001",
                "shot_id": "shot_001",
                "operation": "retime_shot",
                "parameters": {"old_frames": 120, "new_frames": 96},
                "precondition_measurement_ids": [],
                "postcondition_measurement_ids": ["m_shot_001_shot_duration_planned"],
                "postcondition": "逐镜时长贴近声明",
                "applied": True, "applied_at": "", "waived": False,
                "waive_reason": "",
            }],
            "measurements": [{
                "measurement_id": "m_shot_001_shot_duration_planned",
                "shot_id": "shot_001", "transition_id": None,
                "subject_id": None, "frame": None,
                "metric": "shot_duration_planned", "value": 4.0,
                "expected": 4.0, "unit": "seconds",
                "source": "plan_intent", "provenance": "plan_intent",
            }],
        },
    }
    target = _write_spatial_ruler_observation(summary, tmp_path)
    assert target is not None
    doc = json.loads(Path(target).read_text(encoding="utf-8"))
    ops = [p["operation"] for p in doc["prescriptions"]]
    assert ops == ["retime_shot"], ops          # 已应用处方，不重算
    ids = [m["measurement_id"] for m in doc["measurements"]]
    assert ids.count("m_shot_001_shot_duration_planned") == 1, ids
    assert "m_shot_001_cast_presence" in ids
    assert validate_observation(doc) == []


def test_write_returns_none_without_plan_or_evidence(tmp_path):
    summary = {"run_id": "empty", "mode": "offline", "success": False,
               "shots": 0, "plan": None,
               "spatial_ruler_plan_evidence": None}
    assert _write_spatial_ruler_observation(summary, tmp_path) is None
