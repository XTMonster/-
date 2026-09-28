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
from ..delivery.manifest import build_manifest
from ..delivery.prompts import DEFAULT_STYLE, render_prompt_sheet
from ..layer3_engine.collection_router import audit_renderable_objects
from ..utils.logger import get_logger
from ..utils.threading_guard import main_thread_only
from .camera_trajectory import camera_trajectory
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

    @property
    def ok(self) -> bool:
        return not self.aborted and bool(self.files)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok, "aborted": self.aborted, "reason": self.reason,
            "out_dir": self.out_dir, "files": list(self.files),
            "shots": list(self.shots), "warnings": list(self.warnings),
            "total_frames": self.total_frames,
            "duration_s": round(self.duration_s, 2),
            "audit_leaks": list(self.audit_leaks),
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
    ]
    if os.path.exists(os.path.join(report.out_dir, "camera_traj.json")):
        lines.insert(-1, "4. `camera_traj.json` 提供逐帧相机内外参，"
                         "可喂给相机可控的视频生成模型。")
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
                   project: str = "BlockDirector") -> DeliveryReport:
    """导出完整交付包。画面审计不通过则中止。"""
    started = time.perf_counter()
    scene = bpy.context.scene
    out_dir = Path(out_dir)
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
        if config.per_shot_clips:
            path, frames = render_shot_video(
                scene, shot["start_frame"], shot["end_frame"], video_base,
                codec=str(config.video_codec), crf=str(config.crf))
            if os.path.exists(path):
                report.files.append(path)
            else:
                report.warnings.append(f"{shot_id}: 视频未生成（{path}）")
            report.total_frames += frames

        frame_path = str(frames_dir / f"{shot_id}.png")
        if render_first_frame(scene, shot["start_frame"], frame_path):
            report.files.append(frame_path)
        else:
            report.warnings.append(f"{shot_id}: 首帧未生成")

        report.shots.append({"shot_id": shot_id,
                             "start_frame": shot["start_frame"],
                             "end_frame": shot["end_frame"],
                             "video": f"blockout_{shot_id}.mp4"
                                      if config.per_shot_clips else None})
        log.info("已导出镜头 %s（%d-%d）", shot_id,
                 shot["start_frame"], shot["end_frame"])

    manifest = build_manifest(plan, build_summary=build_summary,
                              resolution=(width, height), style=style,
                              project=project)
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

    scene.frame_start, scene.frame_end = original_range
    report.duration_s = time.perf_counter() - started

    readme_path = export_dir / "README.md"
    readme_path.write_text(_readme(manifest, report), encoding="utf-8")
    report.files.append(str(readme_path))

    log.info("交付完成：%d 个文件，用时 %.1fs", len(report.files), report.duration_s)
    return report
