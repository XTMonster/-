"""Ticket 06：交付证据与回放（纯层，无 bpy）。

钉住：
* ``write_observation`` 写盘、字节确定性、NaN/Inf 拒绝；
* 从 ``audit_log.jsonl`` 事件（shot_audit / guard_warning /
  spatial_ruler_plan_audit）重放折档：同一份日志两次折档逐字节相同，
  且产物过结构校验；
* README 在有观测文档时引用 ``ruler_observation.json``，缺省零形状差。
"""

from __future__ import annotations

import json

from block_director.contracts.plan import Plan, Responsibility, ShotPlan
from block_director.delivery.manifest import build_manifest
from block_director.delivery.readme import render_readme
from block_director.layer5_orchestrator.ruler_observation import (
    build_observation,
    build_observation_from_log,
    validate_observation,
    write_observation,
)

FPS = 24


class _Brief:
    speakers = [{"speaker": "米迦尔", "listener": "伊恩"}]
    gaze = [{"from": "米迦尔", "to": "偷盗者"}]
    space = [{"character": "偷盗者", "relative_to": "伊恩"}]


def _plan() -> Plan:
    plan = Plan(scene_heading="码头市场")
    plan.shots = [
        ShotPlan("shot_001", "建立", "ELS", 120, order=1,
                 characters=["米迦尔", "伊恩", "偷盗者"],
                 responsibility=Responsibility(
                     white_model=["米迦尔", "伊恩", "偷盗者"])),
        ShotPlan("shot_002", "推进", "MS", 96, order=2,
                 characters=["米迦尔"],
                 responsibility=Responsibility(white_model=["米迦尔"])),
    ]
    return plan


def _build_results() -> dict:
    return {
        "shot_001": {"lens": 24.0},
        "shot_002": {"lens": 35.0, "camera_position": [3.0, -2.5, 1.6],
                     "camera_target": [0.0, 0.5, 1.0]},
    }


def _guard_warning(shot_id: str, kind: str, evidence: dict) -> dict:
    return {
        "shot_id": shot_id, "frame_range": [1, 24], "type": kind,
        "subject": "米迦尔", "evidence": evidence, "severity": "warning",
        "confidence": "high", "declared_intent": "",
        "suggestion_hint": "结构化修复提示",
    }


def _observation() -> dict:
    return build_observation(
        plan=_plan(),
        parsed=None, brief=_Brief(),
        shot_audits={
            "shot_001": {
                "passed": False, "score": 64.7, "errors": [], "warnings": [],
                "guard_warnings": [_guard_warning(
                    "shot_001", "subject_not_visible",
                    {"visible_ratio": 0.0, "frames": 22})],
            },
            "shot_002": {
                "passed": True, "score": 79.2, "errors": [], "warnings": [],
                "guard_warnings": [],
            },
        },
        build_results=_build_results(),
        fps=FPS,
        run_context={"source_run": "fixture", "status": "completed",
                     "summary": {"shots": 2, "characters": 3}},
        observation_id="obs-delivery-fixture",
        plan_findings=[],
        prescriptions=[],
    )


def _records() -> list:
    return [
        {"kind": "plan_received",
         "data": {"plan": _plan().to_dict()}},
        {"kind": "brief_received",
         "data": {"brief": {
             "speakers": [{"speaker": "米迦尔", "listener": "伊恩"}],
             "gaze": [{"from": "米迦尔", "to": "偷盗者"}],
             "space": [{"character": "偷盗者", "relative_to": "伊恩"}]}}},
        {"kind": "spatial_ruler_plan_audit", "data": {
            "findings": [{"rule": "SR001", "severity": "warning",
                          "target": "shot_001",
                          "message": "角色已从 white_model 恢复",
                          "suggestion": ""}],
            "prescriptions": [], "measurements": []}},
        {"kind": "shot_audit", "data": {
            "shot": "shot_001", "passed": False, "composition_score": 64.7,
            "findings": []}},
        {"kind": "guard_warning", "data": {
            "shot_id": "shot_001", "frames_sampled": 24,
            "warnings": [_guard_warning(
                "shot_001", "subject_not_visible",
                {"visible_ratio": 0.0, "frames": 22})]}},
        {"kind": "shot_audit", "data": {
            "shot": "shot_002", "passed": True, "composition_score": 79.2,
            "findings": []}},
    ]


def _manifest() -> dict:
    return build_manifest(_plan())


# --------------------------------------------------------------------------- #
# write_observation
# --------------------------------------------------------------------------- #
def test_write_observation_writes_and_roundtrips(tmp_path):
    path = write_observation(_observation(), tmp_path)
    assert path.name == "ruler_observation.json"
    assert path.exists()
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["observation_id"] == "obs-delivery-fixture"
    assert validate_observation(loaded) == []


def test_write_observation_is_deterministic(tmp_path):
    first = write_observation(_observation(), tmp_path).read_bytes()
    second = write_observation(_observation(), tmp_path).read_bytes()
    assert first == second


def test_write_observation_refuses_nan(tmp_path):
    doc = _observation()
    doc["measurements"][0]["value"] = float("nan")
    try:
        write_observation(doc, tmp_path)
    except ValueError:
        return
    raise AssertionError("NaN 必须被写盘拒绝")


# --------------------------------------------------------------------------- #
# 重放折档
# --------------------------------------------------------------------------- #
def test_replay_build_from_log_is_deterministic():
    first = json.dumps(build_observation_from_log(
        _records(), _plan(), brief=_Brief(),
        build_summary={"results": [
            {"shot_id": "shot_001", "lens": 24.0},
            {"shot_id": "shot_002", "lens": 35.0,
             "camera_position": [3.0, -2.5, 1.6],
             "camera_target": [0.0, 0.5, 1.0]}]},
        fps=FPS, run_context={"status": "replayed"},
        observation_id="obs-replay-fixture"),
        ensure_ascii=False, sort_keys=True)
    second = json.dumps(build_observation_from_log(
        _records(), _plan(), brief=_Brief(),
        build_summary={"results": [
            {"shot_id": "shot_001", "lens": 24.0},
            {"shot_id": "shot_002", "lens": 35.0,
             "camera_position": [3.0, -2.5, 1.6],
             "camera_target": [0.0, 0.5, 1.0]}]},
        fps=FPS, run_context={"status": "replayed"},
        observation_id="obs-replay-fixture"),
        ensure_ascii=False, sort_keys=True)
    assert first == second


def test_replay_build_from_log_uses_events():
    doc = build_observation_from_log(
        _records(), _plan(), brief=_Brief(),
        build_summary={"results": [
            {"shot_id": "shot_001", "lens": 24.0},
            {"shot_id": "shot_002", "lens": 35.0,
             "camera_position": [3.0, -2.5, 1.6],
             "camera_target": [0.0, 0.5, 1.0]}]},
        fps=FPS, run_context={"status": "replayed"},
        observation_id="obs-replay-fixture")
    metrics = {(m["shot_id"], m["metric"]) for m in doc["measurements"]}
    assert ("shot_001", "composition_score") in metrics
    assert ("shot_001", "visibility_ratio") in metrics
    assert ("shot_002", "composition_score") in metrics
    by_op = {p["operation"]: p for p in doc["prescriptions"]}
    assert by_op["restore_cast"]["applied"] is True
    assert validate_observation(doc) == []


def test_replay_build_with_plan_only_events_is_valid():
    doc = build_observation_from_log(
        [{"kind": "plan_received",
          "data": {"plan": _plan().to_dict()}}],
        _plan(), brief=None, build_summary=None,
        fps=FPS, run_context={"status": "replayed"},
        observation_id="obs-replay-min")
    assert doc["shot_specs"] and doc["measurements"]
    assert validate_observation(doc) == []


# --------------------------------------------------------------------------- #
# README 引用（零形状差）
# --------------------------------------------------------------------------- #
def test_readme_silent_without_observation(tmp_path):
    baseline = render_readme(_manifest(), out_dir=tmp_path)
    assert "ruler_observation.json" not in baseline
    assert render_readme(_manifest(), out_dir=tmp_path) == baseline


def test_readme_references_observation_when_present(tmp_path):
    write_observation(_observation(), tmp_path)
    text = render_readme(_manifest(), out_dir=tmp_path,
                         ruler_observation=True)
    assert "ruler_observation.json" in text
    assert "空间尺观测" in text
