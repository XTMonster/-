"""Per-shot detail revision loop.

The loop is intentionally pure Python.  Blender rendering, world mutation and
rollback are injected through callbacks so the quality decision can be tested
and replayed without ``bpy``.
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Dict, Mapping, Sequence

from block_director.cinema.coarse_revision import apply_coarse_prescriptions
from block_director.contracts.audit import canonical_fingerprint
from block_director.contracts.coarse_proposal import (
    CoarseProposalRequest,
    validate_coarse_proposal,
)
from block_director.contracts.coarse_reference import (
    coarse_reference_content_fingerprint,
)
from block_director.contracts.correction import (
    correction_candidate_dispositions,
    correction_candidate_lifecycle,
)
from block_director.contracts.quality import blockout_quality_report
from block_director.contracts.world_state import world_state_fingerprint


class DetailLoopBlocked(RuntimeError):
    """A detail callback blocked the loop with a stable machine-readable code."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "detail_loop_blocked",
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = str(code or "detail_loop_blocked")
        self.details = copy.deepcopy(dict(details or {}))


def _observation_report(observation: Any) -> Dict[str, Any]:
    if isinstance(observation, Mapping):
        report = observation.get("report")
        if isinstance(report, Mapping):
            return copy.deepcopy(dict(report))
        return copy.deepcopy(dict(observation))
    report = getattr(observation, "report", None)
    if isinstance(report, Mapping):
        return copy.deepcopy(dict(report))
    raise TypeError("observe() must return an observation or blockout report")


def _observation_complete(observation: Any) -> bool:
    complete = getattr(observation, "complete", None)
    if complete is not None:
        return bool(complete)
    if isinstance(observation, Mapping) and "complete" in observation:
        return observation.get("complete") is True
    # Legacy bare-report seam has no frame pointers.
    return True


def _observation_id(observation: Any) -> str:
    explicit = getattr(observation, "observation_id", None)
    if explicit is None and isinstance(observation, Mapping):
        explicit = observation.get("observation_id")
    return str(explicit or "")


def _observation_errors(observation: Any) -> list[str]:
    raw = getattr(observation, "errors", None)
    if raw is None and isinstance(observation, Mapping):
        raw = observation.get("errors")
    return [str(item) for item in (raw or [])]


def _observation_review_evidence_errors(
    observation: Any,
    shot_id: str,
) -> list[str]:
    """Require the exact first/middle/last evidence behind a shot decision."""
    errors = list(_observation_errors(observation))
    rows: Dict[str, list[Dict[str, Any]]] = {
        "first": [],
        "middle": [],
        "last": [],
    }
    for frame in _observation_frames(observation):
        frame_shot = str(frame.get("shot_id") or "")
        phase = str(frame.get("phase") or "")
        if frame_shot and frame_shot != str(shot_id):
            continue
        if phase in rows:
            rows[phase].append(frame)
    for phase in ("first", "middle", "last"):
        candidates = rows[phase]
        if len(candidates) != 1:
            errors.append(
                f"{shot_id}[{phase}]: expected exactly one review frame, "
                f"found {len(candidates)}")
            continue
        frame = candidates[0]
        if not str(frame.get("path") or frame.get("png") or "").strip():
            errors.append(f"{shot_id}[{phase}]: review frame path is missing")
        if frame.get("readable") is False:
            errors.append(f"{shot_id}[{phase}]: review frame is unreadable")
    return errors


def _observation_semantic_review_errors(observation: Any) -> list[str]:
    report = _observation_report(observation)
    review = report.get("vlm_review")
    if isinstance(review, Mapping):
        review_disposition = review.get("disposition")
        if isinstance(review_disposition, Mapping) \
                and str(review_disposition.get("status") or "") \
                == "escalate_human":
            keys = [
                str(key) for key in (
                    review_disposition.get("escalated_keys") or [])
                if str(key)
            ]
            return [
                "vlm_review: semantic issues escalated after repeated "
                "rounds"
                + (f" ({', '.join(keys)})" if keys else "")
            ]
    if report.get("vlm_review_required") is not True:
        return []
    if not isinstance(review, Mapping):
        return ["vlm_review: required semantic review evidence is missing"]
    status = str(review.get("status") or "")
    outcome = str(review.get("outcome") or "")
    if status == "ok" and outcome in {"reviewed_pass", "reviewed_open"}:
        return []
    reason = str(review.get("reason") or review.get("error") or "").strip()
    detail = outcome or status or "unknown"
    return [
        "vlm_review: required semantic review is "
        + detail
        + (f" ({reason})" if reason else "")
    ]


def _semantic_review_blocked_code(errors: Sequence[str]) -> str:
    if any("escalated after repeated rounds" in str(error)
           for error in errors):
        return "semantic_review_escalated"
    return "semantic_review_required"


def _observation_world_state(observation: Any) -> Dict[str, Any]:
    if isinstance(observation, Mapping):
        value = observation.get("world_state")
    else:
        value = getattr(observation, "world_state", None)
    return copy.deepcopy(dict(value)) if isinstance(value, Mapping) else {}


def _observation_mapping(observation: Any, name: str) -> Dict[str, Any]:
    if isinstance(observation, Mapping):
        value = observation.get(name)
    else:
        value = getattr(observation, name, None)
    return copy.deepcopy(dict(value)) if isinstance(value, Mapping) else {}


def _observation_frames(observation: Any) -> tuple[Dict[str, Any], ...]:
    if isinstance(observation, Mapping):
        value = observation.get("frames")
    else:
        value = getattr(observation, "frames", None)
    if not isinstance(value, (list, tuple)):
        return ()
    result: list[Dict[str, Any]] = []
    for item in value:
        if hasattr(item, "to_dict"):
            item = item.to_dict()
        if isinstance(item, Mapping):
            result.append(copy.deepcopy(dict(item)))
    return tuple(result)


def _observation_correction_candidates(
    observation: Any,
    shot_id: str,
) -> list[Dict[str, Any]]:
    """Return the bounded candidate ledger attached to one observation."""
    report = _observation_report(observation)
    rows = report.get("correction_candidates")
    if not isinstance(rows, (list, tuple)):
        return []
    result: list[Dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        row = copy.deepcopy(dict(raw))
        row_shot = str(row.get("shot_id") or "")
        if row_shot and row_shot != str(shot_id):
            continue
        result.append(row)
    return result


def _operations_with_candidate_refs(
    records: Sequence[Mapping[str, Any]],
    prescriptions: Sequence[Mapping[str, Any]],
) -> list[Dict[str, Any]]:
    """Carry proposal candidate references onto deterministic applier rows."""
    references: Dict[str, list[str]] = {}
    for prescription in prescriptions:
        if not isinstance(prescription, Mapping):
            continue
        prescription_id = str(
            prescription.get("prescription_id") or "")
        if not prescription_id:
            continue
        candidate_ids = prescription.get("candidate_ids")
        if candidate_ids is None and prescription.get("candidate_id"):
            candidate_ids = [prescription.get("candidate_id")]
        references[prescription_id] = [
            str(candidate_id)
            for candidate_id in (candidate_ids or ())
            if str(candidate_id or "")
        ]
    enriched: list[Dict[str, Any]] = []
    for raw in records:
        row = copy.deepcopy(dict(raw))
        prescription_id = str(row.get("prescription_id") or "")
        if not row.get("candidate_ids") and references.get(prescription_id):
            row["candidate_ids"] = list(references[prescription_id])
        enriched.append(row)
    return enriched


def _serializable_observation(observation: Any) -> Any:
    if hasattr(observation, "to_dict"):
        return copy.deepcopy(observation.to_dict())
    return copy.deepcopy(observation)


def _physical_fingerprint(
    observation: Any,
    *,
    fallback_reference: Mapping[str, Any] | None = None,
) -> str:
    explicit = getattr(observation, "world_state_fingerprint", None)
    if explicit is None and isinstance(observation, Mapping):
        explicit = observation.get("world_state_fingerprint")
    if explicit:
        return str(explicit)
    world_state = _observation_world_state(observation)
    if world_state:
        return world_state_fingerprint(world_state)
    observed_reference = _observation_mapping(observation, "reference")
    if observed_reference:
        return coarse_reference_content_fingerprint(observed_reference)
    if fallback_reference:
        return coarse_reference_content_fingerprint(fallback_reference)
    return ""


def _neighbor_state_fingerprint(
    reference: Mapping[str, Any],
    shot_id: str,
) -> str:
    """Hash every non-target shot state while ignoring metadata-only notes."""
    content = copy.deepcopy(dict(reference))
    content.pop("revisions", None)
    content.pop("notes", None)
    content["camera_intents"] = [
        item for item in (content.get("camera_intents") or [])
        if str(item.get("shot_id") or "") != shot_id
    ]
    staging = content.get("shot_staging")
    if isinstance(staging, Mapping):
        content["shot_staging"] = {
            str(key): copy.deepcopy(value)
            for key, value in staging.items()
            if str(key) != shot_id
        }
    return canonical_fingerprint(content)


def _shot_quality(
    report: Mapping[str, Any],
    shot_id: str,
) -> tuple[Dict[str, Any], Dict[str, Any], bool, float | None]:
    quality = blockout_quality_report(report)
    shot = dict((quality.get("shots") or {}).get(shot_id) or {})
    composition = dict(shot.get("composition") or {})
    hard_error_count = int(shot.get("hard_error_count") or 0)
    passed = (
        composition.get("status") in {"pass", "exempt"}
        and hard_error_count == 0
    )
    score = composition.get("score")
    return (
        quality,
        shot,
        passed,
        float(score) if isinstance(score, (int, float)) else None,
    )


def _shot_ids(detail_shots: Sequence[Mapping[str, Any]]) -> list[str]:
    result: list[str] = []
    for row in detail_shots:
        shot_id = str(row.get("shot_id") or "")
        if shot_id and shot_id not in result:
            result.append(shot_id)
    return result


def run_detail_revision_loop(
    *,
    detail_shots: Sequence[Mapping[str, Any]],
    reference: Mapping[str, Any],
    observe: Callable[[Mapping[str, Any], str], Any],
    rebuild: Callable[[Mapping[str, Any], str], None],
    restore_best: Callable[[Mapping[str, Any], str], None] | None = None,
    proposal_provider: Callable[[Any], Mapping[str, Any] | None] | None = None,
    sequence_review: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
    max_revisions: int = 5,
    no_gain_limit: int = 3,
    knowledge_context: str = "",
    record_evidence: (
        Callable[[str, Any, Mapping[str, Any]], None] | None
    ) = None,
) -> Dict[str, Any]:
    """Run isolated observe-propose-apply-remeasure loops per shot.

    The returned reference points at each shot's retained best.  A failed shot
    remains available for diagnostic delivery and prevents sequence review.
    Incomplete evidence and user-owned animation conflicts are blocked;
    budget, proposal, scope and cycle failures are named shot failures.
    """
    if max_revisions < 1:
        raise ValueError("max_revisions must be >= 1")
    if no_gain_limit < 1:
        raise ValueError("no_gain_limit must be >= 1")
    current = copy.deepcopy(dict(reference))
    shots: Dict[str, Dict[str, Any]] = {}
    all_passed = True

    def _record_evidence(
        shot_id: str,
        observation: Any,
        version: Mapping[str, Any],
    ) -> str:
        if record_evidence is None:
            return ""
        try:
            record_evidence(
                shot_id,
                _serializable_observation(observation),
                copy.deepcopy(dict(version)),
            )
        except DetailLoopBlocked as exc:
            return exc.code
        except Exception as exc:  # noqa: BLE001 - evidence failure is named
            return f"{type(exc).__name__}: {exc}"
        return ""

    shot_ids = _shot_ids(detail_shots)
    if not shot_ids:
        all_passed = False

    for shot_id in shot_ids:
        observation = observe(current, shot_id)
        report = _observation_report(observation)
        quality, shot_quality, passed, score = _shot_quality(report, shot_id)
        review_errors = _observation_review_evidence_errors(
            observation, shot_id)
        semantic_errors = _observation_semantic_review_errors(observation)
        review_errors.extend(semantic_errors)
        complete = _observation_complete(observation) and not review_errors
        correction_candidates = _observation_correction_candidates(
            observation, shot_id)
        semantic_review = copy.deepcopy(dict(
            report.get("vlm_review") or {}))
        measurements = copy.deepcopy(dict(
            report.get("measurements") or {}))
        versions = [{
            "version": 0,
            "observation_id": _observation_id(observation),
            "score": score,
            "passed": passed,
            "quality": quality,
            "shot_quality": shot_quality,
            "physical_fingerprint": _physical_fingerprint(
                observation, fallback_reference=current),
            "disposition": "new_high",
            "knowledge_context": str(knowledge_context or ""),
            "proposal": {},
            "semantic_review": semantic_review,
            "measurements": measurements,
            "correction_candidates": correction_candidate_lifecycle(
                [], correction_candidates, [], shot_id=shot_id),
        }]
        evidence_error = _record_evidence(shot_id, observation, versions[0])
        if not complete:
            shots[shot_id] = {
                "status": "blocked",
                "versions": versions,
                "best_version": None,
                "adopted_version": None,
                "best_score": None,
                "blocked_code": (
                    _semantic_review_blocked_code(semantic_errors)
                    if semantic_errors
                    else "observation_evidence_incomplete"),
                "blocked_reason": "; ".join(
                    review_errors
                    or ["observation evidence is incomplete"]),
            }
            all_passed = False
            continue
        if evidence_error:
            shots[shot_id] = {
                "status": "blocked",
                "versions": versions,
                "best_version": None,
                "adopted_version": None,
                "best_score": None,
                "blocked_code": "evidence_record_failed",
                "blocked_reason": evidence_error,
            }
            all_passed = False
            continue
        if passed:
            shots[shot_id] = {
                "status": "passed",
                "versions": versions,
                "best_version": 0,
                "adopted_version": 0,
                "best_score": score,
                "blocked_code": "",
                "blocked_reason": "",
            }
            continue
        best_reference = copy.deepcopy(current)
        best_version = 0
        best_score = score
        best_rank = _quality_rank(
            shot_quality, passed=passed, score=score)
        blocked_code = ""
        blocked_reason = ""
        no_gain = 0
        shot_passed = False
        seen_physical_fingerprints: set[str] = set()
        initial_physical = _physical_fingerprint(
            observation, fallback_reference=current)
        if initial_physical:
            seen_physical_fingerprints.add(initial_physical)
        for revision_no in range(1, max_revisions + 1):
            if proposal_provider is None:
                blocked_code = "agent_proposal_unavailable"
                blocked_reason = (
                    "detail shot did not pass and no Agent proposal provider "
                    "is configured")
                break
            request = CoarseProposalRequest(
                round_no=revision_no,
                observation_id=_observation_id(observation),
                reference=current,
                report=report,
                manifest=_observation_mapping(observation, "manifest"),
                world_state=_observation_world_state(observation),
                frames=_observation_frames(observation),
                knowledge_context=str(knowledge_context or ""),
            )
            try:
                raw = proposal_provider(request=request)
                proposal = validate_coarse_proposal(
                    raw, reference=current)
            except DetailLoopBlocked as exc:
                blocked_code = exc.code
                blocked_reason = str(exc)
                break
            except Exception as exc:  # noqa: BLE001 - provider evidence
                blocked_code = "agent_proposal_rejected"
                blocked_reason = f"{type(exc).__name__}: {exc}"
                break
            prescriptions = list(proposal.get("prescriptions") or [])
            if any(str(item.get("shot_id") or "") != shot_id
                   for item in prescriptions):
                blocked_code = "proposal_scope_violation"
                blocked_reason = (
                    f"proposal for {shot_id} contains prescriptions "
                    "for another shot")
                break
            known_candidate_ids = {
                str(item.get("candidate_id") or "")
                for item in correction_candidates
                if str(item.get("candidate_id") or "")
            }
            unknown_candidate_ids = sorted({
                str(candidate_id)
                for item in prescriptions
                for candidate_id in (item.get("candidate_ids") or [])
                if str(candidate_id)
                and str(candidate_id) not in known_candidate_ids
            })
            if unknown_candidate_ids:
                blocked_code = "invalid_candidate_reference"
                blocked_reason = (
                    f"proposal for {shot_id} references candidate ids that "
                    f"are not in this observation: "
                    + ", ".join(unknown_candidate_ids))
                break
            neighbor_before = _neighbor_state_fingerprint(current, shot_id)
            candidate, records = apply_coarse_prescriptions(
                current,
                prescriptions,
                revision_id=f"detail-{shot_id}-round-{revision_no}",
                round_no=revision_no,
            )
            records = _operations_with_candidate_refs(
                records, prescriptions)
            if not any(record.get("applied") for record in records):
                all_no_op = bool(records) and all(
                    record.get("no_op") for record in records)
                blocked_code = (
                    "prescriptions_all_noop"
                    if all_no_op else "prescriptions_all_rejected")
                blocked_reason = (
                    f"all correction candidates for {shot_id} were "
                    f"{'no-op' if all_no_op else 'rejected'}")
                break
            if _neighbor_state_fingerprint(
                    candidate, shot_id) != neighbor_before:
                blocked_code = "neighbor_state_mutation"
                blocked_reason = (
                    f"candidate for {shot_id} changed another shot's state")
                break
            try:
                rebuild(candidate, shot_id)
            except DetailLoopBlocked as exc:
                blocked_code = exc.code
                blocked_reason = str(exc)
                break
            observation = observe(candidate, shot_id)
            report = _observation_report(observation)
            review_errors = _observation_review_evidence_errors(
                observation, shot_id)
            semantic_errors = _observation_semantic_review_errors(observation)
            review_errors.extend(semantic_errors)
            if not _observation_complete(observation) or review_errors:
                remeasured_correction_candidates = (
                    _observation_correction_candidates(observation, shot_id))
                version = {
                    "version": len(versions),
                    "observation_id": _observation_id(observation),
                    "score": None,
                    "passed": False,
                    "quality": {},
                    "shot_quality": {},
                    "physical_fingerprint": _physical_fingerprint(
                        observation, fallback_reference=candidate),
                    "disposition": "incomplete",
                    "candidate": copy.deepcopy(candidate),
                    "operations": copy.deepcopy(records),
                    "knowledge_context": str(knowledge_context or ""),
                    "proposal": copy.deepcopy(proposal),
                    "semantic_review": copy.deepcopy(dict(
                        report.get("vlm_review") or {})),
                    "measurements": copy.deepcopy(dict(
                        report.get("measurements") or {})),
                    "correction_candidates": correction_candidate_lifecycle(
                        correction_candidates,
                        remeasured_correction_candidates,
                        records,
                        shot_id=shot_id,
                    ),
                }
                versions.append(version)
                evidence_error = _record_evidence(
                    shot_id, observation, version)
                current = copy.deepcopy(best_reference)
                if restore_best is None:
                    blocked_code = "physical_restore_unavailable"
                    blocked_reason = (
                        "candidate evidence is incomplete and no physical "
                        "restore callback is configured")
                else:
                    try:
                        restore_best(current, shot_id)
                    except DetailLoopBlocked as exc:
                        blocked_code = exc.code
                        blocked_reason = str(exc)
                    else:
                        blocked_code = (
                            _semantic_review_blocked_code(semantic_errors)
                            if semantic_errors
                            else "observation_evidence_incomplete")
                        blocked_reason = "; ".join(
                            review_errors
                            or ["candidate observation evidence is incomplete"])
                if evidence_error:
                    blocked_code = "evidence_record_failed"
                    blocked_reason = evidence_error
                break
            (
                quality,
                shot_quality,
                candidate_passed,
                candidate_score,
            ) = _shot_quality(report, shot_id)
            candidate_rank = _quality_rank(
                shot_quality, passed=candidate_passed, score=candidate_score)
            higher = candidate_rank > best_rank
            remeasured_correction_candidates = (
                _observation_correction_candidates(observation, shot_id))
            physical_fingerprint = _physical_fingerprint(
                observation, fallback_reference=candidate)
            repeated_physical_state = bool(
                physical_fingerprint
                and physical_fingerprint in seen_physical_fingerprints
                and not higher
            )
            disposition = "candidate_cycle" if repeated_physical_state else (
                "new_high" if higher else (
                    "revert" if candidate_rank < best_rank else "tie"))
            version = {
                "version": len(versions),
                "observation_id": _observation_id(observation),
                "score": candidate_score,
                "passed": candidate_passed,
                "quality": quality,
                "shot_quality": shot_quality,
                "physical_fingerprint": physical_fingerprint,
                "disposition": disposition,
                "candidate": copy.deepcopy(candidate),
                "operations": copy.deepcopy(records),
                "knowledge_context": str(knowledge_context or ""),
                "proposal": copy.deepcopy(proposal),
                "semantic_review": copy.deepcopy(dict(
                    report.get("vlm_review") or {})),
                "measurements": copy.deepcopy(dict(
                    report.get("measurements") or {})),
                "correction_candidates": correction_candidate_lifecycle(
                    correction_candidates,
                    remeasured_correction_candidates,
                    records,
                    shot_id=shot_id,
                ),
            }
            versions.append(version)
            evidence_error = _record_evidence(
                shot_id, observation, version)
            if evidence_error:
                current = copy.deepcopy(best_reference)
                if restore_best is not None and not higher:
                    try:
                        restore_best(current, shot_id)
                    except DetailLoopBlocked as exc:
                        blocked_code = exc.code
                        blocked_reason = str(exc)
                        break
                blocked_code = "evidence_record_failed"
                blocked_reason = evidence_error
                break
            if higher:
                best_reference = copy.deepcopy(candidate)
                best_version = len(versions) - 1
                best_score = candidate_score
                best_rank = candidate_rank
                current = candidate
                correction_candidates = remeasured_correction_candidates
                no_gain = 0
            else:
                no_gain += 1
                current = copy.deepcopy(best_reference)
                if restore_best is None:
                    blocked_code = "physical_restore_unavailable"
                    blocked_reason = (
                        "candidate did not exceed best and no physical "
                        "restore callback is configured")
                    break
                try:
                    restore_best(current, shot_id)
                except DetailLoopBlocked as exc:
                    blocked_code = exc.code
                    blocked_reason = str(exc)
                    break
            if physical_fingerprint:
                seen_physical_fingerprints.add(physical_fingerprint)
            if repeated_physical_state:
                blocked_code = "candidate_cycle_detected"
                blocked_reason = (
                    f"{shot_id} returned to an already observed physical "
                    f"state ({physical_fingerprint}); best restored")
                break
            if candidate_passed:
                shot_passed = True
                break
            if no_gain >= no_gain_limit:
                blocked_code = "no_improvement_limit"
                blocked_reason = (
                    f"{shot_id} made no new best in {no_gain} consecutive "
                    "attempts")
                break
        else:
            blocked_code = "max_revisions_reached"
            blocked_reason = (
                f"{shot_id} reached {max_revisions} revision attempts "
                "without passing")

        current = copy.deepcopy(best_reference)
        if shot_passed:
            shots[shot_id] = {
                "status": "passed",
                "versions": versions,
                "best_version": best_version,
                "adopted_version": best_version,
                "best_score": best_score,
                "blocked_code": "",
                "blocked_reason": "",
            }
            continue
        if not blocked_code:
            blocked_code = "max_revisions_reached"
            blocked_reason = (
                f"{shot_id} reached {max_revisions} revision attempts "
                "without passing")
        blocked_status = (
            blocked_code == "observation_evidence_incomplete"
            or blocked_code == "semantic_review_required"
            or blocked_code == "semantic_review_escalated"
            or blocked_code == "user_animation_conflict"
            or blocked_code == "physical_restore_unavailable"
            or blocked_code == "evidence_record_failed"
        )
        all_passed = False
        shots[shot_id] = {
            "status": "blocked" if blocked_status else "failed",
            "versions": versions,
            "best_version": best_version,
            "adopted_version": None,
            "best_score": best_score,
            "blocked_code": blocked_code,
            "failure_code": "" if blocked_status else blocked_code,
            "blocked_reason": blocked_reason,
        }

    sequence: Dict[str, Any] = {
        "status": "not_run",
        "verdict": "blocked",
        "shot_phase": {"all_passed": all_passed},
    }
    status = "blocked"
    if all_passed and sequence_review is not None:
        try:
            reviewed = copy.deepcopy(dict(sequence_review(current)))
        except Exception as exc:  # noqa: BLE001 - review failure is evidence
            reviewed = {
                "verdict": "blocked",
                "blocked_code": "sequence_review_failed",
                "blocked_reason": f"{type(exc).__name__}: {exc}",
            }
        sequence = {
            **reviewed,
            "shot_phase": {"all_passed": True},
        }
        status = (
            "approved"
            if str(reviewed.get("verdict") or "blocked") == "pass"
            else "blocked"
        )
    elif all_passed:
        sequence = {
            "status": "blocked",
            "verdict": "blocked",
            "blocked_code": "sequence_review_unavailable",
            "blocked_reason": (
                "all shots passed but no sequence review callback is "
                "configured"),
            "shot_phase": {"all_passed": True},
        }

    return {
        "schema_version": "detail-loop-result/v1",
        "status": status,
        "reference": current,
        "shots": shots,
        "sequence_review": sequence,
    }


def _quality_rank(
    shot_quality: Mapping[str, Any],
    *,
    passed: bool,
    score: float | None,
) -> tuple[int, float, int]:
    return (
        1 if passed else 0,
        float(score) if score is not None else float("-inf"),
        -int(shot_quality.get("hard_error_count") or 0),
    )


__all__ = ["DetailLoopBlocked", "run_detail_revision_loop"]
