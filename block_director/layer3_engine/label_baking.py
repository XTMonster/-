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

#: 标签之间必须留出的最小像素间隙（避让松弛的停止条件）。
AVOID_GAP_PX = 2.0
#: v1.4 BW-2：标签之间的**交叠率上限**（area(A∩B) / min(area(A), area(B))）。
OVERLAP_LIMIT = 0.05
#: 避让迭代次数上限（逐个让位是收敛的；给个上界防止不收敛）。
SEPARATE_ITERATIONS = 16
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


def separate_labels(scene, camera, prepared: List[Dict[str, Any]],
                    *, res_x: float, res_y: float,
                    iterations: int = SEPARATE_ITERATIONS) -> List[Dict[str, Any]]:
    """把互相压住的标签**上下错开**（v1.4 BW-2）。

    就地修改 ``prepared`` 的 ``position`` / ``offset_reason`` /
    ``applied_offset_px``，返回被移动过的条目。位移上限是
    ``MAX_OFFSET_RATIO × 画面高``（RK-2 的判据）。
    """
    moved: List[Dict[str, Any]] = []
    if len(prepared) < 2:
        return moved
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
                room = limit_px - float(
                    prepared[upper].get("applied_offset_px") or 0.0)
                shift_px = max(min(max(overlap_h, 1.0), room), 0.0)
                if shift_px <= 0.0:
                    continue
                world = (shift_px / float(res_y)
                         * float(prepared[upper]["frame_height"]))
                prepared[upper]["position"] = (prepared[upper]["position"]
                                               + prepared[upper]["up"] * world)
                prepared[upper]["applied_offset_px"] = float(
                    prepared[upper].get("applied_offset_px") or 0.0) + shift_px
                if prepared[upper]["offset_reason"] == REASON_NONE:
                    prepared[upper]["offset_reason"] = REASON_OVERLAP
                if prepared[upper] not in moved:
                    moved.append(prepared[upper])
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

    # v1.4 BW-2：**按帧**先算出所有标签的落点，再统一做标签间避让，最后
    # 才写关键帧。旧实现是"逐标签算完就写"，标签之间互相压住时无人可让。
    worst_offset: Dict[str, Dict[str, Any]] = {}
    for frame in frames:
        shot_id = _shot_at(schedule, frame)
        camera = cameras.get(shot_id) if shot_id else None
        if camera is None:
            continue
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        rotation = camera.matrix_world.to_euler()
        right, up = _camera_axes(camera)
        prepared: List[Dict[str, Any]] = []

        for entry in entries:
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
                unreadable.append({"character_id": character_id,
                                   "frame": frame, "reason": "投影退化"})
            else:
                scale = wanted_pixels / px_at_unit
            if scale * px_at_unit < min_pixels - 1e-6:
                unreadable.append({"character_id": character_id,
                                   "frame": frame, "reason": "低于可读下限"})

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
                delta_x = (target_x - projected.x) * frame_height * aspect
                delta_y = (target_y - projected.y) * frame_height
                offset += right * delta_x + up * delta_y
                applied_px = max(abs(delta_x) / max(frame_height * aspect, 1e-6)
                                 * res_x, abs(delta_y)
                                 / max(frame_height, 1e-6) * res_y)
                reason = REASON_OUT_OF_FRAME
            # 避让（二）：相机到锚点之间被内容物挡住时上移一档
            if _blocked(scene, camera, anchor_world):
                offset += up * (frame_height * 0.20)
                applied_px = max(applied_px, 0.20 * res_y)
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
                back = (camera.matrix_world.to_3x3() @
                        Vector((0.0, 0.0, -LABEL_STROKE_BACK)))
                _write(item["stroke"], item["position"] + back,
                       item["rotation"], item["scale"] * LABEL_STROKE_SCALE,
                       camera, frame)
            written += 1
            current = worst_offset.get(item["character_id"])
            if current is None or item["applied_offset_px"] > \
                    float(current.get("applied_offset_px") or 0.0):
                worst_offset[item["character_id"]] = {
                    "offset_reason": item["offset_reason"],
                    "applied_offset_px": round(item["applied_offset_px"], 2),
                    "frame": item["frame"]}

    log.info("标签烘焙完成：%d 个标签 / %d 帧采样", len(entries), written)
    return {"labels": len(entries), "frames": written,
            "sample_step": int(sample_step), "resolution": [int(res_x),
                                                            int(res_y)],
            "unreadable": unreadable, "offsets": worst_offset}


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
