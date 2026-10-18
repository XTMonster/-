"""Ticket 03：PipelineGate 状态机 + 粗排基准冻结（纯层，不 import bpy）。

- 每条阶段跃迁可测：fail 不流过下一阶段、冻结前禁止细排、细排/序列未过
  禁止 final；
- 冻结产物含指纹；冻结后机位/走位漂移 -> approval_required finding。
"""

from __future__ import annotations

import pytest

from block_director.cinema.pipeline_gates import (
    PipelinePhase,
    can_transition,
    coarse_gate,
    final_gate,
    freeze_coarse_baseline,
    baseline_drift_findings,
    E_BLOCKOUT_APPROVAL_REQUIRED,
)


def _report(findings=(), verdict=None):
    return {
        "schema_version": "blockout-report/v1",
        "manifest_fingerprint": "abc",
        "verdict": "pass" if verdict is None
        else ("fail" if any(f.get("severity") == "error"
                            for f in findings) else "pass"),
        "findings": [dict(f) for f in findings],
        "checks": [],
        "notes": [],
    }


def _manifest(**overrides):
    doc = {
        "schema_version": "blockout-manifest/v1",
        "scene_id": "dock_fly_bomb",
        "primitives": [],
        "cameras": [{
            "shot_id": "shot_001", "camera_id": "cam_shot_001",
            "position": [-0.5, 5.5, 2.0], "target": [-0.2, 0.0, 0.8],
            "lens_mm": 35.0, "fov_deg": 54.4, "movements": [],
            "start_frame": 1, "end_frame": 72,
            "provenance": "script_declaration", "resolved": True,
        }],
        "shot_table": [],
        "asset_registry": [],
        "scene_prop_ids": [],
        "checkpoints": [],
        "notes": [],
    }
    doc.update(overrides)
    return doc


def _approval():
    from block_director.contracts.blockout import approval_state_machine
    return approval_state_machine(
        "scene_01_blockout.blend", "global", None, "camera-approved",
        _manifest(), approved_by="test", target_state="frozen",
        approved_at="t0")


# ---------------------------------------------------------------------------
# 阶段状态机

def test_phase_forward_chain_is_sequential():
    chain = [v for v in [
        "SCRIPT_UNDERSTOOD", "COARSE_REFERENCE_READY", "BLOCKOUT_BUILT",
        "COARSE_OBSERVED", "COARSE_APPROVED", "BASELINE_FROZEN",
        "SHOT_TABLE_READY", "DETAIL_BLOCKING", "DETAIL_REVIEWED",
        "SEQUENCE_REVIEWED", "FINAL_EXPORTED",
    ]]
    for current, nxt in zip(chain, chain[1:]):
        assert can_transition(current, nxt)
    assert can_transition("FINAL_EXPORTED", "FINAL_EXPORTED") is False


def test_coarse_fail_loops_back_to_reference_not_forward():
    assert can_transition(PipelinePhase.COARSE_OBSERVED,
                          PipelinePhase.COARSE_REFERENCE_READY)
    assert can_transition(PipelinePhase.COARSE_OBSERVED,
                          PipelinePhase.COARSE_APPROVED) is True
    assert can_transition(PipelinePhase.COARSE_OBSERVED,
                          PipelinePhase.DETAIL_BLOCKING) is False


def test_unfrozen_baseline_blocks_detail():
    assert can_transition(PipelinePhase.BASELINE_FROZEN,
                          PipelinePhase.SHOT_TABLE_READY)
    assert can_transition(PipelinePhase.SHOT_TABLE_READY,
                          PipelinePhase.DETAIL_BLOCKING)
    assert can_transition(PipelinePhase.SHOT_TABLE_READY,
                          PipelinePhase.DETAIL_REVIEWED) is False


# ---------------------------------------------------------------------------
# 粗排 gate

def test_coarse_gate_passes_only_without_error_findings():
    ok = coarse_gate(_report(findings=[]))
    assert ok["passed"] is True
    bad = coarse_gate(_report(findings=[{
        "check_id": "E_BLOCKOUT_EMPTY_WALL", "shot_id": "shot_001",
        "severity": "error", "message": "空墙",
    }]))
    assert bad["passed"] is False
    assert any("error" in r for r in bad["reasons"])


def test_coarse_gate_allows_no_warning_failures():
    ok = coarse_gate(_report(findings=[{
        "check_id": "off_screen", "shot_id": "shot_001",
        "severity": "warning", "message": "出画",
    }]))
    assert ok["passed"] is True


# ---------------------------------------------------------------------------
# 冻结与漂移

def test_freeze_writes_baseline_with_fingerprints():
    baseline = freeze_coarse_baseline(
        reference={"schema_version": "coarse-world-reference/v1",
                   "scene_id": "dock_fly_bomb", "characters": [],
                   "props": [], "anchors": [],
                   "camera_intents": [], "shots": [], "revisions": [],
                   "notes": []},
        manifest=_manifest(), report=_report(),
        approvals=[_approval()], approved_by="test", approved_at="t0")
    assert baseline["state"] == "frozen"
    assert baseline["schema_version"] == "coarse-baseline/v1"
    assert baseline["reference_fingerprint"]
    assert baseline["manifest_fingerprint"]
    assert baseline["approval"]["state"] == "frozen"


def test_baseline_drift_flags_camera_move():
    manifest = _manifest()
    approval = _approval()
    baseline = freeze_coarse_baseline(
        reference={"schema_version": "coarse-world-reference/v1",
                   "scene_id": "dock_fly_bomb", "characters": [],
                   "props": [], "anchors": [],
                   "camera_intents": [], "shots": [], "revisions": [],
                   "notes": []},
        manifest=manifest, report=_report(),
        approvals=[approval], approved_by="test", approved_at="t0")
    moved = _manifest(cameras=[{
        "shot_id": "shot_001", "camera_id": "cam_shot_001",
        "position": [9.9, 9.9, 9.9], "target": [-0.2, 0.0, 0.8],
        "lens_mm": 35.0, "fov_deg": 54.4, "movements": [],
        "start_frame": 1, "end_frame": 72,
        "provenance": "script_declaration", "resolved": True,
    }])
    findings = baseline_drift_findings(baseline, moved)
    assert any(f["check_id"] == E_BLOCKOUT_APPROVAL_REQUIRED
               for f in findings)


# ---------------------------------------------------------------------------
# final gate

def test_final_gate_requires_every_stage_pass():
    ok = final_gate(coarse_pass=True, baseline_frozen=True,
                    detail_results={"shot_001": True},
                    sequence_verdict="pass")
    assert ok["passed"] is True


def test_final_gate_fails_when_detail_or_sequence_missing():
    r1 = final_gate(coarse_pass=False, baseline_frozen=True,
                    detail_results={"shot_001": True},
                    sequence_verdict="pass")
    assert r1["passed"] is False
    assert any("粗排" in x for x in r1["reasons"])

    r2 = final_gate(coarse_pass=True, baseline_frozen=False,
                    detail_results={"shot_001": True},
                    sequence_verdict="pass")
    assert r2["passed"] is False
    assert any("冻结" in x for x in r2["reasons"])

    r3 = final_gate(coarse_pass=True, baseline_frozen=True,
                    detail_results={"shot_001": False},
                    sequence_verdict="pass")
    assert r3["passed"] is False
    assert any("细排" in x for x in r3["reasons"])

    r4 = final_gate(coarse_pass=True, baseline_frozen=True,
                    detail_results={"shot_001": True},
                    sequence_verdict="fail")
    assert r4["passed"] is False
    assert any("序列" in x for x in r4["reasons"])
