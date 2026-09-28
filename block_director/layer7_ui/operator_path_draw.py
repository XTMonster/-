"""画线工具（执行文档 v1.2 §9.5 / §13.5）。

用户在视口里拖出一条折线 → RDP 简化 → Catmull-Rom 平滑 → 生成位置关键帧与
沿线切线的朝向，并保留一条 ``BD_Path_*`` **曲线对象**（可编辑后重新生成动画）。

两段式实现，是刻意的：

- **交互**（``invoke``/``modal``）只负责采集点：射线投射到 Z=0 地面平面；
- **落地**（:func:`commit_drawn_path`）是普通函数，输入点列、输出路径对象与
  关键帧——没有鼠标也能调用，因此可以在 headless 里测试。

红线同 §9.5：路径曲线属于辅助物，放 ``BlockDirector/Guides``，**不入渲染**。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import bpy
from bpy.props import FloatProperty, StringProperty
from bpy.types import Operator
from mathutils import Vector

from ..layer3_engine.collection_router import GUIDES_COLLECTION
from ..layer3_engine.scene_context import get_context
from ..motion.path import (
    RDP_EPSILON,
    SAMPLES_PER_SEGMENT,
    facing_along,
    path_length,
    simplify_and_smooth,
)
from ..settings import get_config
from ..utils.geometry import facing_to_rotation_z
from ..utils.logger import get_logger
from ..utils.threading_guard import main_thread_only

log = get_logger("path-draw")

GROUND_Z = 0.0
MIN_SPACING = 0.05          # 采样最小间距（米），过滤手抖


def _guides_collection():
    collection = bpy.data.collections.get(GUIDES_COLLECTION)
    if collection is None:
        collection = bpy.data.collections.new(GUIDES_COLLECTION)
        bpy.context.scene.collection.children.link(collection)
    return collection


@main_thread_only("create_path_curve")
def create_path_curve(character_id: str, points: Sequence[Sequence[float]],
                      index: int = 1):
    """把点列做成一条 Guides 里的 POLY 曲线（可编辑、不渲染）。"""
    curve = bpy.data.curves.new(f"BD_Path_{character_id}_{index:03d}",
                                type='CURVE')
    curve.dimensions = '3D'
    spline = curve.splines.new('POLY')
    spline.points.add(len(points) - 1)
    for point, value in zip(spline.points, points):
        point.co = (float(value[0]), float(value[1]), float(value[2]), 1.0)
    obj = bpy.data.objects.new(curve.name, curve)
    obj.hide_render = True                     # §9.5：辅助物绝不入渲染
    _guides_collection().objects.link(obj)
    return obj


@main_thread_only("commit_drawn_path")
def commit_drawn_path(points: Sequence[Sequence[float]], *, character_id: str,
                      start_frame: int = 1, fps: int = 24,
                      epsilon: float = RDP_EPSILON,
                      samples_per_segment: int = SAMPLES_PER_SEGMENT,
                      context=None) -> Dict[str, Any]:
    """把画出来的折线落成"路径曲线 + 角色关键帧"（§9.5）。"""
    frame_context = context or get_context()
    if frame_context is None:
        raise ValueError("当前没有 BlockDirector 场景上下文；请先构建一次场景")
    character = frame_context.character(character_id)
    if character is None:
        known = ", ".join(sorted(frame_context.characters)) or "（无）"
        raise ValueError(f"找不到角色 {character_id}。可用角色: {known}")

    raw = [(float(p[0]), float(p[1]), float(p[2])) for p in points]
    if len(raw) < 2:
        raise ValueError("至少要两个点才能生成路径")

    simplified = simplify_and_smooth(raw, epsilon=epsilon,
                                     samples_per_segment=samples_per_segment)
    total = path_length(simplified)
    speed = float(get_config().animation.walk_speed) or 0.05
    frames = max(int(round(total / speed)), 1)
    end_frame = int(start_frame) + frames

    curve = create_path_curve(character_id, simplified)

    # 沿路径给位置与朝向关键帧：位置直接取平滑后的采样点，朝向取切线
    facings = facing_along(simplified)
    root = character.root
    step = max(len(simplified) // max(frames, 1), 1)
    inserted = 0
    for index in range(0, len(simplified), step):
        point = simplified[index]
        frame = int(start_frame) + int(round(index / max(len(simplified) - 1, 1)
                                             * frames))
        root.location = (point[0], point[1], root.location.z)
        root.rotation_euler[2] = facing_to_rotation_z(facings[index])
        root.keyframe_insert(data_path="location", frame=frame)
        root.keyframe_insert(data_path="rotation_euler", index=2, frame=frame)
        inserted += 2

    log.info("画线落成：%d 点 → %d 采样点，%d 帧，%d 个关键帧",
             len(raw), len(simplified), frames, inserted)
    return {"ok": True, "character_id": character_id,
            "path_object": curve.name, "raw_points": len(raw),
            "points": len(simplified), "start_frame": int(start_frame),
            "end_frame": end_frame, "frames": frames,
            "length": round(total, 4), "keyframes": inserted}


def _ground_point(context, event) -> Optional[Tuple[float, float, float]]:
    """把鼠标位置射线投射到 Z=0 地面平面上。"""
    from bpy_extras.view3d_utils import region_2d_to_origin_3d, region_2d_to_vector_3d

    region = context.region
    region_data = context.region_data
    coord = (event.mouse_region_x, event.mouse_region_y)
    origin = region_2d_to_origin_3d(region, region_data, coord)
    direction = region_2d_to_vector_3d(region, region_data, coord)
    if abs(direction.z) < 1e-6:
        return None
    t = (GROUND_Z - origin.z) / direction.z
    if t <= 0:
        return None
    hit = origin + direction * t
    return (hit.x, hit.y, GROUND_Z)


class BLOCKDIRECTOR_OT_draw_path(Operator):
    """在视口里拖出一条走位路径（§9.5）。"""

    bl_idname = "blockdirector.draw_path"
    bl_label = "画走位路径"
    bl_description = "按住左键在地面上拖出路径，回车确认 / ESC 取消"
    bl_options = {'REGISTER', 'UNDO'}

    character_id: StringProperty(name="角色", default="")
    start_frame: FloatProperty(name="起始帧", default=1.0, min=1.0)

    def invoke(self, context, event):         # pragma: no cover - 需交互
        if context.area is None or context.area.type != 'VIEW_3D':
            self.report({'ERROR'}, "请在 3D 视口里使用画线工具")
            return {'CANCELLED'}
        self._points: List[Tuple[float, float, float]] = []
        context.window_manager.modal_handler_add(self)
        self.report({'INFO'}, "拖出路径，回车确认")
        return {'RUNNING_MODAL'}

    def modal(self, context, event):          # pragma: no cover - 需交互
        if event.type in {'RIGHTMOUSE', 'ESC'}:
            self._points = []
            return {'CANCELLED'}
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            point = _ground_point(context, event)
            if point is not None:
                if (not self._points
                        or Vector(point).distance(
                            Vector(self._points[-1])) >= MIN_SPACING):
                    self._points.append(point)
            return {'RUNNING_MODAL'}
        if event.type in {'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
            return self._finish(context)
        return {'RUNNING_MODAL'}

    def _finish(self, context):               # pragma: no cover - 需交互
        character_id = self.character_id
        scene_context = get_context()
        if not character_id:
            characters = sorted(scene_context.characters) if scene_context else []
            if not characters:
                self.report({'ERROR'}, "场景里没有可用的角色")
                return {'CANCELLED'}
            character_id = characters[0]
        try:
            report = commit_drawn_path(self._points, character_id=character_id,
                                       start_frame=int(self.start_frame))
        except ValueError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        self.report({'INFO'}, f"路径 {report['path_object']}："
                              f"{report['points']} 点 / {report['frames']} 帧")
        return {'FINISHED'}


CLASSES = (BLOCKDIRECTOR_OT_draw_path,)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:  # noqa: BLE001
            log.warning("注销 %s 失败", cls.__name__)
