"""视锥采样器（v1.6 B3，FR-C1 引擎层；TDD §4.2）。

把一镜的帧时间轴变成 ``List[FrameSample]``，喂给纯层
:mod:`..cinema.frustum_metrics`。职责边界（卡 B3 红线）：

* **只采样、不判定**——告警判定全部在纯层 ``frustum_metrics``；本模块不产出
  ``GuardWarning``、不写审计；
* **只读场景，不改渲染设置**——不碰 ``scene.render``、``scene.camera`` 与
  ``view_layer`` 的任何渲染字段；
* 采样后**必须还原当前帧**（``finally`` 保证，异常路径同样还原）；
* 采样失败一律抛 :class:`SamplingError`（携带 ``E_GUARD_001``），
  **绝不静默吞掉**。

可见比例之外还累计**外来遮挡物的类别归因**：每条射线首交的"非基建、非本
主体"对象沿父链折成语义类别（角色/群众/道具/特效/环境/未知遮挡物，可带 id），
按帧写进 ``FrameSample.occlusion_by_class``（占 N=9 采样点的比例）。纯层
``compare_with_intent`` 的 occlusion 告警把同一镜头帧段的归因合并进
``GuardWarning.evidence``，让"主体被挡"不再是匿名读数。

实现要点（TDD §4.2 / 卡 B3 钉死）：

* 投影**只用** ``bpy_extras.object_utils.world_to_camera_view``
  （已封装 shift/焦距/像素比；禁止手写投影矩阵）；
* 每帧 ``scene.frame_set(f)`` → ``evaluated_depsgraph_get()``，主体包围盒与相机
  一律读 **depsgraph 求值后**的状态（``obj.evaluated_get(dg).matrix_world``，
  相机也传 ``camera.evaluated_get(dg)`` 给投影函数）；
* 8 个包围盒角点任一 ``z < 0`` → ``behind_camera=True``（投影失效，单列；
  此时不再做射线采样，``visible_ratio=0.0``——纯层只按 ``behind_camera`` 判，
  不消费该值）；
* 可见比例：N=9 个采样点逐点 ``scene.ray_cast(dg, cam_pos, dir)``；命中对象
  归属主体（父链到 root，复用 composition_guide 的 ``_belongs_to``）且
  ``|命中距离 - 目标距离| <= 0.05 m`` 计可见；可见比例 = 可见点数 / 9；
* 采样点优先落在角色的**真实可见表面**（躯干圆柱 3×2 + 头球 3，见
  :func:`_real_surface_points`）——v1.6 B3 修复：含眼球的 AABB 朝机面在
  空处（默认几何下 ``y = ±0.3145``，躯干前表面只有 ``y = ±0.25``，差
  0.0645 m > 0.05 容差），9 条射线全部落空、真实角色恒量成 invisible；
  没有 body/head 部件的通用主体（如测试立方体）回退到 AABB 朝机面的 3×3
  网格（旧路径，立方体的 AABB 面就是它的真实表面）；
* ``extra_frames``：相机/主体动画关键帧 ±1（事件帧加密），与显式传入的
  ``extra_frames`` 取并集、夹回镜头区间；默认步长 = ``config.guard.sample_step``
  （``settings.get_config()``，与 UI/面板同一个真源）；
* 采样帧集 = ``range(start, end+1, step)`` ∪ {末帧} ∪ 关键帧邻域 ∪ 显式
  extra_frames（末帧必采样——出画/离场事件需要时间轴终点）。

已知边界（调研报告 §2，如实记录，不改判据）：N=9 表面点仍不是主体像素的均匀
采样，顶视机位（朝机方向与躯干轴平行）等极端摆放下射线首交点可能先落在顶面/
边棱，"可见比例 0 才标 high"是纯层对这一口径的配套设计；本模块不把近似当精确
像素裁切率。
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Tuple

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

from ..cinema.composition import SubjectBox
from ..cinema.frustum_metrics import FrameSample
from ..cinema.spatial_digest import (
    SpatialCamera,
    SpatialElement,
    SpatialFrame,
    aabb_gap,
)
from ..contracts.enums import ErrorCode
from ..settings import get_config
from ..utils.blender_compat import action_fcurves
from ..utils.logger import get_logger
from ..utils.threading_guard import main_thread_only
from .cinema_engine.composition_guide import (
    MAX_RAY_STEPS,
    _belongs_to,
    _in_guides,
    _world_bounds,
    occluder_class,
)
from .character_system.character_factory import get_facing
from .rule_checker import OBSTACLE_PREFIXES, screen_facing_for
from .scene_context import get_context

log = get_logger("frustum-sampler")

#: 采样失败错误码。单一真源是 ``contracts/enums.py::ErrorCode.GUARD_001``
#: （v1.6 B3 注册行已落地）；这里只派生，不再手抄第二份字面量。
GUARD_001_CODE = str(ErrorCode.GUARD_001)

#: 包围盒表面可见性采样点数（TDD §4.2 钉死）。
VISIBLE_SAMPLE_POINTS = 9

#: 射线命中距离 vs 目标距离的容差（米）（TDD §4.2 钉死）。
RAY_TOLERANCE_M = 0.05

#: 屏幕朝向的数值零点（沿用 composition_guide._screen_facing 的口径）。
FACING_EPS = 1e-6

#: 真实表面采样的方位展开角（弧度）：3 列 = 朝机方向 ± SURFACE_SPREAD。
SURFACE_SPREAD = 0.35

#: 躯干两行在轴向的偏移（相对躯干半高）。
TORSO_ROW_RATIO = 0.25


class SamplingError(RuntimeError):
    """采样失败（E_GUARD_001）。采样器唯一对外的异常通道。"""

    def __init__(self, message: str) -> None:
        super().__init__(f"[{GUARD_001_CODE}] {message}")
        self.code = GUARD_001_CODE
        self.message = message


def _subject_id(subject) -> str:
    return str(getattr(subject, "id", "")
               or getattr(subject, "name", "") or "?")


def _shot_span(shot_id: str, context) -> Tuple[int, int]:
    """这一镜的 ``(起, 止)``；拿不到就抛 :class:`SamplingError`。"""
    span = (context.schedule or {}).get(shot_id)
    if not span or len(span) < 2:
        raise SamplingError(f"场景里没有镜头 {shot_id} 的帧区间")
    start, end = int(span[0]), int(span[1])
    if end < start:
        raise SamplingError(f"镜头 {shot_id} 帧区间非法：{span!r}")
    return start, end


def _sample_frames(start: int, end: int, step: int,
                   extra_frames: Iterable[int],
                   keyframes: Iterable[int]) -> List[int]:
    """采样帧集：步长网格 ∪ 末帧 ∪ 关键帧邻域 ∪ 显式 extra_frames。"""
    frames = set(range(start, end + 1, step))
    frames.add(end)
    for extra in extra_frames:
        try:
            frame = int(extra)
        except (TypeError, ValueError) as exc:
            raise SamplingError(f"非法 extra_frames 元素 {extra!r}") from exc
        if start <= frame <= end:
            frames.add(frame)
    frames.update(int(frame) for frame in keyframes
                  if start <= int(frame) <= end)
    return sorted(frames)


def _require_perspective(shot_id: str, camera) -> None:
    """卡 V11：相机类型不是 ``PERSP`` 就直接抛 :class:`SamplingError`。"""
    camera_type = str(getattr(getattr(camera, "data", None), "type", "")
                      or "")
    if camera_type != "PERSP":
        raise SamplingError(
            f"镜头 {shot_id} 相机 {getattr(camera, 'name', '?')} 类型为 "
            f"{camera_type or '（无）'}，不是 PERSP，无法做透视投影")


def _pair_collisions(bounds_map: Dict[str, Tuple[Vector, Vector]]
                     ) -> List[Dict[str, Any]]:
    """本帧角色×角色 AABB 间隙（``{pair, gap}``，浮点 3 位）。"""
    pairs: List[Dict[str, Any]] = []
    ids = sorted(bounds_map)
    for first in range(len(ids)):
        for second in range(first + 1, len(ids)):
            low_a, high_a = bounds_map[ids[first]]
            low_b, high_b = bounds_map[ids[second]]
            gap = aabb_gap(tuple(low_a), tuple(high_a),
                           tuple(low_b), tuple(high_b))
            pairs.append({"pair": [ids[first], ids[second]],
                          "gap": round(float(gap), 3)})
    return pairs


def _object_world_bounds(evaluated) -> Optional[Tuple[Vector, Vector]]:
    """单个求值后对象的 bound_box → 世界 AABB；空盒返回 ``None``。"""
    bound_box = getattr(evaluated, "bound_box", None)
    if not bound_box:
        return None
    low = [float("inf")] * 3
    high = [float("-inf")] * 3
    matrix = evaluated.matrix_world
    for corner in bound_box:
        point = matrix @ Vector(corner)
        for index in range(3):
            low[index] = min(low[index], point[index])
            high[index] = max(high[index], point[index])
    return Vector(low), Vector(high)


def _shot_objects(shot_id: str, context) -> List[object]:
    """本镜的相机（对象 + 数据）与全部主体的动画载体。"""
    objects: List[object] = []
    camera = context.camera_for(shot_id)
    if camera is not None:
        objects.append(camera)
        data = getattr(camera, "data", None)
        if data is not None:
            objects.append(data)
    for subject in context.subjects_for(shot_id):
        all_objects = getattr(subject, "all_objects", None)
        objects.extend(all_objects() if callable(all_objects)
                       else list(all_objects or []))
    return objects


def _keyframe_neighborhood(shot_id: str, context,
                           start: int, end: int) -> List[int]:
    """相机/主体动画关键帧 ±1（事件帧加密），夹回镜头区间。"""
    frames = set()
    for obj in _shot_objects(shot_id, context):
        action = getattr(getattr(obj, "animation_data", None), "action", None)
        if action is None:
            continue
        #: Blender 5.x 移除了 ``action.fcurves``（改动画层模型）；用兼容层的
        #: ``action_fcurves`` 单一真源，不各写一份版本分支。
        for fcurve in action_fcurves(action):
            for point in fcurve.keyframe_points:
                key = int(round(float(point.co[0])))
                for delta in (-1, 0, 1):
                    frame = key + delta
                    if start <= frame <= end:
                        frames.add(frame)
    return sorted(frames)


def _face_grid_points(low: Vector, high: Vector,
                      camera_pos: Vector) -> List[Vector]:
    """包围盒朝相机那一面的 3×3（N=9）表面采样点（世界坐标）。

    面是 AABB 的六个轴对齐面之一；取 ``(camera_pos - face_center)·外法线``
    最大的那张（相机在盒内时退化为最近的面对——该情形投影已失效，纯层按
    ``behind_camera`` 处理，这里只保证确定性）。
    """
    center = (low + high) * 0.5
    half = (high - low) * 0.5
    best: Optional[Tuple[float, int, int]] = None
    for axis in range(3):
        for sign in (1, -1):
            face_center = center.copy()
            face_center[axis] += sign * half[axis]
            normal = Vector((0.0, 0.0, 0.0))
            normal[axis] = float(sign)
            score = (camera_pos - face_center).dot(normal)
            if best is None or score > best[0]:
                best = (score, axis, sign)
    assert best is not None
    _score, axis, sign = best
    fixed = low[axis] if sign < 0 else high[axis]
    others = [index for index in range(3) if index != axis]
    points: List[Vector] = []
    for fu in (0.0, 0.5, 1.0):
        for fv in (0.0, 0.5, 1.0):
            point = [0.0, 0.0, 0.0]
            point[axis] = fixed
            point[others[0]] = (low[others[0]]
                                + fu * (high[others[0]] - low[others[0]]))
            point[others[1]] = (low[others[1]]
                                + fv * (high[others[1]] - low[others[1]]))
            points.append(Vector(point))
    return points


def _box_spans(bound_box) -> Optional[Tuple[float, float, float]]:
    """bound_box 三轴跨度 ``(dx, dy, dz)``；空盒返回 ``None``。"""
    if not bound_box:
        return None
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    for corner in bound_box:
        for index in range(3):
            lo[index] = min(lo[index], corner[index])
            hi[index] = max(hi[index], corner[index])
    return tuple(hi[index] - lo[index] for index in range(3))


def _real_surface_points(subject, depsgraph,
                         camera_pos: Vector) -> Optional[List[Vector]]:
    """角色真实可见表面的 N=9 采样点（世界坐标）：躯干圆柱 3×2 + 头球 3。

    v1.6 B3 修复：包围盒 AABB 的"朝机面"被眼球顶到空处（默认几何下
    ``y = ±0.3145``，躯干前表面只有 ``y = ±0.25``——差 0.0645 m > 0.05 容差，
    9 条射线全部落空、真实角色恒量成 invisible）。这里改在**真实表面**取点：

    * 躯干圆柱：半径/半高从 body 网格实测（默认几何即 ``BODY_RADIUS`` /
      ``BODY_HEIGHT``），轴向前后两行 × 绕轴 ±:data:`SURFACE_SPREAD` 三列；
    * 头球：半径从 head 网格实测（默认几何即 ``head_r``），沿"朝机方向"
      及其绕 ``朝机方向 × 躯干轴`` 切向 ±:data:`SURFACE_SPREAD` 三列。

    这些点都在朝机半球面上：对凸体（圆柱/球）而言，从机位打到点的射线
    **首交点就是该点**，距离差落在 0.05 m 容差内（网格细分误差远小于容差）。
    没有 body/head 部件的通用主体返回 ``None``，调用方回退到 AABB 面网格。
    """
    parts = getattr(subject, "parts", None)
    if not parts:
        return None
    body = parts.get("body")
    head = parts.get("head")
    if body is None or head is None:
        return None
    body_eval = body.evaluated_get(depsgraph)
    head_eval = head.evaluated_get(depsgraph)
    body_matrix = body_eval.matrix_world
    head_matrix = head_eval.matrix_world
    body_spans = _box_spans(getattr(body_eval, "bound_box", ()))
    head_spans = _box_spans(getattr(head_eval, "bound_box", ()))
    if body_spans is None or head_spans is None:
        return None
    body_scale = body_matrix.to_scale()
    head_scale = head_matrix.to_scale()
    #: 局部 bound_box（对象自身坐标系，与绕 Z 的朝向无关）给出网格尺寸；
    #: 半径/高度再乘世界缩放。Blender 5.x 的 ``Mesh`` 已没有 ``dimensions``。
    body_radius = (max(body_spans[0], body_spans[1]) * 0.5
                   * max(body_scale.x, body_scale.y))
    body_height = abs(float(body_spans[2] * body_scale.z))
    head_radius = (max(head_spans) * 0.5 * max(head_scale[:]))
    if body_radius <= 1e-9 or body_height <= 1e-9 or head_radius <= 1e-9:
        return None

    body_center = body_matrix.translation.copy()
    head_center = head_matrix.translation.copy()
    axis = (body_matrix.to_3x3() @ Vector((0.0, 0.0, 1.0))).normalized()

    #: 躯干三列：朝机方向绕躯干轴 ±SURFACE_SPREAD（切向偏移量 = tan(角)）。
    to_body = camera_pos - body_center
    forward = to_body - axis * to_body.dot(axis)
    if forward.length < 1e-9:
        forward = axis.orthogonal()        # 机位在轴线上（顶视等）：任取水平向
    forward = forward.normalized()
    tangent = axis.cross(forward)
    spread = math.tan(SURFACE_SPREAD)
    columns = [
        (forward - tangent * spread).normalized(),
        forward,
        (forward + tangent * spread).normalized(),
    ]

    points: List[Vector] = []
    half_height = body_height * 0.5
    for row in (-TORSO_ROW_RATIO * half_height,
                TORSO_ROW_RATIO * half_height):
        for direction in columns:
            points.append(body_center + axis * row + direction * body_radius)

    #: 头球三列：朝机方向（3D，含俯仰）绕"朝机 × 躯干轴"切向 ±SURFACE_SPREAD。
    to_head = camera_pos - head_center
    if to_head.length < 1e-9:
        to_head = -axis
    view = to_head.normalized()
    tilt = view.cross(axis)
    if tilt.length < 1e-6:                 # 朝机方向与躯干轴平行：换参考向量
        tilt = view.cross(Vector((0.0, 1.0, 0.0)))
    if tilt.length < 1e-6:
        tilt = view.cross(Vector((1.0, 0.0, 0.0)))
    tilt = tilt.normalized()
    for sign in (-1.0, 0.0, 1.0):
        direction = (view + tilt * (sign * spread)).normalized()
        points.append(head_center + direction * head_radius)
    return points


def _visible_fraction(scene, depsgraph, camera_pos: Vector,
                      subject, points: List[Vector],
                      characters: Optional[Dict[str, Any]] = None) -> Tuple:
    """N=9 个包围盒表面点的可见占比（0–1）＋ 外来遮挡类别归因。

    ``occlusion_by_class`` 的键是语义类别闭集（``"角色"``/``"群众"``/``"道具"``
    /``"特效"``/``"环境"``/``"未知遮挡物"``，角色/道具可带 id 后缀），值是
    该类挡住本帧 9 个采样点的比例。射线命中本主体（自遮挡）或基建/辅助物
    不计入任何类别。
    """
    visible = 0
    occlusion_by_class: Dict[str, int] = {}
    for point in points:
        direction = point - camera_pos
        distance = direction.length
        if distance < 1e-6:
            continue                      # 采样点与机位重合：不计可见
        unit = direction / distance
        travelled = 0.0
        for _step in range(MAX_RAY_STEPS):
            origin = camera_pos + unit * travelled
            remaining = distance - travelled + RAY_TOLERANCE_M
            hit, location, _normal, _index, obj, _matrix = scene.ray_cast(
                depsgraph, origin, unit, distance=max(remaining, 1e-4))
            if not hit or obj is None:
                break
            hit_distance = (location - camera_pos).length
            if _belongs_to(obj, subject):
                if abs(hit_distance - distance) <= RAY_TOLERANCE_M:
                    visible += 1
                break
            if obj.hide_render or _in_guides(obj):
                #: 辅助物不参与遮挡判定：跳过去继续投（与 composition_guide 同款）。
                travelled = (location - camera_pos).length + 1e-3
                if travelled >= distance + RAY_TOLERANCE_M:
                    break
                continue
            # 外来遮挡物：该采样点不可见，按语义类别归因（基建已跳过）。
            blocker_class = occluder_class(obj, characters or {})
            if blocker_class is not None:
                occlusion_by_class[blocker_class] = (
                    occlusion_by_class.get(blocker_class, 0) + 1)
            break
    fraction = float(visible) / float(VISIBLE_SAMPLE_POINTS)
    by_class = {cls: round(count / VISIBLE_SAMPLE_POINTS, 6)
                for cls, count in occlusion_by_class.items()}
    return fraction, by_class


def _sample_subject(subject, scene, depsgraph, camera_eval, camera_pos,
                    shot_id: str, frame: int, facing: float,
                    bounds=None, collisions=(),
                    characters: Optional[Dict[str, Any]] = None) -> FrameSample:
    """单个主体在当前帧的投影结果（NDC 全身盒 + 可见比例 + 机后标记）。"""
    if bounds is None:
        bounds = _world_bounds(subject, depsgraph)
    if bounds is None:
        raise SamplingError(
            f"主体 {_subject_id(subject)} 在镜头 {shot_id} 第 {frame} 帧没有"
            "可投影的网格（bound_box 为空）")
    low, high = bounds
    xs: List[float] = []
    ys: List[float] = []
    behind = False
    for ix in (low.x, high.x):
        for iy in (low.y, high.y):
            for iz in (low.z, high.z):
                projected = world_to_camera_view(
                    scene, camera_eval, Vector((ix, iy, iz)))
                xs.append(float(projected.x))
                ys.append(float(projected.y))
                if float(projected.z) < 0.0:
                    behind = True
    visible = 0.0
    occlusion_by_class: Dict[str, float] = {}
    if not behind:
        points = _real_surface_points(subject, depsgraph, camera_pos)
        if points is None:
            points = _face_grid_points(low, high, camera_pos)
        visible, occlusion_by_class = _visible_fraction(
            scene, depsgraph, camera_pos, subject, points, characters)
    box = SubjectBox(
        name=str(getattr(subject, "name", "") or _subject_id(subject)),
        left=min(xs), right=max(xs), top=max(ys), bottom=min(ys),
        facing=facing)
    return FrameSample(frame=frame, subject=_subject_id(subject), box=box,
                       visible_ratio=visible, behind_camera=behind,
                       shot_id=shot_id, collisions=list(collisions),
                       occlusion_by_class=occlusion_by_class)


@main_thread_only("frustum_sampler.sample_shot")
def sample_shot(shot_id, step=None, extra_frames=()) -> List[FrameSample]:
    """对一镜逐帧采样，产出纯层要的 ``FrameSample`` 列表（TDD §4.2）。

    ``step`` 缺省取 ``config.guard.sample_step``（``settings.get_config()``）。
    ``extra_frames`` 与相机/主体关键帧 ±1 取并集（事件帧加密）。采样中任何
    失败都抛 :class:`SamplingError`（``E_GUARD_001``）；结束后还原当前帧，
    不改任何渲染设置。
    """
    context = get_context()
    if context is None:
        raise SamplingError("没有活动场景上下文（SceneContext），无法采样")
    shot_id = str(shot_id)
    if step is None:
        step = int(get_config().guard.sample_step)
    step = int(step)
    if step < 1:
        raise SamplingError(f"非法采样步长 {step}：必须 >= 1")
    start, end = _shot_span(shot_id, context)
    camera = context.camera_for(shot_id)
    if camera is None:
        raise SamplingError(f"镜头 {shot_id} 没有相机，无法投影")
    _require_perspective(shot_id, camera)
    subjects = context.subjects_for(shot_id)
    if not subjects:
        return []                          # 空镜：合法，无主体可采样
    frames = _sample_frames(start, end, step, extra_frames,
                            _keyframe_neighborhood(shot_id, context,
                                                   start, end))
    scene = bpy.context.scene
    previous_frame = int(scene.frame_current)
    shot = context.shot(shot_id)
    samples: List[FrameSample] = []
    current_frame = previous_frame
    try:
        for frame in frames:
            current_frame = int(frame)
            scene.frame_set(current_frame)
            depsgraph = bpy.context.evaluated_depsgraph_get()
            camera_eval = camera.evaluated_get(depsgraph)
            camera_pos = camera_eval.matrix_world.translation.copy()
            #: 朝向复用 rule_checker.screen_facing_for 的"头朝向投影到屏幕 X"
            #: 口径（get_facing 的头朝向向量，不另造第二份投影逻辑）。
            facing_map = screen_facing_for(shot, context=context, camera=camera)
            #: 卡 V11：本帧全主体的世界包围盒先算一次，再算角色×角色碰撞对，
            #: 与投影结果一起写进 FrameSample（喂纯层 element_collision）。
            bounds_map: Dict[str, Tuple[Vector, Vector]] = {}
            for subject in subjects:
                bounds = _world_bounds(subject, depsgraph)
                if bounds is None:
                    raise SamplingError(
                        f"主体 {_subject_id(subject)} 在镜头 {shot_id} 第 "
                        f"{current_frame} 帧没有可投影的网格（bound_box 为空）")
                bounds_map[_subject_id(subject)] = bounds
            collisions = _pair_collisions(bounds_map)
            for subject in subjects:
                subject_id = _subject_id(subject)
                dot = float(facing_map.get(subject_id, 0.0))
                facing = (0.0 if abs(dot) < FACING_EPS
                          else (1.0 if dot > 0.0 else -1.0))
                samples.append(_sample_subject(
                    subject, scene, depsgraph, camera_eval, camera_pos,
                    shot_id, current_frame, facing,
                    bounds=bounds_map[subject_id], collisions=collisions,
                    characters=context.characters))
    except SamplingError:
        raise
    except Exception as exc:  # noqa: BLE001 - 归一为采样错误码，原异常入链
        raise SamplingError(
            f"镜头 {shot_id} 第 {current_frame} 帧采样失败：{exc}") from exc
    finally:
        scene.frame_set(previous_frame)
        bpy.context.view_layer.update()
    log.debug("镜头 %s 采样完成：%d 帧 × %d 主体 → %d 条 FrameSample",
              shot_id, len(frames), len(subjects), len(samples))
    return samples


@main_thread_only("frustum_sampler.sample_spatial")
def sample_spatial(shot_id, frames) -> List[SpatialFrame]:
    """对指定帧采样**空间数据**（卡 V11）：相机模型 + 本镜角色 + 场景里的
    ``BD_Prop_*``/``BD_Wall_*``。

    只读场景、采样后还原当前帧、失败抛 :class:`SamplingError`；正交相机直接
    报错。群众（``context.crowd``）与 ``hide_render`` 的道具/墙不采样；
    角色没有可投影网格时抛错（与 :func:`sample_shot` 同口径）。
    """
    context = get_context()
    if context is None:
        raise SamplingError("没有活动场景上下文（SceneContext），无法采样")
    shot_id = str(shot_id)
    start, end = _shot_span(shot_id, context)
    camera = context.camera_for(shot_id)
    if camera is None:
        raise SamplingError(f"镜头 {shot_id} 没有相机，无法采样")
    _require_perspective(shot_id, camera)
    selected: List[int] = []
    for raw in frames:
        try:
            frame = int(raw)
        except (TypeError, ValueError) as exc:
            raise SamplingError(f"非法采样帧 {raw!r}") from exc
        if start <= frame <= end:
            selected.append(frame)
    selected = sorted(set(selected))
    if not selected:
        return []

    scene = bpy.context.scene
    previous_frame = int(scene.frame_current)
    out: List[SpatialFrame] = []
    current_frame = previous_frame
    try:
        for frame in selected:
            current_frame = int(frame)
            scene.frame_set(current_frame)
            depsgraph = bpy.context.evaluated_depsgraph_get()
            camera_eval = camera.evaluated_get(depsgraph)
            matrix = camera_eval.matrix_world
            forward = (matrix.to_3x3() @ Vector((0.0, 0.0, -1.0))).normalized()
            up = (matrix.to_3x3() @ Vector((0.0, 1.0, 0.0))).normalized()
            camera_data = camera.data
            spatial_camera = SpatialCamera(
                position=tuple(matrix.translation),
                forward=tuple(forward), up=tuple(up),
                lens_mm=float(camera_data.lens),
                sensor_width=float(camera_data.sensor_width),
                sensor_height=float(camera_data.sensor_height),
                sensor_fit=str(camera_data.sensor_fit),
                render_width=int(scene.render.resolution_x),
                render_height=int(scene.render.resolution_y))

            elements: List[SpatialElement] = []
            for subject in context.subjects_for(shot_id):
                bounds = _world_bounds(subject, depsgraph)
                if bounds is None:
                    raise SamplingError(
                        f"主体 {_subject_id(subject)} 在镜头 {shot_id} 第 "
                        f"{current_frame} 帧没有可投影的网格（bound_box 为空）")
                low, high = bounds
                elements.append(SpatialElement(
                    id=_subject_id(subject), kind="character",
                    aabb_min=tuple(low), aabb_max=tuple(high),
                    center=tuple((low + high) * 0.5),
                    facing=tuple(get_facing(subject))))
            for obj in bpy.data.objects:
                if obj.type != "MESH" or obj.hide_render:
                    continue
                if not obj.name.startswith(OBSTACLE_PREFIXES):
                    continue
                kind = "prop" if obj.name.startswith("BD_Prop_") else "wall"
                evaluated = obj.evaluated_get(depsgraph)
                bounds = _object_world_bounds(evaluated)
                if bounds is None:
                    continue
                low, high = bounds
                elements.append(SpatialElement(
                    id=obj.name, kind=kind,
                    aabb_min=tuple(low), aabb_max=tuple(high),
                    center=tuple((low + high) * 0.5)))
            out.append(SpatialFrame(frame=current_frame, shot_id=shot_id,
                                    camera=spatial_camera,
                                    elements=elements))
    except SamplingError:
        raise
    except Exception as exc:  # noqa: BLE001 - 归一为采样错误码，原异常入链
        raise SamplingError(
            f"镜头 {shot_id} 第 {current_frame} 帧空间采样失败：{exc}") from exc
    finally:
        scene.frame_set(previous_frame)
        bpy.context.view_layer.update()
    return out
