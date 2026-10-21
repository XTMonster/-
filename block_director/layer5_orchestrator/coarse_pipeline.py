"""白模预演完整流程：粗排管线编排器（Ticket 05，bpy 侧）。

串起：剧本理解（SceneBrief）-> 粗编排参考 JSON -> BlockoutManifest ->
体块建场景 -> 低采样预览观察 -> 修正循环（处方改参考 JSON -> 重建 -> 再观察，
收敛或显式阻塞）-> 粗排 gate 通过 -> 冻结 coarse_world_baseline -> 分镜表。

粗排阶段任何 fail 都不得继续到细排/导出 final；每轮修正落 revision 留痕。
所有 bpy 调用延迟导入，保证模块可被纯层 import。
"""

from __future__ import annotations

import copy
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

from block_director.contracts.blockout import approval_state_machine
from block_director.contracts.observation import (
    ObservationBundle,
    build_observation_bundle,
)
from block_director.contracts.plan import Plan
from block_director.cinema.blockout import build_blockout_manifest
from block_director.cinema.coarse_loop import run_coarse_revision_loop
from block_director.cinema.evidence_builder import build_shot_evidence_store
from block_director.cinema.pipeline_gates import (
    PipelinePhase,
    freeze_coarse_baseline,
)
from block_director.cinema.spatial_design import build_design_snapshot
from block_director.layer5_orchestrator.understand import (
    deterministic_brief,
)
from block_director.layer5_orchestrator.spatial_ruler import (
    apply_plan_prescriptions,
)

_ATTEMPT_DIR_RE = re.compile(r"^attempt-\d{3,}$")


@dataclass(frozen=True)
class CoarsePipelineAdapters:
    """Blender-facing operations injected at the coarse-pipeline boundary."""

    build_manifest: Callable[[Mapping[str, Any], Any], Mapping[str, Any]]
    build_scene: Callable[[Mapping[str, Any]], None]
    render_preview: Callable[..., Mapping[str, Any]]
    collect_world_state: Callable[[Mapping[str, Any]], Mapping[str, Any]]


def _default_adapters() -> CoarsePipelineAdapters:
    # Import bpy-facing modules only when an adapter is actually invoked.
    # Importing a ``layer3_engine`` submodule executes that package's
    # ``__init__`` and therefore imports bpy; doing that here made the pure
    # coarse-pipeline seam unimportable outside Blender.
    def build_scene(manifest: Mapping[str, Any]) -> None:
        from block_director.layer3_engine.blockout_scene import (
            build_blockout_scene,
        )

        build_blockout_scene(manifest)

    def render_preview(
        manifest: Mapping[str, Any],
        out_dir: Path | str,
        **kwargs: Any,
    ) -> Mapping[str, Any]:
        from block_director.layer8_delivery.blockout_preview import (
            render_blockout_preview,
        )

        return render_blockout_preview(manifest, out_dir, **kwargs)

    def collect_world_state(
        manifest: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        from block_director.layer3_engine.world_state import (
            collect_blockout_world_state,
        )

        return collect_blockout_world_state(manifest)

    return CoarsePipelineAdapters(
        build_manifest=build_blockout_manifest,
        build_scene=build_scene,
        render_preview=render_preview,
        collect_world_state=collect_world_state,
    )


def _reset_generated_attempts(out: Path) -> Path:
    """Remove only prior ``attempt-NNN`` outputs produced by this pipeline."""
    root = out / "coarse" / "observations"
    root.mkdir(parents=True, exist_ok=True)
    for child in root.iterdir():
        if _ATTEMPT_DIR_RE.fullmatch(child.name) and child.is_dir():
            shutil.rmtree(child)
    return root


def _clear_generated_preview(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for child in target.iterdir():
        if child.is_file() and child.suffix.lower() == ".png":
            child.unlink()


def _publish_best_preview(bundle: Mapping[str, Any], target: Path) -> None:
    """Publish only the retained best observation's exact frame files."""
    _clear_generated_preview(target)
    for row in bundle.get("frames") or []:
        source = Path(str(row.get("path") or ""))
        if not source.is_file():
            continue
        destination = target / source.name
        if destination.exists():
            raise ValueError(
                f"duplicate preview filename in best observation: {source.name}")
        shutil.copy2(source, destination)


def _observation_file(payload: Mapping[str, Any]) -> Path:
    return Path(str(payload.get("evidence_dir") or "")) / "observation.json"


def _json_dump(obj: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def _approve_manifest_to_frozen(manifest: Mapping[str, Any]) -> List[Dict]:
    """draft -> camera-approved -> frozen（纯函数，不落盘）。"""
    approved = approval_state_machine(
        "scene_01_blockout.blend", "global", None, "draft", manifest,
        approved_by="coarse-pipeline", target_state="camera-approved",
        approved_at="deterministic-replay")
    frozen = approval_state_machine(
        "scene_01_blockout.blend", "global", None, "camera-approved",
        manifest, approved_by="coarse-pipeline", target_state="frozen",
        approved_at="deterministic-replay")
    return [approved, frozen]


def run_coarse_pipeline(
    *,
    plan: Any,
    out_dir: Path | str,
    reference: Optional[Mapping[str, Any]] = None,
    script_text: str = "",
    brief: Any = None,
    cast_positions: Optional[Mapping[str, Any]] = None,
    cast_facings: Optional[Mapping[str, Any]] = None,
    scene_id: str = "",
    max_revisions: Optional[int] = None,
    fps: int = 24,
    adapters: Optional[CoarsePipelineAdapters] = None,
    proposal_provider: Optional[Callable[..., Mapping[str, Any] | None]] = None,
    transport: Any = None,
    knowledge: Any = None,
    audit: Any = None,
    budget: Any = None,
    proposal_max_tokens: int = 12000,
    run_id: str = "",
) -> Dict[str, Any]:
    """跑完整粗排管线，落盘全部产物，返回 pipeline_report。

    ``plan`` 支持 Plan 或 dict；``brief`` 缺省时用确定性理解
    （``deterministic_brief``，零 LLM）。
    """
    if isinstance(plan, Plan):
        plan = plan
    elif isinstance(plan, Mapping):
        plan = Plan.from_dict(copy.deepcopy(dict(plan)))
    else:
        raise TypeError(f"plan must be Plan or mapping, got {type(plan)!r}")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    adapter = adapters or _default_adapters()
    observations_root = _reset_generated_attempts(out)
    if proposal_provider is None and transport is not None:
        from .coarse_agent import make_coarse_proposal_provider

        proposal_provider = make_coarse_proposal_provider(
            transport=transport,
            knowledge=knowledge,
            audit=audit,
            budget=budget,
            max_tokens=int(proposal_max_tokens),
        )

    #: 1) 剧本理解（Stage S）
    if brief is None:
        char_names: List[str] = []
        if isinstance(plan, Mapping):
            for s in plan.get("shots") or []:
                char_names.extend(str(n) for n in (s.get("characters") or []))
        else:
            for s in getattr(plan, "shots", None) or []:
                char_names.extend(str(n) for n
                                  in (getattr(s, "characters", None) or []))
        brief = deterministic_brief(parsed=None,
                                    characters=sorted(set(char_names)))

    #: 2) 计划级空间尺必须先于任何建场/预览落地声明时长。否则对白预算
    #: 会把计划拉长，粗排观察的帧时间轴从一开始就与剧本声明错位。
    declared_frames = [
        int(getattr(shot, "declared_duration_frames", 0) or 0)
        for shot in plan.shots
    ]
    declared_seconds_by_shot = {
        str(shot.shot_id): frames / float(fps)
        for shot, frames in zip(plan.shots, declared_frames)
        if frames > 0
    }
    declared_total_seconds = (
        sum(declared_frames) / float(fps)
        if declared_frames and all(frames > 0 for frames in declared_frames)
        else None
    )
    (plan, plan_findings, plan_prescriptions, plan_measurements) = (
        apply_plan_prescriptions(
            plan,
            brief=brief,
            declared_total_seconds=declared_total_seconds,
            declared_seconds_by_shot=declared_seconds_by_shot,
            fps=int(fps),
        )
    )
    plan_after_path = out / "plan_after.json"
    _json_dump(plan.to_dict(), plan_after_path)
    plan_finding_payloads = [
        (item.to_dict() if hasattr(item, "to_dict") else dict(item))
        for item in plan_findings
    ]

    #: 3) 粗编排参考世界坐标 JSON（单一真源；可注入已审阅/已修改的 JSON）。
    #: 即使调用方提供了 reference，也必须用落地后的计划同步 shots[]；旧文件
    #: 里的时长/取景目标不能覆盖本轮可执行计划。
    if reference is None:
        reference = build_design_snapshot(
            brief=brief, plan=plan, cast_positions=cast_positions,
            cast_facings=cast_facings,
            scene_id=scene_id)
    reference = _attach_plan_shots(
        copy.deepcopy(dict(reference)), plan)
    _json_dump(reference, out / "coarse_world_reference.json")

    hard_plan_findings = [
        item for item in plan_findings
        if str(getattr(getattr(item, "severity", ""), "value",
                       getattr(item, "severity", ""))) == "error"
    ]
    if hard_plan_findings:
        effective_run_id = str(run_id or out.name)
        blocked_report = {
            "schema_version": "coarse-pipeline-report/v1",
            "run_id": effective_run_id,
            "scene_id": str(
                scene_id or reference.get("scene_id") or ""),
            "phase": PipelinePhase.COARSE_REFERENCE_READY,
            "coarse_status": "blocked",
            "blocked_code": "plan_ruler_hard_findings",
            "blocked_reason": (
                "空间尺计划级硬发现阻断建场："
                + "；".join(
                    str(item.message) for item in hard_plan_findings)),
            "best_score": None,
            "plan_prescriptions": list(plan_prescriptions),
            "plan_measurements": list(plan_measurements),
            "plan_findings": plan_finding_payloads,
            "rounds": [],
            "observation_count": 0,
            "proposal_rejection_count": 0,
            "gates": {
                "coarse": "blocked",
                "baseline": "missing",
                "detail": "pending",
                "sequence": "pending",
                "final": "pending",
            },
            "artifacts": {
                "plan_after": str(plan_after_path),
                "coarse_world_reference": str(
                    out / "coarse_world_reference.json"),
                "observations": str(observations_root),
                "baseline": None,
            },
        }
        _json_dump(
            blocked_report, out / "coarse_pipeline_report.json")
        return blocked_report

    #: 4..6) blockout -> observe -> revise loop -> freeze
    manifest: Dict[str, Any] = {}
    last_report: Dict[str, Any] = {"verdict": "unresolved",
                                    "findings": [], "checks": []}
    attempt_count = 0

    def rebuild(ref: Mapping[str, Any]) -> None:
        """用最新参考 JSON 重建 manifest + 体块场景（bpy 延迟导入）。"""
        nonlocal manifest
        manifest = dict(adapter.build_manifest(design=ref, plan=plan))
        adapter.build_scene(manifest)

    def observe(ref: Mapping[str, Any]) -> ObservationBundle:
        """Render and bind report, manifest, world state and exact frames."""
        nonlocal attempt_count
        nonlocal last_report
        attempt_count += 1
        attempt_dir = observations_root / f"attempt-{attempt_count:03d}"
        attempt_dir.mkdir(parents=True, exist_ok=False)
        preview = adapter.render_preview(
            manifest, attempt_dir, expected=plan, reference_json=ref)
        last_report = dict(preview["report"])
        world_state = dict(adapter.collect_world_state(manifest))
        if isinstance(preview.get("shot_staging"), Mapping):
            world_state["render_staging"] = copy.deepcopy(
                dict(preview["shot_staging"]))
        bundle = build_observation_bundle(
            reference=ref,
            manifest=manifest,
            report=last_report,
            world_state=world_state,
            evidence_dir=attempt_dir,
            frame_records=list(preview.get("previews") or []),
        )
        bundle.write_atomic(attempt_dir / "observation.json")
        _json_dump(bundle.reference, attempt_dir / "reference.json")
        _json_dump(bundle.manifest, attempt_dir / "manifest.json")
        _json_dump(bundle.world_state, attempt_dir / "world_state.json")
        return bundle

    from block_director.cinema.coarse_loop import DEFAULT_MAX_REVISIONS

    rebuild(reference)
    outcome = run_coarse_revision_loop(
        reference=reference,
        report_loader=observe,
        rebuild=rebuild,
        restore_best=rebuild,
        proposal_provider=proposal_provider,
        max_revisions=int(max_revisions or DEFAULT_MAX_REVISIONS),
        fps=int(fps),
    )
    final_reference = outcome["reference"]
    final_report = outcome["report"]
    final_manifest = dict(outcome.get("manifest") or manifest)
    final_world_state = dict(outcome.get("world_state") or {})
    best_payload = outcome.get("best_observation")
    if not isinstance(best_payload, Mapping):
        raise ValueError("coarse loop did not retain an observation bundle")
    best_bundle = ObservationBundle.from_dict(best_payload)
    if Path(best_bundle.evidence_dir).resolve() != (
            _observation_file(best_payload).parent.resolve()):
        raise ValueError("best observation evidence directory is inconsistent")
    _json_dump(final_reference, out / "coarse_world_reference.json")
    _json_dump(final_report, out / "blockout_report.json")
    _json_dump(final_manifest, out / "blockout_manifest.json")
    _json_dump(final_world_state, out / "blockout_world_state.json")
    _publish_best_preview(best_payload, out / "preview")

    coarse_ok = outcome["status"] == "approved"
    effective_run_id = str(run_id or out.name)
    evidence_store = build_shot_evidence_store(
        run_id=effective_run_id,
        scene_id=str(scene_id or reference.get("scene_id") or ""),
        plan=plan,
        observations=outcome.get("observations") or [],
        rounds=outcome.get("rounds") or [],
        best_observation_id=str(outcome.get("best_observation_id") or ""),
        coarse_passed=coarse_ok,
    )
    evidence_store_path = out / "coarse" / "evidence_store.json"
    evidence_store.save_atomic(evidence_store_path)
    approvals: List[Dict[str, Any]] = []
    baseline: Dict[str, Any] | None = None
    if coarse_ok:
        approvals = _approve_manifest_to_frozen(final_manifest)
        baseline = freeze_coarse_baseline(
            reference=final_reference,
            manifest=final_manifest,
            report=final_report,
            approvals=approvals,
            approved_by="coarse-pipeline",
            approved_at="deterministic-replay")
        _json_dump(approvals,
                   out / "approval" / "blockout-approval.json")
        _json_dump(baseline, out / "coarse_world_baseline.json")

    phase = (PipelinePhase.COARSE_REFERENCE_READY
             if not coarse_ok
             else PipelinePhase.BASELINE_FROZEN)
    pipeline_report = {
        "schema_version": "coarse-pipeline-report/v1",
        "run_id": effective_run_id,
        "scene_id": str(scene_id or reference.get("scene_id") or ""),
        "phase": phase,
        "coarse_status": outcome["status"],
        "blocked_code": outcome.get("blocked_code") or "",
        "blocked_reason": outcome.get("blocked_reason") or "",
        "best_score": outcome.get("best_score"),
        "best_fingerprint": outcome.get("best_fingerprint"),
        "best_observation_id": outcome.get("best_observation_id"),
        "best_manifest_fingerprint": best_bundle.manifest_fingerprint,
        "best_report_fingerprint": best_bundle.report_fingerprint,
        "best_world_state_fingerprint": best_bundle.world_state_fingerprint,
        "latest_observation_id": outcome.get("latest_observation_id"),
        "latest_candidate_observation_id": outcome.get(
            "latest_candidate_observation_id"),
        "latest_candidate_reference": copy.deepcopy(
            outcome.get("latest_candidate") or {}),
        "latest_candidate_report": copy.deepcopy(
            outcome.get("latest_candidate_report") or {}),
        "observation_count": len(outcome.get("observations") or []),
        "rollback_count": int(outcome.get("rollback_count") or 0),
        "proposal_rejection_count": int(
            outcome.get("proposal_rejection_count") or 0),
        "no_gain": int(outcome.get("no_gain") or 0),
        "plan_prescriptions": list(plan_prescriptions),
        "plan_measurements": list(plan_measurements),
        "plan_findings": plan_finding_payloads,
        "rounds": [
            {"round_no": r["round_no"],
             "observation_id": r.get("observation_id"),
             "report": copy.deepcopy(r.get("report") or {}),
             "verdict": r["report"].get("verdict"),
             "findings": len(r["report"].get("findings") or []),
             "quality": r.get("quality"),
             "disposition": r.get("disposition"),
             "rollback_applied": r.get("rollback_applied"),
             "rollback": copy.deepcopy(r.get("rollback") or {}),
             "comparison": copy.deepcopy(r.get("comparison") or {}),
             "best_score": r.get("best_score"),
             "no_gain": r.get("no_gain"),
             "candidate": copy.deepcopy(r.get("candidate") or {}),
             "candidate_observation_id": r.get("candidate_observation_id"),
             "candidate_manifest_fingerprint": r.get(
                 "candidate_manifest_fingerprint"),
             "candidate_report_fingerprint": r.get(
                 "candidate_report_fingerprint"),
             "candidate_world_state_fingerprint": r.get(
                 "candidate_world_state_fingerprint"),
             "candidate_fingerprint": r.get("candidate_fingerprint"),
             "candidate_reference_repeated": bool(
                 r.get("candidate_reference_repeated")),
             "best_fingerprint": r.get("best_fingerprint"),
             "cycle_detected": r.get("cycle_detected", False),
             "provider_kind": r.get("provider_kind", ""),
             "proposal": copy.deepcopy(r.get("proposal")),
             "proposal_rejected": bool(r.get("proposal_rejected")),
             "rejection_reason": str(r.get("rejection_reason") or ""),
             "rejected_code": str(r.get("rejected_code") or ""),
             "proposal_reason": (
                 (r.get("proposal") or {}).get("reason")
                 if isinstance(r.get("proposal"), Mapping) else ""),
             "knowledge_provenance": (
                 (r.get("proposal") or {}).get("knowledge_provenance")
                 if isinstance(r.get("proposal"), Mapping) else None),
             "applied_count": r.get("applied_count", 0),
             "prescriptions": copy.deepcopy(r.get("prescriptions") or [])}
            for r in outcome["rounds"]
        ],
        "gates": {
            "coarse": "pass" if coarse_ok else "blocked",
            "baseline": ("frozen" if baseline else "missing"),
            "detail": "pending",
            "sequence": "pending",
            "final": "pending",
        },
        "artifacts": {
            "plan_after": str(plan_after_path),
            "coarse_world_reference": str(out / "coarse_world_reference.json"),
            "blockout_manifest": str(out / "blockout_manifest.json"),
            "blockout_report": str(out / "blockout_report.json"),
            "blockout_world_state": str(out / "blockout_world_state.json"),
            "best_observation": str(_observation_file(best_payload)),
            "observations": str(observations_root),
            "evidence_store": str(evidence_store_path),
            "baseline": str(out / "coarse_world_baseline.json")
            if baseline else None,
        },
    }
    _json_dump(pipeline_report, out / "coarse_pipeline_report.json")
    return pipeline_report


def _attach_plan_shots(reference: Mapping[str, Any],
                       plan: Any) -> Dict[str, Any]:
    """把 plan 的分镜语义层（shots[]）并入粗编排参考 JSON。

    build_design_snapshot 只产出空间层（characters/camera_intents），
    shots[]（镜号/时长/出场角色/动作）是处方与细排派生的必需语义层；
    参考 JSON 作为单一真源必须携带它。R2 Ticket 10（真跑
    20261019-r2-market-coin-accept-3）：`framing_target`（拍对象声明）与
    `responsibility`（含 skip_white_model 的 J3 分工）同样是粗排消费的
    语义键——`blockout_report._framing_target_checks` 从 shots 读拍对象，
    skip 豁免也要读分工声明；缺了它们，检查照发而处方/豁免无从谈起。
    """
    result = copy.deepcopy(dict(reference))
    if isinstance(plan, Mapping):
        result["shots"] = [dict(s) for s in plan.get("shots") or []]
    else:
        result["shots"] = []
        for s in getattr(plan, "shots", None) or []:
            #: 参考 JSON 是跨阶段单一真源，必须复用 ShotPlan 的完整 serde。
            #: 手工维护七键白名单已两次漏字段：R2 丢 framing_target/
            #: responsibility，细排相机重解又丢 shot_type/composition，
            #: 把 ELS 降成默认 MS（真跑构图 85.5 -> 75.3）。完整 to_dict()
            #: 让新增 ShotPlan 字段天然穿过所有下游，不再逐步打补丁。
            to_dict = getattr(s, "to_dict", None)
            if callable(to_dict):
                result["shots"].append(dict(to_dict()))
                continue
            entry = {k: getattr(s, k) for k in (
                "shot_id", "order", "intent", "shot_type", "duration_frames",
                "characters", "actions", "camera")
                if hasattr(s, k)}
            #: 非契约对象兜底时仍保证 framing_target/responsibility 恒出键。
            for key in ("framing_target", "responsibility"):
                value = getattr(s, key, None)
                if value is not None:
                    value_to_dict = getattr(value, "to_dict", None)
                    entry[key] = (value_to_dict() if callable(value_to_dict)
                                  else value)
                else:
                    entry[key] = None
            result["shots"].append(entry)
    return result


__all__ = ["CoarsePipelineAdapters", "run_coarse_pipeline"]
