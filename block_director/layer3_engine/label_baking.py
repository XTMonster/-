"""渲染标签的构建期烘焙（v1.3 诉求 4）。

参考视频里的角色标签有两条硬要求：**跟着角色**、**任何景别都看得清**。
两者都靠在这里逐帧烘焙世界变换实现，而**不依赖渲染期的 handler**：

* 跟随：每帧取 LabelAnchor 的世界位置；
* 朝向：取当前镜头相机的世界旋转（公告板）；
* 字号：**屏幕恒定**——按"锚点到相机的距离"反算世界高度，
  使投影后的像素高度落在 ``[min_pixels, target_pixels]`` 区间，
  上限再按画面高度的一个比例夹住，避免大远景里标签大得离谱；
* 避让：锚点投影出画时把它推回画内；被前景挡住时上移一档。

采样步长默认 4 帧：相机在 v1.3 里基本是静态的，4 帧步长 + 贝塞尔插值
足够平滑，而每帧每标签写三条曲线会平白多出几万个关键帧。
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

from ..utils.logger import get_logger
from ..utils.threading_guard import main_thread_only
from .character_system.character_label import (
    LABEL_STROKE_BACK,
    LABEL_STROKE_SCALE,
)

log = get_logger("label-bake")

DEFAULT_SAMPLE_STEP = 4
DEFAULT_TARGET_PIXELS = 30.0
DEFAULT_MIN_PIXELS = 24.0
DEFAULT_MAX_RATIO = 0.06
FRAME_MARGIN = 0.06          # 画内安全边距（占画面比例）


def _camera_frame_height(distance: float, lens: float,
                         sensor_width: float = 36.0,
                         aspect: float = 16.0 / 9.0) -> float:
    """距离 ``distance`` 处画面的世界高度。"""
    sensor_height = float(sensor_width) / float(aspect)
    vfov = 2.0 * math.atan(sensor_height / (2.0 * float(lens)))
    return 2.0 * distance * math.tan(vfov / 2.0)


def _unit_pixel_height(scene, camera, position: Vector, up: Vector,
                       size: float, resolution_y: float) -> float:
    """单位缩放下，标签在屏幕上的像素高度。

    两个端点由 **(位置 ± 相机上方向 × size/2)** 解析构造，而不是去读对象
    ``matrix_world``：对象一旦有关键帧，``view_layer.update()`` 就会用动画值
    覆盖手动设的单位缩放，量出来的基准会跟着上一帧跑（实测偏差三成）。
    几何解算（按视场角反推）也不可靠——``sensor_fit=AUTO`` 与离轴投影都会
    带来同样的偏差，所以这里用引擎自己的投影函数量。
    """
    half = float(size) / 2.0
    top = position + up * half
    bottom = position - up * half
    projected_top = world_to_camera_view(scene, camera, top)
    projected_bottom = world_to_camera_view(scene, camera, bottom)
    return abs(projected_top.y - projected_bottom.y) * float(resolution_y)


def _sample_frames(schedule: Dict[str, Tuple[int, int]],
                   step: int) -> List[int]:
    frames: List[int] = []
    for start, end in schedule.values():
        cursor = int(start)
        while cursor < int(end):
            frames.append(cursor)
            cursor += max(int(step), 1)
        frames.append(int(end))
    return sorted(set(frames))


def _shot_at(schedule: Dict[str, Tuple[int, int]], frame: int
             ) -> Optional[str]:
    for shot_id, (start, end) in schedule.items():
        if int(start) <= frame <= int(end):
            return shot_id
    return None


@main_thread_only("collect_label_entries")
def collect_label_entries(characters: Sequence[Any]) -> List[Dict[str, Any]]:
    """从场景里找回已存在的渲染标签。

    单镜再生会换掉相机，标签的公告板与字号必须跟着重烘；而重生成路径里
    没有"创建标签"的那份局部状态，所以按命名约定找回它们。
    """
    entries: List[Dict[str, Any]] = []
    for character in characters or ():
        character_id = str(getattr(character, "id", "") or "")
        if not character_id:
            continue
        fill = bpy.data.objects.get(f"BD_Label_{character_id}_Fill")
        if fill is None:
            continue
        entries.append({
            "character_id": character_id,
            "fill": fill,
            "stroke": bpy.data.objects.get(f"BD_Label_{character_id}_Stroke"),
            "anchor": getattr(character, "label_anchor", None),
        })
    return entries


@main_thread_only("bake_labels")
def bake_labels(scene, entries: Sequence[Dict[str, Any]],
                schedule: Dict[str, Tuple[int, int]],
                cameras: Dict[str, Any], *,
                sample_step: int = DEFAULT_SAMPLE_STEP,
                target_pixels: float = DEFAULT_TARGET_PIXELS,
                min_pixels: float = DEFAULT_MIN_PIXELS,
                max_ratio: float = DEFAULT_MAX_RATIO,
                resolution: Sequence[int] = (1280, 720)) -> Dict[str, Any]:
    """给渲染标签烘焙逐帧变换；返回一份可写进交付报告的摘要。"""
    if not entries or not schedule or not cameras:
        return {"labels": 0, "frames": 0, "unreadable": []}

    res_y = float(max(int(resolution[1]), 1))
    res_x = float(max(int(resolution[0]), 1))
    aspect = res_x / res_y
    frames = _sample_frames(schedule, sample_step)
    unreadable: List[Dict[str, Any]] = []
    written = 0

    for entry in entries:
        fill = entry.get("fill")
        stroke = entry.get("stroke")
        anchor = entry.get("anchor")
        character_id = str(entry.get("character_id") or "")
        if fill is None or anchor is None:
            continue
        base_size = float(getattr(fill.data, "size", 1.0) or 1.0)

        for frame in frames:
            shot_id = _shot_at(schedule, frame)
            camera = cameras.get(shot_id) if shot_id else None
            if camera is None:
                continue
            scene.frame_set(frame)
            bpy.context.view_layer.update()

            anchor_world = anchor.matrix_world.translation.copy()
            cam_world = camera.matrix_world.translation.copy()
            distance = max((anchor_world - cam_world).length, 1e-3)
            lens = float(camera.data.lens) or 50.0
            frame_height = _camera_frame_height(distance, lens,
                                                aspect=aspect)

            position = anchor_world
            rotation = camera.matrix_world.to_euler()
            right, up = _camera_axes(camera)
            # 先在单位缩放下量一次真实像素高度，再按比例反解（见
            # _unit_pixel_height 的说明）。这样"屏幕恒定字号"由构造保证，
            # 也与交付时用同一套投影量出来的结果一致。
            px_at_unit = _unit_pixel_height(scene, camera, position, up,
                                            base_size, res_y)

            max_pixels = max(max_ratio * res_y, min_pixels)
            wanted_pixels = min(max(target_pixels, min_pixels), max_pixels)
            if px_at_unit <= 1e-6:
                scale = 1.0
                unreadable.append({"character_id": character_id,
                                   "frame": frame, "reason": "投影退化"})
            else:
                scale = wanted_pixels / px_at_unit
            if scale * px_at_unit < min_pixels - 1e-6:
                unreadable.append({"character_id": character_id,
                                   "frame": frame, "reason": "低于可读下限"})

            # 避让：锚点投影出画时推回画内
            projected = world_to_camera_view(scene, camera, anchor_world)
            offset = Vector((0.0, 0.0, 0.0))
            if not (FRAME_MARGIN <= projected.x <= 1.0 - FRAME_MARGIN
                    and FRAME_MARGIN <= projected.y <= 1.0 - FRAME_MARGIN):
                target_x = min(max(projected.x, FRAME_MARGIN),
                               1.0 - FRAME_MARGIN)
                target_y = min(max(projected.y, FRAME_MARGIN),
                               1.0 - FRAME_MARGIN)
                offset += right * ((target_x - projected.x)
                                   * frame_height * aspect)
                offset += up * ((target_y - projected.y) * frame_height)
            # 遮挡：相机到锚点之间被内容物挡住时上移一档
            if _blocked(scene, camera, anchor_world):
                offset += up * (frame_height * 0.20)
            position = position + offset

            _write(fill, position, rotation, scale, camera, frame)
            if stroke is not None:
                back = (camera.matrix_world.to_3x3() @
                        Vector((0.0, 0.0, -LABEL_STROKE_BACK)))
                _write(stroke, position + back, rotation,
                       scale * LABEL_STROKE_SCALE, camera, frame)
            written += 1

    log.info("标签烘焙完成：%d 个标签 / %d 帧采样", len(entries), written)
    return {"labels": len(entries), "frames": written,
            "sample_step": int(sample_step), "resolution": [int(res_x),
                                                            int(res_y)],
            "unreadable": unreadable}


def _camera_axes(camera) -> Tuple[Vector, Vector]:
    matrix = camera.matrix_world.to_3x3()
    right = (matrix @ Vector((1.0, 0.0, 0.0))).normalized()
    up = (matrix @ Vector((0.0, 1.0, 0.0))).normalized()
    return right, up


def _blocked(scene, camera, point: Vector) -> bool:
    origin = camera.matrix_world.translation
    direction = point - origin
    distance = direction.length
    if distance <= 1e-6:
        return False
    hit, location, _normal, _index, hit_object, _matrix = scene.ray_cast(
        bpy.context.view_layer.depsgraph, origin,
        direction.normalized(), distance=distance)
    if not hit:
        return False
    name = getattr(hit_object, "name", "") if hit_object is not None else ""
    return bool(name) and name.startswith("BD_") and not name.startswith("BD_Label")


def _write(obj, position: Vector, rotation, scale: float,
           camera, frame: int) -> None:
    obj.location = position
    obj.rotation_euler = rotation
    obj.scale = (scale, scale, scale)
    obj.keyframe_insert("location", frame=frame)
    obj.keyframe_insert("rotation_euler", frame=frame)
    obj.keyframe_insert("scale", frame=frame)
