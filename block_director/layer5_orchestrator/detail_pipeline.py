"""白模预演完整流程：细排编排器（Ticket 06，bpy 侧）。

从冻结粗排基准派生 DetailShotContract -> 在既有关键帧语义上落实逐镜节拍 ->
逐镜审核（空间漂移/粗排硬伤 error -> 阻塞；构图软指标记录 warning）-> 全片
回放（序列审查，语义检查沿用既有纯层判据）-> final gate 通过才导出
``final_video.mp4``；fail 只产出诊断产物并标记 ``final:false``。

细排不重建独立世界坐标：任何全局空间改动被 ``spatial_drift_review`` 阻塞，
必须退回粗排审批。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

from block_director.cinema.detail_blocking import derive_detail_shots
from block_director.cinema.detail_loop import run_detail_revision_loop
from block_director.cinema.detail_review import detail_review_verdict
from block_director.cinema.pipeline_gates import (
    PipelinePhase,
    coarse_gate,
    final_gate,
)


def _json_dump(obj: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def _default_session_factory(**kwargs: Any) -> Any:
    from block_director.layer3_engine.detail_session import DetailSceneSession

    values = dict(kwargs)
    transport = values.pop("transport", None)
    values.pop("knowledge", None)
    return DetailSceneSession(**values, vlm_transport=transport)


def run_detail_pipeline(
    *,
    baseline: Mapping[str, Any],
    plan: Any,
    out_dir: Path | str,
    render_video: bool = True,
    fps: int = 24,
    runtime_world_state: Mapping[str, Any] | None = None,
    session: Any = None,
    transport: Any = None,
    knowledge: Any = None,
    proposal_provider: Callable[..., Mapping[str, Any] | None] | None = None,
    proposal_max_tokens: int = 12000,
    session_factory: Callable[..., Any] | None = None,
    run_id: str = "",
    scene_id: str = "",
    max_revisions: int = 5,
    no_gain_limit: int = 3,
    knowledge_context: str = "",
) -> Dict[str, Any]:
    """跑细排阶段，返回 pipeline_report（gates 含 final 判定）。

    ``baseline`` 必须是 ``freeze_coarse_baseline`` 产物（含 reference/manifest/
    approval/fingerprints）；细排派生与审核全部基于它。
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    coarse = coarse_gate(dict(baseline.get("report") or {}))
    baseline_frozen = str(baseline.get("state") or "") == "frozen"

    #: 1) 从冻结基准派生逐镜细排数据
    detail_shots = derive_detail_shots(baseline=baseline, plan=plan)
    _json_dump(detail_shots, out / "detail_shots.json")

    if session is None and (session_factory is not None or transport is not None):
        provider = proposal_provider
        if provider is None and transport is not None:
            from .coarse_agent import make_coarse_proposal_provider

            provider = make_coarse_proposal_provider(
                transport=transport,
                knowledge=knowledge,
                max_tokens=int(proposal_max_tokens),
                stage="detail",
            )
        reference = dict(baseline.get("reference") or {})
        effective_run_id = str(run_id or out.name or "detail-run")
        effective_scene_id = str(
            scene_id
            or reference.get("scene_id")
            or getattr(plan, "scene_heading", "")
            or "blockdirector_scene")
        factory = session_factory or _default_session_factory
        session = factory(
            baseline=baseline,
            plan=plan,
            out_dir=out,
            run_id=effective_run_id,
            scene_id=effective_scene_id,
            proposal_provider=provider,
            transport=transport,
            knowledge=knowledge,
        )

    if session is not None:
        session.prepare()
        outcome = run_detail_revision_loop(
            detail_shots=detail_shots,
            reference=session.reference,
            observe=session.observe,
            rebuild=session.apply,
            restore_best=session.restore,
            proposal_provider=getattr(session, "proposal_provider", None),
            sequence_review=session.review_sequence,
            record_evidence=session.record_evidence,
            max_revisions=int(max_revisions),
            no_gain_limit=int(no_gain_limit),
            knowledge_context=str(knowledge_context or ""),
        )
        _json_dump(outcome, out / "detail_loop.json")
        detail_ok = {
            str(shot_id): value.get("status") == "passed"
            for shot_id, value in (outcome.get("shots") or {}).items()
        }
        review = {
            "per_shot": {
                shot_id: {
                    "ok": passed,
                    "status": (
                        (outcome.get("shots") or {}).get(shot_id) or {}
                    ).get("status"),
                    "blocked_code": (
                        (outcome.get("shots") or {}).get(shot_id) or {}
                    ).get("blocked_code", ""),
                    "best_score": (
                        (outcome.get("shots") or {}).get(shot_id) or {}
                    ).get("best_score"),
                }
                for shot_id, passed in detail_ok.items()
            },
            "all_ok": bool(detail_ok) and all(detail_ok.values()),
            "reasons": [
                f"{shot_id}：{value.get('blocked_reason') or value.get('status')}"
                for shot_id, value in (outcome.get("shots") or {}).items()
                if value.get("status") != "passed"
            ],
        }
        _json_dump(review, out / "detail_review.json")
        sequence_review = dict(outcome.get("sequence_review") or {})
        sequence_verdict = str(
            sequence_review.get("verdict") or "blocked")
        _json_dump(sequence_review, out / "sequence_review.json")
        gate = final_gate(
            coarse_pass=bool(coarse["passed"]),
            baseline_frozen=baseline_frozen,
            detail_results=detail_ok,
            sequence_verdict=sequence_verdict,
        )
        session_manifest = getattr(session, "manifest", {}) or {}
        retained_manifest_path = out / "detail_retained_manifest.json"
        final_manifest_path = out / "detail_final_manifest.json"
        retained_reference_path = out / "detail_retained_reference.json"
        final_reference_path = out / "detail_final_reference.json"
        _json_dump(session_manifest, retained_manifest_path)
        _json_dump(session.reference, retained_reference_path)
        if gate["passed"]:
            _json_dump(session_manifest, final_manifest_path)
            _json_dump(session.reference, final_reference_path)
        else:
            final_manifest_path.unlink(missing_ok=True)
            final_reference_path.unlink(missing_ok=True)
        video: Dict[str, Any] = {
            "rendered": False,
            "final": False,
            "partial": False,
            "diagnostic": False,
            "failed_shots": [
                shot_id for shot_id, passed in detail_ok.items()
                if not passed
            ],
        }
        if render_video:
            from block_director.layer8_delivery.blockout_sequence import (
                render_blockout_sequence_video,
            )

            passed_ids = [
                shot_id for shot_id, passed in detail_ok.items() if passed
            ]
            failed_ids = [
                shot_id for shot_id, passed in detail_ok.items() if not passed
            ]
            if gate["passed"]:
                rendered = render_blockout_sequence_video(
                    session_manifest,
                    out / "final_delivery",
                    fps=int(fps),
                )
                source = Path(str(rendered.get("full_path") or ""))
                if not source.is_file():
                    raise FileNotFoundError(
                        f"final render did not produce a video: {source}")
                final_path = out / "final_video.mp4"
                import shutil

                shutil.copyfile(source, final_path)
                video = {
                    "rendered": True,
                    "final": True,
                    "partial": False,
                    "diagnostic": False,
                    "full_path": str(final_path),
                    "final_path": str(final_path),
                    "shot_videos": rendered.get("shot_videos") or [],
                    "failed_shots": [],
                }
            elif passed_ids:
                rendered = render_blockout_sequence_video(
                    session_manifest,
                    out / "partial_delivery",
                    fps=int(fps),
                    shot_ids=passed_ids,
                )
                path = str(rendered.get("full_path") or "")
                video = {
                    "rendered": True,
                    "final": False,
                    "partial": False,
                    "diagnostic": True,
                    "full_path": path,
                    "partial_path": path,
                    "shot_videos": rendered.get("shot_videos") or [],
                    "failed_shots": failed_ids,
                }
            else:
                rendered = render_blockout_sequence_video(
                    session_manifest,
                    out / "diagnostic_delivery",
                    fps=int(fps),
                )
                video = {
                    "rendered": True,
                    "final": False,
                    "partial": False,
                    "diagnostic": True,
                    "full_path": str(rendered.get("full_path") or ""),
                    "shot_videos": rendered.get("shot_videos") or [],
                    "failed_shots": failed_ids,
                }
        report = {
            "schema_version": "detail-pipeline-report/v1",
            "phase": (
                PipelinePhase.FINAL_EXPORTED
                if gate["passed"] and video["final"]
                else PipelinePhase.SEQUENCE_REVIEWED
            ),
            "gates": {
                "coarse": "pass" if coarse["passed"] else "blocked",
                "baseline": "frozen" if baseline_frozen else "unfrozen",
                "detail": "pass" if review["all_ok"] else "blocked",
                "sequence": sequence_verdict,
                "final": "pass" if gate["passed"] else "blocked",
            },
            "detail_review": review,
            "detail_loop": outcome,
            "sequence_verdict": sequence_verdict,
            "final": bool(video.get("final", False)),
            "video": video,
            "artifacts": {
                "detail_shots": str(out / "detail_shots.json"),
                "detail_manifest": str(retained_manifest_path),
                "detail_reference": str(retained_reference_path),
                "detail_final_manifest": (
                    str(final_manifest_path) if gate["passed"] else None),
                "detail_final_reference": (
                    str(final_reference_path) if gate["passed"] else None),
                "detail_review": str(out / "detail_review.json"),
                "detail_loop": str(out / "detail_loop.json"),
                "sequence_review": str(out / "sequence_review.json"),
                "final_video": (
                    str(out / "final_video.mp4")
                    if video.get("final") else None),
                "partial_video": (
                    video.get("partial_path")
                    if video.get("partial") else None),
                "diagnostic_video": (
                    video.get("full_path")
                    if video.get("diagnostic") else None),
                "failed_shots": list(video.get("failed_shots") or []),
            },
        }
        _json_dump(report, out / "detail_pipeline_report.json")
        return report

    #: 2) 逐镜细排：继承冻结坐标，按 DetailShotContract 构建关键帧语义
    #:    （bpy 延迟导入；细排构建复用 scene_executor/shot_builder 的语义，
    #:    不重建空间，只落地动作/姿态/道具/节拍的帧段代理）。
    from block_director.layer3_engine.blockout_scene import (
        build_blockout_scene,
    )
    try:
        from block_director.layer3_engine.blockout_scene import (
            ensure_blockout_scene,
        )
    except ImportError:
        ensure_blockout_scene = build_blockout_scene
    manifest = baseline.get("manifest") or {}
    scene_build = ensure_blockout_scene(manifest, clear_scene=True)
    from block_director.layer3_engine.detail_scene import apply_detail_beats
    apply_detail_beats(detail_shots, manifest)

    #: 统一构图尺子（两把尺子断裂修复）：粗排 preview 已改为按被摄局部
    #: 主体 + 景别窗口评分，细排 gate 必须用**同一把尺子**重测冻结空间
    #: 的构图，而不是沿用冻结 baseline 里整身框时代的旧 composition
    #: （55–58 分 -> 细排永远 blocked）。只重测构图 check，空间不漂移、
    #: 不重新判粗排硬伤。
    from block_director.layer8_delivery.blockout_preview import (
        refresh_blockout_composition,
    )
    refresh_result = refresh_blockout_composition(
        baseline=baseline, out_dir=out / "detail_composition_refresh",
        expected=plan, reference_json=baseline.get("reference"),
        runtime_world_state=runtime_world_state, return_manifest=True)
    if isinstance(refresh_result, Mapping) \
            and isinstance(refresh_result.get("report"), Mapping):
        blockout_report = refresh_result["report"]
        refreshed_manifest = refresh_result.get("manifest") or manifest
        refreshed_reference = refresh_result.get("reference")
        refreshed_world_state = refresh_result.get("observed_world_state")
        refreshed_previews = list(refresh_result.get("previews") or [])
    else:
        #: 兼容测试/嵌入方提供的旧单返回值边界；生产实现始终返回信封。
        blockout_report = refresh_result
        refreshed_manifest = manifest
        refreshed_reference = baseline.get("reference")
        refreshed_world_state = {}
        refreshed_previews = []
    retained_manifest_path = out / "detail_retained_manifest.json"
    final_manifest_path = out / "detail_final_manifest.json"
    retained_reference_path = out / "detail_retained_reference.json"
    final_reference_path = out / "detail_final_reference.json"
    _json_dump(refreshed_manifest, retained_manifest_path)
    if refreshed_reference is not None:
        _json_dump(refreshed_reference, retained_reference_path)

    #: 3) 逐镜审核：只测纯层证据（漂移 + 粗排硬伤 + 构图可测）
    review = detail_review_verdict(detail_shots=detail_shots,
                                   blockout_report=blockout_report,
                                   baseline=baseline,
                                   plan=plan)

    #: 细排质量循环的纯层入口。无物理 session 时，测量信封本身作为第一轮
    #: observation；没有 Agent provider 的失败镜必须具名停在 proposal seam，
    #: 不能退回“一次审核后直接交付”的旧路径。
    def observe_measured(reference, shot_id):
        shot_previews = [
            item for item in refreshed_previews
            if isinstance(item, Mapping)
            and str(item.get("shot_id") or "") == str(shot_id)
        ]
        return {
            "observation_id": "",
            "complete": True,
            "errors": [],
            "reference": refreshed_reference or reference,
            "manifest": refreshed_manifest,
            "report": blockout_report,
            "world_state": refreshed_world_state or {},
            "frames": shot_previews,
        }

    detail_loop = run_detail_revision_loop(
        detail_shots=detail_shots,
        reference=refreshed_reference or baseline.get("reference") or {},
        observe=observe_measured,
        rebuild=lambda _reference, _shot_id: None,
        restore_best=lambda _reference, _shot_id: None,
        proposal_provider=None,
    )
    loop_shots = detail_loop.get("shots") or {}
    if loop_shots:
        detail_ok = {
            str(shot_id): value.get("status") == "passed"
            for shot_id, value in loop_shots.items()
        }
        per_shot = review.setdefault("per_shot", {})
        for shot_id, value in loop_shots.items():
            row = per_shot.setdefault(str(shot_id), {})
            row.update({
                "ok": value.get("status") == "passed",
                "status": value.get("status"),
                "blocked_code": value.get("blocked_code", ""),
                "best_score": value.get("best_score"),
            })
        review["all_ok"] = bool(detail_ok) and all(detail_ok.values())
        review["reasons"] = [
            f"{shot_id}：{value.get('blocked_reason') or value.get('status')}"
            for shot_id, value in loop_shots.items()
            if value.get("status") != "passed"
        ]
        if detail_loop.get("status") != "approved":
            review["all_ok"] = False
            review["blocked_code"] = "agent_detail_session_required"
            review["blocked_reason"] = (
                "measurement-only detail execution cannot approve a "
                "sequence or publish final; a live Agent-backed "
                "DetailSceneSession is required")
            review["reasons"].append(review["blocked_reason"])
    else:
        detail_ok = {}
        review["all_ok"] = False
    _json_dump(review, out / "detail_review.json")
    _json_dump(detail_loop, out / "detail_loop.json")

    #: 4) 全片回放：序列审查（语义检查沿用既有纯层判据）
    from block_director.layer8_delivery.blockout_sequence import (
        run_blockout_sequence_review,
    )
    if review["all_ok"]:
        sequence = run_blockout_sequence_review(refreshed_manifest, out,
                                                render_video=False)
        sequence_verdict = str(sequence["review"].get("verdict") or "fail")
    else:
        sequence_verdict = "blocked"
        sequence = {
            "review": {
                "verdict": "blocked",
                "blocked_code": "detail_gate_blocked",
                "blocked_reason": (
                    "sequence review requires every non-empty shot to pass"),
                "findings": [],
            },
            "video": {"rendered": False},
        }
    _json_dump(sequence["review"], out / "sequence_review.json")

    #: 5) final gate
    gate = final_gate(
        coarse_pass=bool(coarse["passed"]),
        baseline_frozen=baseline_frozen,
        detail_results=detail_ok,
        sequence_verdict=sequence_verdict,
    )
    if gate["passed"]:
        _json_dump(refreshed_manifest, final_manifest_path)
        if refreshed_reference is not None:
            _json_dump(refreshed_reference, final_reference_path)
    else:
        final_manifest_path.unlink(missing_ok=True)
        final_reference_path.unlink(missing_ok=True)

    video: Dict[str, Any] = {"rendered": False, "final": False,
                             "partial": False, "failed_shots": []}
    if render_video:
        #: 失败镜不停止整条交付链：只渲染逐镜审核已通过的镜头，并把失败
        #: 镜号显式写入失败清单；绝不把失败镜伪装成 final 通过镜。
        per_shot = review.get("per_shot") or {}
        passed_ids = [str(shot_id) for shot_id, value in per_shot.items()
                      if isinstance(value, Mapping) and bool(value.get("ok"))]
        failed_ids = [str(shot_id) for shot_id, value in per_shot.items()
                      if not (isinstance(value, Mapping)
                              and bool(value.get("ok")))]
        if passed_ids:
            seq2 = run_blockout_sequence_review(
                refreshed_manifest, out, render_video=not failed_ids)
            #: 若存在失败镜，重新生成一个只包含通过镜的交付片段；否则
            #: 既有全量路径即为 final。render_blockout_sequence_video 的
            #: shot_ids 过滤保持 manifest 顺序与帧范围不变。
            if failed_ids:
                from block_director.layer8_delivery.blockout_sequence import (
                    render_blockout_sequence_video,
                )
                partial_dir = out / "partial_delivery"
                partial = render_blockout_sequence_video(
                    refreshed_manifest, partial_dir, fps=fps,
                    shot_ids=passed_ids)
                video = {
                    "rendered": True,
                    "final": False,
                    "partial": True,
                    "full_path": str(partial.get("full_path") or ""),
                    "partial_path": str(partial.get("full_path") or ""),
                    "shot_videos": partial.get("shot_videos") or [],
                    "failed_shots": failed_ids,
                }
            else:
                final_allowed = bool(gate["passed"])
                video = {
                    "rendered": True,
                    "final": final_allowed,
                    "partial": not final_allowed,
                    "diagnostic": not final_allowed,
                    "full_path": str(seq2["video"].get("full_path") or ""),
                    "shot_videos": seq2["video"].get("shot_videos") or [],
                    "failed_shots": [],
                }
                if not final_allowed:
                    video["partial_path"] = video["full_path"]
                else:
                    #: final 视频别名：最终交付物固定名
                    full = seq2["video"].get("full_path")
                    if full:
                        import shutil
                        shutil.copyfile(Path(full), out / "final_video.mp4")
                        video["final_path"] = str(out / "final_video.mp4")
        else:
            #: 全镜未过时仍生成诊断白模视频（不称 final、不降低门槛），让
            #: 用户可以审看失败镜的实际画面并继续回溯；失败清单保持完整。
            from block_director.layer8_delivery.blockout_sequence import (
                render_blockout_sequence_video,
            )
            diagnostic = render_blockout_sequence_video(
                refreshed_manifest, out / "diagnostic_delivery", fps=fps)
            video = {
                "rendered": True,
                "final": False,
                "partial": True,
                "diagnostic": True,
                "full_path": str(diagnostic.get("full_path") or ""),
                "partial_path": str(diagnostic.get("full_path") or ""),
                "shot_videos": diagnostic.get("shot_videos") or [],
                "failed_shots": failed_ids,
            }

    report = {
        "schema_version": "detail-pipeline-report/v1",
        "phase": PipelinePhase.FINAL_EXPORTED if gate["passed"] and video[
            "final"] else PipelinePhase.SEQUENCE_REVIEWED,
        "gates": {
            "coarse": "pass" if coarse["passed"] else "blocked",
            "baseline": "frozen" if baseline_frozen else "unfrozen",
            "detail": "pass" if review["all_ok"] else "blocked",
            "sequence": sequence_verdict,
            "final": "pass" if gate["passed"] else "blocked",
        },
        "detail_review": review,
        "detail_loop": detail_loop,
        "sequence_verdict": sequence_verdict,
        "final": bool(video.get("final", False)),
        "video": video,
        "artifacts": {
            "detail_shots": str(out / "detail_shots.json"),
            "detail_manifest": str(retained_manifest_path),
            "detail_reference": (
                str(retained_reference_path)
                if refreshed_reference is not None else None),
            "detail_final_manifest": (
                str(final_manifest_path) if gate["passed"] else None),
            "detail_final_reference": (
                str(final_reference_path)
                if gate["passed"] and refreshed_reference is not None
                else None),
            "detail_review": str(out / "detail_review.json"),
            "detail_loop": str(out / "detail_loop.json"),
            "sequence_review": str(out / "sequence_review.json"),
            "final_video": str(out / "final_video.mp4")
            if video.get("final") else None,
            "partial_video": video.get("partial_path")
            if video.get("partial") else None,
            "failed_shots": list(video.get("failed_shots") or []),
            "scene_build": scene_build,
        },
    }
    _json_dump(report, out / "detail_pipeline_report.json")
    return report

__all__ = ["run_detail_pipeline"]
