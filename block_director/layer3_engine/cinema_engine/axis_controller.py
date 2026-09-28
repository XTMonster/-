"""轴线控制器（执行文档 v1.2 §10.3）。

纯算法在 ``block_director/cinema/axis.py``；本模块把它接到场景：
从角色位置取轴线、用首镜机位确立基准侧、检查越轴、并在视口画出来。
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import bpy
from bpy.types import Object

from ...cinema.axis import (
    Axis,
    axis_for_speakers,
    axis_violation,
    establish_axis,
)
from ...utils.logger import get_logger
from ...utils.threading_guard import main_thread_only
from ..collection_router import mark_as_guide

log = get_logger("axis")

AXIS_COLOR = (0.2, 1.0, 0.3, 1.0)     # 视口里的绿色虚线（§10.3）


def _world_xy(obj: Object) -> Tuple[float, float]:
    location = obj.matrix_world.translation
    return (round(location.x, 4), round(location.y, 4))


@main_thread_only("establish_axis_from_speakers")
def establish_axis_from_speakers(speakers: Sequence,
                                 camera: Optional[Object] = None) -> Optional[Axis]:
    """用当前说话的两人建立轴线，并以给定机位确立基准侧（首镜）。"""
    bpy.context.view_layer.update()
    pairs: List[Tuple[Tuple[float, float], str]] = []
    for character in speakers:
        root = getattr(character, "root", None)
        if root is None:
            continue
        pairs.append((_world_xy(root), getattr(character, "name", "")))
    axis = axis_for_speakers(pairs)
    if axis is None:
        return None
    if camera is not None:
        camera_xy = _world_xy(camera)
        axis = establish_axis(axis, camera_xy)
        log.info("轴线已确立：%s → %s，基准侧 %+d",
                 axis.left_label, axis.right_label, axis.established_side)
    return axis


@main_thread_only("check_camera_axis")
def check_camera_axis(axis: Axis, camera: Object) -> Optional[str]:
    """返回越轴说明；合规返回 None。"""
    bpy.context.view_layer.update()
    return axis_violation(axis, _world_xy(camera))


@main_thread_only("visualize_axis")
def visualize_axis(axis: Axis, name: str = "BD_Axis_scene_001",
                   length: float = 6.0) -> Object:
    """把轴线画成一条视角参考线，放进 Guides（不参与渲染）。"""
    existing = bpy.data.objects.get(name)
    if existing is not None:
        bpy.data.objects.remove(existing, do_unlink=True)

    dx, dy = axis.direction
    if dx == 0.0 and dy == 0.0:
        dx, dy = 1.0, 0.0
    cx = (axis.start[0] + axis.end[0]) / 2.0
    cy = (axis.start[1] + axis.end[1]) / 2.0
    half = max(length, axis.length) / 2.0
    points = [(-dx * half, -dy * half), (dx * half, dy * half)]

    mesh = bpy.data.meshes.new(f"{name}_mesh")
    mesh.from_pydata([(cx + px, cy + py, 0.02) for px, py in points], [],
                     [(0, 1)])
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    material = bpy.data.materials.get("BD_Mat_Axis")
    if material is None:
        material = bpy.data.materials.new("BD_Mat_Axis")
    material.diffuse_color = AXIS_COLOR
    mesh.materials.append(material)
    obj["bd_element_type"] = "axis"
    return mark_as_guide(obj)
