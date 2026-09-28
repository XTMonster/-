"""构图分析（执行文档 v1.2 §10.4）。

把角色投影到归一化视口坐标（§17.4 的 ``world_to_camera_view``，返回 [0,1]），
用 ``scene.ray_cast`` 做遮挡检测，再把结果交给纯计算模块评分。
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

import bpy
from bpy_extras.object_utils import world_to_camera_view
from bpy.types import Object
from mathutils import Vector

from ...cinema.composition import (
    CompositionReport,
    SubjectBox,
    evaluate_composition,
)
from ...cinema.framing import SHOT_FRAME, SUBJECT_HEIGHT
from ...utils.logger import get_logger
from ...utils.threading_guard import main_thread_only
from ..collection_router import GUIDES_COLLECTION

log = get_logger("composition")

MAX_RAY_STEPS = 8


def _in_guides(obj: Object) -> bool:
    return any(c.name == GUIDES_COLLECTION for c in obj.users_collection)


def _belongs_to(obj: Object, character) -> bool:
    node: Optional[Object] = obj
    root = getattr(character, "root", None)
    while node is not None:
        if node is root:
            return True
        node = node.parent
    return False


def _world_bounds(character, depsgraph) -> Optional[Tuple[Vector, Vector]]:
    low = [float("inf")] * 3
    high = [float("-inf")] * 3
    found = False
    for obj in getattr(character, "meshes", []):
        evaluated = obj.evaluated_get(depsgraph)
        matrix = evaluated.matrix_world
        for corner in evaluated.bound_box:
            point = matrix @ Vector(corner)
            found = True
            for index in range(3):
                low[index] = min(low[index], point[index])
                high[index] = max(high[index], point[index])
    if not found:
        return None
    return Vector(low), Vector(high)


def _screen_box(character, depsgraph, scene, camera) -> Optional[SubjectBox]:
    bounds = _world_bounds(character, depsgraph)
    if bounds is None:
        return None
    low, high = bounds
    xs: List[float] = []
    ys: List[float] = []
    for ix in (low.x, high.x):
        for iy in (low.y, high.y):
            for iz in (low.z, high.z):
                projected = world_to_camera_view(scene, camera, Vector((ix, iy, iz)))
                xs.append(projected.x)
                ys.append(projected.y)
    return SubjectBox(name=getattr(character, "name", "?"),
                      left=min(xs), right=max(xs),
                      top=max(ys), bottom=min(ys),
                      facing=_screen_facing(character, scene, camera))


def _screen_facing(character, scene, camera) -> float:
    """角色朝向在屏幕空间的水平符号：+1 朝右，-1 朝左，0 无水平朝向。

    必须在**相机空间**里判断：如果角色基本正对或背对镜头，透视会让它在
    屏幕上"偏"向一侧，直接拿投影差值当朝向会把它误判成朝画面外——
    这种情况应当视为没有水平朝向（§10.4 的视线空间不适用）。
    """
    root = getattr(character, "root", None)
    if root is None:
        return 0.0
    yaw = root.matrix_world.to_euler().z
    facing_world = Vector((math.sin(yaw), math.cos(yaw), 0.0))
    basis = camera.matrix_world.to_3x3()
    screen_right = (basis @ Vector((1.0, 0.0, 0.0))).normalized()
    view_forward = (basis @ Vector((0.0, 0.0, -1.0))).normalized()
    horizontal = facing_world.dot(screen_right)
    depth = facing_world.dot(view_forward)
    if abs(depth) > abs(horizontal) * 1.5:
        return 0.0
    if abs(horizontal) < 1e-6:
        return 0.0
    return 1.0 if horizontal > 0 else -1.0


def _blocking_object(scene, depsgraph, camera_pos: Vector,
                     target: Vector, character) -> Optional[str]:
    """从相机向目标投射，返回第一个真正的遮挡物名字。"""
    direction = target - camera_pos
    distance = direction.length
    if distance < 1e-6:
        return None
    unit = direction.normalized()
    travelled = 0.0
    for _ in range(MAX_RAY_STEPS):
        hit, location, _normal, _index, obj, _matrix = scene.ray_cast(
            depsgraph, camera_pos + unit * travelled, unit,
            distance=max(distance - travelled, 1e-4))
        if not hit or obj is None:
            return None
        if _belongs_to(obj, character):
            return None                      # 先打到目标自己：不算遮挡
        if obj.hide_render or _in_guides(obj):
            travelled = (location - camera_pos).length + 1e-3   # 跳过辅助物
            if travelled >= distance:
                return None
            continue
        return obj.name
    return None


@main_thread_only("evaluate_camera_composition")
def evaluate_camera_composition(camera: Object,
                                characters: Sequence,
                                shot_type: str = "MS",
                                check_occlusion: bool = True
                                ) -> CompositionReport:
    """对当前机位做构图评分。"""
    scene = bpy.context.scene
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()

    boxes: List[SubjectBox] = []
    occluded: Dict[str, bool] = {}
    camera_pos = camera.matrix_world.translation.copy()

    for character in characters:
        box = _screen_box(character, depsgraph, scene, camera)
        if box is None:
            continue
        boxes.append(box)
        if check_occlusion:
            bounds = _world_bounds(character, depsgraph)
            if bounds is not None:
                center = (bounds[0] + bounds[1]) / 2.0
                blocker = _blocking_object(scene, depsgraph, camera_pos,
                                           center, character)
                occluded[box.name] = blocker is not None

    frame = SHOT_FRAME.get(str(shot_type).upper())
    expected_height = None
    if frame is not None:
        # 角色在画面里应有的高度占比 = 角色高 / 画面高
        expected_height = max(0.05, min(1.5, SUBJECT_HEIGHT / frame.frame_height))

    report = evaluate_composition(boxes, occluded=occluded or None,
                                  expected_height=expected_height)
    log.info("构图评分：%.1f（%s）", report.score,
             "通过" if report.passed else "需调整")
    return report
