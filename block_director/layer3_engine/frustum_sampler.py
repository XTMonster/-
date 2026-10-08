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

实现要点（TDD §4.2 / 卡 B3 钉死）：

* 投影**只用** ``bpy_extras.object_utils.world_to_camera_view``
  （已封装 shift/焦距/像素比；禁止手写投影矩阵）；
* 每帧 ``scene.frame_set(f)`` → ``evaluated_depsgraph_get()``，主体包围盒与相机
  一律读 **depsgraph 求值后**的状态（``obj.evaluated_get(dg).matrix_world``，
  相机也传 ``camera.evaluated_get(dg)`` 给投影函数）；
* 8 个包围盒角点任一 ``z < 0`` → ``behind_camera=True``（投影失效，单列；
  此时不再做射线采样，``visible_ratio=0.0``——纯层只按 ``behind_camera`` 判，
  不消费该值）；
* 可见比例：包围盒**朝相机那一面**的 3×3（N=9）表面采样点，逐点
  ``scene.ray_cast(dg, cam_pos, dir)``；命中对象归属主体（父链到 root，
  复用 composition_guide 的 ``_belongs_to``）且
  ``|命中距离 - 目标距离| <= 0.05 m`` 计可见；可见比例 = 可见点数 / 9；
* ``extra_frames``：相机/主体动画关键帧 ±1（事件帧加密），与显式传入的
  ``extra_frames`` 取并集、夹回镜头区间；默认步长 = ``config.guard.sample_step``
  （``settings.get_config()``，与 UI/面板同一个真源）；
* 采样帧集 = ``range(start, end+1, step)`` ∪ {末帧} ∪ 关键帧邻域 ∪ 显式
  extra_frames（末帧必采样——出画/离场事件需要时间轴终点）。

已知边界（调研报告 §2，如实记录，不改判据）：N=9 包围盒表面点不是主体像素的
均匀采样，圆柱/细长主体的角点会落在空处——"可见比例 0 才标 high"是纯层对这一
口径的配套设计；本模块不换采样点布局、不把近似当精确像素裁切率。
"""
from __future__ import annotations

from typing import Iterable, List, Optional, Tuple

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

from ..cinema.composition import SubjectBox
from ..cinema.frustum_metrics import FrameSample
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
)
from .rule_checker import screen_facing_for
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


def _visible_fraction(scene, depsgraph, camera_pos: Vector,
                      subject, points: List[Vector]) -> float:
    """N=9 个包围盒表面点的可见占比（0–1）。"""
    visible = 0
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
            break                          # 外来遮挡物：该采样点不可见
    return float(visible) / float(VISIBLE_SAMPLE_POINTS)


def _sample_subject(subject, scene, depsgraph, camera_eval, camera_pos,
                    shot_id: str, frame: int, facing: float) -> FrameSample:
    """单个主体在当前帧的投影结果（NDC 全身盒 + 可见比例 + 机后标记）。"""
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
    if not behind:
        points = _face_grid_points(low, high, camera_pos)
        visible = _visible_fraction(scene, depsgraph, camera_pos,
                                    subject, points)
    box = SubjectBox(
        name=str(getattr(subject, "name", "") or _subject_id(subject)),
        left=min(xs), right=max(xs), top=max(ys), bottom=min(ys),
        facing=facing)
    return FrameSample(frame=frame, subject=_subject_id(subject), box=box,
                       visible_ratio=visible, behind_camera=behind,
                       shot_id=shot_id)


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
            for subject in subjects:
                subject_id = _subject_id(subject)
                dot = float(facing_map.get(subject_id, 0.0))
                facing = (0.0 if abs(dot) < FACING_EPS
                          else (1.0 if dot > 0.0 else -1.0))
                samples.append(_sample_subject(
                    subject, scene, depsgraph, camera_eval, camera_pos,
                    shot_id, current_frame, facing))
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
