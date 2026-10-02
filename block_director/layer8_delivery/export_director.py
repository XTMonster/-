"""交付编排（执行文档 v1.2 §15）。

一条命令从场景产出：分镜 mp4 + 首帧 PNG + shots.json + prompts.md
（可选相机轨迹）+ README。**导出前先做画面审计**——辅助物一旦会入画就
直接中止，而不是产出一段带文字标签的"脏"参考视频。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import bpy

from ..contracts.enums import resolution_for
from ..contracts.plan import Plan
from ..delivery.depth import depth_range_note
from ..delivery.manifest import build_manifest
from ..delivery.prompts import DEFAULT_STYLE, render_prompt_sheet
from ..layer3_engine.collection_router import (
    audit_renderable_objects,
    labels_collection,
)
from ..utils.logger import get_logger
from ..utils.threading_guard import main_thread_only
from .camera_trajectory import camera_trajectory
from .concat import ConcatUnavailable, concat_shot_clips, full_output_path
from .depth_pass import DepthUnavailable, render_depth_sequence
from .renderer import apply_delivery_settings, render_first_frame, render_shot_video

log = get_logger("delivery")


@dataclass
class DeliveryReport:
    out_dir: str = ""
    aborted: bool = False
    reason: str = ""
    files: List[str] = field(default_factory=list)
    shots: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    total_frames: int = 0
    duration_s: float = 0.0
    audit_leaks: List[str] = field(default_factory=list)
    depth_shots: List[Dict[str, Any]] = field(default_factory=list)
    full_video: str = ""
    total_frames_concat: int = 0
    #: 声明要产出却没落盘的文件（视频 / 首帧）。v1.2 没有这个字段，
    #: 于是"六段视频一个都没生成"也会因为 shots.json 等元数据文件写成功
    #: 而报 ok=True——调用方据此判定成功，用户拿到的却是一个空交付包。
    missing_clips: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        if self.aborted or not self.files:
            return False
        return not self.missing_clips

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok, "aborted": self.aborted, "reason": self.reason,
            "out_dir": self.out_dir, "files": list(self.files),
            "shots": list(self.shots), "warnings": list(self.warnings),
            "total_frames": self.total_frames,
            "duration_s": round(self.duration_s, 2),
            "audit_leaks": list(self.audit_leaks),
            "depth_shots": list(self.depth_shots),
            "full_video": self.full_video,
            "total_frames_concat": self.total_frames_concat,
            "missing_clips": list(self.missing_clips),
        }


def _shot_ranges(plan: Plan,
                 build_summary: Optional[Dict[str, Any]]
                 ) -> List[Dict[str, Any]]:
    results = {r.get("shot_id"): r for r in
               (build_summary or {}).get("results", [])}
    ranges: List[Dict[str, Any]] = []
    cursor = 1
    for shot in plan.shots:
        result = results.get(shot.shot_id, {})
        start = int(result.get("start_frame", cursor))
        end = int(result.get("end_frame", start + shot.duration_frames - 1))
        ranges.append({"shot_id": shot.shot_id, "start_frame": start,
                       "end_frame": end,
                       "camera": result.get("camera", f"BD_Cam_{shot.shot_id}")})
        cursor = end + 1
    return ranges


def _readme(manifest: Dict[str, Any], report: DeliveryReport) -> str:
    width, height = manifest["resolution"]
    lines = [
        f"# {manifest['project']} — 白模预演交付包",
        "",
        f"- 分辨率：{width}×{height} @ {manifest['fps']}fps",
        f"- 镜头数：{len(manifest['shots'])}，总时长 "
        f"{round(manifest['total_frames'] / manifest['fps'], 2)} 秒",
        f"- 生成时间：{manifest['generated_at']}",
        "",
        "## 怎么用",
        "",
        "1. 取 `blockout_<shot>.mp4` 作为**参考视频**（结构 / 机位 / 节奏）；",
        "2. 取 `first_frames/<shot>.png` 作为**输入图**（图生视频）；",
        "3. 取 `prompts.md` 里对应镜头的 Prompt 作为**提示词**。",
        "",
        "> 参考视频里带白字黑描边的角色标签，便于审阅；"
        "`first_frames/` 与 depth 序列**刻意不带标签**，"
        "避免标签被下游视频模型当成画面内容学走。",
        "",
    ]
    if os.path.exists(os.path.join(report.out_dir, "camera_traj.json")):
        lines.insert(-1, "4. `camera_traj.json` 提供逐帧相机内外参，"
                         "可喂给相机可控的视频生成模型。")
        lines.append("")
    if os.path.exists(os.path.join(report.out_dir, "blockout_full.mp4")):
        lines.insert(-1, "5. `blockout_full.mp4` 是各镜按顺序接成的全片，"
                         "适合一次性喂给视频模型。")
        lines.append("")
    if any(name.startswith("depth_shot_") for name in
           os.listdir(report.out_dir) if os.path.isdir(
               os.path.join(report.out_dir, name))):
        lines.append("## 深度序列")
        lines.append("")
        lines.append(depth_range_note())
        lines.append("")
    if report.warnings:
        lines.append("## 告警")
        lines.append("")
        lines.extend(f"- {w}" for w in report.warnings)
        lines.append("")
    return "\n".join(lines)


@main_thread_only("export_project")
def export_project(plan: Plan, *,
                   build_summary: Optional[Dict[str, Any]] = None,
                   out_dir: Path,
                   config,
                   style: str = DEFAULT_STYLE,
                   compliance: Optional[Dict[str, Any]] = None,
                   project: str = "BlockDirector",
                   llm_calls: int = 0,
                   retrieval_calls: int = 0,
                   crowd: Optional[Sequence[Dict[str, Any]]] = None,
                   parsed=None,
                   timing_overrides: Optional[Sequence[Dict[str, Any]]] = None,
                   action_conflicts: Optional[Sequence[Dict[str, Any]]] = None,
                   audit_pass_rate: Optional[Dict[str, Any]] = None,
                   knowledge_provenance: Optional[Dict[str, Any]] = None,
                   knowledge: Optional[Dict[str, Any]] = None
                   ) -> DeliveryReport:
    """导出完整交付包。画面审计不通过则中止。"""
    started = time.perf_counter()
    scene = bpy.context.scene
    # 绝对化：Blender 内 ``bpy.path.abspath("//")`` 在未保存 .blend 时为空串，
    # 相对路径的渲染产物不会落在进程工作目录（实测跑到 C:\runs\...）。
    # 交付层自己做这道防线，不依赖每个调用方都记得传绝对路径。
    out_dir = Path(os.path.abspath(str(out_dir)))
    export_dir = out_dir / "export"
    frames_dir = export_dir / "first_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    report = DeliveryReport(out_dir=str(export_dir))

    leaks = audit_renderable_objects()
    if leaks:
        report.aborted = True
        report.audit_leaks = list(leaks)
        report.reason = ("导出中止：以下对象会出现在参考视频中："
                         + "、".join(leaks))
        log.error(report.reason)
        return report

    report.warnings.extend(apply_delivery_settings(scene, config))

    width, height = resolution_for(config.preset)
    ranges = _shot_ranges(plan, build_summary)
    original_range = (scene.frame_start, scene.frame_end)

    for shot in ranges:
        shot_id = shot["shot_id"]
        video_base = str(export_dir / f"blockout_{shot_id}.mp4")
        shot_frames = int(shot["end_frame"]) - int(shot["start_frame"]) + 1
        if config.per_shot_clips:
            # 参考视频**带**角色标签（v1.3 诉求 4）
            path, frames = render_shot_video(
                scene, shot["start_frame"], shot["end_frame"], video_base,
                codec=str(config.video_codec), crf=str(config.crf))
            if os.path.exists(path):
                report.files.append(path)
            else:
                report.warnings.append(f"{shot_id}: 视频未生成（{path}）")
                report.missing_clips.append(path)
            report.total_frames += frames

        # 首帧 PNG 与 depth 序列**不带**标签：它们是喂给下游视频模型的输入图，
        # 把标签烫进去会被模型当成画面内容学走。
        labels = labels_collection()
        if labels is not None:
            labels.hide_render = True
        try:
            frame_path = str(frames_dir / f"{shot_id}.png")
            if render_first_frame(scene, shot["start_frame"], frame_path):
                report.files.append(frame_path)
            else:
                report.warnings.append(f"{shot_id}: 首帧未生成")
                report.missing_clips.append(frame_path)

            report.shots.append({"shot_id": shot_id,
                                 "start_frame": shot["start_frame"],
                                 "end_frame": shot["end_frame"],
                                 "video": f"blockout_{shot_id}.mp4"
                                          if config.per_shot_clips else None})
            if config.export_depth:
                try:
                    depth = render_depth_sequence(scene, shot["start_frame"],
                                                  shot["end_frame"],
                                                  str(export_dir), shot_id)
                    report.files.extend(depth["files"][:1])   # 清单里留一个代表
                    report.shots[-1]["depth"] = depth_range_note()
                    report.shots[-1]["depth_frames"] = depth["frames"]
                    report.depth_shots.append(
                        {"shot_id": shot_id,
                         "dir": str(Path(depth["dir"]).relative_to(export_dir)),
                         "frames": depth["frames"],
                         "range_m": depth["range_m"]})
                except DepthUnavailable as exc:
                    report.warnings.append(f"{shot_id}: depth 导出跳过（{exc}）")
        finally:
            if labels is not None:
                labels.hide_render = False
        log.info("已导出镜头 %s（%d-%d）", shot_id,
                 shot["start_frame"], shot["end_frame"])

    if config.full_concat and config.per_shot_clips:
        clips = [str(export_dir / f"blockout_{shot['shot_id']}.mp4")
                 for shot in ranges]
        clip_frames = [int(shot["end_frame"]) - int(shot["start_frame"]) + 1
                       for shot in ranges]
        try:
            concat = concat_shot_clips(
                scene, clips, full_output_path(export_dir),
                clip_frames=clip_frames,
                preset=str(config.preset), fps=24,
                codec=str(config.video_codec), crf=str(config.crf))
            if concat["ok"]:
                report.files.append(concat["path"])
                report.full_video = concat["path"]
                report.total_frames_concat = concat["frames"]
            else:
                report.warnings.append(f"全片拼接未产出文件（{concat['path']}）")
                report.missing_clips.append(concat["path"])
            if concat["skipped"]:
                report.warnings.append(
                    "以下分镜视频不存在，未参与拼接："
                    + "、".join(concat["skipped"]))
        except ConcatUnavailable as exc:
            report.warnings.append(f"全片拼接跳过（{exc}）")

    manifest = build_manifest(plan, build_summary=build_summary,
                              resolution=(width, height), style=style,
                              project=project, llm_calls=llm_calls,
                              retrieval_calls=retrieval_calls, crowd=crowd,
                              parsed=parsed,
                              timing_overrides=timing_overrides,
                              action_conflicts=action_conflicts,
                              audit_pass_rate=audit_pass_rate,
                              knowledge_provenance=knowledge_provenance,
                              knowledge=knowledge)
    manifest_path = export_dir / "shots.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    report.files.append(str(manifest_path))

    prompt_path = export_dir / "prompts.md"
    prompt_path.write_text(render_prompt_sheet(plan, style=style,
                                               resolution=(width, height),
                                               project=project),
                           encoding="utf-8")
    report.files.append(str(prompt_path))

    if config.export_camera_traj:
        trajectory = camera_trajectory(scene, ranges)
        trajectory_path = export_dir / "camera_traj.json"
        trajectory_path.write_text(
            json.dumps(trajectory, ensure_ascii=False, indent=2), encoding="utf-8")
        report.files.append(str(trajectory_path))

    if compliance is not None:
        # 剧本落实对照表（v1.3 R015/R016）：声明 → 落实 → 偏差。
        # 它让"AI 有没有照剧本做"成为可核对的事实，而不是只能靠人看片。
        compliance_path = export_dir / "script_compliance.json"
        compliance_path.write_text(
            json.dumps(compliance, ensure_ascii=False, indent=2),
            encoding="utf-8")
        report.files.append(str(compliance_path))
        if not compliance.get("ok", True):
            errors = [item for item in compliance.get("findings", [])
                      if str(item.get("severity")) == "error"]
            report.warnings.append(
                f"剧本落实审核发现 {len(errors)} 项偏差，详见 script_compliance.json")

    scene.frame_start, scene.frame_end = original_range
    report.duration_s = time.perf_counter() - started

    readme_path = export_dir / "README.md"
    readme_path.write_text(_readme(manifest, report), encoding="utf-8")
    report.files.append(str(readme_path))

    log.info("交付完成：%d 个文件，用时 %.1fs", len(report.files), report.duration_s)
    return report
