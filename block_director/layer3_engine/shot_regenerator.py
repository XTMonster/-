"""单镜重生成（执行文档 v1.2 §8.3 / §13.2 的"重生成此镜"）。

这是"AI 视频生成不理想 → 回头只调某一镜"的入口：**只动这一镜**，其余镜头
的相机、关键帧与时间轴一概不碰。三条保护：

1. 先 ``sync_from_blender()`` 回读用户改动，再重建——否则用户挪过的角色会被
   计划里的旧坐标覆盖（§8.3 的 DoD 原文："手动修改被保留"）；
2. 打上 ``bd_user_animated`` 的角色整段跳过重烘焙（用户调过的关键帧不覆盖）；
3. 只删这一镜帧范围内的关键帧，别的镜头照旧。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import bpy

from ..contracts.cast import CastMember, SceneSpec
from ..contracts.plan import Plan
from ..cinema.schedule import shot_ranges
from ..motion.model import ActionRequest
from ..utils.blender_compat import action_fcurves
from ..utils.logger import get_logger
from ..utils.threading_guard import main_thread_only
from .character_system import MotionBlender
from .scene_context import SceneContext, get_context
from .scene_sync import SceneSynchronizer, is_user_animated
from .shot_builder import (ShotBuildResult, action_requests, conflict_warnings,
                           _axis_for_placement, _initial_cast_positions,
                           axis_for_shot, live_subject_entries,
                           place_shot_camera)
from .cinema_engine import establish_axis_from_speakers
from ..cinema.axis import axis_status, camera_side_of, pair_spans

log = get_logger("shot-regen")


class ShotRegenError(RuntimeError):
    """无法重生成。消息里给出可执行的下一步。"""


@main_thread_only("clear_keyframes_in_range")
def clear_keyframes_in_range(character, start: int, end: int,
                             skip_objects: Sequence[str] = ()) -> int:
    """只删 ``[start, end]`` 内的关键帧，其余镜头的动画原样保留。"""
    removed = 0
    skip = set(skip_objects)
    for obj in character.all_objects():
        if obj.name in skip:
            continue
        animation = obj.animation_data
        if animation is None or animation.action is None:
            continue
        for curve in action_fcurves(animation.action):
            doomed = [point for point in curve.keyframe_points
                      if start <= point.co.x <= end]
            for point in reversed(doomed):
                curve.keyframe_points.remove(point)
                removed += 1
            if doomed:
                curve.update()
    return removed


@main_thread_only("regenerate_shot")
def regenerate_shot(shot_id: str, *, plan: Optional[Plan] = None,
                    spec: Optional[SceneSpec] = None,
                    context: Optional[SceneContext] = None,
                    sync: Optional[SceneSynchronizer] = None,
                    sync_edits: bool = True) -> Dict[str, Any]:
    """重建单个镜头：回读用户改动 → 换相机 → 重烘这一镜的动作。"""
    context = context or get_context()
    if context is None:
        raise ShotRegenError("当前没有 BlockDirector 场景上下文；请先构建一次场景")
    plan = plan if plan is not None else context.plan
    if plan is None:
        raise ShotRegenError("上下文里没有分镜计划，无法重生成单镜")

    shot = next((item for item in plan.shots if item.shot_id == shot_id), None)
    if shot is None:
        known = ", ".join(item.shot_id for item in plan.shots) or "（无）"
        raise ShotRegenError(f"找不到镜头 {shot_id}。可用镜头: {known}")

    spec = spec or SceneSpec.from_plan(plan)
    protected: List[str] = []

    # 1) 回读用户改动（§8.3）：不这么做，下面的重建会把用户挪过的角色推回去
    if sync is not None and sync_edits:
        plan, spec = sync.sync_from_blender(plan, spec)
        context.plan = plan

    cast_map: Dict[str, CastMember] = {member.id: member for member in spec.cast}
    ranges = shot_ranges(plan)
    start, end = ranges[shot_id]
    #: 方案 B：与主构建同一条登记——``context.schedule`` 是 auditor 视锥
    #: 采样 / 标签烘焙 / 交付层的帧区间真源。逐镜 rebuild 不写它，guard
    #: 采样就会报 E_GUARD_001「场景里没有镜头 X 的帧区间」（headless
    #: 64 镜实测，shot_064）。
    context.schedule[shot_id] = (start, end)
    scene = bpy.context.scene
    warnings: List[str] = []

    # 2) 只替换这一镜的相机与剪切标记
    previous = context.cameras.get(shot_id)
    old_marker = scene.timeline_markers.get(f"BD_Cut_{shot_id}")
    if old_marker is not None:
        scene.timeline_markers.remove(old_marker)
    if previous is not None:
        bpy.data.objects.remove(previous, do_unlink=True)
    # 对准点 Empty 与相机成对存在，必须一起删。否则 create_camera 会新建出
    # ``BD_CamTarget_<shot>.001``，而 ``_shot_target_object()`` 按原名查找时
    # 仍返回旧对象——move_camera / reframe 会去动一个和相机已经没有约束关系
    # 的 Empty，表现为"加了运镜但画面不动"。
    stale_target = scene.objects.get(f"BD_CamTarget_{shot_id}")
    if stale_target is not None:
        bpy.data.objects.remove(stale_target, do_unlink=True)

    # v1.3：与主构建共用同一个机位解算入口。
    # v1.2 这里写死 side="front" 并丢掉 lens，重生成后朝向与焦距都会回退。
    bundle, solution, _frame = place_shot_camera(
        shot, cast_map, spec,
        #: 方案 B（§3.6.4 #5）：与主构建同一条轴线入口——逐镜重建不重新猜
        #: 轴侧，否则会把机位摆到观众没看见过的一侧（R001 越轴）。
        axis=axis_for_shot(context, shot),
        #: 与主构建同一条口径：按**此刻**人在哪、朝哪摆机位（v1.6）。
        entries=live_subject_entries(shot, context.characters))
    marker = scene.timeline_markers.new(f"BD_Cut_{shot_id}", frame=start)
    marker.camera = bundle.camera
    context.cameras[shot_id] = bundle.camera
    context.shot_types[shot_id] = str(shot.shot_type).upper()
    warnings.extend(solution.warnings)

    # 3) 重烘这一镜的动作：帧范围之外的关键帧不动，用户调过的角色整段保护
    requests = action_requests(shot, start, cast_map, warnings)
    warnings.extend(conflict_warnings(requests, shot_id))
    by_character: Dict[str, List[ActionRequest]] = {}
    for request in requests:
        by_character.setdefault(request.character_id, []).append(request)

    keyframes = 0
    for character_id, character_requests in by_character.items():
        character = context.character(character_id)
        if character is None:
            warnings.append(f"{character_id}: 场景里没有这个角色，已跳过动作重烘")
            continue
        guarded = [obj.name for obj in character.all_objects()
                   if is_user_animated(obj)]
        if guarded:
            protected.append(character_id)
            warnings.append(
                f"{character_id}: 用户手动调整过动画，已保留不覆盖"
                f"（{', '.join(guarded)}）")
            continue
        clear_keyframes_in_range(character, start, end)
        blender = MotionBlender(character)
        blender.requests.extend(character_requests)
        try:
            result = blender.bake(clear=False)
        except ValueError as exc:
            warnings.append(f"{character_id}: 动作重烘失败（{exc}）")
            continue
        keyframes += result.keyframes

    if scene.camera is previous or scene.camera is None:
        scene.camera = bundle.camera
    bpy.context.view_layer.update()

    #: 方案 B（§3.6.5）：逐镜预演必须复刻主构建的**顺序轴状态机**，否则
    #: prepare+rebuild 路径的 shot_002 会拿不到 axis（机位被摆到
    #: "观众没看见过"的一侧，R001 越轴）。主构建的第二趟在循环里推进
    #: live_side/spans；这里把同一状态持久化在 context 上（SceneContext 的
    #: ``axis_live_side``/``axis_spans``），规则真源不复制：
    #: `_axis_for_placement` / `establish_axis_from_speakers` /
    #: `pair_spans` / `camera_side_of` 全是主构建同一批函数。
    live_side = getattr(context, "axis_live_side", None)
    spans = dict(getattr(context, "axis_spans", None) or {})
    placed_axis = axis_for_shot(context, shot)
    advanced = set(getattr(context, "axis_advanced_shots", None) or ())
    first_axis_pass = str(shot.shot_id) not in advanced
    if context.axis is None and len(shot.characters) >= 2:
        speakers = [context.characters[cid] for cid in shot.characters[:2]
                    if cid in context.characters]
        if len(speakers) == 2:
            context.axis = establish_axis_from_speakers(speakers,
                                                       bundle.camera)
            if live_side is None:
                live_side = int(context.axis.established_side)
    axis_pair: List[str] = []
    axis_side_sign = 0
    axis_status_value = ""
    if context.axis is not None:
        axis_pair = [str(context.axis.left_label),
                     str(context.axis.right_label)]
        camera_xy = (round(bundle.camera.matrix_world.translation.x, 4),
                     round(bundle.camera.matrix_world.translation.y, 4))
        axis_status_value = str(axis_status(context.axis, camera_xy))
        if not spans:
            spans = pair_spans(context.axis, plan,
                               _initial_cast_positions(context))
        span = spans.get(str(shot.shot_id))
        if span is not None:
            camera_position = bundle.camera.matrix_world.translation
            before_side = camera_side_of(span[0], span[1], camera_position)
            after_side = camera_side_of(span[2], span[3], camera_position)
            axis_side_sign = int(before_side)
            both_in_frame = len(
                [cid for cid in (shot.characters or [])
                 if str(cid) in (context.axis.left_label,
                                 context.axis.right_label)]) >= 2
            if (first_axis_pass and both_in_frame and before_side != 0
                    and after_side != 0 and before_side != after_side):
                current_side = (int(placed_axis.established_side)
                                if placed_axis is not None
                                else int(context.axis.established_side))
                live_side = -current_side
                warnings.append(
                    f"{shot.shot_id}: 连线扫过机位 ⇒ 观众看得见这次换位，"
                    f"从下一镜起改到第 {live_side:+d} 侧")
    if first_axis_pass:
        advanced.add(str(shot.shot_id))
        context.axis_advanced_shots = advanced
    context.axis_live_side = live_side
    context.axis_spans = spans

    # v1.3 诉求 4：标签的公告板与屏幕字号是按镜头烘焙的，换了机位必须重烘，
    # 否则这一镜的标签会沿用旧机位的朝向与大小。
    from ..settings import get_config
    from .label_baking import bake_labels, collect_label_entries

    entries = collect_label_entries(list(context.characters.values()))
    if entries:
        app_config = get_config()
        label_config = app_config.character
        label_report = bake_labels(
            scene, entries, context.schedule, context.cameras,
            target_pixels=float(label_config.label_pixels),
            min_pixels=float(label_config.label_min_pixels),
            max_ratio=float(label_config.label_max_ratio),
            resolution=app_config.delivery.resolution,
            adaptive_sampling=bool(app_config.labels.adaptive_sampling),
            fullframe_verify=bool(app_config.labels.fullframe_verify))
        # v1.6 A7（D-19）：全帧自检的余量进重生成告警，不静默。
        overlap_report = label_report.get("label_overlap_report") or {}
        overlap_frames = list(overlap_report.get("overlap_frames") or [])
        if overlap_frames:
            shown = ", ".join(str(frame) for frame in overlap_frames[:5])
            if len(overlap_frames) > 5:
                shown += " …"
            warnings.append(
                f"标签全帧自检：{len(overlap_frames)} 帧交叠仍超 "
                f"{float(overlap_report.get('limit') or 0.05):g}"
                f"（最高 {float(overlap_report.get('max_overlap_ratio') or 0):.1%}，"
                f"帧 {shown}）")

    log.info("重生成单镜 %s：%d-%d，%d 个关键帧", shot_id, start, end, keyframes)
    #: 逐镜路径的 results 必须与整场构建（``ShotBuildResult.to_dict``）
    #: **同构**——单一真源，不抄第二份精度/字段表。D1 曾在此手写 dict：
    #: 机位 4 位、lens 3 位、缺 ``shot_type/camera_target/characters/
    #: axis_*``，replay 探针按 4 位指纹对比整场与逐镜 results 即红
    #: （2026-10-12 全链实测 -4.6607 vs -4.661）。这里直接复用 dataclass
    #: 序列化；``ok/keyframes/protected`` 是驱动与 UI 消费的额外键，保留。
    target = tuple(bundle.target.location) if bundle.target is not None \
        else (0.0, 0.0, 0.0)
    payload = ShotBuildResult(
        shot_id=shot_id, shot_type=str(shot.shot_type),
        start_frame=start, end_frame=end, camera=bundle.camera.name,
        camera_position=tuple(bundle.camera.location),
        camera_target=target, lens=float(bundle.lens),
        characters=list(shot.characters), motions=len(requests),
        warnings=warnings, axis_pair=axis_pair,
        axis_side_sign=axis_side_sign, axis_status=axis_status_value
    ).to_dict()
    payload["ok"] = True
    payload["keyframes"] = keyframes
    payload["protected"] = protected
    return payload
