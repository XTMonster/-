"""粗排修正循环驱动器（Ticket 05 纯层骨架，不 import bpy）。

``observe -> coarse gate -> fail(处方) -> 修改粗排参考 JSON -> rebuild ->
re-observe``，直到 gate 通过或显式超轮阻塞。bpy 的重建/渲染由调用方经
``rebuild`` 回调注入，循环本身纯层可测。
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Dict, List, Mapping

from block_director.contracts.audit import canonical_fingerprint
from block_director.contracts.coarse_reference import (
    coarse_reference_content_fingerprint,
)
from block_director.contracts.coarse_proposal import (
    CoarseProposalError,
    CoarseProposalRequest,
    validate_coarse_proposal,
)
from block_director.contracts.quality import blockout_quality_report
from block_director.contracts.observation import ObservationBundle
from block_director.contracts.world_state import world_state_fingerprint
from block_director.cinema.coarse_revision import (
    apply_coarse_prescriptions,
)
from block_director.cinema.pipeline_gates import coarse_gate

#: 粗排修正循环轮数上限（用户 2026-10-20 裁决：50 轮，主要质量）。
#: 这是"能收敛就收敛"的上限，不是鼓励跑满——高质量粗排靠剧本语义
#: 少数轮即通过；硬伤处方仍受 no-op/全部失败短路保护，不会空转 50 次。
DEFAULT_MAX_REVISIONS = 50
#: Consecutive schema/authority rejections that may be corrected against the
#: same rendered observation.  A rejected tool argument is Agent feedback, not
#: a new physical scene and therefore must not consume a revision or render.
DEFAULT_MAX_PROPOSAL_REJECTIONS = 2


def _observation_report(observation: Any) -> Dict[str, Any]:
    if isinstance(observation, ObservationBundle):
        return copy.deepcopy(dict(observation.report))
    if isinstance(observation, Mapping):
        report = observation.get("report")
        if observation.get("observation_id") and isinstance(report, Mapping):
            return copy.deepcopy(dict(report))
        return copy.deepcopy(dict(observation))
    raise TypeError("report_loader must return a report or ObservationBundle")


def _observation_complete(observation: Any) -> bool:
    if isinstance(observation, ObservationBundle):
        return observation.complete
    if isinstance(observation, Mapping) and observation.get("observation_id"):
        return observation.get("complete") is True
    #: Explicit legacy pure-test seam: a bare report has no frame pointers.
    return True


def _observation_id(observation: Any) -> str:
    if isinstance(observation, ObservationBundle):
        return observation.observation_id
    if isinstance(observation, Mapping):
        return str(observation.get("observation_id") or "")
    return ""


def _observation_manifest(observation: Any) -> Dict[str, Any]:
    if isinstance(observation, ObservationBundle):
        return copy.deepcopy(dict(observation.manifest))
    if isinstance(observation, Mapping):
        manifest = observation.get("manifest")
        if isinstance(manifest, Mapping):
            return copy.deepcopy(dict(manifest))
    return {}


def _observation_world_state(observation: Any) -> Dict[str, Any]:
    if isinstance(observation, ObservationBundle):
        return copy.deepcopy(dict(observation.world_state))
    if isinstance(observation, Mapping):
        world = observation.get("world_state")
        if isinstance(world, Mapping):
            return copy.deepcopy(dict(world))
    return {}


def _observation_frames(observation: Any) -> List[Dict[str, Any]]:
    if isinstance(observation, ObservationBundle):
        return [item.to_dict() for item in observation.frames]
    if isinstance(observation, Mapping):
        frames = observation.get("frames")
        if isinstance(frames, (list, tuple)):
            return [
                copy.deepcopy(dict(item))
                for item in frames
                if isinstance(item, Mapping)
            ]
    return []


def _observation_errors(observation: Any) -> List[str]:
    if isinstance(observation, ObservationBundle):
        return list(observation.verify_errors())
    if isinstance(observation, Mapping):
        return [str(item) for item in (observation.get("errors") or [])]
    return []


def _serializable_observation(observation: Any) -> Any:
    if isinstance(observation, ObservationBundle):
        return observation.to_dict()
    return copy.deepcopy(observation)


def _observation_candidate_record(observation: Any) -> Dict[str, Any]:
    """Bind one rebuilt candidate to its exact observation and physical world."""
    manifest = _observation_manifest(observation)
    world_state = _observation_world_state(observation)
    if isinstance(observation, ObservationBundle):
        reference_fingerprint = observation.reference_fingerprint
        manifest_fingerprint = observation.manifest_fingerprint
        report_fingerprint = observation.report_fingerprint
        world_fingerprint = observation.world_state_fingerprint
        bundle_fingerprint = observation.bundle_fingerprint
        evidence_dir = observation.evidence_dir
    else:
        source = observation if isinstance(observation, Mapping) else {}
        reference_fingerprint = str(
            source.get("reference_fingerprint") or
            coarse_reference_content_fingerprint(
                dict(source.get("reference") or {})))
        manifest_fingerprint = str(
            source.get("manifest_fingerprint") or "")
        report_fingerprint = str(
            source.get("report_fingerprint") or
            canonical_fingerprint(_observation_report(observation)))
        world_fingerprint = str(
            source.get("world_state_fingerprint") or
            (world_state_fingerprint(world_state) if world_state else ""))
        bundle_fingerprint = str(
            source.get("bundle_fingerprint") or "")
        evidence_dir = str(source.get("evidence_dir") or "")
    rebuild_summary = {
        "manifest_fingerprint": manifest_fingerprint,
        "world_state_fingerprint": world_fingerprint,
        "primitive_count": len(manifest.get("primitives") or []),
        "camera_count": len(manifest.get("cameras") or []),
        "shot_count": len(manifest.get("shot_table") or []),
        "evidence_complete": _observation_complete(observation),
        "evidence_dir": evidence_dir,
    }
    return {
        "observation_id": _observation_id(observation),
        "reference_fingerprint": reference_fingerprint,
        "manifest_fingerprint": manifest_fingerprint,
        "report_fingerprint": report_fingerprint,
        "world_state_fingerprint": world_fingerprint,
        "bundle_fingerprint": bundle_fingerprint,
        "report": _observation_report(observation),
        "rebuild_summary": rebuild_summary,
    }


def _observation_physical_fingerprint(observation: Any) -> str:
    """Stable identity of the physical scene that produced an observation."""
    if isinstance(observation, ObservationBundle):
        return str(observation.world_state_fingerprint or "")
    if isinstance(observation, Mapping):
        explicit = str(
            observation.get("world_state_fingerprint") or "")
        if explicit:
            return explicit
        world_state = _observation_world_state(observation)
        if world_state:
            return world_state_fingerprint(world_state)
        #: A bare blockout report's manifest fingerprint identifies the report
        #: contract, not the physical scene.  Legacy pure-report seams often use
        #: one stable placeholder for every attempt.  Treating that value as a
        #: world fingerprint fabricates a cycle after round one and prevents the
        #: real max-revision/no-gain paths.  Physical cycle detection therefore
        #: requires an ObservationBundle or an explicit world fingerprint.
        return ""
    return ""


def _proposal_history(rounds: List[Dict[str, Any]],
                      *, limit: int = 6) -> tuple[Dict[str, Any], ...]:
    """Compact, Agent-facing ledger of remeasured correction attempts.

    ``rounds`` is owned by the deterministic loop.  The Agent never receives
    arbitrary tool state or a self-reported score: each row is derived from the
    applied prescription records and the subsequent physical observation.
    """
    rows: List[Dict[str, Any]] = []
    for row in rounds[-max(1, int(limit)):]:
        proposal = row.get("proposal")
        if not isinstance(proposal, Mapping):
            proposal = {}
        proposed = {
            str(item.get("prescription_id") or ""): item
            for item in (proposal.get("prescriptions") or [])
            if isinstance(item, Mapping)
        }
        rejected = bool(row.get("proposal_rejected"))
        records = [
            item for item in (row.get("prescriptions") or [])
            if isinstance(item, Mapping)
        ]
        if rejected and not records:
            records = [
                item for item in (proposal.get("prescriptions") or [])
                if isinstance(item, Mapping)
            ]
        prescriptions: List[Dict[str, Any]] = []
        for record in records:
            if not isinstance(record, Mapping):
                continue
            prescription_id = str(
                record.get("prescription_id") or "")
            source = proposed.get(prescription_id) or {}
            prescriptions.append({
                "prescription_id": prescription_id,
                "shot_id": str(record.get("shot_id") or ""),
                "entity": str(
                    record.get("entity")
                    or source.get("entity")
                    or ""),
                "component": str(record.get("component") or ""),
                "target_value": copy.deepcopy(
                    source.get("target_value")),
                "applied": bool(record.get("applied")),
                "no_op": bool(record.get("no_op")),
                "rejected": bool(
                    record.get("rejected")
                    or (rejected and not record.get("applied"))),
                "reason": str(
                    record.get("reason")
                    or source.get("reason")
                    or ""),
                "after": copy.deepcopy(record.get("after")),
            })
        comparison = row.get("comparison")
        if not isinstance(comparison, Mapping):
            comparison = {}
        rows.append({
            "round_no": int(row.get("round_no") or 0),
            "disposition": str(
                comparison.get("disposition")
                or row.get("disposition")
                or ""),
            "candidate_score": comparison.get("candidate_score"),
            "best_score_before": comparison.get("best_score_before"),
            "best_score_after": comparison.get("best_score_after"),
            "candidate_fingerprint": str(
                row.get("candidate_fingerprint") or ""),
            "candidate_reference_repeated": bool(
                row.get("candidate_reference_repeated")),
            "cycle_detected": bool(row.get("cycle_detected")),
            "provider_kind": str(row.get("provider_kind") or ""),
            "reason": str(proposal.get("reason") or ""),
            "proposal_rejected": rejected,
            "rejection_reason": str(row.get("rejection_reason") or ""),
            "prescriptions": prescriptions,
        })
    return tuple(rows)


def run_coarse_revision_loop(
    *,
    reference: Mapping[str, Any],
    report_loader: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    rebuild: Callable[[Mapping[str, Any]], None],
    restore_best: Callable[[Mapping[str, Any]], None] | None = None,
    proposal_provider: Callable[..., Mapping[str, Any] | None] | None = None,
    knowledge_context: str = "",
    max_revisions: int = DEFAULT_MAX_REVISIONS,
    max_proposal_rejections: int = DEFAULT_MAX_PROPOSAL_REJECTIONS,
    no_gain_limit: int = 3,
    fps: int = 24,
) -> Dict[str, Any]:
    """跑粗排修正循环，返回 outcome。

    ``outcome`` 键：``status``（approved / blocked）、``reference``（当前参考
    JSON）、``report``（最新报告）、``rounds``（每轮
    ``{round_no, report, prescriptions}``）、``blocked_reason``（blocked 时）。

    循环契约：

    * 每轮先 ``report_loader(reference)`` 观察；
    * ``coarse_gate`` 通过 -> approved（不再重建）；
    * 不通过且未超轮 -> Agent ``proposal_provider`` 产出结构化提案 ->
      ``apply_coarse_prescriptions`` -> rebuild -> re-observe；
    * 无 proposal provider 或提案空/非法 -> blocked；不得隐式调用确定性
      处方器冒充 Agent；
    * 超轮仍未通过 -> blocked（不降级通过）。
    """
    if max_revisions < 1:
        raise ValueError(f"max_revisions must be >= 1: {max_revisions!r}")
    if max_proposal_rejections < 0:
        raise ValueError(
            "max_proposal_rejections must be >= 0: "
            f"{max_proposal_rejections!r}")
    if no_gain_limit < 1:
        raise ValueError(f"no_gain_limit must be >= 1: {no_gain_limit!r}")

    current = copy.deepcopy(reference)
    #: Search-space reference is deliberately separate from the physical best.
    #: A failed candidate is restored in Blender, but the next correction may
    #: need to continue from that explored candidate (for example repeated
    #: pull-back for an oversized subject).  Starting every attempt from best
    #: regenerates the same candidate and falsely looks like a cycle.
    search_reference = copy.deepcopy(reference)
    best_reference = copy.deepcopy(reference)
    best_report: Dict[str, Any] | None = None
    best_quality: Dict[str, Any] | None = None
    best_observation: Any | None = None
    best_manifest: Dict[str, Any] = {}
    best_world_state: Dict[str, Any] = {}
    best_rank = None
    latest_report: Dict[str, Any] | None = None
    latest_observation: Any | None = None
    latest_candidate_reference = copy.deepcopy(reference)
    latest_candidate_report: Dict[str, Any] | None = None
    latest_candidate_observation: Any | None = None
    no_gain = 0
    rollback_count = 0
    proposal_rejection_count = 0
    rounds: List[Dict[str, Any]] = []
    observations: List[Any] = []
    seen_candidate_fingerprints: set[str] = set()
    seen_physical_state_fingerprints: set[str] = set()
    awaiting_candidate_round_index: int | None = None

    def _rank(quality: Mapping[str, Any], *, evidence_complete: bool):
        minimum = quality.get("min_composition")
        if minimum is None:
            minimum = (float("-inf")
                       if int(quality.get("unresolved_count") or 0)
                       else float("inf"))
        return (
            1 if quality.get("gate_ready") and evidence_complete else 0,
            float(minimum),
            -int(quality.get("hard_error_count") or 0),
        )

    def _observe(ref: Mapping[str, Any]) -> Any:
        nonlocal latest_observation
        observation = report_loader(ref)
        observations.append(observation)
        latest_observation = observation
        return observation

    def _restore_and_observe() -> Any | None:
        """Restore the physical best, then acquire fresh evidence from it."""
        nonlocal current, best_observation, best_report
        nonlocal best_quality, best_rank
        nonlocal best_manifest, best_world_state, latest_observation
        current = copy.deepcopy(best_reference)
        if restore_best is not None:
            restore_best(current)
        if restore_best is None:
            return None
        restored = _observe(current)
        if _observation_complete(restored):
            restored_report = _observation_report(restored)
            restored_quality = blockout_quality_report(restored_report)
            best_observation = restored
            best_report = restored_report
            best_quality = restored_quality
            best_rank = _rank(restored_quality, evidence_complete=True)
            best_manifest = _observation_manifest(restored)
            best_world_state = _observation_world_state(restored)
            latest_observation = restored
        return restored

    def _finish_blocked(code: str, reason: str) -> Dict[str, Any]:
        #: The result always points at the retained best.  In a real Blender
        #: run the restored best must be observed again before it is reported.
        if (restore_best is not None
                and _observation_id(latest_observation)
                != _observation_id(best_observation)):
            _restore_and_observe()
        return {
            "status": "blocked",
            "reference": copy.deepcopy(best_reference),
            "report": copy.deepcopy(best_report or latest_report or {}),
            "latest_report": copy.deepcopy(latest_report or {}),
            "latest_candidate_report": copy.deepcopy(
                latest_candidate_report or {}),
            "latest_candidate": copy.deepcopy(latest_candidate_reference),
            "manifest": copy.deepcopy(best_manifest),
            "world_state": copy.deepcopy(best_world_state),
            "observations": [
                _serializable_observation(item) for item in observations],
            "best_observation": _serializable_observation(best_observation)
            if best_observation is not None else None,
            "rounds": rounds,
            "blocked_code": code,
            "blocked_reason": reason,
            "best_score": (best_quality or {}).get("min_composition"),
            "best_fingerprint": coarse_reference_content_fingerprint(
                best_reference),
            "best_observation_id": _observation_id(best_observation),
            "latest_observation_id": _observation_id(latest_observation),
            "latest_candidate_observation_id": _observation_id(
                latest_candidate_observation),
            "rollback_count": rollback_count,
            "proposal_rejection_count": proposal_rejection_count,
            "no_gain": no_gain,
        }

    measurement_no = 1
    while measurement_no <= max_revisions:
        observed_candidate_round: Dict[str, Any] | None = None
        observation = _observe(current)
        report = _observation_report(observation)
        if awaiting_candidate_round_index is not None:
            candidate_round = rounds[awaiting_candidate_round_index]
            candidate_record = _observation_candidate_record(observation)
            candidate_round["candidate_observation_id"] = _observation_id(
                observation)
            candidate_round["candidate_manifest_fingerprint"] = (
                candidate_record["manifest_fingerprint"])
            candidate_round["candidate_report_fingerprint"] = (
                candidate_record["report_fingerprint"])
            candidate_round["candidate_world_state_fingerprint"] = (
                candidate_record["world_state_fingerprint"])
            candidate_round["candidate"] = candidate_record
            observed_candidate_round = candidate_round
            awaiting_candidate_round_index = None
        latest_report = report
        latest_candidate_reference = copy.deepcopy(current)
        latest_candidate_report = copy.deepcopy(report)
        latest_candidate_observation = observation
        quality = blockout_quality_report(report)
        gate = coarse_gate(report)
        evidence_complete = _observation_complete(observation)
        if not evidence_complete:
            evidence_errors = _observation_errors(observation)
            gate = {
                "passed": False,
                "reasons": [
                    "观察证据不完整：" + "；".join(
                        evidence_errors or ["unknown incomplete observation"])
                ],
                "quality": quality,
            }
            rounds.append({
                "round_no": len(rounds) + 1,
                "report": report,
                "prescriptions": [],
                "applied_count": 0,
                "quality": quality,
                "observation_id": _observation_id(observation),
                "disposition": "blocked_incomplete_evidence",
                "rollback_applied": False,
                "best_score": (best_quality or {}).get("min_composition"),
                "no_gain": no_gain,
            })
            return _finish_blocked(
                "observation_evidence_incomplete",
                "粗排观察证据不完整：" + "；".join(
                    evidence_errors or ["unknown incomplete observation"]),
            )
        rank = _rank(quality, evidence_complete=evidence_complete)
        previous_best_rank = best_rank
        previous_best_quality = copy.deepcopy(best_quality)
        physical_fingerprint = _observation_physical_fingerprint(observation)
        is_new_best = best_rank is None or rank > best_rank
        repeated_physical_state = bool(
            physical_fingerprint
            and physical_fingerprint in seen_physical_state_fingerprints
            and not is_new_best
        )
        disposition = "observe"
        rollback_applied = False
        restore_unavailable = False
        restored_observation: Any | None = None
        if is_new_best:
            best_reference = copy.deepcopy(current)
            search_reference = copy.deepcopy(current)
            best_report = copy.deepcopy(report)
            best_quality = copy.deepcopy(quality)
            best_observation = observation
            best_manifest = _observation_manifest(observation)
            best_world_state = _observation_world_state(observation)
            best_rank = rank
            no_gain = 0
            disposition = "new_high"
        else:
            no_gain += 1
            if repeated_physical_state:
                disposition = "rollback_repeated_state"
                if restore_best is None:
                    restore_unavailable = True
                else:
                    rollback_applied = True
                    rollback_count += 1
                    restored_observation = _restore_and_observe()
            else:
                current_fingerprint = coarse_reference_content_fingerprint(
                    current)
                best_fingerprint = coarse_reference_content_fingerprint(
                    best_reference)
                if current_fingerprint != best_fingerprint:
                    disposition = "revert" if rank < best_rank else "tie"
                    if restore_best is None:
                        restore_unavailable = True
                    else:
                        rollback_applied = True
                        rollback_count += 1
                        restored_observation = _restore_and_observe()
                else:
                    disposition = "tie"
        if physical_fingerprint:
            seen_physical_state_fingerprints.add(physical_fingerprint)
        if observed_candidate_round is not None:
            observed_candidate_round["comparison"] = {
                "disposition": disposition,
                "candidate_score": quality.get("min_composition"),
                "best_score_before": (
                    previous_best_quality or {}).get("min_composition"),
                "best_score_after": (
                    best_quality or {}).get("min_composition"),
                "candidate_rank": list(rank),
                "best_rank_before": (
                    list(previous_best_rank)
                    if previous_best_rank is not None else None),
                "best_rank_after": list(best_rank),
                "evidence_complete": evidence_complete,
            }
            observed_candidate_round["rollback"] = {
                "applied": rollback_applied,
                "to_observation_id": (
                    _observation_id(best_observation)
                    if rollback_applied else ""),
                "to_reference_fingerprint": (
                    coarse_reference_content_fingerprint(best_reference)
                    if rollback_applied else ""),
                "reason": (
                    "candidate_did_not_exceed_best"
                    if rollback_applied else
                    "physical_restore_unavailable"
                    if restore_unavailable else ""),
            }
            observed_candidate_round["rollback_applied"] = rollback_applied
            observed_candidate_round["no_gain"] = no_gain
            observed_candidate_round["best_score"] = (
                best_quality or {}).get("min_composition")
        if restore_unavailable:
            if repeated_physical_state and observed_candidate_round is not None:
                observed_candidate_round["cycle_detected"] = True
            return _finish_blocked(
                "physical_restore_unavailable",
                "候选未超过 best，但未配置物理恢复回调；"
                "不得只替换 reference/JSON 冒充已恢复场景")
        if repeated_physical_state:
            if observed_candidate_round is not None:
                observed_candidate_round["cycle_detected"] = True
            return _finish_blocked(
                "candidate_cycle_detected",
                "粗排候选回到已观察过的物理状态，"
                f"检测到重复/短周期振荡（world={physical_fingerprint}）；"
                "已恢复最佳版本并停止修正循环")
        if rollback_applied:
            #: A rollback confirmation is auxiliary evidence, not a correction
            #: round.  The next Agent proposal must start from the physical
            #: best (freshly observed when possible), and must not consume one
            #: of max_revisions merely to re-read the restored state.
            active_observation = (
                restored_observation
                if restored_observation is not None
                else best_observation)
            if active_observation is not None:
                observation = active_observation
                report = _observation_report(observation)
                quality = blockout_quality_report(report)
                gate = coarse_gate(report)
                evidence_complete = _observation_complete(observation)
            search_reference = copy.deepcopy(best_reference)
            current = copy.deepcopy(best_reference)
            disposition = "proposal_from_restored_best"
            rollback_applied = False
        if gate["passed"]:
            current_id = _observation_id(observation)
            best_id = _observation_id(best_observation)
            if current_id and best_id and current_id != best_id:
                #: A passing candidate is the new best by rank.  This branch
                #: only guards stale bookkeeping, never lowers the pass gate.
                best_observation = observation
                best_report = copy.deepcopy(report)
                best_manifest = _observation_manifest(observation)
                best_world_state = _observation_world_state(observation)
            return {
                "status": "approved",
                "reference": copy.deepcopy(best_reference),
                "report": copy.deepcopy(best_report or report),
                "latest_report": copy.deepcopy(report),
                "latest_candidate_report": copy.deepcopy(
                    latest_candidate_report or report),
                "latest_candidate": copy.deepcopy(
                    latest_candidate_reference),
                "manifest": copy.deepcopy(best_manifest),
                "world_state": copy.deepcopy(best_world_state),
                "observations": [
                    _serializable_observation(item) for item in observations],
                "best_observation": _serializable_observation(
                    best_observation),
                "rounds": rounds,
                "blocked_code": "",
                "blocked_reason": "",
                "best_score": (best_quality or {}).get("min_composition"),
                "best_fingerprint": coarse_reference_content_fingerprint(
                    best_reference),
                "best_observation_id": _observation_id(best_observation),
                "latest_observation_id": _observation_id(latest_observation),
                "latest_candidate_observation_id": _observation_id(
                    latest_candidate_observation),
                "rollback_count": rollback_count,
                "proposal_rejection_count": proposal_rejection_count,
                "no_gain": 0,
            }
        if measurement_no >= max_revisions:
            #: T3：阻塞轮也要留痕（该轮 report + 空处方），使报告 rounds 数
            #: 与 blocked_reason 里“达到 N 轮上限”一致，不再出现
            #: “rounds 只有 2 条却提示 3 轮上限”的账实不符。
            rounds.append({
                "round_no": len(rounds) + 1,
                "report": report,
                "prescriptions": [],
                "applied_count": 0,
                "quality": quality,
                "observation_id": _observation_id(observation),
                "disposition": disposition,
                "rollback_applied": rollback_applied,
                "best_score": (best_quality or {}).get("min_composition"),
                "no_gain": no_gain,
            })
            return _finish_blocked(
                    "max_revisions_reached",
                    f"达到修正轮数上限（{max_revisions} 轮）仍未通过粗排 gate："
                    + "；".join(gate["reasons"] or ["存在 error finding"]))
        if no_gain >= no_gain_limit:
            rounds.append({
                "round_no": len(rounds) + 1,
                "report": report,
                "prescriptions": [],
                "applied_count": 0,
                "quality": quality,
                "observation_id": _observation_id(observation),
                "disposition": disposition,
                "rollback_applied": rollback_applied,
                "best_score": (best_quality or {}).get("min_composition"),
                "no_gain": no_gain,
            })
            return _finish_blocked(
                "no_improvement_limit",
                f"连续 {no_gain} 轮无新高，粗排循环停止并恢复最佳版本")
        if proposal_provider is None:
            rounds.append({
                "round_no": len(rounds) + 1,
                "report": report,
                "prescriptions": [],
                "applied_count": 0,
                "quality": quality,
                "observation_id": _observation_id(observation),
                "disposition": disposition,
                "rollback_applied": rollback_applied,
                "best_score": (best_quality or {}).get("min_composition"),
                "no_gain": no_gain,
                "provider_kind": "",
                "proposal": None,
            })
            return _finish_blocked(
                "agent_proposal_unavailable",
                "粗排未通过但未配置 Agent proposal provider；"
                "程序不得以确定性处方器冒充导演大脑")
        rejected_on_observation = 0
        while True:
            request = CoarseProposalRequest(
                round_no=len(rounds) + 1,
                observation_id=_observation_id(observation),
                reference=search_reference,
                report=report,
                manifest=_observation_manifest(observation),
                world_state=_observation_world_state(observation),
                frames=tuple(_observation_frames(observation)),
                history=_proposal_history(rounds),
                knowledge_context=str(knowledge_context or ""),
            )
            try:
                raw_proposal = proposal_provider(request=request)
            except CoarseProposalError as exc:
                rejection_reason = str(exc) or type(exc).__name__
                rounds.append({
                    "round_no": len(rounds) + 1,
                    "report": report,
                    "prescriptions": [],
                    "applied_count": 0,
                    "quality": quality,
                    "observation_id": _observation_id(observation),
                    "disposition": disposition,
                    "rollback_applied": rollback_applied,
                    "best_score": (
                        best_quality or {}).get("min_composition"),
                    "no_gain": no_gain,
                    "provider_kind": str(
                        getattr(proposal_provider, "provider_kind", "")
                        or ""),
                    "proposal": None,
                    "disposition": (
                        "proposal_rejected"
                        if exc.recoverable else disposition),
                    "proposal_rejected": bool(exc.recoverable),
                    "rejection_reason": (
                        rejection_reason if exc.recoverable else ""),
                    "rejected_code": exc.code,
                    "provider_error": {
                        "type": type(exc).__name__,
                        "code": exc.code,
                        "message": rejection_reason,
                        "details": copy.deepcopy(exc.details),
                    },
                })
                if exc.recoverable:
                    rejected_on_observation += 1
                    proposal_rejection_count += 1
                    if rejected_on_observation >= max_proposal_rejections:
                        return _finish_blocked(
                            exc.code,
                            "Agent 粗排提案协议错误："
                            f"{rejection_reason}（同一观察连续拒绝 "
                            f"{rejected_on_observation} 次）")
                    continue
                return _finish_blocked(
                    exc.code,
                    f"Agent 粗排提案阻断：{exc}",
                )
            except Exception as exc:  # noqa: BLE001 - provider failure is evidence
                rounds.append({
                    "round_no": len(rounds) + 1,
                    "report": report,
                    "prescriptions": [],
                    "applied_count": 0,
                    "quality": quality,
                    "observation_id": _observation_id(observation),
                    "disposition": disposition,
                    "rollback_applied": rollback_applied,
                    "best_score": (
                        best_quality or {}).get("min_composition"),
                    "no_gain": no_gain,
                    "provider_kind": str(
                        getattr(proposal_provider, "provider_kind", "")
                        or ""),
                    "proposal": None,
                    "provider_error": {
                        "type": type(exc).__name__, "message": str(exc)},
                })
                return _finish_blocked(
                    "agent_proposal_failed",
                    f"Agent 粗排提案失败：{type(exc).__name__}: {exc}")
            raw_source = (
                str(raw_proposal.get("source") or "")
                if isinstance(raw_proposal, Mapping) else "")
            configured_kind = str(
                getattr(proposal_provider, "provider_kind", "") or "")
            declared_kind = (
                str(raw_proposal.get("provider_kind") or "")
                if isinstance(raw_proposal, Mapping) else "")
            if raw_source == "offline_fixture" \
                    and configured_kind != "offline_fixture":
                rounds.append({
                    "round_no": len(rounds) + 1,
                    "report": report,
                    "prescriptions": [],
                    "applied_count": 0,
                    "quality": quality,
                    "observation_id": _observation_id(observation),
                    "disposition": disposition,
                    "rollback_applied": rollback_applied,
                    "best_score": (
                        best_quality or {}).get("min_composition"),
                    "no_gain": no_gain,
                    "provider_kind": configured_kind,
                    "proposal_source": raw_source,
                    "proposal": copy.deepcopy(raw_proposal),
                    "proposal_rejected": True,
                })
                return _finish_blocked(
                    "agent_proposal_source_spoofed",
                    "offline_fixture 提案必须通过显式 "
                    "OfflineFixtureCoarseProposalProvider 选择，"
                    "不得冒充 Agent 运行")
            try:
                proposal = validate_coarse_proposal(
                    raw_proposal, reference=search_reference)
            except (CoarseProposalError, TypeError, ValueError) as exc:
                rejection_reason = str(exc) or type(exc).__name__
                rounds.append({
                    "round_no": len(rounds) + 1,
                    "report": report,
                    "prescriptions": [],
                    "applied_count": 0,
                    "quality": quality,
                    "observation_id": _observation_id(observation),
                    "disposition": "proposal_rejected",
                    "rollback_applied": False,
                    "best_score": (
                        best_quality or {}).get("min_composition"),
                    "no_gain": no_gain,
                    "provider_kind": configured_kind or declared_kind,
                    "proposal_source": raw_source,
                    "proposal": copy.deepcopy(raw_proposal)
                    if isinstance(raw_proposal, Mapping)
                    else raw_proposal,
                    "proposal_rejected": True,
                    "rejection_reason": rejection_reason,
                    "rejected_code": (
                        exc.code if isinstance(exc, CoarseProposalError)
                        else "schema_or_authority_invalid"),
                })
                rejected_on_observation += 1
                proposal_rejection_count += 1
                if rejected_on_observation >= max_proposal_rejections:
                    return _finish_blocked(
                        "agent_proposal_rejected",
                        "Agent 粗排提案被拒绝："
                        f"{rejection_reason}（同一观察连续拒绝 "
                        f"{rejected_on_observation} 次）")
                continue
            rejected_on_observation = 0
            break
        prescriptions = list(proposal["prescriptions"])
        provider_kind = str(
            getattr(proposal_provider, "provider_kind", "")
            or declared_kind
            or proposal.get("provider_kind") or "")
        proposal_source = str(
            proposal.get("source") or raw_source or provider_kind)
        if not provider_kind:
            rounds.append({
                "round_no": len(rounds) + 1,
                "report": report,
                "prescriptions": [],
                "applied_count": 0,
                "quality": quality,
                "observation_id": _observation_id(observation),
                "disposition": disposition,
                "rollback_applied": rollback_applied,
                "best_score": (best_quality or {}).get("min_composition"),
                "no_gain": no_gain,
                "provider_kind": "",
                "proposal_source": proposal_source,
                "proposal": proposal,
            })
            return _finish_blocked(
                "agent_proposal_provenance_missing",
                "Agent 粗排提案缺少 provider_kind，无法证明提案来源")
        proposal_round = len(rounds) + 1
        candidate, records = apply_coarse_prescriptions(
            search_reference, prescriptions,
            revision_id=f"coarse-round-{proposal_round}",
            round_no=proposal_round)
        candidate_fingerprint = coarse_reference_content_fingerprint(candidate)
        rounds.append({
            "round_no": len(rounds) + 1,
            "report": report,
            "prescriptions": records,
            "applied_count": sum(1 for r in records if r["applied"]),
            "quality": quality,
            "observation_id": _observation_id(observation),
            "disposition": disposition,
            "rollback_applied": rollback_applied,
            "best_score": (best_quality or {}).get("min_composition"),
            "no_gain": no_gain,
            "candidate_fingerprint": candidate_fingerprint,
            "best_fingerprint": coarse_reference_content_fingerprint(
                best_reference),
            "provider_kind": provider_kind,
            "proposal_source": proposal_source,
            "proposal": proposal,
            "knowledge_context": str(knowledge_context or ""),
        })
        #: 硬错误的零变化优先级高于软构图处方。不能因为同一镜还能生成
        #: ``push_in``/``pull_back`` 这类软处方，就把已经无法修复的空墙、
        #: 未解析主体伪装成"有进展"继续重建；否则会绕过 R2-F6 的不可收敛
        #: 保护。软处方仍会在没有硬错误零变化时正常应用。
        hard_noop = [
            r for r in records
            if (not r.get("applied") and r.get("no_op")
                and (str((r.get("derived_from") or {}).get("check_id") or "")
                     in {"E_BLOCKOUT_EMPTY_WALL",
                        "E_BLOCKOUT_FRAMING_TARGET_UNRESOLVED"}
                     or any(tag in str(r.get("prescription_id") or "")
                            for tag in ("empty_wall", "framing_target_unresolved"))))
        ]
        hard_findings = [
            f for f in (report.get("findings") or [])
            if str(f.get("check_id") or "")
            in {"E_BLOCKOUT_EMPTY_WALL",
               "E_BLOCKOUT_FRAMING_TARGET_UNRESOLVED"}
        ]
        if hard_findings and hard_noop and not any(
                r.get("applied") and str(
                    (r.get("derived_from") or {}).get("check_id") or "")
                in {"E_BLOCKOUT_EMPTY_WALL",
                   "E_BLOCKOUT_FRAMING_TARGET_UNRESOLVED"}
                or r.get("applied") and any(
                    tag in str(r.get("prescription_id") or "")
                    for tag in ("empty_wall", "framing_target_unresolved"))
                for r in records):
            return _finish_blocked(
                    "irrecoverable_hard_error",
                    "粗排硬错误处方全部零变化（应用后世界坐标一致），"
                    "软构图处方不得掩盖不可收敛根因；"
                    "需补缺主体或回写实测世界坐标后重试")
        #: R2-F6：处方存在但全部零变化（应用后世界坐标一致）-> 不可收敛。
        #: 继续重建只是把修正预算耗在没有效果的空转上，必须如实 blocked。
        if prescriptions and records and all(
                not r.get("applied") and r.get("no_op")
                for r in records):
            return _finish_blocked(
                    "prescriptions_all_noop",
                    "粗排处方全部零变化（应用后世界坐标一致），"
                    "修正循环不可收敛；阻塞根因在计划/场景脱节，"
                    "需补缺主体或回写实测世界坐标后重试")
        if prescriptions and records and all(
                not r.get("applied") for r in records):
            return _finish_blocked(
                    "prescriptions_all_rejected",
                    "粗排处方全部应用失败（未知实体/零变化），"
                    "修正循环不可收敛，未降级通过")
        #: A repeated target reference is not yet a repeated physical state.
        #: The rebuild may be refused, clamped, or otherwise produce different
        #: geometry.  Record the repeat and let the next observation decide;
        #: claiming a cycle before the world is remeasured would be fabricated
        #: evidence and would also prevent the honest no-gain/max-revision path.
        rounds[-1]["candidate_reference_repeated"] = bool(
            candidate_fingerprint in seen_candidate_fingerprints)
        seen_candidate_fingerprints.add(candidate_fingerprint)
        search_reference = copy.deepcopy(candidate)
        current = candidate
        awaiting_candidate_round_index = len(rounds) - 1
        rebuild(current)
        measurement_no += 1
    return _finish_blocked(
        "coarse_loop_exited", "粗排修正循环异常退出（不应到达）")


__all__ = [
    "run_coarse_revision_loop",
    "DEFAULT_MAX_REVISIONS",
    "DEFAULT_MAX_PROPOSAL_REJECTIONS",
]
