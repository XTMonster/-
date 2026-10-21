"""Agent and explicit offline-fixture providers for coarse blocking revision."""

from __future__ import annotations

import copy
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

from ..cinema.coarse_revision import build_coarse_prescriptions
from ..cinema.shot_staging import effective_reference_for_shot
from ..contracts.coarse_proposal import (
    COARSE_PROPOSAL_SCHEMA_VERSION,
    CoarseProposalRequest,
    CoarseProposalError,
    camera_entity_id,
    emit_coarse_proposal_tool,
    legal_entities_by_shot,
)
from ..contracts.enums import MessageRole, Purpose, ToolChoice
from ..contracts.messages import ChatPayload, Message
from ..contracts.vlm_review import frame_data_uri

COARSE_PROVIDER_TOOL = "emit_coarse_proposal"
MAX_FAILED_SHOTS_PER_ROUND = 3


def failed_shot_ids(report: Mapping[str, Any]) -> List[str]:
    """Return shots needing revision in director-priority order.

    The report mixes checks whose smaller value is worse (composition,
    visibility) with checks whose larger value is worse (subject area,
    foreground occlusion).  Sorting every ``actual`` ascending therefore lets
    soft area diagnostics displace a failed composition from the Agent's
    three-shot context.  Keep hard findings first, then composition failures,
    then other soft failures by their threshold gap.
    """
    hard: List[str] = []
    composition: List[tuple[float, str]] = []
    soft: List[tuple[float, str]] = []
    for finding in report.get("findings") or []:
        if not isinstance(finding, Mapping):
            continue
        if str(finding.get("severity") or "") != "error":
            continue
        shot_id = str(finding.get("shot_id") or "").strip()
        if shot_id and shot_id not in hard:
            hard.append(shot_id)
    for check in report.get("checks") or []:
        if not isinstance(check, Mapping):
            continue
        if str(check.get("verdict") or "") not in {"fail", "unresolved"}:
            continue
        shot_id = str(check.get("shot_id") or "").strip()
        if not shot_id:
            continue
        actual = check.get("actual")
        try:
            score = float(actual)
        except (TypeError, ValueError):
            score = float("inf")
        if str(check.get("check_id") or "") == "composition":
            composition.append((score, shot_id))
            continue
        threshold = check.get("threshold")
        try:
            gap = abs(float(actual) - float(threshold))
        except (TypeError, ValueError):
            gap = float("inf")
        soft.append((-gap, shot_id))
    ordered = list(hard)
    for _score, shot_id in sorted(
            composition, key=lambda pair: (pair[0], pair[1])):
        if shot_id not in ordered:
            ordered.append(shot_id)
    #: For subject_area / foreground_occlusion, larger excess is worse; the
    #: negative gap makes the ascending sort put the widest breach first.
    for _gap, shot_id in sorted(soft, key=lambda pair: (pair[0], pair[1])):
        if shot_id not in ordered:
            ordered.append(shot_id)
    return ordered


def _failure_lines(
    report: Mapping[str, Any], shot_ids: Sequence[str],
) -> Dict[str, List[Dict[str, Any]]]:
    wanted = set(shot_ids)
    result: Dict[str, List[Dict[str, Any]]] = {shot: [] for shot in shot_ids}
    for key in ("findings", "checks"):
        for item in report.get(key) or []:
            if not isinstance(item, Mapping):
                continue
            shot_id = str(item.get("shot_id") or "")
            if shot_id in wanted:
                result[shot_id].append(copy.deepcopy(dict(item)))
    return result


def _correction_candidates(
    report: Mapping[str, Any],
    shot_ids: Sequence[str],
) -> Dict[str, List[Dict[str, Any]]]:
    """Expose the exact stable candidate IDs the Agent may reference."""
    wanted = set(str(shot_id) for shot_id in shot_ids)
    result: Dict[str, List[Dict[str, Any]]] = {
        str(shot_id): [] for shot_id in shot_ids}
    for item in report.get("correction_candidates") or []:
        if not isinstance(item, Mapping):
            continue
        shot_id = str(item.get("shot_id") or "")
        if shot_id not in wanted:
            continue
        result[shot_id].append({
            "candidate_id": str(item.get("candidate_id") or ""),
            "kind": str(item.get("kind") or ""),
            "subject": str(item.get("subject") or ""),
            "source": str(item.get("source") or ""),
            "severity": str(item.get("severity") or ""),
            "suggested_tool": str(item.get("suggested_tool") or ""),
            "evidence": str(item.get("evidence") or ""),
        })
    return result


def _normalise_history(
    history: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Keep the reconciliation ledger shape stable for the model prompt."""
    rows: List[Dict[str, Any]] = []
    for item in list(history)[-6:]:
        if not isinstance(item, Mapping):
            continue
        prescriptions: List[Dict[str, Any]] = []
        for record in item.get("prescriptions") or []:
            if not isinstance(record, Mapping):
                continue
            prescriptions.append({
                "prescription_id": str(
                    record.get("prescription_id") or ""),
                "shot_id": str(record.get("shot_id") or ""),
                "entity": str(record.get("entity") or ""),
                "component": str(record.get("component") or ""),
                "target_value": copy.deepcopy(
                    record.get("target_value")),
                "applied": bool(record.get("applied")),
                "no_op": bool(record.get("no_op")),
                "rejected": bool(record.get("rejected")),
                "reason": str(record.get("reason") or ""),
                "after": copy.deepcopy(record.get("after")),
            })
        rows.append({
            "round_no": int(item.get("round_no") or 0),
            "disposition": str(item.get("disposition") or ""),
            "candidate_score": item.get("candidate_score"),
            "best_score_before": item.get("best_score_before"),
            "best_score_after": item.get("best_score_after"),
            "candidate_fingerprint": str(
                item.get("candidate_fingerprint") or ""),
            "candidate_reference_repeated": bool(
                item.get("candidate_reference_repeated")),
            "cycle_detected": bool(item.get("cycle_detected")),
            "provider_kind": str(item.get("provider_kind") or ""),
            "reason": str(item.get("reason") or ""),
            "proposal_rejected": bool(item.get("proposal_rejected")),
            "rejection_reason": str(item.get("rejection_reason") or ""),
            "prescriptions": prescriptions,
        })
    return rows


def _visual_frame_map(
    request: CoarseProposalRequest,
    shot_ids: Sequence[str],
) -> Dict[tuple[str, str], Dict[str, Any]]:
    """Require the exact first/middle/last frames the director Agent reviews."""
    rows: Dict[tuple[str, str], List[Dict[str, Any]]] = {}
    for item in request.frames:
        shot_id = str(item.get("shot_id") or "")
        phase = str(item.get("phase") or "")
        rows.setdefault((shot_id, phase), []).append(dict(item))
    missing: List[str] = []
    selected: Dict[tuple[str, str], Dict[str, Any]] = {}
    for shot_id in shot_ids:
        shot_problems: List[str] = []
        for phase in ("first", "middle", "last"):
            candidates = rows.get((shot_id, phase), [])
            if len(candidates) != 1:
                shot_problems.append(phase)
                continue
            row = candidates[0]
            path = Path(str(row.get("path") or row.get("png") or ""))
            if (not path.is_file() or row.get("readable") is not True
                    or not str(row.get("file_sha256") or "")
                    or not str(row.get("pixel_sha256") or "")):
                shot_problems.append(f"{phase}:unreadable")
                continue
            selected[(shot_id, phase)] = row
        if shot_problems:
            missing.append(f"{shot_id}[{','.join(shot_problems)}]")
    if missing:
        raise CoarseProposalError(
            "visual_evidence_incomplete: "
            + "; ".join(missing)
            + " (each failed shot requires digest-backed "
              "first/middle/last frames)",
            code="visual_evidence_incomplete",
            details={"shots": list(missing)},
        )
    return selected


def _aggregate_retrieval_events(
    events: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Summarise canonical retrieval events without losing item order."""

    def unique(values: Any) -> List[str]:
        result: List[str] = []
        seen = set()
        for value in values:
            item = str(value or "")
            if item and item not in seen:
                seen.add(item)
                result.append(item)
        return result

    hit_cards: List[str] = []
    hit_edges: List[str] = []
    hit_cases: List[str] = []
    injected_cards: List[str] = []
    injected_edges: List[str] = []
    injected_cases: List[str] = []
    backends: List[str] = []
    degradation_reasons: List[str] = []
    drops: List[Dict[str, str]] = []
    seen_drops = set()
    actual_tokens = 0
    network_calls = 0
    injected = False
    degraded = False
    for event in events:
        hit_cards.extend(event.get("hit_card_ids") or ())
        hit_edges.extend(event.get("hit_edge_ids") or ())
        hit_cases.extend(event.get("hit_case_ids") or ())
        injected_cards.extend(event.get("injected_card_ids") or ())
        injected_edges.extend(event.get("injected_edge_ids") or ())
        injected_cases.extend(event.get("injected_case_ids") or ())
        backends.append(str(event.get("actual_backend") or ""))
        reason = str(event.get("degradation_reason") or "")
        if reason:
            degradation_reasons.append(reason)
        actual_tokens += int(event.get("actual_injected_tokens") or 0)
        network_calls += int(bool(event.get("network_call")))
        injected = injected or bool(event.get("injected"))
        degraded = degraded or bool(event.get("degraded"))
        for drop in event.get("drops") or ():
            if not isinstance(drop, Mapping):
                continue
            row = {
                "id": str(drop.get("id") or ""),
                "kind": str(drop.get("kind") or ""),
                "reason": str(drop.get("reason") or ""),
            }
            key = (row["id"], row["kind"], row["reason"])
            if row["id"] and key not in seen_drops:
                seen_drops.add(key)
                drops.append(row)
    return {
        "event_count": len(events),
        "hit_card_ids": unique(hit_cards),
        "hit_edge_ids": unique(hit_edges),
        "hit_case_ids": unique(hit_cases),
        "injected_card_ids": unique(injected_cards),
        "injected_edge_ids": unique(injected_edges),
        "injected_case_ids": unique(injected_cases),
        "actual_injected_tokens": actual_tokens,
        "drops": drops,
        "backends": unique(backends),
        "degraded": degraded,
        "degradation_reasons": unique(degradation_reasons),
        "network_call_count": network_calls,
        "injected": injected,
    }


def _knowledge_for_shots(
    knowledge: Any,
    reference: Mapping[str, Any],
    report: Mapping[str, Any],
    shot_ids: Sequence[str],
    *,
    stage: str = "coarse",
) -> tuple[str, Dict[str, Any]]:
    if knowledge is None or not hasattr(knowledge, "block_for_shot"):
        return "", {"status": "disabled"}
    initial_payload = (
        knowledge.trace_payload()
        if hasattr(knowledge, "trace_payload") else {})
    seen_event_ids = {
        str(event.get("retrieval_event_id") or "")
        for event in (initial_payload.get("retrieval_events") or [])
        if isinstance(event, Mapping)
    }
    all_events: List[Dict[str, Any]] = []
    shots = {
        str(item.get("shot_id") or ""): item
        for item in (reference.get("shots") or [])
        if isinstance(item, Mapping)
    }
    failures = _failure_lines(report, shot_ids)
    blocks: Dict[str, str] = {}
    per_shot_trace: Dict[str, Any] = {}
    per_shot_events: Dict[str, List[Dict[str, Any]]] = {}
    for shot_id in shot_ids:
        shot = shots.get(shot_id) or {}
        problem_text = " ".join(
            str(item.get("message") or item.get("check_id") or "")
            for item in failures.get(shot_id) or [])
        actions = [
            str(item.get("type") or item.get("action_type") or "")
            for item in (shot.get("actions") or [])
            if isinstance(item, Mapping)
        ]
        block = knowledge.block_for_shot(
            str(shot.get("shot_type") or ""),
            " ".join(filter(None, [
                str(shot.get("intent") or ""), problem_text])),
            actions,
            shot_id=shot_id,
            analogy=str(shot.get("intent") or ""),
            stage=stage,
        )
        if block:
            blocks[shot_id] = block
        trace_payload = (
            knowledge.trace_payload()
            if hasattr(knowledge, "trace_payload") else {})
        raw_events = [
            copy.deepcopy(dict(event))
            for event in (trace_payload.get("retrieval_events") or [])
            if isinstance(event, Mapping)
        ]
        shot_events = [
            event for event in raw_events
            if str(event.get("retrieval_event_id") or "")
            not in seen_event_ids
        ]
        seen_event_ids.update(
            str(event.get("retrieval_event_id") or "")
            for event in shot_events
            if event.get("retrieval_event_id")
        )
        all_events.extend(shot_events)
        per_shot_events[shot_id] = shot_events
        shot_trace = (trace_payload.get("shot_scope") or {})
        per_shot_trace[shot_id] = {
            "backend": trace_payload.get("backend"),
            "degraded": bool(trace_payload.get("degraded")),
            "degraded_reason": trace_payload.get("degraded_reason"),
            "shot_scope": copy.deepcopy(shot_trace),
            "retrieval_events": shot_events,
            "event_count": len(shot_events),
            **_aggregate_retrieval_events(shot_events),
        }
    text = "\n\n".join(
        f"【镜号 {shot_id}】\n{block}"
        for shot_id, block in blocks.items())
    summary = _aggregate_retrieval_events(all_events)
    return text, {
        "status": "retrieved" if text else "no_hits",
        "injected_blocks": blocks,
        "per_shot_trace": per_shot_trace,
        "per_shot_events": per_shot_events,
        "events": all_events,
        "event_count": len(all_events),
        "summary": summary,
    }


def _effective_characters_by_shot(
    reference: Mapping[str, Any],
    shot_ids: Sequence[str],
) -> Dict[str, List[Dict[str, Any]]]:
    """Return the exact per-shot cast records visible to the director Agent."""
    shots = {
        str(item.get("shot_id") or ""): item
        for item in (reference.get("shots") or [])
        if isinstance(item, Mapping)
    }
    result: Dict[str, List[Dict[str, Any]]] = {}
    for shot_id in shot_ids:
        shot = shots.get(shot_id) or {}
        names = {
            str(name) for name in (shot.get("characters") or []) if str(name)
        }
        framing = shot.get("framing_target")
        if isinstance(framing, Mapping) and framing.get("ref"):
            names.add(str(framing.get("ref")))
        effective = effective_reference_for_shot(reference, shot_id)
        result[shot_id] = [
            {
                "name": str(item.get("name") or ""),
                "position": copy.deepcopy(item.get("position")),
                "facing": copy.deepcopy(item.get("facing")),
                "position_provenance": str(
                    item.get("position_provenance") or "continuity_base"),
                "position_reason": str(item.get("position_reason") or ""),
                "effective_shot_id": str(
                    item.get("effective_shot_id") or shot_id),
            }
            for item in (effective.get("characters") or [])
            if isinstance(item, Mapping)
            and str(item.get("name") or "") in names
        ]
    return result


@dataclass
class AgentCoarseProposalProvider:
    """Real director-agent proposal adapter over the common transport."""

    transport: Any
    knowledge: Any = None
    audit: Any = None
    budget: Any = None
    max_tokens: int = 12000
    temperature: float = 0.2
    provider_kind: str = "agent_model"
    stage: str = "coarse"

    def __call__(
        self,
        *,
        request: CoarseProposalRequest,
    ) -> Mapping[str, Any]:
        report = dict(request.report)
        failed = failed_shot_ids(report)
        if not failed:
            raise CoarseProposalError(
                "report has no failed shot to revise",
                code="agent_proposal_no_failed_shots",
            )
        selected = failed[:MAX_FAILED_SHOTS_PER_ROUND]
        visual_frames = _visual_frame_map(request, selected)
        rag_text, rag_provenance = _knowledge_for_shots(
            self.knowledge, request.reference, report, selected,
            stage=self.stage)
        shots = {
            str(item.get("shot_id") or ""): item
            for item in (request.reference.get("shots") or [])
            if isinstance(item, Mapping)
        }
        cameras = {
            str(item.get("shot_id") or ""): item
            for item in (request.reference.get("camera_intents") or [])
            if isinstance(item, Mapping)
        }
        render_staging = request.world_state.get("render_staging")
        staging_audit = {
            shot_id: copy.deepcopy(render_staging[shot_id])
            for shot_id in selected
            if isinstance(render_staging, Mapping)
            and isinstance(render_staging.get(shot_id), Mapping)
        }
        compact = {
            "round_no": int(request.round_no),
            "observation_id": request.observation_id,
            "failed_shot_ids": selected,
            "continuity_characters": [
                {
                    "name": str(item.get("name") or ""),
                    "position": item.get("position"),
                    "facing": item.get("facing"),
                }
                for item in (request.reference.get("characters") or [])
                if isinstance(item, Mapping)
            ],
            "effective_characters_by_shot": _effective_characters_by_shot(
                request.reference, selected),
            "shots": [copy.deepcopy(shots[shot]) for shot in selected
                      if shot in shots],
            "cameras": [copy.deepcopy(cameras[shot]) for shot in selected
                        if shot in cameras],
            "camera_entities": {
                shot: camera_entity_id(cameras[shot], shot)
                for shot in selected if shot in cameras
            },
            "legal_entities_by_shot": legal_entities_by_shot(
                request.reference, selected),
            "failures": _failure_lines(report, selected),
            "correction_candidates": _correction_candidates(
                report, selected),
            "world_state": request.world_state,
            "staging_audit": staging_audit,
            "frame_digests": request.frame_digests,
            "previous_rounds": _normalise_history(request.history),
            "knowledge": rag_text or "（本次无知识命中）",
            "external_knowledge_context": request.knowledge_context,
        }
        system = (
            "你是 BlockDirector 的导演 Agent。当前阶段是白模粗排，不是细排或成片。"
            "你必须像一个导演那样读取首/中/末帧、剧本语义、结构化测量、世界坐标和"
            "实际 RAG 内容，然后只提出本轮最小、可执行的局部修改。\n\n"
            "硬规则：\n"
            "1. 程序测量是硬事实；VLM/视觉直觉只能解释和补充，不能覆盖它。\n"
            "2. 角色站位修改只作用于指定 shot_id，不得把它当全局连续性基准。\n"
            "3. 相机和角色只能修改本工具允许的结构化字段，不得直接写 Blender。"
            "camera 处方的 entity 必须逐字复制 "
            "legal_entities_by_shot[shot_id].camera 中的值（优先 "
            "camera_entities[shot_id]，例如 cam_shot_007），绝不能写泛化的 "
            "camera；character 处方的 entity 必须逐字复制同一表中 "
            "legal_entities_by_shot[shot_id].character 的精确角色名。\n"
            "4. 每条处方必须有 reason 和 evidence_refs，引用具体镜号/测量/画面。\n"
            "5. 只选最关键的 1–3 个失败镜做本轮局部调整；后续轮次会重新测量。\n"
            "6. 不得为了过门捏造测量、删除失败或把未通过当通过。\n"
            "7. 必须读取 previous_rounds。已经 applied 但 candidate_score 未超过 "
            "best、被标为 cycle/repeated，或已回滚的同镜同 component 处方不得原样重复；"
            "应基于新的失败证据改变目标镜、轴、方向或幅度。\n"
            "8. 必须调用 emit_coarse_proposal，不能只回复说明文字。"
            "target / character_position 的 target_value 必须是 {x,y,z}；"
            "distance / strafe 必须写绝对世界坐标 "
            "{position:{x,y,z},target?:{x,y,z}}，不得只写米数标量；"
            "position.y / position.z 的 target_value 必须是数字。"
            "工具参数必须是合法 JSON；reason 等字符串内如需引号，使用中文引号"
            "或正确转义，避免破坏 JSON。\n"
            "9. 若 correction_candidates[shot_id] 非空，每条相关处方必须在 "
            "candidate_ids 中逐字引用对应 candidate_id；不得自行改写、"
            "截断或引用其它镜的候选。"
        )
        parts: List[Dict[str, Any]] = [{
            "type": "text",
            "text": "结构化导演上下文：\n" + json.dumps(
                compact, ensure_ascii=False, indent=2),
        }]
        for shot_id in selected:
            for phase in ("first", "middle", "last"):
                frame = visual_frames[(shot_id, phase)]
                path = Path(str(frame.get("path") or frame.get("png") or ""))
                parts.append({
                    "type": "text",
                    "text": f"【{shot_id} / {phase}】",
                })
                parts.append({
                    "type": "image_url",
                    "image_url": {"url": frame_data_uri(path)},
                })
        payload = ChatPayload(
            messages=[
                Message(role=MessageRole.SYSTEM, content=system),
                Message(role=MessageRole.USER, content=parts),
            ],
            tools=[emit_coarse_proposal_tool(request.reference)],
            tool_choice=ToolChoice.REQUIRED,
            temperature=float(self.temperature),
            max_tokens=max(1, int(self.max_tokens)),
            purpose=Purpose.COARSE,
        )
        if self.budget is not None:
            exhausted = self.budget.exhausted_reason()
            if exhausted:
                raise CoarseProposalError(
                    f"coarse Agent call blocked by run budget: {exhausted}",
                    code="coarse_budget_exhausted",
                    details={"budget": self.budget.summary},
                )
        started = time.monotonic()
        try:
            reply = self.transport.chat(payload)
        except Exception as exc:
            if self.budget is not None:
                self.budget.record_llm(None)
            if self.audit is not None:
                self.audit.log_llm(
                    str(Purpose.COARSE),
                    None,
                    time.monotonic() - started,
                    error=f"{type(exc).__name__}: {exc}",
                    payload=payload,
                )
            raise
        if self.budget is not None:
            self.budget.record_llm(reply.usage)
        if self.audit is not None:
            self.audit.log_llm(
                str(Purpose.COARSE),
                reply,
                time.monotonic() - started,
                request_id=str(getattr(reply, "request_id", "") or ""),
                payload=payload,
            )
        call = next(
            (item for item in reply.tool_calls or []
             if item.function.name == COARSE_PROVIDER_TOOL),
            None,
        )
        if call is None:
            names = [item.function.name for item in reply.tool_calls or []]
            raise CoarseProposalError(
                f"agent reply has no {COARSE_PROVIDER_TOOL} call; "
                f"actual={names}",
                code="agent_proposal_protocol_error",
                details={"tool_calls": names},
                recoverable=True,
            )
        try:
            proposal = call.function.parsed_arguments()
        except (TypeError, ValueError) as exc:
            raise CoarseProposalError(
                f"{COARSE_PROVIDER_TOOL} arguments are invalid: {exc}",
                code="agent_proposal_protocol_error",
                details={"tool_call_id": call.id},
                recoverable=True,
            ) from exc
        proposal["provider_kind"] = self.provider_kind
        configured_model = str(getattr(self.transport, "model", "") or "")
        proposal["provider"] = {
            "kind": self.provider_kind,
            "model": str(reply.model or configured_model),
            "configured_model": configured_model,
            "transport_provider": str(
                getattr(self.transport, "provider", "")
                or getattr(self.transport, "backend", "")
                or ""),
            "transport_class": type(self.transport).__name__,
            "usage": reply.usage.to_dict() if reply.usage is not None else None,
            "finish_reason": reply.finish_reason,
            "request_id": reply.request_id,
            "tool_call_id": call.id,
            "round_no": int(request.round_no),
            "observation_id": request.observation_id,
            "frame_digests": request.frame_digests,
        }
        proposal["knowledge_provenance"] = rag_provenance
        return proposal


class OfflineFixtureCoarseProposalProvider:
    """Explicit deterministic fixture; never presented as a model proposal."""

    provider_kind = "offline_fixture"

    def __call__(
        self,
        *,
        request: CoarseProposalRequest,
    ) -> Mapping[str, Any]:
        report = dict(request.report)
        prescriptions = build_coarse_prescriptions(
            report=report, reference=request.reference, only_hard=False)
        empty_wall_shots = {
            str(finding.get("shot_id") or "")
            for finding in (report.get("findings") or [])
            if isinstance(finding, Mapping)
            and finding.get("check_id") == "E_BLOCKOUT_EMPTY_WALL"
        }
        #: An empty-wall target repair is a prerequisite for trusting visual
        #: framing metrics.  Stacking a distance change derived from the same
        #: pre-repair frame can move the camera away after the target has been
        #: fixed.  Re-measure first; later rounds can still adjust distance.
        prescriptions = [
            item for item in prescriptions
            if not (
                str(item.get("shot_id") or "") in empty_wall_shots
                and str((item.get("derived_from") or {}).get("check_id") or "")
                in {"on_screen", "composition"}
            )
        ]
        for item in prescriptions:
            derived = item.get("derived_from") or {}
            evidence = derived.get("check_id") or "coarse_report"
            shot_id = str(item.get("shot_id") or "")
            item.setdefault("reason", str(
                item.get("prescription_id") or "offline fixture adjustment"))
            item.setdefault(
                "evidence_refs", [f"{evidence}:{shot_id}".rstrip(":")])
        if not prescriptions:
            raise CoarseProposalError(
                "offline_fixture_no_prescriptions: the deterministic fixture "
                "found no applicable correction",
                code="offline_fixture_no_prescriptions",
            )
        return {
            "schema_version": COARSE_PROPOSAL_SCHEMA_VERSION,
            "source": self.provider_kind,
            "provider_kind": self.provider_kind,
            "reason": "显式 offline fixture 确定性处方（非模型提案）",
            "observation_id": request.observation_id,
            "prescriptions": prescriptions,
        }


def make_coarse_proposal_provider(
    *,
    transport: Any = None,
    knowledge: Any = None,
    audit: Any = None,
    budget: Any = None,
    max_tokens: int = 12000,
    stage: str = "coarse",
) -> AgentCoarseProposalProvider | OfflineFixtureCoarseProposalProvider | None:
    """Build the explicit provider for a run; no provider means no fallback."""
    if transport is None:
        return None
    from .offline import OfflineTransport

    if isinstance(transport, OfflineTransport):
        return OfflineFixtureCoarseProposalProvider()
    if not hasattr(transport, "chat"):
        return None
    return AgentCoarseProposalProvider(
        transport=transport,
        knowledge=knowledge,
        audit=audit,
        budget=budget,
        max_tokens=int(max_tokens),
        stage=str(stage or "coarse"),
    )


__all__ = [
    "AgentCoarseProposalProvider",
    "OfflineFixtureCoarseProposalProvider",
    "failed_shot_ids",
    "make_coarse_proposal_provider",
]
