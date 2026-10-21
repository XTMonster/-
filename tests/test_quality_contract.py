"""Canonical quality decisions shared by every pipeline entry point."""

from __future__ import annotations

from block_director.cinema.quality_contract import (
    blockout_quality_report,
    composition_decision,
)


def test_composition_decision_has_strict_boundary():
    assert composition_decision(79.99)["status"] == "fail"
    assert composition_decision(80.0)["status"] == "fail"
    assert composition_decision(80.01)["status"] == "pass"


def test_missing_composition_evidence_is_blocked_not_passed():
    decision = composition_decision(None)

    assert decision["status"] == "blocked"
    assert decision["reason"] == "composition_unresolved"


def test_only_declared_empty_shot_with_evidence_is_exempt():
    exempt = composition_decision(
        None,
        empty_shot_declared=True,
        empty_shot_evidence=True,
    )
    missing_evidence = composition_decision(
        None,
        empty_shot_declared=True,
        empty_shot_evidence=False,
    )

    assert exempt["status"] == "exempt"
    assert missing_evidence["status"] == "blocked"
    assert missing_evidence["reason"] == "empty_shot_evidence_missing"


def test_blockout_quality_report_is_the_canonical_coarse_decision():
    report = {
        "findings": [{
            "check_id": "E_BLOCKOUT_EMPTY_WALL",
            "shot_id": "shot_002",
            "severity": "error",
        }],
        "checks": [
            {"check_id": "composition", "shot_id": "shot_001",
             "actual": 82.0},
            {"check_id": "composition", "shot_id": "shot_002",
             "actual": 80.0},
        ],
    }

    decision = blockout_quality_report(report)

    assert decision["gate_ready"] is False
    assert decision["min_composition"] == 80.0
    assert decision["hard_error_count"] == 1
    assert decision["shots"]["shot_001"]["composition"]["status"] == "pass"
    assert decision["shots"]["shot_002"]["composition"]["status"] == "fail"


def test_blockout_quality_report_blocks_missing_composition_evidence():
    report = {
        "findings": [],
        "checks": [
            {"check_id": "subject_visible", "shot_id": "shot_001",
             "actual": 1.0, "verdict": "pass"},
        ],
    }

    decision = blockout_quality_report(report)

    assert decision["gate_ready"] is False
    assert decision["shots"]["shot_001"]["composition"]["reason"] == (
        "composition_unresolved")


def test_legacy_top_level_pass_without_shot_evidence_is_blocked():
    report = {
        "verdict": "pass",
        "findings": [],
        "checks": [],
    }

    decision = blockout_quality_report(report)

    assert decision["gate_ready"] is False
    assert decision["shots"] == {}
    assert decision["blocked_reasons"] == ["composition_unresolved"]
