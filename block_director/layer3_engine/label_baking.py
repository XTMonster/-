"""渲染标签的构建期烘焙（v1.3 诉求 4）。

参考视频里的角色标签有两条硬要求：**跟着角色**、**任何景别都看得清**。
两者都靠在这里逐帧烘焙世界变换实现，而**不依赖渲染期的 handler**：

* 跟随：每帧取 LabelAnchor 的世界位置；
* 朝向：取当前镜头相机的世界旋转（公告板）；
* 字号：**屏幕恒定**——按"锚点到相机的距离"反算世界高度，
  使投影后的像素高度落在 ``[min_pixels, target_pixels]`` 区间，
  上限再按画面高度的一个比例夹住，避免大远景里标签大得离谱；
* 避让：锚点投影出画时把它推回画内；被前景挡住时上移一档。
* 互斥：同一帧里两个标签的屏幕包围盒不许相碰（v1.4 BW-2）——先把每个标签
  摆到它的"锚点 + 出画/遮挡修正"处，再按屏幕纵向做一次**确定性松弛**，
  把重叠的标签上下推开；每个触发避让的帧都记下 ``offset_reason`` 与像素
  位移（RK-2 按 ``offset_reason`` 分档判定）。

采样步长默认 4 帧：相机在 v1.3 里基本是静态的，4 帧步长 + 贝塞尔插值
足够平滑，而每帧每标签写三条曲线会平白多出几万个关键帧。

v1.6 A7（D-19）把「互斥」从采样帧扩到**成片每一帧**：① 步长自适应——锚点
相对屏幕速度超阈、或插值帧检出重叠时，该区段加密至每帧；② 松弛从纯纵向
升二维（纵向预算耗尽时横向错开，推开顺序按标签 id 确定性排序）；③ 烘焙后
做**全帧自检**：超限帧重烘、复检，余量如实写进 ``label_overlap_report``，
绝不隐藏。
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

from ..contracts.audit import LABEL_OVERLAP_REPORT
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

#: 标签之间必须留出的最小像素间隙（避让松弛的停止条件）。
AVOID_GAP_PX = 2.0
#: v1.4 BW-2：标签之间的**交叠率上限**（area(A∩B) / min(area(A), area(B))）。
OVERLAP_LIMIT = 0.05
#: 避让迭代次数上限（逐个让位是收敛的；给个上界防止不收敛）。
SEPARATE_ITERATIONS = 16
#: v1.6 A7（D-19）：相对屏幕速度（NDC/帧）超过此値时，区段加密至每帧。
ADAPTIVE_SPEED_THRESHOLD = 0.03
#: v1.6 A7（D-19）：全帧自检里「超限帧重烘 → 复检」的轮数上限；打满仍超限
#: 的帧如实写进报告，绝不隐藏。
FULLFRAME_REBAKE_ROUNDS = 3

#: 触发避让的帧允许的最大位移（占画面高的比例，RK-2 的判据）。
#: **只此一处定义**——两处定义会静默分叉（v1.4 §3.5 的"禁止死字段"同理）。
MAX_OFFSET_RATIO = 0.25

#: ``offset_reason`` 的取值（v1.4 §2.5 / RK-2 的口径，单一词表）。
REASON_NONE = "none"
REASON_OUT_OF_FRAME = "out_of_frame"
REASON_OCCLUDED = "occluded"
REASON_OVERLAP = "overlap"


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
                   step: int,
                   extra_frames: Optional[List[int]] = None) -> List[int]:
    frames: List[int] = []
    for start, end in schedule.values():
        cursor = int(start)
        while cursor < int(end):
            frames.append(cursor)
            cursor += max(int(step), 1)
        frames.append(int(end))
    if extra_frames:
        frames.extend(extra_frames)
    return sorted(set(frames))


def _shot_at(schedule: Dict[str, Tuple[int, int]], frame: int
             ) -> Optional[str]:
    for shot_id, (start, end) in schedule.items():
        if int(start) <= frame <= int(end):
            return shot_id
    return None


def _glyph_half_extents(fill, scale: float) -> Tuple[float, float]:
    """标签在**世界单位**下的半宽 / 半高（近似：逐字约一个字身宽）。

    ``curve.size`` 是字号，对象 ``scale`` 是烘焙时反解出的屏幕恒定倍率。
    中文一个字基本是正方形，所以宽 ≈ 字号 × 字数 × 0.95、高 ≈ 字号。
    """
    size = abs(float(getattr(fill.data, "size", 1.0) or 1.0) * float(scale))
    text = str(getattr(fill.data, "body", "") or "")
    length = max(len(text), 1)
    return size * 0.5 * length * 0.95, size * 0.5


def _screen_box(scene, camera, position, right, up,
                half_w: float, half_h: float,
                res_x: float, res_y: float):
    """把标签的四边形投影成屏幕像素 AABB ``(x0, y0, x1, y1)``。"""
    xs: List[float] = []
    ys: List[float] = []
    for sx in (-1.0, 1.0):
        for sy in (-1.0, 1.0):
            point = position + right * (sx * half_w) + up * (sy * half_h)
            projected = world_to_camera_view(scene, camera, point)
            xs.append(projected.x * res_x)
            ys.append(projected.y * res_y)
    return (min(xs), min(ys), max(xs), max(ys))


def _overlap_ratio(a, b) -> float:
    """两个屏幕 AABB 的交叠率（分母取**较小**的那个面积）。"""
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    if width <= 0.0 or height <= 0.0:
        return 0.0
    area = width * height
    smaller = min((a[2] - a[0]) * (a[3] - a[1]),
                  (b[2] - b[0]) * (b[3] - b[1]))
    if smaller <= 0.0:
        return 0.0
    return area / smaller


def _object_centre(obj) -> Optional[Vector]:
    """对象几何包围盒中心的世界坐标（``bound_box`` 已含字号）。"""
    try:
        corners = [obj.matrix_world @ Vector(corner)
                   for corner in obj.bound_box]
    except (ReferenceError, RuntimeError):
        return None
    if not corners:
        return None
    return sum(corners, Vector()) / len(corners)


def separate_labels(scene, camera, prepared: List[Dict[str, Any]],
                    *, res_x: float, res_y: float,
                    iterations: int = SEPARATE_ITERATIONS) -> List[Dict[str, Any]]:
    """把互相压住的标签**上下错开**（v1.4 BW-2）。

    就地修改 ``prepared`` 的 ``position`` / ``offset_reason`` /
    ``applied_offset_px``，返回被移动过的条目。位移上限是
    ``MAX_OFFSET_RATIO × 画面高``（RK-2 的判据）。v1.6 A7（D-19）起纵向
    预算耗尽时横向错开（二维松弛）。
    """
    moved: List[Dict[str, Any]] = []
    if len(prepared) < 2:
        return moved
    # v1.6 A7（D-19）：推开顺序按标签 id 确定性排序——上移谁、横推谁都与
    # ``prepared`` 的入列顺序无关（入列顺序由调用方决定，不能成为松弛结果）。
    prepared = sorted(prepared,
                      key=lambda item: str(item.get("character_id") or ""))
    limit_px = MAX_OFFSET_RATIO * float(res_y)
    for _ in range(max(int(iterations), 1)):
        boxes = []
        for item in prepared:
            half_w, half_h = _glyph_half_extents(item["fill"], item["scale"])
            boxes.append(_screen_box(scene, camera, item["position"],
                                     item["right"], item["up"],
                                     half_w, half_h, res_x, res_y))
        worst = 0.0
        for i in range(len(prepared)):
            for j in range(i + 1, len(prepared)):
                ratio = _overlap_ratio(boxes[i], boxes[j])
                if ratio <= OVERLAP_LIMIT:
                    continue
                worst = max(worst, ratio)
                upper, lower = (i, j) if boxes[i][3] >= boxes[j][3] else (j, i)
                overlap_h = (min(boxes[upper][3], boxes[lower][3])
                             - max(boxes[upper][1], boxes[lower][1]))
                room_upper = limit_px - float(
                    prepared[upper].get("applied_offset_px") or 0.0)
                room_lower = limit_px - float(
                    prepared[lower].get("applied_offset_px") or 0.0)
                need_px = max(overlap_h, 1.0)
                #: 双向分摊（v1.6 G2）：原实现只把 upper 往上推，lower 不动——
                #: 拥挤帧里 upper 的预算先耗尽，两个几乎重合的标签怎么都分不开
                #: （v4 真跑最高 96.8% 交叠）。改成两标签各让一半，每个标签的
                #: 位移预算仍 ≤ MAX_OFFSET_RATIO×画高（RK-2 判据不变）。
                shift_upper = min(need_px / 2.0, room_upper)
                shift_lower = min(need_px - shift_upper, room_lower)
                shift_upper += min(need_px - shift_upper - shift_lower,
                                   room_upper - shift_upper)
                shift_px = shift_upper + shift_lower
                if shift_px <= 0.0:
                    # Vertical budget exhausted — try horizontal push (v1.6 A7 D-19 2D松弛).
                    # 横推标签 id 靠后的那个（prepared 已按 id 排序，确定性）。
                    overlap_w = (min(boxes[i][2], boxes[j][2])
                                 - max(boxes[i][0], boxes[j][0]))
                    if overlap_w <= 0.0:
                        continue
                    room_i = limit_px - float(
                        prepared[i].get("applied_offset_px") or 0.0)
                    room_j = limit_px - float(
                        prepared[j].get("applied_offset_px") or 0.0)
                    need_w = max(overlap_w, 1.0)
                    shift_j = min(need_w / 2.0, room_j)
                    shift_i = min(need_w - shift_j, room_i)
                    shift_j += min(need_w - shift_j - shift_i,
                                   room_j - shift_j)
                    shift_w = shift_i + shift_j
                    if shift_w <= 0.0:
                        continue
                    _aspect = float(res_x) / max(float(res_y), 1.0)
                    for mover, amount in ((j, shift_j), (i, -shift_i)):
                        if amount <= 0.0:
                            continue
                        world_h = (abs(amount) / float(res_x)
                                   * float(prepared[mover]["frame_height"])
                                   * _aspect)
                        sign = 1.0 if amount > 0 else -1.0
                        prepared[mover]["position"] = (
                            prepared[mover]["position"]
                            + prepared[mover]["right"] * (world_h * sign))
                        prepared[mover]["applied_offset_px"] = float(
                            prepared[mover].get("applied_offset_px") or 0.0) \
                            + abs(amount)
                        if prepared[mover]["offset_reason"] == REASON_NONE:
                            prepared[mover]["offset_reason"] = REASON_OVERLAP
                        if prepared[mover] not in moved:
                            moved.append(prepared[mover])
                    continue
                for mover, amount, axis in ((upper, shift_upper, 1.0),
                                            (lower, shift_lower, -1.0)):
                    if amount <= 0.0:
                        continue
                    world = (amount / float(res_y)
                             * float(prepared[mover]["frame_height"]))
                    prepared[mover]["position"] = (
                        prepared[mover]["position"]
                        + prepared[mover]["up"] * (world * axis))
                    prepared[mover]["applied_offset_px"] = float(
                        prepared[mover].get("applied_offset_px") or 0.0) + amount
                    if prepared[mover]["offset_reason"] == REASON_NONE:
                        prepared[mover]["offset_reason"] = REASON_OVERLAP
                    if prepared[mover] not in moved:
                        moved.append(prepared[mover])
        if worst <= OVERLAP_LIMIT:
            break
    return moved


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


def _screen_box_from_obj(scene, camera, obj, res_x: float, res_y: float):
    """全帧自检用：从对象当前 matrix_world 的 bound_box 求屏幕像素 AABB。

    烘焙后调用 scene.frame_set + view_layer.update 即可让 matrix_world 反映
    关键帧插值结果，无需重新计算 prepared 数据。
    """
    matrix = obj.matrix_world
    xs: List[float] = []
    ys: List[float] = []
    for corner in obj.bound_box:
        pt = world_to_camera_view(scene, camera, matrix @ Vector(corner))
        xs.append(pt.x * res_x)
        ys.append(pt.y * res_y)
    if not xs:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(xs), min(ys), max(xs), max(ys))


def _empty_overlap_report() -> Dict[str, Any]:
    """``label_overlap_report`` 的空态（字段与 ``V16_EVENT_FIELDS`` 对拍）。"""
    return {"max_overlap_ratio": 0.0, "overlap_frames": [],
            "frames_checked": 0, "limit": float(OVERLAP_LIMIT)}


def _schedule_frames(schedule: Dict[str, Tuple[int, int]]) -> List[int]:
    """计划里所有会被渲染的帧（含两端）。"""
    frames: List[int] = []
    for start, end in schedule.values():
        frames.extend(range(int(start), int(end) + 1))
    return sorted(set(frames))


def _scan_overlap(scene, cameras, schedule, entries, res_x: float,
                  res_y: float, frames: Sequence[int],
                  subjects: Optional[Dict[str, Sequence[str]]] = None
                  ) -> Tuple[List[int], float]:
    """扫 ``frames`` 每一帧的标签两两交叠；返回 ``(超限帧清单, 最大交叠率)``。

    量法与 ``tools/blender_tests/test_label_layout.py`` 的 ``_overlap`` /
    ``_screen_box`` 一致（RK-2 的 5% 判据原样），只是把覆盖范围从采样帧
    扩到任意帧集。
    """
    over: List[int] = []
    worst = 0.0
    for frame in frames:
        shot_id = _shot_at(schedule, frame)
        camera = cameras.get(shot_id) if shot_id else None
        if camera is None:
            continue
        wanted = (set(str(item) for item in (subjects or {}).get(
            str(shot_id), ()))
            if subjects is not None else None)
        frame_fills = [
            entry.get("fill") for entry in entries
            if wanted is None
            or str(entry.get("character_id") or "") in wanted]
        if len(frame_fills) < 2:
            continue
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        boxes: List[Tuple[float, float, float, float]] = []
        for fill in frame_fills:
            if fill is None:
                continue
            boxes.append(_screen_box_from_obj(scene, camera, fill,
                                              res_x, res_y))
        flagged = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                ratio = _overlap_ratio(boxes[i], boxes[j])
                if ratio > worst:
                    worst = ratio
                if ratio > OVERLAP_LIMIT and not flagged:
                    over.append(frame)
                    flagged = True
    return over, worst


def _densified_frames(baked: Sequence[int], over: Sequence[int]) -> List[int]:
    """超限**插值帧**所在区段加密到每帧（v1.6 A7 D-19 步长自适应）。

    已经烘过的超限帧不是插值问题（是松弛容量问题），这里不处理——它们归
    全帧自检的重烘/如实报告管。
    """
    baked_set = set(int(frame) for frame in baked)
    added: List[int] = []
    for frame in sorted(set(int(frame) for frame in over)):
        if frame in baked_set:
            continue
        left = None
        right = None
        for key in sorted(baked_set):
            if key < frame:
                left = key
            elif key > frame:
                right = key
                break
        if left is None or right is None or right - left <= 1:
            continue
        added.extend(range(left + 1, right))
    return sorted(set(added))


def _anchor_ndc(scene, camera, entry) -> Optional[Tuple[float, float]]:
    """标签锚点当前帧的屏幕 NDC 坐标；锚点缺失返回 ``None``。"""
    anchor = entry.get("anchor")
    if anchor is None:
        return None
    projected = world_to_camera_view(
        scene, camera, anchor.matrix_world.translation.copy())
    return float(projected.x), float(projected.y)


def _speed_dense_frames(scene, cameras, schedule, base_frames, entries
                        ) -> List[int]:
    """锚点相对屏幕速度超阈的区段加密到每帧（v1.6 A7 D-19 触发条件①）。"""
    extra: List[int] = []
    for shot_id, (start, end) in schedule.items():
        camera = cameras.get(shot_id)
        if camera is None:
            continue
        shot_base = [frame for frame in base_frames
                     if int(start) <= frame <= int(end)]
        for fa, fb in zip(shot_base, shot_base[1:]):
            if fb - fa <= 1:
                continue
            scene.frame_set(fa)
            bpy.context.view_layer.update()
            positions_a = [_anchor_ndc(scene, camera, entry)
                           for entry in entries]
            scene.frame_set(fb)
            bpy.context.view_layer.update()
            positions_b = [_anchor_ndc(scene, camera, entry)
                           for entry in entries]
            for pa, pb in zip(positions_a, positions_b):
                if pa is None or pb is None:
                    continue
                speed = math.hypot(pb[0] - pa[0], pb[1] - pa[1]) \
                    / float(max(fb - fa, 1))
                if speed > ADAPTIVE_SPEED_THRESHOLD:
                    extra.extend(range(fa + 1, fb))
                    break
    return extra


@main_thread_only("bake_labels")
def bake_labels(scene, entries: Sequence[Dict[str, Any]],
                schedule: Dict[str, Tuple[int, int]],
                cameras: Dict[str, Any], *,
                sample_step: int = DEFAULT_SAMPLE_STEP,
                target_pixels: float = DEFAULT_TARGET_PIXELS,
                min_pixels: float = DEFAULT_MIN_PIXELS,
                max_ratio: float = DEFAULT_MAX_RATIO,
                resolution: Sequence[int] = (1280, 720),
                adaptive_sampling: bool = True,
                fullframe_verify: bool = True,
                subjects: Optional[Dict[str, Sequence[str]]] = None
                ) -> Dict[str, Any]:
    """给渲染标签烘焙逐帧变换；返回一份可写进交付报告的摘要。

    v1.6 A7（D-19）：``adaptive_sampling`` 在锚点相对屏幕速度大、或插值帧
    检出重叠时把区段加密到每帧；``fullframe_verify`` 烘焙后扫**每一帧**，
    超限帧重烘并复检，余量如实写进 ``label_overlap_report``，绝不隐藏。
    """
    if not entries or not schedule or not cameras:
        return {"labels": 0, "frames": 0, "unreadable": [],
                LABEL_OVERLAP_REPORT: _empty_overlap_report()}

    res_y = float(max(int(resolution[1]), 1))
    res_x = float(max(int(resolution[0]), 1))
    aspect = res_x / res_y
    # v1.6 A7（D-19）：标签 id 排序是二维松弛的确定性来源——推开顺序与调用方
    # 传入的入列顺序脱钩（按 id 排序处理）。
    ordered_entries = sorted(
        entries, key=lambda entry: str(entry.get("character_id") or ""))
    base_frames = _sample_frames(schedule, sample_step)

    # v1.6 A7（D-19）触发条件①：锚点相对屏幕速度超阈 ⇒ 区段加密至每帧。
    extra: List[int] = []
    if adaptive_sampling and len(ordered_entries) >= 2:
        extra = _speed_dense_frames(scene, cameras, schedule,
                                    base_frames, ordered_entries)
    frames = _sample_frames(schedule, sample_step, extra_frames=extra)
    unreadable: Dict[Tuple[str, int], Dict[str, Any]] = {}
    written = 0

    # v1.4 BW-2：**按帧**先算出所有标签的落点，再统一做标签间避让，最后
    # 才写关键帧。旧实现是"逐标签算完就写"，标签之间互相压住时无人可让。
    worst_offset: Dict[str, Dict[str, Any]] = {}

    def _bake_frame(frame: int) -> None:
        nonlocal written
        shot_id = _shot_at(schedule, frame)
        camera = cameras.get(shot_id) if shot_id else None
        if camera is None:
            return
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        rotation = camera.matrix_world.to_euler()
        right, up = _camera_axes(camera)
        prepared: List[Dict[str, Any]] = []

        active_entries = ordered_entries
        if subjects is not None and shot_id is not None:
            wanted = set(str(item) for item in subjects.get(
                str(shot_id), ()) or ())
            active_entries = [
                entry for entry in ordered_entries
                if str(entry.get("character_id") or "") in wanted]
        for entry in active_entries:
            fill = entry.get("fill")
            stroke = entry.get("stroke")
            anchor = entry.get("anchor")
            character_id = str(entry.get("character_id") or "")
            if fill is None or anchor is None:
                continue
            base_size = float(getattr(fill.data, "size", 1.0) or 1.0)
            anchor_world = anchor.matrix_world.translation.copy()
            cam_world = camera.matrix_world.translation.copy()
            distance = max((anchor_world - cam_world).length, 1e-3)
            lens = float(camera.data.lens) or 50.0
            frame_height = _camera_frame_height(distance, lens, aspect=aspect)

            position = anchor_world
            # 屏幕恒定字号：先在单位缩放下量一次真实像素高度，再按比例反解。
            # **已知缺陷（P12 未完成项）**：这个基准在 35mm/50mm 两个镜头之间
            # 量出来的屏幕高度会差 37%（实测 15.0 px → 9.38 px），因为
            # "投影一段 curve.size 长的线段"隐含假设字形正好填满 em 框。
            # 修法应改为对**字形自身的 bound_box** 做定点迭代（量一次真实
            # 投影高度、按比例修正、重复几次），试过但还没收敛到稳定值，
            # 暂不启用，避免引入未验证的回归；镜头内连续性是好的（0%）。
            px_at_unit = _unit_pixel_height(scene, camera, position, up,
                                            base_size, res_y)
            max_pixels = max(max_ratio * res_y, min_pixels)
            wanted_pixels = min(max(target_pixels, min_pixels), max_pixels)
            if px_at_unit <= 1e-6:
                scale = 1.0
                unreadable.setdefault(
                    (character_id, frame),
                    {"character_id": character_id, "frame": frame,
                     "reason": "投影退化"})
            else:
                scale = wanted_pixels / px_at_unit
            if scale * px_at_unit < min_pixels - 1e-6:
                unreadable.setdefault(
                    (character_id, frame),
                    {"character_id": character_id, "frame": frame,
                     "reason": "低于可读下限"})

            reason = REASON_NONE
            offset = Vector((0.0, 0.0, 0.0))
            applied_px = 0.0
            # 避让（一）：锚点投影出画时推回画内
            projected = world_to_camera_view(scene, camera, anchor_world)
            if not (FRAME_MARGIN <= projected.x <= 1.0 - FRAME_MARGIN
                    and FRAME_MARGIN <= projected.y <= 1.0 - FRAME_MARGIN):
                target_x = min(max(projected.x, FRAME_MARGIN),
                               1.0 - FRAME_MARGIN)
                target_y = min(max(projected.y, FRAME_MARGIN),
                               1.0 - FRAME_MARGIN)
                px_x = (target_x - projected.x) * res_x
                px_y = (target_y - projected.y) * res_y
                # v1.4 RK-2②：触发避让的帧，位移不得超过 0.25 × 画面高。
                # 大远景里角色贴着画框时，"完全推回画内"可能要挪半个画面——
                # 那已经不是"避让"而是"另画一个标签"，按上限截断并如实记录。
                span = math.hypot(px_x, px_y)
                allowed = MAX_OFFSET_RATIO * float(res_y)
                if span > allowed > 0.0:
                    factor = allowed / span
                    px_x *= factor
                    px_y *= factor
                delta_x = px_x / float(res_x) * frame_height * aspect
                delta_y = px_y / float(res_y) * frame_height
                offset += right * delta_x + up * delta_y
                applied_px = math.hypot(px_x, px_y)
                reason = REASON_OUT_OF_FRAME
            # 避让（二）：相机到锚点之间被内容物挡住时上移一档
            if _blocked(scene, camera, anchor_world):
                shift = min(0.20 * res_y,
                            max(MAX_OFFSET_RATIO * float(res_y) - applied_px,
                                0.0))
                if shift > 0.0:
                    offset += up * (shift / float(res_y) * frame_height)
                    applied_px += shift
                reason = (REASON_OCCLUDED if reason == REASON_NONE
                          else reason + "+" + REASON_OCCLUDED)
            prepared.append({
                "character_id": character_id, "fill": fill, "stroke": stroke,
                "position": position + offset, "rotation": rotation,
                "right": right, "up": up, "scale": scale,
                "frame_height": frame_height, "frame": frame,
                "offset_reason": reason, "applied_offset_px": applied_px,
            })

        # 避让（三）：标签之间互相让位（BW-2 的核心）
        separate_labels(scene, camera, prepared, res_x=res_x, res_y=res_y)

        for item in prepared:
            _write(item["fill"], item["position"], item["rotation"],
                   item["scale"], camera, frame)
            if item["stroke"] is not None:
                # 描边是**同一层放大 1.15 倍**的副本，为了不与白字打架要沿视轴
                # 后退一点。v1.4 RK-1⑤：后退必须沿**相机到标签的视线**后退，
                # 否则离轴标签会产生视差——实测上扩 3.8 px、下扩 1.7 px，
                # `|e_up − e_down| ≤ 1 px` 当场失败。沿视线后退则屏幕中心不变。
                cam_world = camera.matrix_world.translation
                ray = item["position"] - cam_world
                depth = ray.length
                if depth > LABEL_STROKE_BACK + 1e-4:
                    stroke_position = (cam_world
                                       + ray * ((depth - LABEL_STROKE_BACK)
                                                / depth))
                else:
                    back = (camera.matrix_world.to_3x3() @
                            Vector((0.0, 0.0, -LABEL_STROKE_BACK)))
                    stroke_position = item["position"] + back
                stroke_scale = item["scale"] * LABEL_STROKE_SCALE
                # 放大是**绕文字原点**做的，而字形包围盒并不关于原点对称
                # （下划线、降部会把盒子往下拉），于是环带会偏向一侧
                # （实测上 3.4 px / 下 2.1 px）。这里把描边整体平移
                # ``中心差``，让两个掩膜的 AABB 中心重合（RK-1⑤）。
                stroke = item["stroke"]
                stroke.location = stroke_position
                stroke.rotation_euler = item["rotation"]
                stroke.scale = (stroke_scale, stroke_scale, stroke_scale)
                bpy.context.view_layer.update()
                centre_fill = _object_centre(item["fill"])
                centre_stroke = _object_centre(stroke)
                if centre_fill is not None and centre_stroke is not None:
                    stroke.location = (stroke.location
                                       + (centre_fill - centre_stroke))
                _write(stroke, stroke.location, item["rotation"],
                       stroke_scale, camera, frame)
            written += 1
            current = worst_offset.get(item["character_id"])
            if current is None or item["applied_offset_px"] > \
                    float(current.get("applied_offset_px") or 0.0):
                worst_offset[item["character_id"]] = {
                    "offset_reason": item["offset_reason"],
                    "applied_offset_px": round(item["applied_offset_px"], 2),
                    "frame": item["frame"],
                    # v1.4 §3.3：shots.json.labels{} 要写 text 与 anchor_z。
                    "text": str(getattr(item["fill"].data, "body", "") or ""),
                    "anchor_z": round(
                        float(item["position"].z), 4),
                }

    for frame in frames:
        _bake_frame(frame)

    overlap_report = _empty_overlap_report()
    rendered = _schedule_frames(schedule)
    scanned = False
    over: List[int] = []
    worst = 0.0

    # v1.6 A7（D-19）触发条件②：插值帧检出重叠 ⇒ 该区段加密直至每帧。
    if adaptive_sampling and len(ordered_entries) >= 2:
        over, worst = _scan_overlap(scene, cameras, schedule,
                                    ordered_entries, res_x, res_y, rendered,
                                    subjects=subjects)
        scanned = True
        added = _densified_frames(frames, over)
        for frame in added:
            _bake_frame(frame)

    # v1.6 A7（D-19）：烘焙后全帧自检——超限帧重烘 → 复检；余量如实进报告。
    if fullframe_verify:
        overlap_report["frames_checked"] = len(rendered)
        if not scanned:
            over, worst = _scan_overlap(scene, cameras, schedule,
                                        ordered_entries, res_x, res_y,
                                        rendered, subjects=subjects)
        rounds = 0
        while over and rounds < FULLFRAME_REBAKE_ROUNDS:
            for frame in sorted(set(over)):
                _bake_frame(frame)
            rounds += 1
            over, worst = _scan_overlap(scene, cameras, schedule,
                                        ordered_entries, res_x, res_y,
                                        rendered, subjects=subjects)
        overlap_report["overlap_frames"] = sorted(set(over))
        overlap_report["max_overlap_ratio"] = round(float(worst), 6)
        if overlap_report["overlap_frames"]:
            log.warning(
                "标签全帧自检：%d/%d 帧交叠仍超 %.1f%%（最高 %.1f%%）",
                len(overlap_report["overlap_frames"]),
                overlap_report["frames_checked"],
                float(OVERLAP_LIMIT) * 100.0, float(worst) * 100.0)

    log.info("标签烘焙完成：%d 个标签 / %d 帧采样", len(entries), written)
    return {"labels": len(entries), "frames": written,
            "sample_step": int(sample_step), "resolution": [int(res_x),
                                                            int(res_y)],
            "unreadable": list(unreadable.values()), "offsets": worst_offset,
            LABEL_OVERLAP_REPORT: overlap_report}


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
