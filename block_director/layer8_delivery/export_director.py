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

from ..cinema.camera_narration import narrate
from ..cinema.schedule import shot_ranges
from ..contracts.elements import ElementRegistry, build_registry
from ..contracts.enums import ErrorCode, resolution_for
from ..contracts.errors import user_message
from ..contracts.plan import FPS, Plan, unknown_cast_ids
from ..delivery.depth import depth_range_note
from ..delivery.manifest import build_manifest
from ..delivery.prompts import (
    DEFAULT_STYLE,
    render_prompt_sheet,
    unknown_prompt_names,
)
from ..delivery.readme import render_readme
from ..layer3_engine.collection_router import (
    audit_renderable_objects,
    labels_collection,
)
from ..layer3_engine.character_system.character_factory import get_facing
from ..layer3_engine.rule_checker import continuity_snapshot
from ..layer3_engine.scene_context import get_context
from ..utils.logger import get_logger
from ..utils.threading_guard import main_thread_only
from .camera_trajectory import camera_trajectory
from .concat import ConcatUnavailable, concat_shot_clips, full_output_path
from .depth_pass import DepthUnavailable, render_depth_sequence
from .export_sandbox import export_sandbox
from .mask_pass import MaskUnavailable, render_mask_pass
from .package import build_reference_pack
from .reference_cards import render_reference_cards
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
    mask_shots: List[Dict[str, Any]] = field(default_factory=list)
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
            "mask_shots": list(self.mask_shots),
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
                       "camera": result.get("camera", f"BD_Cam_{shot.shot_id}"),
                       #: v1.7 J3：镜头级 skip 的数据源。``responsibility`` 是
                       #: 契约对象（可 None），渲染循环据此跳过该镜渲染但保留
                       #: shots.json 元数据；未声明镜恒 None ⇒ 零行为差。
                       "responsibility": getattr(shot, "responsibility", None)})
        cursor = end + 1
    return ranges


def _readme(manifest: Dict[str, Any], report: DeliveryReport,
            label_overlap_report: Optional[Dict[str, Any]] = None) -> str:
    return render_readme(manifest, out_dir=Path(report.out_dir),
                         warnings=report.warnings,
                         label_overlap_report=label_overlap_report)


def _cast_id_errors(plan: Plan,
                    roster: Optional[Sequence[str]]) -> Optional[str]:
    """v1.6 A2：交付前自检角色表成员资格。"""
    if roster is None:
        return None
    bad = unknown_cast_ids(plan, roster)
    if not bad:
        return None
    return user_message(ErrorCode.CAST_001,
                        ids=", ".join(bad),
                        roster=", ".join(sorted(str(x) for x in roster)))


def _element_registry(plan: Plan) -> ElementRegistry:
    """v1.6 E1：交付装配构建**唯一一份**元素登记表（SC-06：prompts / mask /
    reference 共用同一份）。数据源只有 SceneContext 与计划，不从图像反推：
    角色取 ``spec.cast``（缺省时构建器按同一 DEFAULT_COLORS 分配回落），
    道具取 ``spec.props``，环境件取 ``plan.environment.anchors``。
    """
    context = get_context()
    spec = getattr(context, "spec", None)
    cast = [member.to_dict() for member in (spec.cast if spec else [])]
    props = [dict(item) for item in (spec.props if spec else [])]
    environment = [dict(item) for item in
                   ((plan.environment or {}).get("anchors") or [])]
    return build_registry(plan, cast=cast, props=props,
                          environment=environment)


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
                   knowledge: Optional[Dict[str, Any]] = None,
                   roster: Optional[Sequence[str]] = None,
                   review_requests: Optional[Sequence[Dict[str, Any]]] = None,
                   brief=None,
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

    cast_error = _cast_id_errors(plan, roster)
    if cast_error:
        report.aborted = True
        report.reason = cast_error
        log.error(report.reason)
        return report

    #: v1.6 E1（FR-A2/FR-A4）：先生成唯一一份登记表，prompts / mask /
    #: reference 共用（SC-06）。表外名字在**渲染之前**判 error 中止——
    #: 与画面前审计、角色表校验同一条"不产出脏交付包"的纪律；也放在
    #: ``apply_delivery_settings`` 之前，中止路径不留下已改的场景设置。
    width, height = resolution_for(config.preset)
    registry = _element_registry(plan)
    prompt_text = render_prompt_sheet(plan, style=style,
                                      resolution=(width, height),
                                      project=project, registry=registry)
    unknown = unknown_prompt_names(prompt_text, registry)
    if unknown:
        report.aborted = True
        report.reason = ("导出中止：prompts.md 引用了元素登记表之外的名字："
                         + "、".join(unknown))
        log.error(report.reason)
        return report

    #: v1.7 I1：主体渲染段整体进导出沙箱——render.* 的 10 项＋scene.camera
    #: 进入时备份、退出（含异常路径）逐项还原；只加包裹，渲染参数不改。
    #: fps 用契约层的 FPS 常量（DeliveryConfig 没有 animation 字段，不能读
    #: config.animation.fps；contracts/ 无 bpy 依赖，导入安全）。
    with export_sandbox(scene, camera=scene.camera,
                        fps=FPS):
        report.warnings.extend(apply_delivery_settings(scene, config))

        ranges = _shot_ranges(plan, build_summary)
        original_range = (scene.frame_start, scene.frame_end)
        context = get_context()

        for shot in ranges:
            shot_id = shot["shot_id"]
            #: v1.7 J3（镜头级 skip）：skip_white_model 的镜头**照常入 shots.json**
            #: （只写元数据、标 ``skip_white_model: true``），但跳过 mp4/首帧/
            #: depth/路径采样——没有白模视频，也就不进成片与拼接。相机已由构建
            #: 层建好，连续性/审计不受影响（skip 只在交付层生效）。
            responsibility = shot.get("responsibility")
            skip_shot = bool(getattr(responsibility, "skip_white_model", False))
            if skip_shot:
                report.shots.append({
                    "shot_id": shot_id,
                    "start_frame": int(shot["start_frame"]),
                    "end_frame": int(shot["end_frame"]),
                    "video": None,
                    "skip_white_model": True,
                })
                log.info("镜头 %s 声明 skip_white_model，跳过渲染", shot_id)
                continue
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

            #: v1.7 I3：本镜角色 9 帧等距采样 → ``build_summary`` 的
            #: ``result["paths"]``（manifest ``paths`` 键的数据源）。渲染循环里
            #: 做，让路径与渲染用同一份 schedule 同帧读；无上下文（离线回放/
            #: 旧路径）时留空 dict，不猜。结束后还原帧号。
            start_frame = int(shot["start_frame"])
            end_frame = int(shot["end_frame"])
            frames = [start_frame + round(index * (end_frame - start_frame) / 8)
                      for index in range(9)]
            build_summary = dict(build_summary or {})
            results = build_summary.setdefault("results", [])
            result = next((item for item in results
                           if item.get("shot_id") == shot_id), None)
            if result is None:
                result = {"shot_id": shot_id}
                results.append(result)
            result["paths"] = {}
            if context is not None:
                sample_frame = int(scene.frame_current)
                try:
                    for character in context.subjects_for(shot_id):
                        root = getattr(character, "root", None)
                        if root is None:
                            result["paths"][str(character.id)] = []
                            continue
                        points = []
                        for frame in frames:
                            scene.frame_set(frame)
                            bpy.context.view_layer.update()
                            translation = root.matrix_world.translation
                            points.append([round(float(translation.x), 2),
                                           round(float(translation.y), 2),
                                           round(float(translation.z), 2)])
                        result["paths"][str(character.id)] = points
                finally:
                    if scene.frame_current != sample_frame:
                        scene.frame_set(sample_frame)
                        bpy.context.view_layer.update()
            log.info("已导出镜头 %s（%d-%d）", shot_id,
                     shot["start_frame"], shot["end_frame"])

        #: v1.6 E2（FR-A3）：逐元素遮罩（可选，默认开）。非 EEVEE 后端出不了遮罩
        #: 就跳过并写进报告告警（与 depth 的 DepthUnavailable 同一模式），绝不
        #: 静默；成功时逐镜记进 ``mask_shots``。帧表与分镜 mp4 同一份 schedule。
        if config.mask_pass:
            try:
                mask_results = render_mask_pass(
                    scene, registry, shot_ranges(plan), str(export_dir))
                report.mask_shots.extend(
                    {"shot_id": str(item["shot_id"]),
                     "dir": str(Path(item["dir"]).relative_to(export_dir)),
                     "frames": int(item["frames"]),
                     "start_frame": int(item["start_frame"]),
                     "end_frame": int(item["end_frame"])}
                    for item in mask_results)
            except MaskUnavailable as exc:
                report.warnings.append(f"mask 导出跳过（{exc}）")

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

        #: v1.6 D3（FR-B2）：shots.json 的每镜 ``rhythm.tension`` 只来自 brief 的
        #: 节奏弧。brief 两种形状都收：契约对象取 ``rhythm_arc`` 属性，普通字典
        #: （SDL/replay 通路）取 ``rhythm_arc`` 键；没有 brief 就不传、不猜。
        rhythm_arc = None
        if isinstance(brief, dict):
            rhythm_arc = brief.get("rhythm_arc")
        elif brief is not None:
            rhythm_arc = getattr(brief, "rhythm_arc", None)

        manifest = build_manifest(plan, build_summary=build_summary,
                                  resolution=(width, height), style=style,
                                  project=project, llm_calls=llm_calls,
                                  retrieval_calls=retrieval_calls, crowd=crowd,
                                  parsed=parsed,
                                  timing_overrides=timing_overrides,
                                  action_conflicts=action_conflicts,
                                  audit_pass_rate=audit_pass_rate,
                                  knowledge_provenance=knowledge_provenance,
                                  knowledge=knowledge,
                                  review_requests=review_requests,
                                  registry=registry,
                                  rhythm_arc=rhythm_arc)

        #: v1.7 I3（接线 2/3）：写盘前逐镜产 ``camera_narration``——相机对象在
        #: 本镜帧段内等距 9 采样喂 ``narrate``，主体锚点 = paths 首角色首点 XY。
        #: 相机**显式**取 ``context.cameras``（不复读 scene.camera，cut marker
        #: 才会派生错机位）；缺 paths / 缺相机则**留缺不写键**（诚实留缺，不猜）。
        #: 采样前后还原帧号（与 check_shot 同一纪律）。
        if context is not None:
            result_by_id = {r.get("shot_id"): r for r in
                            (build_summary or {}).get("results", [])}
            for shot_payload in (manifest.get("shots") or []):
                shot_id = str(shot_payload.get("shot_id") or "")
                result = result_by_id.get(shot_id) or {}
                paths = result.get("paths") or {}
                if not paths:
                    continue
                camera = context.cameras.get(shot_id)
                if camera is None:
                    continue
                start = int(shot_payload.get("start_frame") or 1)
                end = int(shot_payload.get("end_frame") or start)
                frames = [start + round(i * (end - start) / 8) for i in range(9)]
                sample_frame = int(scene.frame_current)
                try:
                    camera_samples = []
                    for frame in frames:
                        scene.frame_set(frame)
                        bpy.context.view_layer.update()
                        t = camera.matrix_world.translation
                        camera_samples.append({
                            "position": [round(float(t.x), 2),
                                         round(float(t.y), 2),
                                         round(float(t.z), 2)],
                            "lens": float(camera.data.lens),
                        })
                    first_char_id = next(iter(paths))
                    first_point = paths[first_char_id][0]
                    anchor = [float(first_point[0]), float(first_point[1])]
                    first_char = context.character(first_char_id)
                    try:
                        facing = (get_facing(first_char)
                                  if first_char is not None
                                  else (0.0, 1.0, 0.0))
                    except Exception:
                        facing = (0.0, 1.0, 0.0)
                    narration = narrate(camera_samples, anchor, facing)
                    result["camera_narration"] = narration
                    shot_payload["camera_narration"] = narration
                finally:
                    if scene.frame_current != sample_frame:
                        scene.frame_set(sample_frame)
                        bpy.context.view_layer.update()

        manifest_path = export_dir / "shots.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
        report.files.append(str(manifest_path))

        #: v1.6 E1（FR-A2）：元素登记表单独落盘，与 shots.json / prompts.md 同源。
        elements_path = export_dir / "elements.json"
        elements_path.write_text(json.dumps(registry.to_dict(), ensure_ascii=False,
                                            indent=2), encoding="utf-8")
        report.files.append(str(elements_path))

        #: v1.6 E3（FR-A5）：角色定妆卡（可选，默认开）。渲染后函数原样恢复场景。
        if config.reference_cards:
            report.files.extend(
                render_reference_cards(scene, registry, str(export_dir)))

    prompt_path = export_dir / "prompts.md"
    prompt_path.write_text(prompt_text, encoding="utf-8")
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

    #: v1.7 I3（接线 3/3）：整场连续性快照 + reference_pack 五件套。失败即交付
    #: 失败，如实上抛（不 try/except 吞）；``continuity_snapshot`` 缺上下文/缺口
    #: 镜返回空结构，package 收空结构照样写盘——不猜。五件套路径进 report.files。
    continuity: Dict[str, Any] = {}
    for shot in plan.shots:
        continuity[shot.shot_id] = continuity_snapshot(
            shot.shot_id, context=context)
    pack = build_reference_pack(export_dir, plan, config, manifest,
                                continuity=continuity)
    report.files.extend(pack.files)
    report.warnings.extend(pack.warnings)

    report.duration_s = time.perf_counter() - started

    #: v1.6 A7（D-19）：把构建期烘焙的全帧自检余量带进交付 README——
    #: 标签互不遮挡的验收判据（RK-2 的 5% 阈值）从采样帧扩到全帧之后，
    #: 交付包必须能读到结构化余量，而不是只有一条 summary.warnings 字符串。
    label_report = dict((build_summary or {}).get("label_report") or {})
    label_overlap_report = dict(label_report.get("label_overlap_report") or {})

    readme_path = export_dir / "README.md"
    readme_path.write_text(
        _readme(manifest, report,
                label_overlap_report=label_overlap_report),
        encoding="utf-8")
    report.files.append(str(readme_path))

    log.info("交付完成：%d 个文件，用时 %.1fs", len(report.files), report.duration_s)
    return report
