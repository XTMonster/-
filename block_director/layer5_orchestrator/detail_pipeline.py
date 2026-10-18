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
from typing import Any, Dict, List, Mapping, Optional

from block_director.cinema.detail_blocking import derive_detail_shots
from block_director.cinema.detail_review import detail_review_verdict
from block_director.cinema.pipeline_gates import (
    PipelinePhase,
    final_gate,
)


def _json_dump(obj: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def run_detail_pipeline(
    *,
    baseline: Mapping[str, Any],
    plan: Any,
    out_dir: Path | str,
    render_video: bool = True,
    fps: int = 24,
) -> Dict[str, Any]:
    """跑细排阶段，返回 pipeline_report（gates 含 final 判定）。

    ``baseline`` 必须是 ``freeze_coarse_baseline`` 产物（含 reference/manifest/
    approval/fingerprints）；细排派生与审核全部基于它。
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    #: 1) 从冻结基准派生逐镜细排数据
    detail_shots = derive_detail_shots(baseline=baseline, plan=plan)
    _json_dump(detail_shots, out / "detail_shots.json")

    #: 2) 逐镜细排：继承冻结坐标，按 DetailShotContract 构建关键帧语义
    #:    （bpy 延迟导入；细排构建复用 scene_executor/shot_builder 的语义，
    #:    不重建空间，只落地动作/姿态/道具/节拍的帧段代理）。
    from block_director.layer3_engine.blockout_scene import (
        build_blockout_scene,
    )
    manifest = baseline.get("manifest") or {}
    build_blockout_scene(manifest, clear_scene=True)
    _apply_detail_beats(detail_shots, manifest)

    #: 3) 逐镜审核：只测纯层证据（漂移 + 粗排硬伤 + 构图可测）
    blockout_report = baseline.get("report") or {}
    review = detail_review_verdict(detail_shots=detail_shots,
                                   blockout_report=blockout_report,
                                   baseline=baseline)
    _json_dump(review, out / "detail_review.json")

    #: 4) 全片回放：序列审查（语义检查沿用既有纯层判据）
    from block_director.layer8_delivery.blockout_sequence import (
        run_blockout_sequence_review,
    )
    sequence = run_blockout_sequence_review(manifest, out,
                                            render_video=False)
    sequence_verdict = str(sequence["review"].get("verdict") or "fail")
    _json_dump(sequence["review"], out / "sequence_review.json")

    #: 5) final gate
    detail_ok = dict(review["per_shot"]) if review["all_ok"] else {
        k: v["ok"] for k, v in review["per_shot"].items()}
    gate = final_gate(
        coarse_pass=True,
        baseline_frozen=str((baseline or {}).get("state")) == "frozen",
        detail_results=detail_ok,
        sequence_verdict=sequence_verdict,
    )

    video: Dict[str, Any] = {"rendered": False, "final": False}
    if gate["passed"] and render_video:
        seq2 = run_blockout_sequence_review(manifest, out,
                                            render_video=True)
        video = {
            "rendered": True,
            "final": True,
            "full_path": str(seq2["video"].get("full_path") or ""),
            "shot_videos": seq2["video"].get("shot_videos") or [],
        }
        #: final 视频别名：最终交付物固定名
        full = seq2["video"].get("full_path")
        if full:
            import shutil
            shutil.copyfile(Path(full), out / "final_video.mp4")
            video["final_path"] = str(out / "final_video.mp4")

    report = {
        "schema_version": "detail-pipeline-report/v1",
        "phase": PipelinePhase.FINAL_EXPORTED if gate["passed"] and video[
            "final"] else PipelinePhase.SEQUENCE_REVIEWED,
        "gates": {
            "coarse": "pass",
            "baseline": "frozen",
            "detail": "pass" if review["all_ok"] else "blocked",
            "sequence": sequence_verdict,
            "final": "pass" if gate["passed"] else "blocked",
        },
        "detail_review": review,
        "sequence_verdict": sequence_verdict,
        "final": bool(video.get("final", False)),
        "video": video,
        "artifacts": {
            "detail_shots": str(out / "detail_shots.json"),
            "detail_review": str(out / "detail_review.json"),
            "sequence_review": str(out / "sequence_review.json"),
            "final_video": str(out / "final_video.mp4")
            if video.get("final") else None,
        },
    }
    _json_dump(report, out / "detail_pipeline_report.json")
    return report


def _apply_detail_beats(detail_shots: List[Mapping[str, Any]],
                        manifest: Mapping[str, Any]) -> None:
    """把 DetailShotContract 的节拍落到 Blender 帧段（代理语义）。

    逐镜细排在该阶段主要指动作/道具/姿态节拍的帧段占位与相机关键帧叠加；
    真正最终动画仍由下游生成。当前只在场景里按节拍标记帧 marker。
    """
    import bpy

    for shot in detail_shots:
        shot_id = str(shot.get("shot_id") or "")
        marker = f"BD_DetailBeat_{shot_id}"
        for beat in shot.get("beats") or []:
            frame = int(beat.get("frame") or 1)
            bpy.context.scene.timeline_markers.new(marker, frame=frame)


__all__ = ["run_detail_pipeline"]
