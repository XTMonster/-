"""Deterministic, serializable adversarial review for one shot version.

This module produces review findings and adjustable-variable suggestions only;
it never mutates a shot plan. Safe-area and thirds measurements are soft visual
references, while the authoritative audit findings remain hard constraints.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping, Optional, Sequence, Tuple


_DISPOSITIONS = frozenset(("pass", "revise", "escalate"))
_SEVERITIES = frozenset(("hard", "major", "minor", "soft"))
_REVIEWER = "adversarial_review_v1"


@dataclass(frozen=True)
class ReviewIssue:
    """One evidence-backed review issue and a suggestion, not a plan edit."""

    type: str
    severity: str
    evidence: str
    suggestion: str
    score_delta: Optional[float] = None

    def __post_init__(self) -> None:
        if self.severity not in _SEVERITIES:
            raise ValueError(f"unsupported issue severity: {self.severity}")
        if not self.type.strip():
            raise ValueError("issue type must be non-empty")
        if not self.evidence.strip():
            raise ValueError("issue evidence must be non-empty")
        if not self.suggestion.strip():
            raise ValueError("issue suggestion must be non-empty")
        if self.score_delta is not None and not math.isfinite(float(self.score_delta)):
            raise ValueError("score_delta must be finite when supplied")

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "severity": self.severity,
            "evidence": self.evidence,
            "suggestion": self.suggestion,
            "score_delta": self.score_delta,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReviewIssue":
        return cls(
            type=str(data["type"]),
            severity=str(data["severity"]),
            evidence=str(data["evidence"]),
            suggestion=str(data["suggestion"]),
            score_delta=(None if data.get("score_delta") is None
                         else float(data["score_delta"])),
        )


@dataclass(frozen=True)
class AdversarialReview:
    """Immutable review record associated with a particular shot version."""

    shot_id: str
    version: int
    disposition: str
    issues: Tuple[ReviewIssue, ...]
    rationale: str
    reviewer: str = _REVIEWER

    def __post_init__(self) -> None:
        if not self.shot_id.strip():
            raise ValueError("shot_id must be non-empty")
        if self.version < 0:
            raise ValueError("version must be non-negative")
        if self.disposition not in _DISPOSITIONS:
            raise ValueError(f"unsupported disposition: {self.disposition}")
        if not self.reviewer.strip():
            raise ValueError("reviewer must be non-empty")
        if not isinstance(self.issues, tuple):
            object.__setattr__(self, "issues", tuple(self.issues))

    def to_dict(self) -> dict[str, Any]:
        return {
            "shot_id": self.shot_id,
            "version": self.version,
            "disposition": self.disposition,
            "issues": [issue.to_dict() for issue in self.issues],
            "rationale": self.rationale,
            "reviewer": self.reviewer,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AdversarialReview":
        return cls(
            shot_id=str(data["shot_id"]),
            version=int(data["version"]),
            disposition=str(data["disposition"]),
            issues=tuple(ReviewIssue.from_dict(item)
                         for item in data.get("issues", ())),
            rationale=str(data.get("rationale", "")),
            reviewer=str(data.get("reviewer", _REVIEWER)),
        )


def _finding_text(finding: Any) -> str:
    """Normalize common audit DTOs without relying on object repr/address."""
    if isinstance(finding, str):
        return finding.strip()
    if isinstance(finding, Mapping):
        rule = finding.get("rule", finding.get("code", ""))
        detail = next((finding[key] for key in
                       ("message", "detail", "description", "error")
                       if finding.get(key)), "")
        if rule and detail:
            return f"{rule}: {detail}"
        if rule or detail:
            return str(rule or detail)
        return "; ".join(
            f"{key}={finding[key]}" for key in sorted(finding, key=str))
    rule = getattr(finding, "rule", getattr(finding, "code", ""))
    detail = getattr(finding, "message", getattr(finding, "detail", ""))
    if rule and detail:
        return f"{rule}: {detail}"
    if rule or detail:
        return str(rule or detail)
    return type(finding).__name__


def _is_indicator(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1", "outside", "unsafe"}
    return False


def _reference_deviations(values: Mapping[str, Any], *, kind: str) -> Tuple[str, ...]:
    """Read explicitly supplied deviations as soft references, never hard gates."""
    details = []
    for key in sorted(values, key=str):
        name = str(key)
        normalized = name.lower()
        value = values[key]
        if kind == "safe_area":
            if any(token in normalized for token in
                   ("violation", "outside", "unsafe", "overflow")):
                if _is_indicator(value):
                    details.append(f"{name}={value}")
            elif any(token in normalized for token in
                     ("within", "inside", "contained", "safe")):
                if value is False:
                    details.append(f"{name}={value}")
        else:
            if "deviation" in normalized:
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    if float(value) > 0:
                        details.append(f"{name}={value}")
                elif _is_indicator(value):
                    details.append(f"{name}={value}")
            elif any(token in normalized for token in
                     ("third", "aligned", "on_grid")) and value is False:
                details.append(f"{name}={value}")
    return tuple(details)


def _has_axis_violation(findings: Sequence[str]) -> bool:
    return any("R001" in item.upper() or "越轴" in item or
               "axis violation" in item.lower() for item in findings)


def review_shot(
    *,
    shot_id: str,
    version: int,
    intent: str,
    audit_passed: bool,
    audit_findings: Sequence[Any],
    framing: Mapping[str, Any],
    safe_area: Mapping[str, Any],
    thirds: Mapping[str, Any],
    visible_ratio: float,
) -> AdversarialReview:
    """Review one immutable shot version and return findings, never edits.

    ``safe_area`` and ``thirds`` are advisory ruler readings. Only hard audit
    findings or major visibility loss can require revision; explicit axis
    violations are escalated for an independent decision.
    """
    ratio = float(visible_ratio)
    if not math.isfinite(ratio) or not 0.0 <= ratio <= 1.0:
        raise ValueError("visible_ratio must be finite and between 0 and 1")

    normalized_findings = tuple(
        text for text in (_finding_text(item) for item in audit_findings)
        if text)
    framing_label = str(framing.get("shot_type", framing.get("framing", "unspecified")))
    intent_label = str(intent).strip() or "unspecified"
    issues = []
    hard_failure = not bool(audit_passed) or bool(normalized_findings)

    if hard_failure:
        evidence = ("; ".join(normalized_findings) if normalized_findings else
                    "hard audit did not pass; no finding detail was supplied")
        suggestion = (
            "Revisit subject placement or camera distance to address the hard audit finding."
            if _has_axis_violation(normalized_findings) else
            "Adjust camera distance, lens, target offset, action timing, or subject placement to resolve the hard finding."
        )
        issues.append(ReviewIssue(
            type="hard_audit_finding",
            severity="hard",
            evidence=evidence,
            suggestion=suggestion,
        ))

    if _has_axis_violation(normalized_findings):
        disposition = "escalate"
    else:
        disposition = "revise" if hard_failure else "pass"

    if ratio <= 0.2:
        issues.append(ReviewIssue(
            type="subject_visibility",
            severity="major",
            evidence=f"visible_ratio={ratio:.6g}; subject is at or below the 0.2 visibility floor",
            suggestion="Adjust camera distance, lens, or subject placement to restore visible subject area.",
        ))
        if disposition == "pass":
            disposition = "revise"

    safe_deviations = _reference_deviations(safe_area, kind="safe_area")
    if safe_deviations:
        issues.append(ReviewIssue(
            type="safe_area_reference",
            severity="soft",
            evidence="safe-area reference deviation: " + ", ".join(safe_deviations),
            suggestion="Consider subject placement or target offset; the safe-area ruler is advisory.",
        ))

    thirds_deviations = _reference_deviations(thirds, kind="thirds")
    if thirds_deviations:
        issues.append(ReviewIssue(
            type="thirds_grid_reference",
            severity="soft",
            evidence="thirds-grid reference deviation: " + ", ".join(thirds_deviations),
            suggestion="Consider subject placement or camera distance; the thirds grid is advisory.",
        ))

    if not issues:
        rationale = (f"No hard findings; framing={framing_label}; "
                     f"intent={intent_label}; visible_ratio={ratio:.6g}.")
    else:
        rationale = (f"{sum(i.severity == 'hard' for i in issues)} hard, "
                     f"{sum(i.severity == 'major' for i in issues)} major, "
                     f"{sum(i.severity == 'soft' for i in issues)} soft issue(s); "
                     f"framing={framing_label}; intent={intent_label}; "
                     f"visible_ratio={ratio:.6g}.")

    return AdversarialReview(
        shot_id=str(shot_id),
        version=int(version),
        disposition=disposition,
        issues=tuple(issues),
        rationale=rationale,
        reviewer=_REVIEWER,
    )
