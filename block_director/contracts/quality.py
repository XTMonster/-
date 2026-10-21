"""Versioned, pure quality contract shared by every pipeline layer."""

from __future__ import annotations

import json
import math
from typing import Any, Dict, Mapping, Sequence

from .evidence import EvidenceStore
from .spatial_snapshot import DIFF_THRESHOLDS

QUALITY_CONTRACT_VERSION = "quality-contract/v1"
DELIVERY_CLASSES = frozenset({
    "final", "partial", "diagnostic", "blocked",
})

#: A composition score must be strictly greater than this value.
COMPOSITION_PASS_SCORE = 80.0
COMPOSITION_PASS_TEXT = f"{COMPOSITION_PASS_SCORE:g}"

COMPOSITION_STATUSES = frozenset({"pass", "fail", "blocked", "exempt"})
STAGING_DESIGN_CHECK_ID = "staging_design_vs_observed"
STAGING_DESIGN_SCOPE = "camera_and_character_start_positions"
STAGING_DESIGN_STATUSES = frozenset({"pass", "fail", "blocked"})
STAGING_DESIGN_METRICS = {
    "camera_position": DIFF_THRESHOLDS["camera_position_m"],
    "camera_target_position": DIFF_THRESHOLDS["camera_target_position_m"],
    "character_position": DIFF_THRESHOLDS["character_position_m"],
}
_COMPOSITION_DECISION_FIELDS = frozenset({
    "schema_version",
    "component",
    "status",
    "reason",
    "score",
    "threshold",
    "strict",
})


def _finite_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be numeric: {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be finite: {value!r}")
    return number


def _strict_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{field_name} must be a bool: {value!r}")
    return value


def composition_decision(
    score: Any,
    *,
    empty_shot_declared: bool = False,
    empty_shot_evidence: bool = False,
    threshold: float = COMPOSITION_PASS_SCORE,
) -> Dict[str, Any]:
    """Classify one shot's composition evidence.

    Missing measurements are never treated as success. Empty shots are
    exempt only when both the declaration and its evidence are present.
    """
    empty_shot_declared = _strict_bool(
        empty_shot_declared, "empty_shot_declared")
    empty_shot_evidence = _strict_bool(
        empty_shot_evidence, "empty_shot_evidence")
    threshold_value = _finite_number(threshold, "threshold")
    if empty_shot_declared and not empty_shot_evidence:
        return {
            "schema_version": QUALITY_CONTRACT_VERSION,
            "component": "composition",
            "status": "blocked",
            "reason": "empty_shot_evidence_missing",
            "score": None,
            "threshold": threshold_value,
            "strict": True,
        }
    if empty_shot_declared:
        return {
            "schema_version": QUALITY_CONTRACT_VERSION,
            "component": "composition",
            "status": "exempt",
            "reason": "declared_empty_shot",
            "score": None,
            "threshold": threshold_value,
            "strict": True,
        }
    if score is None:
        return {
            "schema_version": QUALITY_CONTRACT_VERSION,
            "component": "composition",
            "status": "blocked",
            "reason": "composition_unresolved",
            "score": None,
            "threshold": threshold_value,
            "strict": True,
        }
    value = _finite_number(score, "composition score")
    passed = value > threshold_value
    return {
        "schema_version": QUALITY_CONTRACT_VERSION,
        "component": "composition",
        "status": "pass" if passed else "fail",
        "reason": "" if passed else "composition_not_strictly_above_threshold",
        "score": value,
        "threshold": threshold_value,
        "strict": True,
    }


def validate_quality_decision(decision: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate and normalize one composition quality decision.

    Unknown fields and statuses, incomplete payloads, inconsistent
    status/reason pairs and inconsistent score/threshold combinations fail
    here instead of leaking into reports or delivery.
    """
    if not isinstance(decision, Mapping):
        raise ValueError("quality decision must be a mapping")
    unknown = sorted(set(decision).difference(_COMPOSITION_DECISION_FIELDS))
    if unknown:
        raise ValueError(f"quality decision has unknown fields: {unknown}")
    missing = sorted(_COMPOSITION_DECISION_FIELDS.difference(decision))
    if missing:
        raise ValueError(f"quality decision missing fields: {missing}")
    if decision["schema_version"] != QUALITY_CONTRACT_VERSION:
        raise ValueError(
            f"unsupported quality contract: {decision['schema_version']!r}")
    if decision["component"] != "composition":
        raise ValueError(f"unknown quality component: {decision['component']!r}")
    status = str(decision["status"])
    if status not in COMPOSITION_STATUSES:
        raise ValueError(f"unknown quality status: {status!r}")
    if not isinstance(decision["reason"], str):
        raise ValueError("quality reason must be a string")
    reason = decision["reason"]
    allowed_reasons = {
        "pass": {""},
        "fail": {"composition_not_strictly_above_threshold"},
        "blocked": {
            "composition_unresolved",
            "empty_shot_evidence_missing",
        },
        "exempt": {"declared_empty_shot"},
    }
    if reason not in allowed_reasons[status]:
        raise ValueError(
            f"quality status {status!r} has incompatible reason {reason!r}")
    if decision["strict"] is not True:
        raise ValueError("composition quality decision must be strict")
    threshold = _finite_number(decision["threshold"], "threshold")
    score = decision["score"]
    if status in {"blocked", "exempt"}:
        if score is not None:
            raise ValueError(f"{status} quality decision must not carry a score")
    else:
        value = _finite_number(score, "composition score")
        expected = "pass" if value > threshold else "fail"
        if status != expected:
            raise ValueError(
                f"quality status {status!r} contradicts score {value!r} "
                f"and threshold {threshold!r}")
    return {
        key: decision[key]
        for key in (
            "schema_version",
            "component",
            "status",
            "reason",
            "score",
            "threshold",
            "strict",
        )
    }


def serialize_quality_decision(decision: Mapping[str, Any]) -> str:
    """Stable JSON encoding after full contract validation."""
    normalized = validate_quality_decision(decision)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _staging_blocked(reason: str, *, actual: Any = None,
                     threshold: float | None = None) -> Dict[str, Any]:
    return {
        "schema_version": QUALITY_CONTRACT_VERSION,
        "component": "staging_design",
        "status": "blocked",
        "reason": reason,
        "scope": STAGING_DESIGN_SCOPE,
        "actual": actual,
        "threshold": threshold,
        "strict": True,
    }


def staging_design_decision(
    check: Mapping[str, Any] | None,
) -> Dict[str, Any]:
    """Classify one shot's camera/character start-position evidence.

    The legacy ``design_vs_observed`` check only compared a camera start
    position and therefore cannot authorize the whole coarse staging phase.
    This decision consumes the shot-scoped replacement check. Missing,
    duplicate, malformed, or incomplete evidence is blocked rather than
    guessed from the top-level verdict.
    """
    if not isinstance(check, Mapping):
        return _staging_blocked("staging_design_unresolved")
    evidence = check.get("evidence")
    if not isinstance(evidence, Mapping):
        return _staging_blocked("staging_design_unresolved")
    if evidence.get("scope") not in {None, STAGING_DESIGN_SCOPE}:
        return _staging_blocked("staging_design_evidence_invalid")
    coverage = evidence.get("coverage")
    items = evidence.get("items")
    if not isinstance(coverage, Mapping) or not isinstance(items, Sequence) \
            or isinstance(items, (str, bytes)):
        return _staging_blocked("staging_design_unresolved")
    if not items:
        return _staging_blocked("staging_design_unresolved")

    missing_subjects = coverage.get("missing_subjects")
    if not isinstance(missing_subjects, Sequence) \
            or isinstance(missing_subjects, (str, bytes)):
        return _staging_blocked("staging_design_evidence_invalid")
    if missing_subjects:
        return _staging_blocked("staging_design_subject_missing")

    counts: Dict[str, int] = {}
    for key in (
        "camera_expected",
        "camera_observed",
        "characters_expected",
        "characters_observed",
    ):
        value = coverage.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return _staging_blocked("staging_design_evidence_invalid")
        counts[key] = value
    for key in ("camera_target_expected", "camera_target_observed"):
        value = coverage.get(key, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return _staging_blocked("staging_design_evidence_invalid")
        counts[key] = value
    if counts["camera_observed"] > counts["camera_expected"] \
            or counts["camera_target_observed"] > counts[
                "camera_target_expected"] \
            or counts["characters_observed"] > counts["characters_expected"]:
        return _staging_blocked("staging_design_evidence_invalid")

    normalized_items: list[Mapping[str, Any]] = []
    seen_subjects: set[tuple[str, str]] = set()
    for raw in items:
        if not isinstance(raw, Mapping):
            return _staging_blocked("staging_design_evidence_invalid")
        metric = str(raw.get("metric") or "")
        subject = str(raw.get("subject") or "")
        if metric not in STAGING_DESIGN_METRICS or not subject:
            return _staging_blocked("staging_design_evidence_invalid")
        identity = (metric, subject)
        if identity in seen_subjects:
            return _staging_blocked("staging_design_evidence_invalid")
        seen_subjects.add(identity)
        expected = raw.get("expected")
        if not isinstance(expected, Sequence) \
                or isinstance(expected, (str, bytes)) or len(expected) != 3:
            return _staging_blocked("staging_design_evidence_invalid")
        try:
            for value in expected:
                _finite_number(value, "expected")
        except ValueError:
            return _staging_blocked("staging_design_evidence_invalid")
        threshold_value = raw.get("threshold")
        try:
            threshold = _finite_number(threshold_value, "threshold")
        except ValueError:
            return _staging_blocked("staging_design_evidence_invalid")
        if threshold != STAGING_DESIGN_METRICS[metric]:
            return _staging_blocked("staging_design_evidence_invalid")
        verdict = str(raw.get("verdict") or "")
        if verdict not in {"pass", "fail", "unresolved"}:
            return _staging_blocked("staging_design_evidence_invalid")
        actual = raw.get("actual")
        if verdict == "unresolved":
            if actual is not None:
                return _staging_blocked("staging_design_evidence_invalid")
        else:
            try:
                actual_value = _finite_number(actual, "actual")
            except ValueError:
                return _staging_blocked("staging_design_evidence_invalid")
            expected_verdict = (
                "pass" if actual_value <= threshold else "fail")
            if verdict != expected_verdict:
                return _staging_blocked("staging_design_evidence_invalid")
        normalized_items.append(raw)

    expected_item_count = (
        counts["camera_expected"]
        + counts["camera_target_expected"]
        + counts["characters_expected"])
    if expected_item_count <= 0 or len(normalized_items) != expected_item_count:
        return _staging_blocked("staging_design_unresolved")

    metric_counts: Dict[str, int] = {}
    for item in normalized_items:
        metric = str(item["metric"])
        metric_counts[metric] = metric_counts.get(metric, 0) + 1
    if metric_counts.get("camera_position", 0) != counts["camera_expected"] \
            or metric_counts.get("camera_target_position", 0) != counts[
                "camera_target_expected"] \
            or metric_counts.get("character_position", 0) != (
                counts["characters_expected"]):
        return _staging_blocked("staging_design_unresolved")

    observed_items = [
        item for item in normalized_items
        if str(item["verdict"]) != "unresolved"
    ]
    unresolved_items = len(normalized_items) - len(observed_items)
    if unresolved_items != (
        counts["camera_expected"] - counts["camera_observed"]
        + counts["camera_target_expected"] - counts[
            "camera_target_observed"]
        + counts["characters_expected"] - counts["characters_observed"]
    ):
        return _staging_blocked("staging_design_evidence_invalid")

    numeric_actuals = [
        float(item["actual"]) for item in observed_items
    ]
    actual_max = max(numeric_actuals) if numeric_actuals else None
    try:
        top_actual = (
            None if check.get("actual") is None
            else _finite_number(check.get("actual"), "actual"))
        top_threshold = _finite_number(check.get("threshold"), "threshold")
    except ValueError:
        return _staging_blocked("staging_design_evidence_invalid")
    if top_threshold != max(STAGING_DESIGN_METRICS.values()):
        return _staging_blocked("staging_design_evidence_invalid")
    if unresolved_items:
        if top_actual is not None:
            return _staging_blocked("staging_design_evidence_invalid")
        return _staging_blocked(
            "staging_design_unresolved", threshold=top_threshold)
    if top_actual != actual_max or str(check.get("verdict") or "") not in {
            "pass", "fail"}:
        return _staging_blocked("staging_design_evidence_invalid")
    failing = any(str(item["verdict"]) == "fail"
                  for item in normalized_items)
    final_status = "fail" if failing else "pass"
    if str(check.get("verdict") or "") != final_status:
        return _staging_blocked("staging_design_evidence_invalid")
    return {
        "schema_version": QUALITY_CONTRACT_VERSION,
        "component": "staging_design",
        "status": final_status,
        "reason": "" if final_status == "pass" else "staging_design_not_passing",
        "scope": STAGING_DESIGN_SCOPE,
        "actual": actual_max,
        "threshold": top_threshold,
        "strict": True,
    }


def blockout_quality_report(report: Mapping[str, Any]) -> Dict[str, Any]:
    """Fold a BlockoutReport into the canonical run/shots quality result."""
    findings = [item for item in (report.get("findings") or [])
                if isinstance(item, Mapping)]
    checks = [item for item in (report.get("checks") or [])
              if isinstance(item, Mapping)]
    hard_errors = [item for item in findings
                   if str(item.get("severity") or "") == "error"]
    hard_errors_by_shot: Dict[str, int] = {}
    for finding in hard_errors:
        shot_id = str(finding.get("shot_id") or "")
        hard_errors_by_shot[shot_id] = hard_errors_by_shot.get(shot_id, 0) + 1

    checks_by_shot: Dict[str, list[Mapping[str, Any]]] = {}
    for check in checks:
        shot_id = str(check.get("shot_id") or "")
        if shot_id:
            checks_by_shot.setdefault(shot_id, []).append(check)

    shots: Dict[str, Dict[str, Any]] = {}
    measurable_scores = []
    blocked_reasons = []
    for shot_id, shot_checks in sorted(checks_by_shot.items()):
        composition_checks = [
            check for check in shot_checks
            if str(check.get("check_id") or "") == "composition"
        ]
        staging_checks = [
            check for check in shot_checks
            if str(check.get("check_id") or "") == STAGING_DESIGN_CHECK_ID
        ]
        composition = (
            composition_checks[0] if len(composition_checks) == 1 else None)
        staging = (
            staging_checks[0] if len(staging_checks) == 1 else None)
        empty_evidence = any(
            str(check.get("check_id") or "") == "empty_shot"
            and str(check.get("verdict") or "") in {"pass", "exempt"}
            for check in shot_checks
        )
        decision = composition_decision(
            composition.get("actual")
            if isinstance(composition, Mapping) else None,
            empty_shot_declared=empty_evidence,
            empty_shot_evidence=empty_evidence,
        )
        if decision["status"] not in {"pass", "exempt"}:
            blocked_reasons.append(
                f"{shot_id}:{decision['reason'] or decision['status']}")
        staging_decision = staging_design_decision(staging)
        if staging_decision["status"] != "pass":
            blocked_reasons.append(
                f"{shot_id}:"
                f"{staging_decision['reason'] or staging_decision['status']}")
        if decision["status"] in {"pass", "fail"}:
            measurable_scores.append(float(decision["score"]))
        shots[shot_id] = {
            "composition": decision,
            "staging_design": staging_decision,
            "hard_error_count": int(hard_errors_by_shot.get(shot_id, 0)),
            "empty_shot_evidence": empty_evidence,
        }

    #: Findings can name a shot which has no check row yet. Keep it blocked
    #: instead of silently dropping the entity from the quality decision.
    for shot_id in sorted(hard_errors_by_shot):
        if shot_id and shot_id not in shots:
            decision = composition_decision(None)
            staging_decision = staging_design_decision(None)
            blocked_reasons.append(
                f"{shot_id}:{decision['reason'] or decision['status']}")
            blocked_reasons.append(
                f"{shot_id}:"
                f"{staging_decision['reason'] or staging_decision['status']}")
            shots[shot_id] = {
                "composition": decision,
                "staging_design": staging_decision,
                "hard_error_count": hard_errors_by_shot[shot_id],
                "empty_shot_evidence": False,
            }

    #: A report-level verdict is not evidence that an individual shot was
    #: measured.  Without per-shot checks the run is unresolved, even when a
    #: legacy producer wrote ``verdict: pass``.
    if not shots:
        gate_ready = False
        blocked_reasons.append("composition_unresolved")
        min_composition = None
    else:
        min_composition = (min(measurable_scores)
                           if measurable_scores else None)
        gate_ready = (
            not hard_errors
            and all(shot["composition"]["status"] in {"pass", "exempt"}
                    and shot["staging_design"]["status"] == "pass"
                    for shot in shots.values())
        )

    return {
        "schema_version": QUALITY_CONTRACT_VERSION,
        "component": "blockout",
        "gate_ready": gate_ready,
        "min_composition": min_composition,
        "hard_error_count": len(hard_errors),
        "unresolved_count": sum(
            1 for shot in shots.values()
            if shot["composition"]["status"] == "blocked"
            or shot["staging_design"]["status"] == "blocked"),
        "blocked_reasons": blocked_reasons,
        "shots": shots,
    }


def classify_delivery_quality(
    *,
    evidence_store: EvidenceStore | None,
    shot_ids: Sequence[str],
    sequence_review: Mapping[str, Any] | None,
    pending_review_shot_ids: Sequence[str] = (),
    delivered_shot_ids: Sequence[str] | None = None,
    blocked_shots: Mapping[str, str] | None = None,
) -> Dict[str, Any]:
    """Derive one delivery identity from the authoritative shot evidence.

    This is the only place which decides whether a run may call itself
    ``final``.  A failed shot's retained best remains useful for
    ``diagnostic`` delivery but can never satisfy the final sequence contract.
    """
    ordered = [str(shot_id) for shot_id in shot_ids if str(shot_id)]
    pending_input = [
        str(shot_id) for shot_id in pending_review_shot_ids if str(shot_id)
    ]
    pending = list(dict.fromkeys(pending_input))
    blocked = {
        str(shot_id): str(reason)
        for shot_id, reason in (blocked_shots or {}).items()
        if str(shot_id)
    }
    if not ordered:
        errors = [
            f"{shot_id}:{reason or 'blocked'}"
            for shot_id, reason in sorted(blocked.items())
        ]
        return {
            "schema_version": QUALITY_CONTRACT_VERSION,
            "component": "delivery",
            "delivery_class": "blocked",
            "reasons": ["no_non_empty_shots"] + errors,
            "passed_shots": [],
            "failed_shots": [],
            "pending_review_shots": pending,
            "selected_shots": [],
            "sequence_reviewed_shots": [],
            "sequence_review_passed": False,
            "full_sequence_review_passed": False,
            "subset_sequence_review_passed": False,
            "delivered_shots": [],
            "artifact_check_complete": delivered_shot_ids is not None,
            "adoption_explanations": {},
            "blocked_shots": blocked,
        }
    delivered = (
        list(dict.fromkeys(
            str(shot_id) for shot_id in delivered_shot_ids
            if str(shot_id)
        ))
        if delivered_shot_ids is not None else []
    )
    artifact_check_complete = delivered_shot_ids is not None
    if evidence_store is None:
        return {
            "schema_version": QUALITY_CONTRACT_VERSION,
            "component": "delivery",
            "delivery_class": "blocked",
            "reasons": ["authoritative_evidence_store_unavailable"],
            "passed_shots": [],
            "failed_shots": [],
            "pending_review_shots": pending,
            "selected_shots": [],
            "sequence_reviewed_shots": [],
            "sequence_review_passed": False,
            "full_sequence_review_passed": False,
            "subset_sequence_review_passed": False,
            "delivered_shots": delivered,
            "artifact_check_complete": artifact_check_complete,
            "adoption_explanations": {},
            "blocked_shots": blocked,
        }
    passed: list[str] = []
    failed: list[str] = []
    adoption_explanations: dict[str, str] = {}
    blocked_reasons: list[str] = [
        f"{shot_id}:{reason or 'blocked'}"
        for shot_id, reason in sorted(blocked.items())
    ]
    if len(set(ordered)) != len(ordered):
        blocked_reasons.append("duplicate_shot_ids")
    if len(pending_input) != len(pending):
        blocked_reasons.append("duplicate_pending_review_shot_ids")
    pending_set = set(pending)
    duplicate_pending = {
        shot_id for shot_id in pending
        if pending_input.count(shot_id) > 1
    }
    blocked_reasons.extend(
        f"pending_review_shot_not_in_run:{shot_id}"
        for shot_id in pending
        if shot_id not in set(ordered) and shot_id not in duplicate_pending
    )
    for shot_id in ordered:
        try:
            best_version = evidence_store.best_version(shot_id)
            record = evidence_store.get(shot_id, best_version)
        except KeyError:
            blocked_reasons.append(f"{shot_id}:best_evidence_missing")
            if shot_id not in pending_set:
                failed.append(shot_id)
            continue
        evidence_errors = record.verify_errors()
        if evidence_errors:
            blocked_reasons.extend(
                f"{shot_id}:{reason}" for reason in evidence_errors)
            adoption_explanations[shot_id] = "evidence_incomplete"
            if shot_id not in pending_set:
                failed.append(shot_id)
            continue
        if shot_id in pending_set:
            continue
        try:
            adopted = evidence_store.adopted_version(shot_id)
        except KeyError:
            adopted = None
        if (
            adopted == best_version
            and record.is_passing()
            and record.delivery_eligible is True
        ):
            passed.append(shot_id)
        else:
            semantic_required = (
                record.semantic_review.get("required") is True
            )
            semantic_passed = (
                not semantic_required
                or record.semantic_review.get("reviewed") is True
            )
            if not semantic_passed:
                adoption_explanations[shot_id] = (
                    "required_semantic_review_not_passed")
            elif record.is_passing() and record.delivery_eligible is not True:
                adoption_explanations[shot_id] = (
                    "shot_evidence_not_delivery_eligible")
            elif record.is_passing():
                adoption_explanations[shot_id] = (
                    "best_score_above_threshold_but_version_not_adopted")
            elif str(record.hard_gates.get("status") or "") not in {
                    "", "pass"}:
                adoption_explanations[shot_id] = (
                    "required_hard_gate_not_passed")
            else:
                adoption_explanations[shot_id] = (
                    "composition_not_strictly_above_threshold")
            failed.append(shot_id)

    review = dict(sequence_review or {})
    reviewed_ids = [
        str(shot_id) for shot_id in (review.get("shot_ids") or [])
        if str(shot_id)
    ]
    full_sequence_review_passed = (
        str(review.get("verdict") or "") == "pass"
        and reviewed_ids == ordered
    )
    subset_review_passed = (
        str(review.get("verdict") or "") == "pass"
        and bool(passed)
        and reviewed_ids == passed
    )
    if blocked_reasons:
        delivery_class = "blocked"
        reasons = list(blocked_reasons)
        selected = list(ordered)
    elif pending:
        delivery_class = "diagnostic"
        reasons = ["pending_re_review_prevents_final_delivery"]
        selected = list(ordered)
    elif failed and subset_review_passed:
        delivery_class = "partial"
        reasons = ["failed_shots_omitted_from_partial_delivery"]
        selected = list(passed)
    elif failed:
        delivery_class = "diagnostic"
        reasons = ["failed_shots_require_diagnostic_delivery"]
        if not full_sequence_review_passed:
            reasons.append("full_sequence_review_not_passed")
        selected = list(ordered)
    elif full_sequence_review_passed:
        delivery_class = "final"
        reasons = []
        selected = list(ordered)
    else:
        delivery_class = "diagnostic"
        reasons = ["full_sequence_review_not_passed"]
        selected = list(ordered)
    selected_sequence_review_passed = (
        str(review.get("verdict") or "") == "pass"
        and reviewed_ids == selected
    )
    if len(set(delivered)) != len(delivered):
        blocked_reasons.append("duplicate_delivered_shot_ids")
    if any(shot_id not in set(ordered) for shot_id in delivered):
        blocked_reasons.append("delivered_shot_not_in_plan")
    if artifact_check_complete and (
        len(set(delivered)) != len(delivered)
        or any(shot_id not in set(ordered) for shot_id in delivered)
        or set(delivered) != set(selected)
    ):
        delivery_class = "blocked"
        reasons = ["delivered_artifact_set_mismatch"] + reasons + blocked_reasons
        blocked_reasons = []
    elif artifact_check_complete:
        delivered = list(selected)

    return {
        "schema_version": QUALITY_CONTRACT_VERSION,
        "component": "delivery",
        "delivery_class": delivery_class,
        "reasons": list(dict.fromkeys(reasons + blocked_reasons)),
        "passed_shots": passed,
        "failed_shots": failed,
        "pending_review_shots": pending,
        "selected_shots": selected,
        "sequence_reviewed_shots": reviewed_ids,
        "sequence_review_passed": selected_sequence_review_passed,
        "full_sequence_review_passed": full_sequence_review_passed,
        "subset_sequence_review_passed": subset_review_passed,
        "delivered_shots": delivered,
        "artifact_check_complete": artifact_check_complete,
        "adoption_explanations": adoption_explanations,
        "blocked_shots": blocked,
    }


__all__ = [
    "COMPOSITION_PASS_SCORE",
    "COMPOSITION_PASS_TEXT",
    "COMPOSITION_STATUSES",
    "DELIVERY_CLASSES",
    "STAGING_DESIGN_CHECK_ID",
    "STAGING_DESIGN_SCOPE",
    "STAGING_DESIGN_STATUSES",
    "QUALITY_CONTRACT_VERSION",
    "blockout_quality_report",
    "classify_delivery_quality",
    "composition_decision",
    "serialize_quality_decision",
    "staging_design_decision",
    "validate_quality_decision",
]
