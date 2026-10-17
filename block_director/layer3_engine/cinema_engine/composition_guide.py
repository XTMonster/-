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
from ...cinema.framing import ASPECT_16_9, SHOT_FRAME, SUBJECT_HEIGHT
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


#: 射线命中对象 → 面级遮挡类别（``None`` = 非渲染基建，不当遮挡）。
#: 采样器（``frustum_sampler``）与审核器（``shot_auditor``）的**唯一分类源**；
#: 谁要归类都从 ``occluder_class`` 取，禁止抄第二份闭集。
INFRASTRUCTURE_TYPES = frozenset(
    {"camera", "axis", "label", "label_render"})
CHARACTER_TYPES = frozenset(
    {"character_part", "character_root", "leg_pivot"})


def occluder_class(blocker, characters=None,
                   *, character_types=CHARACTER_TYPES,
                   infrastructure_types=INFRASTRUCTURE_TYPES,
                   belongs_to=None) -> Optional[str]:
    """``bd_element_type`` 沿父链归类命中对象；返回 None 表示非渲染基建。

    归类是渲染语义（crowd/prop/vfx/environment 与角色 id 都要送进证据），
    放在 bpy 侧模块（composition_guide）里；纯层只消费闭集字符串。
    ``characters`` 缺省为空 dict——没有角色表时，``character_part`` 命中
    对象归成不带 id 的 ``"角色"``（不猜归属）。
    """
    from ...cinema.mesh_visibility import (
        OCCLUDER_CHARACTER,
        OCCLUDER_CROWD,
        OCCLUDER_ENVIRONMENT,
        OCCLUDER_PROP,
        OCCLUDER_UNKNOWN,
        OCCLUDER_VFX,
    )

    node = blocker
    while node is not None:
        kind = str(node.get("bd_element_type", "") or "")
        if kind in character_types:
            for character_id, character in (characters or {}).items():
                if (belongs_to or _belongs_to)(node, character):
                    return f"{OCCLUDER_CHARACTER}:{character_id}"
            return OCCLUDER_CHARACTER
        if kind == "crowd":
            return OCCLUDER_CROWD
        if kind == "prop":
            prop_id = str(node.get("bd_sdl_id", "") or "")
            return (f"{OCCLUDER_PROP}:{prop_id}" if prop_id
                    else OCCLUDER_PROP)
        if kind == "vfx":
            return OCCLUDER_VFX
        if kind == "environment":
            return OCCLUDER_ENVIRONMENT
        if kind in infrastructure_types:
            return None
        node = node.parent
    return OCCLUDER_UNKNOWN


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


def intended_window(shot_type: str) -> Optional[Tuple[float, float]]:
    """这个景别**打算**看到的高度范围（世界单位）：``target_z ± frame_height/2``。

    §10.5 的取景表描述的是"该看到哪一段"，而不是"整身都在画里"。构图的
    headroom / framing 只有在这个窗口内评估才说得通——否则 CU 会被按整身判
    "主体出画、头顶被切"，把正常裁切当成错误。
    """
    frame = SHOT_FRAME.get(str(shot_type).upper())
    if frame is None:
        return None
    half = frame.frame_height / 2.0
    return (frame.target_z - half, frame.target_z + half)


def _clip_to_window(low: Vector, high: Vector,
                    window: Optional[Tuple[float, float]]
                    ) -> Tuple[Vector, Vector, bool]:
    """把包围盒按高度窗口裁一刀；完全落在窗口外就退回整身。"""
    if window is None:
        return low, high, False
    win_low, win_high = window
    sliced_low = max(low.z, win_low)
    sliced_high = min(high.z, win_high)
    if sliced_high <= sliced_low:
        return low, high, False
    return (Vector((low.x, low.y, sliced_low)),
            Vector((high.x, high.y, sliced_high)),
            high.z > win_high)


def _project_bounds(low: Vector, high: Vector, character, scene,
                    camera) -> SubjectBox:
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


def _screen_box(character, depsgraph, scene, camera,
                shot_type: str = ""
                ) -> Optional[SubjectBox]:
    bounds = _world_bounds(character, depsgraph)
    if bounds is None:
        return None
    frame = SHOT_FRAME.get(str(shot_type).upper())
    clipped_sides = False
    window = intended_window(shot_type)
    low, high, clipped_top = _clip_to_window(bounds[0], bounds[1], window)
    if frame is not None:
        # 主体比这个景别的画面还宽 → 左右本来就是该出画的（ECU 的"局部占满"）
        clipped_sides = (high.x - low.x) > frame.frame_height * ASPECT_16_9
    box = _project_bounds(low, high, character, scene, camera)
    box.clipped_top = clipped_top
    box.clipped_sides = clipped_sides
    return box


def _screen_facing(character, scene, camera) -> float:
    """角色朝向在屏幕空间的水平符号：+1 朝右，-1 朝左，0 无水平朝向。

    必须在**相机空间**里判断：如果角色基本正对或背对镜头，透视会让它在
    屏幕上"偏"向一侧，直接拿投影差值当朝向会把它误判成朝画面外——
    这种情况应当视为没有水平朝向（§10.4 的视线空间不适用）。
    """
    root = getattr(character, "root", None)
    if root is None:
        return 0.0
    #: 朝向**必须**用 `utils/geometry.py` 的唯一真源回读：角色的正面是局部 +Y，
    #: 绕 Z 转 θ 之后世界朝向是 ``(-sin θ, cos θ)``（`facing_to_rotation_z` 的
    #: 逆）。这里曾经写成 ``(sin θ, cos θ)``——少了那个负号，于是**朝向被镜像**：
    #: 声明面朝 +X 的角色在评分模型眼里面朝 −X，`lead_room` 于是奖励**错的**那一侧
    #: （实测 2026-10-04：同一机位下把主体放到正确三分线，该分项从 0.77 掉到 0.0）。
    from ...utils.geometry import rotation_z_to_facing

    yaw = root.matrix_world.to_euler().z
    facing_world = Vector(rotation_z_to_facing(yaw))
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
    frame = SHOT_FRAME.get(str(shot_type).upper())
    for character in characters:
        # 构图分项只看"这个景别该看到的那一段"；遮挡仍看整身。
        box = _screen_box(character, depsgraph, scene, camera, shot_type)
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

    expected_height = None
    headroom_applies = False
    if frame is not None:
        # 窗口内那一段在画面里应有的高度占比。景别紧到装不下整身时，
        # 该看到的就是整幅画面（比例 1.0），而不是 >1 的"整身/画面"。
        visible = min(SUBJECT_HEIGHT, frame.frame_height)
        expected_height = max(0.05, visible / frame.frame_height)
        # 头顶留白只对"比全身更紧"的景别有意义
        headroom_applies = frame.frame_height <= SUBJECT_HEIGHT

    report = evaluate_composition(boxes, occluded=occluded or None,
                                  expected_height=expected_height,
                                  headroom_applies=headroom_applies)
    log.info("构图评分：%.1f（%s）", report.score,
             "通过" if report.passed else "需调整")
    return report
