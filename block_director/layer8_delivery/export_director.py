"""交付编排（执行文档 v1.2 §15）。

一条命令从场景产出：分镜 mp4 + 首帧 PNG + shots.json + prompts.md
（可选相机轨迹）+ README。**导出前先做画面审计**——辅助物一旦会入画就
直接中止，而不是产出一段带文字标签的"脏"参考视频。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import bpy

from ..cinema.camera_narration import narrate
from ..contracts.elements import ElementRegistry, build_registry
from ..contracts.enums import ErrorCode, resolution_for
from ..contracts.errors import user_message
from ..contracts.plan import FPS, Plan, unknown_cast_ids
from ..delivery.depth import depth_range_note
from ..delivery.concat_inputs import concat_inputs
from ..delivery.failures import (
    align_failures_payload,
    delivered_shot_ids,
)
from ..delivery.manifest import build_manifest
from ..delivery.mask_check import empty_mask_warning
from ..delivery.package import (
    clear_stale_concat_outputs,
    clear_stale_shot_outputs,
    delivery_artifacts_match,
    resolve_delivery_package,
)
from ..delivery.prompts import (
    DEFAULT_STYLE,
    render_prompt_sheet,
    unknown_prompt_names,
)
from ..delivery.report import DeliveryReport
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
            label_overlap_report: Optional[Dict[str, Any]] = None,
            ruler_observation: bool = False,
            failures: Optional[Dict[str, Any]] = None,
            delivery_quality: Optional[Dict[str, Any]] = None) -> str:
    return render_readme(manifest, out_dir=Path(report.out_dir),
                         warnings=report.warnings,
                         label_overlap_report=label_overlap_report,
                         ruler_observation=ruler_observation,
                         failures=(failures or {}).get("failures"),
                         pending_review=(failures or {}).get(
                             "pending_review"),
                         delivery_quality=delivery_quality)


def _ruler_manifest_summary(ruler_evidence, ruler_shot_measurements):
    """``shots.json`` 顶层的 ruler_observation 摘要；无数据返回 None（零形状差）。"""
    if not ruler_evidence and not ruler_shot_measurements:
        return None
    measurements = list((ruler_evidence or {}).get("measurements") or [])
    for items in (ruler_shot_measurements or {}).values():
        measurements.extend(items or [])
    return {
        "file": "ruler_observation.json",
        "schema_version": "spatial-ruler-observation/v2",
        "measurement_count": len(measurements),
        "prescription_count": len(
            (ruler_evidence or {}).get("prescriptions") or []),
    }


def _compliance_verdicts(compliance):
    """compliance findings → 契约 verdict（纯层映射，缺省空表）。"""
    if not compliance:
        return []
    from ..delivery.ruler_evidence import map_compliance_verdicts
    return map_compliance_verdicts(compliance)


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
                   ruler_evidence: Optional[Dict[str, Any]] = None,
                   ruler_shot_measurements: Optional[Dict[str, Any]] = None,
                   ruler_observation: Optional[Dict[str, Any]] = None,
                   spatial_design: Optional[Dict[str, Any]] = None,
                   spatial_observation: Optional[Dict[str, Any]] = None,
                   spatial_diff: Optional[Dict[str, Any]] = None,
                   failures: Optional[Dict[str, Any]] = None,
                   delivery_quality: Optional[Dict[str, Any]] = None,
                   concat_plan: Optional[Plan] = None,
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

    plan_shot_ids = [str(shot.shot_id) for shot in plan.shots]
    quality_payload = (
        dict(delivery_quality) if delivery_quality is not None else None)
    package = resolve_delivery_package(quality_payload, plan_shot_ids)
    clear_stale_concat_outputs(export_dir)
    report = DeliveryReport(
        out_dir=str(export_dir),
        delivery_class=package.delivery_class,
        delivery_quality=dict(quality_payload or {}),
    )
    if package.blocked:
        blocked_quality = dict(quality_payload or {})
        blocked_quality.update({
            "schema_version": str(
                blocked_quality.get("schema_version")
                or "quality-contract/v1"),
            "component": "delivery",
            "delivery_class": "blocked",
            "reasons": list(dict.fromkeys(
                list(blocked_quality.get("reasons") or [])
                + list(package.reasons)
                + ["delivery_package_invalid"]
            )),
            "selected_shots": list(package.selected_shots),
            "sequence_review_passed": False,
        })
        report.delivery_class = "blocked"
        report.delivery_quality = blocked_quality
        report.aborted = True
        details = "、".join(package.reasons) or "blocked"
        report.reason = f"导出中止：交付质量身份为 blocked（{details}）"
        log.error(report.reason)
        return report

    clear_stale_shot_outputs(export_dir, plan_shot_ids)
    frames_dir.mkdir(parents=True, exist_ok=True)
    export_failures = (
        align_failures_payload(failures, quality_payload)
        if quality_payload is not None else failures
    )
    #: 缺陷 D / T8（D3）：fail 镜照常产出最佳版本，渲染后标 ``failed``；
    #: shots.json / prompts.md / README 与失败清单保留真实身份，不伪装通过。
    failure_ids = {str(item.get("shot_id"))
                   for item in (export_failures or {}).get("failures") or []}
    pending_review_ids = {
        str(item.get("shot_id"))
        for item in (export_failures or {}).get("pending_review") or []
    }
    if pending_review_ids:
        report.warnings.append(
            "以下镜头由模型声明完成但审核未通过，已出片并标为待复核："
            + "、".join(sorted(pending_review_ids)))

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

    #: 空间尺观测完整文档（Ticket 04-06）：``build_observation`` 的产物直接
    #: 写盘并进 README/清单；缺省 None ⇒ 现有交付逐字节不变。未过结构校验
    #: 即中止导出——不产脏交付包（坏数据不静默）。
    obs_written = False
    ruler_manifest_summary: Optional[Dict[str, Any]] = None
    if ruler_observation is not None:
        from ..layer5_orchestrator.ruler_observation import validate_observation

        problems = validate_observation(ruler_observation)
        if problems:
            report.aborted = True
            report.reason = ("导出中止：ruler_observation 未通过结构校验："
                             + "；".join(problems[:5]))
            log.error(report.reason)
            return report
        obs_written = True
        ruler_manifest_summary = {
            "file": "ruler_observation.json",
            "schema_version": str(
                ruler_observation.get("schema_version") or ""),
            "measurement_count": len(
                ruler_observation.get("measurements") or []),
            "prescription_count": len(
                ruler_observation.get("prescriptions") or []),
        }
    elif ruler_evidence or ruler_shot_measurements:
        ruler_manifest_summary = _ruler_manifest_summary(
            ruler_evidence, ruler_shot_measurements)

    #: 空间理解快照（Ticket 08）：设计/观测/diff 三份产物与 ruler 同一纪律
    #: ——未过结构校验即中止导出，不产脏交付包。缺省全部 None ⇒ 现有交付
    #: 逐字节不变（零形状差）。
    spatial_artifacts = (
        (spatial_design, "spatial_design_snapshot.json", "design"),
        (spatial_observation, "spatial_observation_snapshot.json",
         "observation"),
        (spatial_diff, "spatial_diff_report.json", "diff"),
    )
    spatial_written: List[Tuple[str, Dict[str, Any]]] = []
    if any(item[0] is not None for item in spatial_artifacts):
        from ..contracts.spatial_snapshot import (
            validate_spatial_artifact,
        )

        for snapshot, filename, artifact in spatial_artifacts:
            if snapshot is None:
                continue
            problems = validate_spatial_artifact(snapshot, artifact)
            if problems:
                report.aborted = True
                report.reason = (f"导出中止：{filename} 未通过结构校验："
                                 + "；".join(problems[:5]))
                log.error(report.reason)
                return report
            spatial_written.append((filename, snapshot))

    #: v1.6 E1（FR-A2/FR-A4）：先生成唯一一份登记表，prompts / mask /
    #: reference 共用（SC-06）。表外名字在**渲染之前**判 error 中止——
    #: 与画面前审计、角色表校验同一条"不产出脏交付包"的纪律；也放在
    #: ``apply_delivery_settings`` 之前，中止路径不留下已改的场景设置。
    width, height = resolution_for(config.preset)
    registry = _element_registry(plan)
    prompt_text = render_prompt_sheet(plan, style=style,
                                      resolution=(width, height),
                                      project=project, registry=registry,
                                      failures=(export_failures or {}).get(
                                          "failures"),
                                      pending_review=(export_failures or {}).get(
                                          "pending_review"),
                                      delivery_quality=quality_payload)
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
        selected_ids = set(package.selected_shots)
        if quality_payload is not None:
            ranges = [
                shot for shot in ranges
                if str(shot.get("shot_id") or "") in selected_ids
            ]
        original_range = (scene.frame_start, scene.frame_end)
        context = get_context()

        for shot in ranges:
            shot_id = shot["shot_id"]
            #: 缺陷 D / T8（D3）修正：fail 镜**照常产出最佳版本参考视频**
            #: （U6/U1：白模预演视频一定要生成），但 report 里标 ``failed``、
            #: 失败清单照旧保留——出片≠伪装通过，成片含尽力而为片段。
            shot_failed = shot_id in failure_ids
            shot_pending_review = shot_id in pending_review_ids
            if shot_failed:
                log.info("镜头 %s 未达门槛，记入失败清单，照常渲染最佳版本",
                         shot_id)
            #: v1.7 J3（镜头级 skip）：skip_white_model 的镜头**照常入 shots.json**
            #: （只写元数据、标 ``skip_white_model: true``），但跳过 mp4/首帧/
            #: depth/路径采样——没有白模视频，也就不进成片与拼接。相机已由构建
            #: 层建好，连续性/审计不受影响（skip 只在交付层生效）。
            responsibility = shot.get("responsibility")
            skip_shot = bool(getattr(responsibility, "skip_white_model", False))
            if skip_shot:
                entry = {
                    "shot_id": shot_id,
                    "start_frame": int(shot["start_frame"]),
                    "end_frame": int(shot["end_frame"]),
                    "video": None,
                    "skip_white_model": True,
                }
                if shot_failed:
                    entry["failed"] = True
                if shot_pending_review:
                    entry["pending_review"] = True
                report.shots.append(entry)
                log.info("镜头 %s 声明 skip_white_model，跳过渲染", shot_id)
                continue
            video_base = str(export_dir / f"blockout_{shot_id}.mp4")
            shot_frames = int(shot["end_frame"]) - int(shot["start_frame"]) + 1
            video_name: Optional[str] = None
            if config.per_shot_clips:
                # 参考视频**带**角色标签（v1.3 诉求 4）
                path, frames = render_shot_video(
                    scene, shot["start_frame"], shot["end_frame"], video_base,
                    codec=str(config.video_codec), crf=str(config.crf))
                if os.path.exists(path):
                    video_name = Path(path).name
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

                entry = {"shot_id": shot_id,
                         "start_frame": shot["start_frame"],
                         "end_frame": shot["end_frame"],
                         "video": video_name}
                if shot_failed:
                    entry["failed"] = True
                if shot_pending_review:
                    entry["pending_review"] = True
                report.shots.append(entry)
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

        if package.requires_artifacts:
            delivered = delivered_shot_ids(report.shots)
            if not delivery_artifacts_match(package, delivered):
                blocked_quality = dict(quality_payload or {})
                blocked_quality.update({
                    "schema_version": str(
                        blocked_quality.get("schema_version")
                        or "quality-contract/v1"),
                    "component": "delivery",
                    "delivery_class": "blocked",
                    "reasons": list(dict.fromkeys(
                        list(blocked_quality.get("reasons") or [])
                        + ["delivered_artifact_set_mismatch"]
                    )),
                    "selected_shots": list(package.selected_shots),
                    "delivered_shots": delivered,
                    "artifact_check_complete": True,
                    "sequence_review_passed": False,
                })
                report.delivery_class = "blocked"
                report.delivery_quality = blocked_quality
                report.aborted = True
                report.reason = (
                    "导出中止：实际逐镜产物集合与交付分类不一致（"
                    f"selected={list(package.selected_shots)}，"
                    f"delivered={delivered}）")
                log.error(report.reason)
                return report
            quality_payload = dict(quality_payload or {})
            quality_payload.update({
                "delivered_shots": list(package.selected_shots),
                "artifact_check_complete": True,
            })
            report.delivery_quality = quality_payload

        #: v1.6 E2（FR-A3）：逐元素遮罩（可选，默认开）。非 EEVEE 后端出不了遮罩
        #: 就跳过并写进报告告警（与 depth 的 DepthUnavailable 同一模式），绝不
        #: 静默；成功时逐镜记进 ``mask_shots``。帧表与分镜 mp4 同一份 schedule。
        if config.mask_pass:
            try:
                mask_ranges = {
                    str(shot["shot_id"]): (
                        int(shot["start_frame"]),
                        int(shot["end_frame"]),
                    )
                    for shot in ranges
                }
                mask_results = render_mask_pass(
                    scene, registry, mask_ranges, str(export_dir))
                for item in mask_results:
                    warning = empty_mask_warning(
                        str(item["shot_id"]),
                        [Path(p) for p in item.get("files") or []])
                    if warning is not None:
                        report.warnings.append(warning)
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
            #: R2-D1：concat 输入来自**完整计划**（resume 场景传 concat_plan），
            #: 缺失 mp4（fail/skip 镜）由 concat_shot_clips 过滤并 warning，
            #: 前段已过镜不再被子集 plan 丢掉。
            clips, clip_frames = concat_inputs(
                plan, export_dir,
                build_summary=build_summary, concat_plan=concat_plan,
                shot_ids=(
                    list(package.selected_shots)
                    if quality_payload is not None else None))
            output_path = (
                str(export_dir / package.concat_filename)
                if package.concat_filename else full_output_path(export_dir))
            try:
                concat = concat_shot_clips(
                    scene, clips, output_path,
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
                                  rhythm_arc=rhythm_arc,
                                  ruler_observation=ruler_manifest_summary,
                                  failures=export_failures,
                                  delivery_quality=quality_payload)

        #: 空间尺观测 JSON（Ticket 06）：优先写完整观测文档
        #: （``ruler_observation``，build_observation 产物）；否则由计划级
        #: 处方＋逐镜几何测量组装成契约 bundle（delivery/ruler_evidence.py）。
        #: 两种路径任选其一；校验发现非空时如实记 warning，不静默、不改判据。
        ruler_bundle, ruler_findings = None, []
        if obs_written:
            ruler_bundle = ruler_observation
        elif ruler_evidence or ruler_shot_measurements:
            ruler_evidence = ruler_evidence or {}
            from ..delivery.ruler_evidence import assemble_bundle
            shot_measurements = ruler_shot_measurements or {}
            flat_measurements = list(ruler_evidence.get("measurements") or [])
            for shot_id in sorted(shot_measurements):
                flat_measurements.extend(shot_measurements[shot_id] or [])
            ruler_bundle, ruler_findings = assemble_bundle(
                observation_id=f"obs_{generated_now()}",
                run_context={
                    "source_run": "",
                    "model": str(getattr(config, "model", "") or ""),
                    "status": "ok",
                },
                plan=plan,
                build_summary=build_summary,
                measurements=flat_measurements,
                verdicts=_compliance_verdicts(compliance),
                prescriptions=list(ruler_evidence.get("prescriptions") or []),
            )
            if ruler_findings:
                report.warnings.append(
                    "ruler_observation.json 校验发现："
                    + "; ".join(f.get("message", "") for f in ruler_findings))

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

    #: 缺陷 D / T8（U1）：失败清单单独落盘，README/prompts.md 与它同源。
    if export_failures is not None and (
            quality_payload is not None
            or (export_failures.get("failures") or [])
            or (export_failures.get("pending_review") or [])):
        failures_path = export_dir / "failures.json"
        failures_path.write_text(
            json.dumps(export_failures, ensure_ascii=False, indent=2),
            encoding="utf-8")
        report.files.append(str(failures_path))

    if quality_payload is not None:
        quality_path = export_dir / "delivery_quality.json"
        quality_path.write_text(
            json.dumps(quality_payload, ensure_ascii=False, indent=2),
            encoding="utf-8")
        report.files.append(str(quality_path))

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

    if ruler_bundle is not None:
        ruler_path = export_dir / "ruler_observation.json"
        ruler_path.write_text(
            json.dumps(ruler_bundle, ensure_ascii=False, indent=2,
                       allow_nan=False),
            encoding="utf-8")
        report.files.append(str(ruler_path))

    #: 空间理解快照（Ticket 08）：设计/观测/diff 三份 JSON 随交付包落盘。
    #: 校验已在函数首部完成（未过即中止）；这里只写盘，失败如实上抛。
    for filename, snapshot in spatial_written:
        spatial_path = export_dir / filename
        spatial_path.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2,
                       allow_nan=False),
            encoding="utf-8")
        report.files.append(str(spatial_path))

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

    readme_text = _readme(manifest, report,
                          label_overlap_report=label_overlap_report,
                          ruler_observation=obs_written,
                          failures=export_failures,
                          delivery_quality=quality_payload)
    readme_path = export_dir / "README.md"
    readme_path.write_text(readme_text, encoding="utf-8")
    report.files.append(str(readme_path))

    log.info("交付完成：%d 个文件，用时 %.1fs", len(report.files), report.duration_s)
    return report
