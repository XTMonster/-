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
from .shot_builder import (action_requests, conflict_warnings,
                           live_subject_entries, place_shot_camera)

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

    # v1.3 诉求 4：标签的公告板与屏幕字号是按镜头烘焙的，换了机位必须重烘，
    # 否则这一镜的标签会沿用旧机位的朝向与大小。
    from ..settings import get_config
    from .label_baking import bake_labels, collect_label_entries

    entries = collect_label_entries(list(context.characters.values()))
    if entries:
        label_config = get_config().character
        bake_labels(scene, entries, context.schedule, context.cameras,
                    target_pixels=float(label_config.label_pixels),
                    min_pixels=float(label_config.label_min_pixels),
                    max_ratio=float(label_config.label_max_ratio),
                    resolution=get_config().delivery.resolution)

    log.info("重生成单镜 %s：%d-%d，%d 个关键帧", shot_id, start, end, keyframes)
    return {"ok": True, "shot_id": shot_id, "start_frame": start,
            "end_frame": end, "camera": bundle.camera.name,
            "camera_position": [round(v, 4) for v in bundle.camera.location],
            "lens": round(float(bundle.lens), 3),
            "motions": len(requests), "keyframes": keyframes,
            "protected": protected, "warnings": warnings}
