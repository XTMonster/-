"""Build immutable per-shot evidence from retained coarse observations."""

from __future__ import annotations

import copy
from typing import Any, Iterable, Mapping, Sequence

from block_director.contracts.audit import canonical_fingerprint
from block_director.contracts.evidence import EvidenceStore, ShotEvidence
from block_director.contracts.observation import ObservationBundle
from block_director.contracts.quality import blockout_quality_report
from block_director.contracts.world_state import normalize_world_state
from block_director.cinema.shot_staging import effective_reference_for_shot


def _bundle(value: ObservationBundle | Mapping[str, Any]) -> ObservationBundle:
    if isinstance(value, ObservationBundle):
        return value
    if isinstance(value, Mapping):
        return ObservationBundle.from_dict(value)
    raise TypeError("observations must contain ObservationBundle or mappings")


def _plan_payload(plan: Any) -> dict[str, Any]:
    if isinstance(plan, Mapping):
        return copy.deepcopy(dict(plan))
    to_dict = getattr(plan, "to_dict", None)
    if callable(to_dict):
        return copy.deepcopy(dict(to_dict()))
    raise TypeError("plan must be a mapping or expose to_dict()")


def _shot_ids(
    plan: Mapping[str, Any],
    observations: Sequence[ObservationBundle],
) -> list[str]:
    ordered: list[str] = []
    for source in (
        plan.get("shots") or [],
        observations[-1].reference.get("shots") if observations else [],
    ):
        for row in source or []:
            if not isinstance(row, Mapping):
                continue
            shot_id = str(row.get("shot_id") or "")
            if shot_id and shot_id not in ordered:
                ordered.append(shot_id)
    return ordered


def _shot_plan(plan: Mapping[str, Any], shot_id: str) -> dict[str, Any]:
    for row in plan.get("shots") or []:
        if isinstance(row, Mapping) and str(row.get("shot_id") or "") == shot_id:
            return copy.deepcopy(dict(row))
    return {}


def _filter_report_rows(
    report: Mapping[str, Any],
    shot_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    checks = [
        copy.deepcopy(dict(row))
        for row in (report.get("checks") or [])
        if isinstance(row, Mapping)
        and str(row.get("shot_id") or "") == shot_id
    ]
    findings = [
        copy.deepcopy(dict(row))
        for row in (report.get("findings") or [])
        if isinstance(row, Mapping)
        and str(row.get("shot_id") or "") == shot_id
    ]
    return checks, findings


def _authoritative_visual_states(
    bundle: ObservationBundle,
    shot_id: str,
) -> list[dict[str, Any]]:
    """Bind report review metadata to the published frame evidence.

    Reports are produced while preview frames still live in a staging
    directory. Observations then publish those frames into immutable evidence
    storage. Report paths must not remain authoritative after that move, while
    the report itself stays unchanged and bound to its fingerprint.
    """
    report_rows = {
        (
            str(row.get("shot_id") or ""),
            int(row.get("frame") or 0),
            str(row.get("phase") or ""),
        ): copy.deepcopy(dict(row))
        for row in (bundle.report.get("visual_states") or [])
        if isinstance(row, Mapping)
        and str(row.get("shot_id") or "") == str(shot_id)
    }
    result: list[dict[str, Any]] = []
    for frame in bundle.frames:
        if frame.shot_id != str(shot_id):
            continue
        row = report_rows.get((frame.shot_id, frame.frame, frame.phase))
        if row is None:
            continue
        row.update({
            "shot_id": frame.shot_id,
            "frame": frame.frame,
            "phase": frame.phase,
            "png": frame.path,
        })
        result.append(row)
    return result


def _semantic_review_from_observation(
    bundle: ObservationBundle,
    shot_id: str,
) -> dict[str, Any]:
    """Bind the judge's exact frame order to published observation frames."""
    review = bundle.report.get("vlm_review")
    if not isinstance(review, Mapping):
        visual_states = _authoritative_visual_states(bundle, shot_id)
        if not visual_states:
            return {}
        reviewed = all(row.get("reviewed") is True for row in visual_states)
        return {
            "status": "reviewed" if reviewed else "not_reviewed",
            "visual_states": visual_states,
            "reviewed": reviewed,
        }

    semantic = copy.deepcopy(dict(review))
    semantic["vlm_status"] = str(semantic.get("status") or "")
    published = {
        (frame.shot_id, frame.frame, frame.phase): frame.to_dict()
        for frame in bundle.frames
        if frame.shot_id == str(shot_id)
    }
    visual_states: list[dict[str, Any]] = []
    for raw in semantic.get("frame_order") or []:
        if not isinstance(raw, Mapping):
            continue
        phase = str(raw.get("phase") or raw.get("label") or "")
        frame_no = int(raw.get("frame") or 0)
        frame = published.get((str(shot_id), frame_no, phase))
        if frame is None:
            continue
        row = copy.deepcopy(dict(raw))
        row.update(frame)
        row.update({
            "shot_id": str(shot_id),
            "label": phase,
            "phase": phase,
            "reviewed": semantic.get("status") == "ok",
        })
        visual_states.append(row)
    semantic["visual_states"] = visual_states
    semantic["reviewed"] = bool(
        semantic.get("vlm_status") == "ok"
        and len(visual_states) == 3
        and all(row.get("reviewed") is True for row in visual_states)
    )
    semantic["status"] = (
        "reviewed" if semantic["reviewed"] else semantic["vlm_status"])
    return semantic


def _rag_for_shot(
    round_row: Mapping[str, Any],
    shot_id: str,
) -> dict[str, Any]:
    """Return only the RAG record that produced this shot candidate."""
    proposal = round_row.get("proposal")
    if not isinstance(proposal, Mapping):
        return {}
    source = proposal.get("knowledge_provenance")
    if not isinstance(source, Mapping):
        source = proposal.get("rag_provenance")
    if not isinstance(source, Mapping):
        return {}
    scoped_shot = str(source.get("shot_id") or "")
    if scoped_shot and scoped_shot != shot_id:
        return {}
    provider_kind = str(
        proposal.get("provider_kind")
        or round_row.get("provider_kind")
        or ""
    )
    proposal_reason = str(proposal.get("reason") or "")
    selected: dict[str, Any] = {}
    for key in ("shots", "per_shot"):
        rows = source.get(key)
        if isinstance(rows, Mapping) and isinstance(rows.get(shot_id), Mapping):
            selected = copy.deepcopy(dict(rows[shot_id]))
            break
    blocks = source.get("injected_blocks")
    if isinstance(blocks, Mapping) and blocks.get(shot_id):
        selected["block"] = str(blocks.get(shot_id) or "")
    trace = source.get("per_shot_trace")
    if isinstance(trace, Mapping) and isinstance(trace.get(shot_id), Mapping):
        selected.update(copy.deepcopy(dict(trace[shot_id])))
    events = source.get("events")
    selected_events: list[dict[str, Any]] = []
    if isinstance(events, list):
        selected_events = [
            copy.deepcopy(dict(event))
            for event in events
            if isinstance(event, Mapping)
            and (
                not event.get("shot_id")
                or str(event.get("shot_id") or "") == shot_id
            )
        ]
        if selected_events:
            selected["events"] = selected_events
    if selected_events:
        def unique_event_ids(
            aggregate_key: str,
            category_keys: Sequence[str],
        ) -> list[str]:
            result: list[str] = []
            for event in selected_events:
                values = event.get(aggregate_key)
                if not isinstance(values, (list, tuple)):
                    values = [
                        value
                        for key in category_keys
                        for value in (event.get(key) or ())
                    ]
                for value in values:
                    item = str(value or "")
                    if item and item not in result:
                        result.append(item)
            return result

        hit_ids = unique_event_ids(
            "hit_ids",
            ("hit_card_ids", "hit_edge_ids", "hit_case_ids"),
        )
        injected_ids = unique_event_ids(
            "injected_ids",
            ("injected_card_ids", "injected_edge_ids", "injected_case_ids"),
        )
        actual_tokens = sum(
            int(event.get("actual_injected_tokens") or 0)
            for event in selected_events
        )
        injected = any(
            event.get("injected") is True
            or any(event.get(key) for key in (
                "injected_card_ids",
                "injected_edge_ids",
                "injected_case_ids",
            ))
            or (
                int(event.get("actual_injected_tokens") or 0) > 0
                and bool(event.get("injected_sha256"))
            )
            for event in selected_events
        )
        selected.update({
            "hit_ids": hit_ids,
            "injected_ids": injected_ids,
            "actual_injected_tokens": actual_tokens,
            "event_count": len(selected_events),
        })
        status = "retrieved" if injected else "no_hits"
    else:
        injected = bool(
            selected.get("injected") is True
            or selected.get("block")
            or float(selected.get("actual_injected_tokens") or 0.0) > 0.0
        )
        status = str(
            selected.get("status")
            or source.get("status")
            or ("retrieved" if injected else "no_hits")
        )
    if status in {"retrieved", "has_hits"} and not selected:
        status = "no_hits"
    result = {
        "shot_id": shot_id,
        "status": status,
        "provider_kind": provider_kind,
        "proposal_reason": proposal_reason,
        "injected": injected,
    }
    result.update(selected)
    result["shot_id"] = shot_id
    result["status"] = status
    result["injected"] = injected
    scope = str(selected.get("scope") or source.get("scope") or "")
    if scope:
        result["scope"] = scope
    else:
        result.pop("scope", None)
    return result


def _with_operation_dispositions(
    candidates: Sequence[Mapping[str, Any]],
    operations: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Bind correction candidates to their measured execution outcome."""
    operation_by_id = {
        str(operation.get("prescription_id") or ""): operation
        for operation in operations
        if operation.get("prescription_id")
    }
    enriched: list[dict[str, Any]] = []
    for source in candidates:
        row = copy.deepcopy(dict(source))
        operation = operation_by_id.get(
            str(row.get("prescription_id") or ""))
        if operation is None:
            disposition = "deferred"
        elif operation.get("applied") is True:
            disposition = "applied"
        else:
            disposition = "rejected"
        row["disposition"] = disposition
        enriched.append(row)
    return enriched


def _shot_slice(
    *,
    shot_plan: Mapping[str, Any],
    reference: Mapping[str, Any],
    manifest: Mapping[str, Any],
    world_state: Mapping[str, Any],
) -> dict[str, Any]:
    """Keep the evidence needed to inspect or restore one shot locally."""
    shot_id = str(shot_plan.get("shot_id") or "")
    effective_reference = effective_reference_for_shot(reference, shot_id)
    names = {
        str(name) for name in (shot_plan.get("characters") or []) if str(name)
    }
    framing = shot_plan.get("framing_target")
    if isinstance(framing, Mapping) and framing.get("ref"):
        names.add(str(framing.get("ref")))

    def rows_by_shot(value: Any, key: str = "shot_id") -> list[dict[str, Any]]:
        if isinstance(value, list):
            return [
                copy.deepcopy(dict(item))
                for item in value
                if isinstance(item, Mapping)
                and str(item.get(key) or item.get("camera_id") or "") == shot_id
            ]
        if isinstance(value, Mapping):
            selected = value.get(shot_id)
            if isinstance(selected, Mapping):
                return [copy.deepcopy(dict(selected))]
        return []

    characters = [
        copy.deepcopy(dict(item))
        for item in (effective_reference.get("characters") or [])
        if isinstance(item, Mapping) and str(item.get("name") or "") in names
    ]
    camera_intents = rows_by_shot(reference.get("camera_intents"))
    manifest_cameras = rows_by_shot(manifest.get("cameras"))
    shot_table = rows_by_shot(manifest.get("shot_table"))
    staging_by_shot = reference.get("shot_staging")
    staging_overlay = (
        copy.deepcopy(dict(staging_by_shot.get(shot_id) or {}))
        if isinstance(staging_by_shot, Mapping)
        and isinstance(staging_by_shot.get(shot_id), Mapping)
        else {}
    )
    render_staging = world_state.get("render_staging")
    render_audit = (
        copy.deepcopy(dict(render_staging.get(shot_id) or {}))
        if isinstance(render_staging, Mapping)
        and isinstance(render_staging.get(shot_id), Mapping)
        else {}
    )
    shot_states = world_state.get("shot_states")
    physical_state = (
        shot_states.get(shot_id)
        if isinstance(shot_states, Mapping)
        and isinstance(shot_states.get(shot_id), Mapping)
        else world_state
    )
    live_characters = physical_state.get("characters")
    selected_live_characters = (
        {
            name: copy.deepcopy(value)
            for name, value in live_characters.items()
            if str(name) in names
        }
        if isinstance(live_characters, Mapping) else {}
    )
    live_cameras = physical_state.get("cameras")
    selected_live_cameras = (
        {shot_id: copy.deepcopy(live_cameras[shot_id])}
        if isinstance(live_cameras, Mapping) and shot_id in live_cameras
        else {}
    )
    prop_ids = {
        str(prop_id)
        for row in shot_table
        for prop_id in (row.get("prop_ids") or [])
        if str(prop_id)
    }
    live_props = physical_state.get("props")
    selected_live_props = (
        {
            name: copy.deepcopy(value)
            for name, value in live_props.items()
            if str(name) in prop_ids
        }
        if isinstance(live_props, Mapping) else {}
    )
    live_anchors = physical_state.get("anchors")
    selected_live_anchors = (
        copy.deepcopy(dict(live_anchors))
        if isinstance(live_anchors, Mapping) else {}
    )
    return {
        "shot_id": shot_id,
        "reference": {
            "scene_id": reference.get("scene_id"),
            "shot": copy.deepcopy(dict(shot_plan)),
            "characters": characters,
            "camera_intents": camera_intents,
            "staging": {
                "overlay": staging_overlay,
                "render_audit": render_audit,
            },
        },
        "manifest": {
            "scene_id": manifest.get("scene_id"),
            "cameras": manifest_cameras,
            "shot_table": shot_table,
        },
        "world_state": {
            "frame": physical_state.get("frame"),
            "characters": selected_live_characters,
            "cameras": selected_live_cameras,
            "props": selected_live_props,
            "anchors": selected_live_anchors,
        },
    }


def build_detail_shot_evidence(
    *,
    run_id: str,
    scene_id: str,
    plan: Any,
    shot_id: str,
    observation: ObservationBundle | Mapping[str, Any],
    version: Mapping[str, Any],
    detail_reason: str,
) -> ShotEvidence:
    """Project one detail-loop observation into immutable shot evidence."""
    plan_payload = _plan_payload(plan)
    bundle = _bundle(observation)
    shot_plan = _shot_plan(plan_payload, str(shot_id))
    quality = blockout_quality_report(bundle.report)
    shot_quality = dict(
        (quality.get("shots") or {}).get(str(shot_id)) or {})
    composition = dict(shot_quality.get("composition") or {})
    version_score = version.get("score")
    if isinstance(version_score, (int, float)) \
            and not isinstance(version_score, bool):
        measured_score = composition.get("score")
        composition["score"] = float(version_score)
        if measured_score != version_score:
            composition["live_measured_score"] = measured_score
    checks, findings = _filter_report_rows(bundle.report, str(shot_id))
    hard_errors = int(shot_quality.get("hard_error_count") or 0)
    shot_passed = (
        composition.get("status") in {"pass", "exempt"}
        and hard_errors == 0
    )
    frames = [
        item.to_dict() for item in bundle.frames
        if item.shot_id == str(shot_id)
    ]
    semantic_review = _semantic_review_from_observation(
        bundle, str(shot_id))
    proposal = (
        copy.deepcopy(dict(version.get("proposal") or {}))
        if isinstance(version.get("proposal"), Mapping) else {}
    )
    proposed_corrections = [
        copy.deepcopy(dict(row))
        for row in (proposal.get("prescriptions") or [])
        if isinstance(row, Mapping)
        and str(row.get("shot_id") or str(shot_id)) == str(shot_id)
    ]
    raw_operations = [
        copy.deepcopy(dict(row))
        for row in (version.get("operations") or [])
        if isinstance(row, Mapping)
    ]
    unified_candidates = version.get("correction_candidates")
    if isinstance(unified_candidates, (list, tuple)):
        correction_candidates = [
            copy.deepcopy(dict(row))
            for row in unified_candidates
            if isinstance(row, Mapping)
        ]
    else:
        correction_candidates = _with_operation_dispositions(
            proposed_corrections, raw_operations)
    applied_operations = _with_operation_dispositions(
        raw_operations, raw_operations)
    rag = _rag_for_shot({
        "proposal": proposal,
        "provider_kind": proposal.get("provider_kind") or "agent",
    }, str(shot_id))
    absence_reasons: dict[str, str] = {}
    if not semantic_review:
        absence_reasons["semantic_review"] = (
            "this detail observation did not include a VLM review")
    if not rag:
        absence_reasons["rag"] = (
            "this detail proposal did not record RAG provenance")
    if not correction_candidates:
        absence_reasons["correction_candidates"] = (
            "this detail observation had no correction candidates")
    if not applied_operations:
        absence_reasons["applied_operations"] = (
            "this detail observation had no applied operations")

    version_no = int(version.get("version") or 0)
    remeasurement = (
        {}
        if version_no == 0
        else {
            "status": "measured",
            "report_fingerprint": bundle.report_fingerprint,
            "shot_quality": copy.deepcopy(shot_quality),
            "world_state_fingerprint": bundle.world_state_fingerprint,
        }
    )
    if not remeasurement:
        absence_reasons["remeasurement"] = (
            "the initial detail observation has no prior correction "
            "to remeasure")
    disposition = {
        "status": str(version.get("disposition") or "observed"),
        "reason": str(detail_reason or "detail revision observation"),
    }
    sequence_gate = {
        "status": "not_evaluated",
        "reason": "sequence review runs after every non-empty shot passes",
    }
    scene_content = canonical_fingerprint({
        "reference": bundle.reference,
        "manifest": bundle.manifest,
        "world_state": normalize_world_state(bundle.world_state),
    })
    return ShotEvidence.create(
        run_id=run_id,
        scene_id=scene_id,
        shot_id=str(shot_id),
        version=version_no,
        parent_version=None if version_no == 0 else version_no - 1,
        reason=str(detail_reason or (
            "detail_initial_observation"
            if version_no == 0
            else f"detail_correction_round_{version_no:03d}"
        )),
        created_at="deterministic-replay",
        plan={
            "scene": plan_payload,
            "shot": shot_plan,
        },
        shot_contract=shot_plan,
        reference=bundle.reference,
        manifest=bundle.manifest,
        world_state=bundle.world_state,
        shot_slice=_shot_slice(
            shot_plan=shot_plan,
            reference=bundle.reference,
            manifest=bundle.manifest,
            world_state=bundle.world_state,
        ),
        build={
            "status": "detail_observed",
            "scene_id": bundle.manifest.get("scene_id"),
            "manifest_fingerprint": bundle.manifest_fingerprint,
            "primitive_count": len(bundle.manifest.get("primitives") or []),
            "camera_count": len(bundle.manifest.get("cameras") or []),
        },
        audit={
            "schema_version": bundle.report.get("schema_version"),
            "verdict": bundle.report.get("verdict"),
            "report_fingerprint": bundle.report_fingerprint,
            "checks": checks,
            "findings": findings,
        },
        measurements={
            "component": "detail_blockout",
            "shot_quality": shot_quality,
            "composition": composition,
            "checks": checks,
            "findings": findings,
            "report_fingerprint": bundle.report_fingerprint,
        },
        score_breakdown={
            "quality_contract": "quality-contract/v1",
            "shot_quality": shot_quality,
            "composition": copy.deepcopy(composition),
            "hard_error_count": hard_errors,
            "sequence": None,
        },
        gates={
            "observation_complete": bundle.complete,
            "shot_passed": shot_passed,
            "quality_contract": "quality-contract/v1",
        },
        hard_gates={
            "status": "pass" if hard_errors == 0 else "fail",
            "passed": hard_errors == 0,
            "failed": [
                finding for finding in findings
                if str(finding.get("severity") or "") == "error"
            ],
            "evaluated": ["shot_findings"],
        },
        sequence_gate=sequence_gate,
        frames=frames,
        semantic_review=semantic_review,
        rag=rag,
        correction={
            "round": version_no,
            "disposition": version.get("disposition"),
            "prescriptions": correction_candidates,
        },
        correction_candidates=correction_candidates,
        applied_operations=applied_operations,
        remeasurement=remeasurement,
        disposition=disposition,
        absence_reasons=absence_reasons,
        basis_fingerprints={
            "observation_id": bundle.observation_id,
            "bundle_fingerprint": bundle.bundle_fingerprint,
            "reference_fingerprint": bundle.reference_fingerprint,
            "manifest_fingerprint": bundle.manifest_fingerprint,
            "report_fingerprint": bundle.report_fingerprint,
            "world_state_fingerprint": bundle.world_state_fingerprint,
            "scene_content_fingerprint": scene_content,
        },
        delivery_eligible=False,
    )


def build_shot_evidence_store(
    *,
    run_id: str,
    scene_id: str,
    plan: Any,
    observations: Iterable[ObservationBundle | Mapping[str, Any]],
    rounds: Sequence[Mapping[str, Any]] = (),
    best_observation_id: str = "",
    coarse_passed: bool = False,
) -> EvidenceStore:
    """Project each scene observation into every referenced shot history.

    ``delivery_eligible`` is intentionally false: coarse evidence proves a
    qualified blockout, never a final video.  ``adopted`` means adopted at the
    coarse stage and is set only after the whole coarse gate passed.
    """
    plan_payload = _plan_payload(plan)
    bundles = [_bundle(item) for item in observations]
    if not bundles:
        raise ValueError("cannot build evidence store without observations")
    store = EvidenceStore(run_id=run_id, scene_id=scene_id)
    shot_ids = _shot_ids(plan_payload, bundles)
    if not shot_ids:
        raise ValueError("plan/reference contains no shot ids")
    candidate_rounds = {
        str(row.get("candidate_observation_id") or ""): copy.deepcopy(dict(row))
        for row in rounds
        if isinstance(row, Mapping) and row.get("candidate_observation_id")
    }
    rounds_by_number = {
        int(row.get("round_no")): copy.deepcopy(dict(row))
        for row in rounds
        if isinstance(row, Mapping) and row.get("round_no")
    }

    for attempt_index, bundle in enumerate(bundles):
        quality = blockout_quality_report(bundle.report)
        round_row = candidate_rounds.get(bundle.observation_id, {})
        if not round_row and attempt_index > 0:
            by_number = rounds_by_number.get(attempt_index, {})
            # Historical rounds did not record candidate_observation_id.
            # Their chronological order still binds round N to attempt N+1.
            if not by_number.get("candidate_observation_id"):
                round_row = by_number
        for shot_id in shot_ids:
            version = len(store.history(shot_id))
            checks, findings = _filter_report_rows(bundle.report, shot_id)
            shot_quality = dict((quality.get("shots") or {}).get(shot_id) or {})
            composition = dict(shot_quality.get("composition") or {})
            hard_errors = int(shot_quality.get("hard_error_count") or 0)
            shot_passed = (
                composition.get("status") in {"pass", "exempt"}
                and hard_errors == 0
            )
            frames = [
                item.to_dict() for item in bundle.frames
                if item.shot_id == shot_id
            ]
            visual_states = _authoritative_visual_states(bundle, shot_id)
            semantic_review = (
                {
                    "status": (
                        "reviewed"
                        if all(row.get("reviewed") is True
                               for row in visual_states)
                        else "not_reviewed"),
                    "visual_states": visual_states,
                    "reviewed": all(
                        row.get("reviewed") is True
                        for row in visual_states),
                }
                if visual_states else {}
            )
            rag = _rag_for_shot(round_row, shot_id)
            prescriptions = [
                copy.deepcopy(dict(row))
                for row in (round_row.get("prescriptions") or [])
                if isinstance(row, Mapping)
                and str(row.get("shot_id") or shot_id) == shot_id
            ]
            applied_operations = [
                {
                    **copy.deepcopy(dict(row)),
                    "disposition": (
                        "applied" if row.get("applied") is True
                        else "rejected"),
                }
                for row in prescriptions
            ]
            absence_reasons = {
                "sequence_gate":
                    "sequence review runs after per-shot evidence capture",
            }
            if not semantic_review:
                absence_reasons["semantic_review"] = (
                    "this observation did not include a VLM review")
            if not rag:
                absence_reasons["rag"] = (
                    "this observation did not record RAG provenance")
            if not prescriptions:
                absence_reasons["correction_candidates"] = (
                    "this observation had no correction candidates")
            if not applied_operations:
                absence_reasons["applied_operations"] = (
                    "this observation had no applied correction operations")
            if version == 0:
                absence_reasons["remeasurement"] = (
                    "the initial observation has no prior correction "
                    "to remeasure")
            remeasurement = (
                {}
                if version == 0
                else {
                    "status": "measured",
                    "report_fingerprint": bundle.report_fingerprint,
                    "shot_quality": copy.deepcopy(shot_quality),
                    "world_state_fingerprint":
                        bundle.world_state_fingerprint,
                }
            )
            disposition = {
                "status": str(
                    round_row.get("disposition")
                    or ("initial_observation" if version == 0
                        else "observer_only")),
                "reason": str(
                    round_row.get("blocked_reason")
                    or round_row.get("reason")
                    or "recorded by the coarse observation pipeline"),
            }
            record = ShotEvidence.create(
                run_id=run_id,
                scene_id=scene_id,
                shot_id=shot_id,
                version=version,
                parent_version=None if version == 0 else version - 1,
                reason=(
                    "coarse_initial_observation"
                    if version == 0
                    else f"coarse_correction_round_{version:03d}"
                ),
                created_at="deterministic-replay",
                plan={
                    "scene": plan_payload,
                    "shot": _shot_plan(plan_payload, shot_id),
                },
                shot_contract=_shot_plan(plan_payload, shot_id),
                reference=bundle.reference,
                manifest=bundle.manifest,
                world_state=bundle.world_state,
                shot_slice=_shot_slice(
                    shot_plan=_shot_plan(plan_payload, shot_id),
                    reference=bundle.reference,
                    manifest=bundle.manifest,
                    world_state=bundle.world_state,
                ),
                build={
                    "status": "observed",
                    "scene_id": bundle.manifest.get("scene_id"),
                    "manifest_fingerprint": bundle.manifest_fingerprint,
                    "primitive_count": len(
                        bundle.manifest.get("primitives") or []),
                    "camera_count": len(
                        bundle.manifest.get("cameras") or []),
                },
                audit={
                    "schema_version": bundle.report.get("schema_version"),
                    "verdict": bundle.report.get("verdict"),
                    "report_fingerprint": bundle.report_fingerprint,
                    "checks": checks,
                    "findings": findings,
                },
                measurements={
                    "component": "blockout",
                    "shot_quality": shot_quality,
                    "composition": composition,
                    "checks": checks,
                    "findings": findings,
                    "report_fingerprint": bundle.report_fingerprint,
                },
                score_breakdown={
                    "quality_contract": "quality-contract/v1",
                    "shot_quality": shot_quality,
                    "composition": copy.deepcopy(composition),
                    "hard_error_count": hard_errors,
                    "sequence": None,
                },
                gates={
                    "observation_complete": bundle.complete,
                    "shot_passed": shot_passed,
                    "coarse_passed": bool(coarse_passed and shot_passed),
                    "quality_contract": "quality-contract/v1",
                },
                hard_gates={
                    "status": "pass" if hard_errors == 0 else "fail",
                    "passed": hard_errors == 0,
                    "failed": [
                        finding for finding in findings
                        if str(finding.get("severity") or "") == "error"
                    ],
                    "evaluated": ["shot_findings"],
                },
                frames=frames,
                semantic_review=semantic_review,
                rag=rag,
                correction={
                    "round": round_row.get("round_no"),
                    "disposition": round_row.get("disposition"),
                    "prescriptions": prescriptions,
                },
                correction_candidates=prescriptions,
                applied_operations=applied_operations,
                remeasurement=remeasurement,
                disposition=disposition,
                absence_reasons=absence_reasons,
                basis_fingerprints={
                    "observation_id": bundle.observation_id,
                    "bundle_fingerprint": bundle.bundle_fingerprint,
                    "reference_fingerprint": bundle.reference_fingerprint,
                    "manifest_fingerprint": bundle.manifest_fingerprint,
                    "report_fingerprint": bundle.report_fingerprint,
                    "world_state_fingerprint": bundle.world_state_fingerprint,
                    "scene_content_fingerprint": canonical_fingerprint({
                        "reference": bundle.reference,
                        "manifest": bundle.manifest,
                        "world_state": normalize_world_state(
                            bundle.world_state),
                    }),
                },
                delivery_eligible=False,
            )
            store.append(record)

            if (best_observation_id
                    and bundle.observation_id == best_observation_id):
                store.mark_best(shot_id, version)

    if coarse_passed:
        for shot_id in shot_ids:
            try:
                best_version = store.best_version(shot_id)
            except KeyError:
                continue
            best_record = store.get(shot_id, best_version)
            if best_record.gates.get("shot_passed") is True:
                store.mark_adopted(shot_id, best_version)

    return store


__all__ = ["build_detail_shot_evidence", "build_shot_evidence_store"]
