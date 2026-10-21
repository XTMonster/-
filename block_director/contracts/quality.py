"""Versioned, pure quality contract shared by every pipeline layer."""

from __future__ import annotations

import json
import math
from typing import Any, Dict, Mapping

QUALITY_CONTRACT_VERSION = "quality-contract/v1"

#: A composition score must be strictly greater than this value.
COMPOSITION_PASS_SCORE = 80.0
COMPOSITION_PASS_TEXT = f"{COMPOSITION_PASS_SCORE:g}"

COMPOSITION_STATUSES = frozenset({"pass", "fail", "blocked", "exempt"})
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
        composition = next(
            (check for check in shot_checks
             if str(check.get("check_id") or "") == "composition"),
            None,
        )
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
        if decision["status"] in {"pass", "fail"}:
            measurable_scores.append(float(decision["score"]))
        shots[shot_id] = {
            "composition": decision,
            "hard_error_count": int(hard_errors_by_shot.get(shot_id, 0)),
            "empty_shot_evidence": empty_evidence,
        }

    #: Findings can name a shot which has no check row yet. Keep it blocked
    #: instead of silently dropping the entity from the quality decision.
    for shot_id in sorted(hard_errors_by_shot):
        if shot_id and shot_id not in shots:
            decision = composition_decision(None)
            blocked_reasons.append(
                f"{shot_id}:{decision['reason'] or decision['status']}")
            shots[shot_id] = {
                "composition": decision,
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
            if shot["composition"]["status"] == "blocked"),
        "blocked_reasons": blocked_reasons,
        "shots": shots,
    }


__all__ = [
    "COMPOSITION_PASS_SCORE",
    "COMPOSITION_PASS_TEXT",
    "COMPOSITION_STATUSES",
    "QUALITY_CONTRACT_VERSION",
    "blockout_quality_report",
    "composition_decision",
    "serialize_quality_decision",
    "validate_quality_decision",
]
