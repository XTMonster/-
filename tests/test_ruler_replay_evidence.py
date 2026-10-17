"""空间尺观测证据回放测试（Ticket 06 纯层，无 bpy）。

``layer9_persistence/replay.py`` 从审计日志把计划级处方/测量与逐镜几何测量
抽回 ``ReplayReport.summary``，交付层据此重产 ``ruler_observation.json``——
全程无 LLM。钉住：

* ``extract_ruler_evidence``：``spatial_ruler_plan_audit`` 事件 → 计划级
  evidence（prescriptions/measurements）；``shot_audit`` 事件 → 逐镜
  ``ruler_measurements``；
* 旧日志（无空间尺事件）诚实给空表，summary 零形状差；
* ``replay()`` 只在有证据时给 summary 挂键；
* 抽出的证据经 ``assemble_bundle`` 可组回一份过 ``validate_bundle`` 的 bundle；
* 运行摘要折档 ``ruler_evidence_from_summary`` 给 headless/UI 导出共用。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from block_director.contracts.plan import Plan, ShotPlan
from block_director.contracts.spatial_ruler import validate_bundle
from block_director.delivery.ruler_evidence import assemble_bundle


def _plan() -> Plan:
    plan = Plan(scene_heading="码头市场")
    plan.shots = [
        ShotPlan("shot_001", "建立", "ELS", 120, order=1,
                 characters=["米迦尔"]),
        ShotPlan("shot_002", "推进", "MS", 96, order=2,
                 characters=["伊恩"]),
    ]
    return plan


def _measurements() -> list:
    return [
        {"measurement_id": "m_shot_001_shot_duration_declared",
         "shot_id": "shot_001", "transition_id": None, "subject_id": None,
         "frame": None, "metric": "shot_duration_declared", "value": 5.0,
         "expected": 5.0, "unit": "seconds", "source": "script_declaration",
         "provenance": "script_declaration"},
        {"measurement_id": "m_shot_001_shot_duration_planned_before",
         "shot_id": "shot_001", "transition_id": None, "subject_id": None,
         "frame": None, "metric": "shot_duration_planned_before", "value": 4.0,
         "expected": None, "unit": "seconds", "source": "plan_intent",
         "provenance": "plan_intent"},
        {"measurement_id": "m_shot_001_shot_duration_planned",
         "shot_id": "shot_001", "transition_id": None, "subject_id": None,
         "frame": None, "metric": "shot_duration_planned", "value": 5.0,
         "expected": None, "unit": "seconds", "source": "plan_intent",
         "provenance": "plan_intent"},
    ]


def _prescriptions() -> list:
    return [{
        "prescription_id": "p_retime_shot_001",
        "shot_id": "shot_001", "operation": "retime_shot",
        "parameters": {"old_frames": 120, "new_frames": 96,
                       "dialogue_policy": {"tail_frames": 12,
                                           "latest_dialogue_end": 0}},
        "precondition_measurement_ids": [
            "m_shot_001_shot_duration_declared",
            "m_shot_001_shot_duration_planned_before"],
        "postcondition_measurement_ids": [
            "m_shot_001_shot_duration_planned"],
        "postcondition": "该镜时长回到声明值，且对白＋收尾余量仍在镜内",
        "applied": True, "applied_at": "", "waived": False, "waive_reason": "",
    }]


def _records() -> list:
    return [
        {"kind": "plan_received", "data": {"plan": _plan().to_dict()}},
        {"kind": "spatial_ruler_plan_audit", "data": {
            "findings": [],
            "prescriptions": _prescriptions(),
            "measurements": _measurements(),
        }},
        {"kind": "shot_audit", "data": {
            "shot": "shot_001", "passed": True, "composition_score": 81.0,
            "findings": [],
            "ruler_measurements": [{
                "measurement_id": "m_shot_001_camera_lens",
                "shot_id": "shot_001", "transition_id": None,
                "subject_id": None, "frame": None, "metric": "camera_lens",
                "value": 50.0, "expected": None, "unit": "mm",
                "source": "blender_geometry",
                "provenance": "blender_geometry",
            }],
        }},
    ]


def _registry():
    def execute(tool, args):
        return SimpleNamespace(ok=True, error="", content="")

    return SimpleNamespace(names=lambda: [], execute=execute)


def _write_log(tmp_path: Path, records) -> Path:
    directory = tmp_path / "runs"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "audit_log.jsonl"
    path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in records),
        encoding="utf-8")
    return path


def test_extract_plan_and_shot_evidence() -> None:
    from block_director.layer9_persistence.replay import extract_ruler_evidence

    plan_evidence, shot_measurements = extract_ruler_evidence(_records())
    assert plan_evidence["prescriptions"][0]["operation"] == "retime_shot"
    assert [m["metric"] for m in plan_evidence["measurements"]] == [
        "shot_duration_declared", "shot_duration_planned_before",
        "shot_duration_planned"]
    assert shot_measurements["shot_001"][0]["metric"] == "camera_lens"
    assert shot_measurements["shot_001"][0]["provenance"] == "blender_geometry"


def test_extract_old_log_is_empty() -> None:
    from block_director.layer9_persistence.replay import extract_ruler_evidence

    plan_evidence, shot_measurements = extract_ruler_evidence([
        {"kind": "plan_received", "data": {"plan": _plan().to_dict()}},
    ])
    assert plan_evidence == {"prescriptions": [], "measurements": []}
    assert shot_measurements == {}


def test_replay_attaches_summary_keys_only_when_present(tmp_path) -> None:
    from block_director.layer9_persistence.replay import replay

    _write_log(tmp_path, _records())
    report = replay(tmp_path, _registry())
    assert report.ok
    assert report.summary["ruler_prescriptions"][0]["operation"] == "retime_shot"
    assert len(report.summary["ruler_measurements"]) == 3
    assert report.summary["ruler_shot_measurements"]["shot_001"][0][
        "metric"] == "camera_lens"


def test_replay_old_log_summary_has_no_ruler_keys(tmp_path) -> None:
    from block_director.layer9_persistence.replay import replay

    _write_log(tmp_path, [
        {"kind": "plan_received", "data": {"plan": _plan().to_dict()}},
    ])
    report = replay(tmp_path, _registry())
    assert report.ok
    for key in ("ruler_prescriptions", "ruler_measurements",
                "ruler_shot_measurements"):
        assert key not in report.summary


def test_extracted_evidence_assembles_valid_bundle() -> None:
    from block_director.layer9_persistence.replay import extract_ruler_evidence

    plan_evidence, shot_measurements = extract_ruler_evidence(_records())
    flat = list(plan_evidence["measurements"])
    for items in shot_measurements.values():
        flat.extend(items)
    bundle, findings = assemble_bundle(
        observation_id="obs_replay_fixture",
        run_context={"source_run": "fixture", "model": "test",
                     "status": "offline"},
        plan=_plan(),
        measurements=flat,
        verdicts=[],
        prescriptions=plan_evidence["prescriptions"],
    )
    assert findings == []
    assert validate_bundle(bundle) == []
    assert len(bundle["measurements"]) == 4


def test_ruler_evidence_from_summary() -> None:
    from block_director.layer5_orchestrator.headless_runner import (
        ruler_evidence_from_summary,
    )

    summary = {
        "compliance": {
            "ruler_prescriptions": [{"operation": "restore_cast"}],
            "ruler_measurements": [{"metric": "cast_presence"}],
        },
        "build": {"results": [
            {"shot_id": "shot_001",
             "ruler_measurements": [{"metric": "camera_lens"}]},
            {"shot_id": "shot_002"},
        ]},
    }
    args = ruler_evidence_from_summary(summary)
    assert args["ruler_evidence"]["prescriptions"][0][
        "operation"] == "restore_cast"
    assert args["ruler_shot_measurements"]["shot_001"][0][
        "metric"] == "camera_lens"
    assert "shot_002" not in args["ruler_shot_measurements"]


def test_ruler_evidence_from_summary_empty() -> None:
    from block_director.layer5_orchestrator.headless_runner import (
        ruler_evidence_from_summary,
    )

    args = ruler_evidence_from_summary({})
    assert args["ruler_evidence"] is None
    assert args["ruler_shot_measurements"] is None


def test_replay_then_build_observation_cli_glue(tmp_path) -> None:
    """``tools/replay_project --export`` 的折档接缝（Ticket 06，无 bpy）：

    重放报告（含构建摘要）→ ``build_observation_from_log`` → 有效 v2 bundle，
    与 CLI 里 ``read_audit_log + report.summary/brief`` 的调用形态逐字对齐。
    旧日志（无空间尺事件）同样能产出一份过结构校验的空 bundle。
    """
    from block_director.layer5_orchestrator.ruler_observation import (
        build_observation_from_log,
        validate_observation,
    )
    from block_director.layer9_persistence import read_audit_log
    from block_director.layer9_persistence.replay import replay

    geometry = {
        "measurement_id": "m_shot_001_camera_lens",
        "shot_id": "shot_001", "transition_id": None, "subject_id": None,
        "frame": None, "metric": "camera_lens", "value": 50.0,
        "expected": None, "unit": "mm", "source": "blender_geometry",
        "provenance": "blender_geometry",
    }

    def _build(plan, spec, brief=None):
        return {"results": [{"shot_id": "shot_001",
                             "ruler_measurements": [geometry]}]}

    _write_log(tmp_path, _records())
    report = replay(tmp_path, _registry(), builder=_build)
    assert report.ok
    assert report.summary["ruler_shot_measurements"]["shot_001"][0][
        "metric"] == "camera_lens"

    doc = build_observation_from_log(
        read_audit_log(tmp_path), report.plan, brief=report.brief,
        build_summary=report.summary, fps=24,
        run_context={"source_run": report.brief_source or "replay",
                     "status": "replayed",
                     "shots": len(report.plan.shots)},
        observation_id=f"obs-replay-{tmp_path.name}")
    ids = {m["measurement_id"] for m in doc["measurements"]}
    assert "m_shot_001_camera_lens" in ids
    assert validate_observation(doc) == []

    # 旧日志（无任何空间尺事件）也走同一条接缝：空 bundle 仍过结构校验。
    _write_log(tmp_path / "old", [
        {"kind": "plan_received", "data": {"plan": _plan().to_dict()}},
    ])
    old = build_observation_from_log(
        read_audit_log(tmp_path / "old"), _plan(), build_summary=None,
        fps=24, run_context={"status": "replayed"},
        observation_id="obs-replay-old")
    assert validate_observation(old) == []


def test_ruler_export_args_prefers_full_document() -> None:
    """headless 导出兜底：有完整 v2 文档就原样带出，不再折摘要。"""
    from tools.run_headless import _ruler_export_args

    args = _ruler_export_args({
        "ruler_observation": {
            "schema_version": "spatial-ruler-observation/v2",
            "measurements": [],
        },
    })
    assert args["ruler_observation"]["schema_version"] == \
        "spatial-ruler-observation/v2"
    assert "ruler_evidence" not in args
    assert "ruler_shot_measurements" not in args


def test_ruler_export_args_falls_back_to_summary() -> None:
    """完整文档缺失时折出计划级处方/测量参数；空摘要零形状差。"""
    from tools.run_headless import _ruler_export_args

    args = _ruler_export_args({
        "compliance": {
            "ruler_prescriptions": [{"operation": "restore_cast"}],
            "ruler_measurements": [{"metric": "cast_presence"}],
        },
    })
    assert "ruler_observation" not in args
    assert args["ruler_evidence"]["prescriptions"][0][
        "operation"] == "restore_cast"
    empty = _ruler_export_args({})
    assert "ruler_observation" not in empty
    assert empty["ruler_evidence"] is None
    assert empty["ruler_shot_measurements"] is None


def test_ruler_delivery_args_reads_driver_state() -> None:
    from block_director.layer5_orchestrator.driver import ruler_delivery_args

    class _StubDriver:
        _ruler_plan_evidence = {
            "prescriptions": [{"operation": "retime_shot"}],
            "measurements": [{"metric": "shot_duration_planned"}],
        }
        build_summary = {"results": [
            {"shot_id": "shot_001",
             "ruler_measurements": [{"metric": "camera_lens"}]},
        ]}

    args = ruler_delivery_args(_StubDriver())
    assert args["ruler_evidence"]["prescriptions"][0][
        "operation"] == "retime_shot"
    assert args["ruler_shot_measurements"]["shot_001"][0][
        "metric"] == "camera_lens"


def test_shot_audits_from_log_carries_ruler_measurements() -> None:
    from block_director.layer5_orchestrator.ruler_observation import (
        shot_audits_from_log,
    )

    audits = shot_audits_from_log(_records())
    assert audits["shot_001"]["ruler_measurements"][0][
        "metric"] == "camera_lens"
    assert audits["shot_001"]["ruler_measurements"][0][
        "provenance"] == "blender_geometry"


def test_build_observation_from_log_folds_geometry_measurements() -> None:
    from block_director.layer5_orchestrator.ruler_observation import (
        build_observation_from_log,
        validate_observation,
    )

    doc = build_observation_from_log(
        _records(), _plan(), observation_id="obs_fold")
    ids = {m["measurement_id"] for m in doc["measurements"]}
    assert "m_shot_001_camera_lens" in ids
    assert validate_observation(doc) == []


def test_ruler_observation_payload_keys_by_target_and_folds() -> None:
    """driver 全文档路径必须按 ``AuditResult.target`` 收逐镜记录并折几何测量。"""
    from block_director.contracts.audit import AuditResult
    from block_director.contracts.plan import Plan, ShotPlan
    from block_director.layer5_orchestrator.driver import PrevisDriver
    from block_director.layer5_orchestrator.offline import OfflineTransport
    from block_director.layer6_audit.audit_logger import AuditLogger

    driver = PrevisDriver(transport=OfflineTransport(), audit=AuditLogger())
    driver.plan = Plan(shots=[
        ShotPlan("shot_001", "建立", "ELS", 120, order=1),
    ])
    result = AuditResult(passed=True, score=81.0, target="shot_001")
    result.ruler_measurements = [{
        "measurement_id": "m_shot_001_camera_lens",
        "shot_id": "shot_001", "transition_id": None, "subject_id": None,
        "frame": None, "metric": "camera_lens", "value": 50.0,
        "expected": None, "unit": "mm", "source": "blender_geometry",
        "provenance": "blender_geometry",
    }]
    driver.audit_results = [result]
    driver.build_summary = {}

    doc = driver._ruler_observation_payload()
    assert doc is not None
    rules = {v["rule_code"] for v in doc["verdicts"]}
    assert "COMPOSITION" in rules          # 修复前 shot_audits 恒空 → 无 verdict
    ids = {m["measurement_id"] for m in doc["measurements"]}
    assert "m_shot_001_camera_lens" in ids
    assert "m_shot_001_composition_score" in ids
