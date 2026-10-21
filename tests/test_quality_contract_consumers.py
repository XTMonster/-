"""Cross-entry-point coverage for the strict composition quality contract."""

from __future__ import annotations

import math

import pytest

from block_director.cinema.composition import CompositionItem, CompositionReport
from block_director.cinema.detail_review import detail_review_verdict
from block_director.cinema.metric_registry import METRICS_BY_NAME
from block_director.cinema.pipeline_gates import coarse_gate
from block_director.cinema.prescription import build_prescriptions
from block_director.contracts.audit import AuditResult
from block_director.contracts.backtrack import backtrack_three_state
from block_director.contracts.plan import Plan, ShotPlan
from block_director.contracts.quality import (
    COMPOSITION_PASS_SCORE,
    composition_decision,
    serialize_quality_decision,
    validate_quality_decision,
)
from block_director.delivery.failures import (
    build_failures_payload,
    render_failures_markdown,
)
from block_director.layer5_orchestrator.driver import _coarse_plan_score
from block_director.layer5_orchestrator.react import should_react
from block_director.knowledge.cards_review_method import (
    CARDS as REVIEW_METHOD_CARDS,
)


BOUNDARIES = (
    (79.99, False),
    (80.0, False),
    (80.01, True),
)


def _coarse_report(score: float) -> dict:
    return {
        "schema_version": "blockout-report/v1",
        "manifest_fingerprint": "scene",
        "verdict": "pass" if score > COMPOSITION_PASS_SCORE else "fail",
        "findings": [],
        "checks": [{
            "check_id": "composition",
            "shot_id": "shot_001",
            "actual": score,
            "threshold": COMPOSITION_PASS_SCORE,
        }],
    }


def _detail_inputs(score: float):
    baseline = {
        "state": "frozen",
        "reference": {
            "characters": [{
                "name": "甲",
                "position": {"x": 0.0, "y": 0.0, "z": 0.0},
            }],
            "camera_intents": [],
        },
    }
    shots = [{
        "schema_version": "detail-shot-contract/v1",
        "shot_id": "shot_001",
        "order": 1,
        "start_frame": 1,
        "end_frame": 24,
        "characters": [{
            "name": "甲",
            "position": {"x": 0.0, "y": 0.0, "z": 0.0},
            "source": "frozen_baseline",
        }],
        "props": [],
        "camera": {
            "position": [0.0, 5.0, 2.0],
            "target": [0.0, 0.0, 1.0],
            "lens_mm": 35.0,
            "movements": [],
        },
        "beats": [],
        "audio_proxy": [],
    }]
    report = _coarse_report(score)
    return baseline, shots, report


def _react_shot() -> ShotPlan:
    return ShotPlan(
        "shot_001",
        "边界测试",
        "MS",
        24,
        order=1,
        characters=["甲"],
    )


@pytest.mark.parametrize(("score", "expected_pass"), BOUNDARIES)
def test_all_quality_consumers_share_the_same_strict_boundary(
    score: float,
    expected_pass: bool,
):
    coarse = coarse_gate(_coarse_report(score))
    assert coarse["passed"] is expected_pass

    baseline, shots, report = _detail_inputs(score)
    detail = detail_review_verdict(
        detail_shots=shots,
        blockout_report=report,
        baseline=baseline,
    )
    assert detail["all_ok"] is expected_pass

    plan_score = _coarse_plan_score({"report": report})
    assert (plan_score == 100.0) is expected_pass

    failure = build_failures_payload(
        terminal_shots={"shot_001": "failed"},
        best_scores={"shot_001": {"score": score}},
        no_gain={"shot_001": 3},
    )["failures"][0]
    assert ("曾过线" in failure["reason"]) is expected_pass

    audit = AuditResult(
        passed=score > COMPOSITION_PASS_SCORE,
        target="shot_001",
        score=score,
        errors=[],
    )
    assert should_react(_react_shot(), audit) is not expected_pass


def test_unresolved_composition_is_blocked_but_evidenced_empty_shot_is_exempt():
    blocked = composition_decision(None)
    exempt = composition_decision(
        None,
        empty_shot_declared=True,
        empty_shot_evidence=True,
    )

    assert blocked["status"] == "blocked"
    assert exempt["status"] == "exempt"


@pytest.mark.parametrize("score", [float("nan"), float("inf"), float("-inf")])
def test_quality_contract_rejects_non_finite_scores(score: float):
    assert not math.isfinite(score)
    with pytest.raises(ValueError, match="finite"):
        composition_decision(score)


@pytest.mark.parametrize("score", [float("nan"), float("inf"), float("-inf")])
def test_backtrack_rejects_non_finite_composition_scores(score: float):
    with pytest.raises(ValueError, match="finite"):
        backtrack_three_state(score)


@pytest.mark.parametrize("score", [float("nan"), float("inf"), float("-inf")])
def test_prescriptions_reject_non_finite_component_scores(score: float):
    report = CompositionReport(
        score=70.0,
        items={"headroom": CompositionItem("headroom", score, 0.15)},
    )

    with pytest.raises(ValueError, match="finite"):
        build_prescriptions(report)


@pytest.mark.parametrize("bad", [1, "true", None])
def test_empty_shot_flags_are_strict_booleans(bad):
    with pytest.raises((TypeError, ValueError)):
        composition_decision(None, empty_shot_declared=bad)


def test_quality_decision_round_trip_is_stable_and_rejects_unknown_status():
    decision = composition_decision(80.01)

    assert validate_quality_decision(decision) == decision
    encoded = serialize_quality_decision(decision)
    assert encoded == serialize_quality_decision(dict(decision))
    assert '"status":"pass"' in encoded

    broken = dict(decision)
    broken["status"] = "probably"
    with pytest.raises(ValueError, match="status"):
        validate_quality_decision(broken)

    missing = dict(decision)
    del missing["reason"]
    with pytest.raises(ValueError, match="missing"):
        validate_quality_decision(missing)


def test_quality_decision_rejects_unknown_fields():
    decision = composition_decision(80.01)
    decision["unexpected"] = True

    with pytest.raises(ValueError, match="unknown.*unexpected"):
        validate_quality_decision(decision)


@pytest.mark.parametrize(
    ("status", "score", "reason"),
    [
        ("pass", 80.01, "composition_unresolved"),
        ("fail", 80.0, ""),
        ("blocked", None, ""),
        ("exempt", None, "composition_unresolved"),
    ],
)
def test_quality_decision_rejects_status_reason_mismatch(
    status: str,
    score: float | None,
    reason: str,
):
    decision = composition_decision(score)
    decision["status"] = status
    decision["reason"] = reason

    with pytest.raises(ValueError, match="reason"):
        validate_quality_decision(decision)


def test_failure_copy_says_strictly_greater_than_eighty():
    failures = build_failures_payload(
        terminal_shots={"shot_001": "failed"},
        best_scores={"shot_001": {"score": 80.0}},
        no_gain={"shot_001": 3},
    )["failures"]
    markdown = render_failures_markdown(failures)

    assert "严格高于 80" in failures[0]["reason"]
    assert "严格高于 80" in markdown
    assert "≥80" not in markdown


def test_composition_metric_copy_uses_the_strict_boundary():
    names = {
        "headroom", "lead_room", "rule_of_thirds",
        "balance", "occlusion", "framing",
    }

    for name in names:
        spec = METRICS_BY_NAME[name]
        copy = " ".join([
            spec.target,
            spec.sample_requirements["good"],
            spec.sample_requirements["ambiguous"],
        ])
        assert spec.target.startswith(">"), f"{name}: {spec.target}"
        assert "≥ 0.8" not in copy, f"{name}: {copy}"


def test_review_method_card_teaches_strict_component_boundary():
    card = next(item for item in REVIEW_METHOD_CARDS
                if item.id == "rev_method_decision")

    assert "分项分数 <= 0.8" in card.content
    assert card.parameters == {
        "pass_score": COMPOSITION_PASS_SCORE,
        "item_threshold": 0.8,
        "item_min_inclusive": False,
    }
