"""视口叠加的几何计算（执行文档 v1.2 §13.4）。

``draw_overlay.py`` 只负责把这里算出来的线段喂给 GPU；几何本身是纯计算，
于是"三分法网格画在哪""安全框内缩多少""视锥四条棱连哪两个点"这些容易画错的
东西可以在 pytest 里断言，而不是靠肉眼在视口里看。

坐标约定：
- 屏幕线用归一化设备坐标 ``[0,1]``（左下原点，与 §17.4 的投影一致）；
- 世界线用 Blender 世界坐标（§1.4 的 Z-up）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, List, Sequence, Tuple

ScreenPoint = Tuple[float, float]
WorldPoint = Tuple[float, float, float]
Segment2D = Tuple[ScreenPoint, ScreenPoint]
Segment3D = Tuple[WorldPoint, WorldPoint]

THIRDS = (1.0 / 3.0, 2.0 / 3.0)

#: 安全框内缩比例（EBU/ITU 的常用值，§13.4 只要求"有 title / action 两种"）
TITLE_SAFE = 0.90
ACTION_SAFE = 0.93


@dataclass
class OverlayGeometry:
    """一次绘制需要的全部线段，按用途分组（颜色由绘制层决定）。"""

    thirds: List[Segment2D] = field(default_factory=list)
    safe_areas: List[List[ScreenPoint]] = field(default_factory=list)
    axis_lines: List[Segment3D] = field(default_factory=list)
    paths: List[List[WorldPoint]] = field(default_factory=list)
    frustums: List[List[WorldPoint]] = field(default_factory=list)
    violations: List[List[ScreenPoint]] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not any((self.thirds, self.safe_areas, self.axis_lines,
                        self.paths, self.frustums, self.violations))


def thirds_grid() -> List[Segment2D]:
    """三分法网格：两条竖线 + 两条横线。"""
    segments: List[Segment2D] = []
    for position in THIRDS:
        segments.append(((position, 0.0), (position, 1.0)))
        segments.append(((0.0, position), (1.0, position)))
    return segments


def screen_rect(inset: float) -> List[ScreenPoint]:
    """按比例内缩的矩形（顺时针四角）。``inset=0`` 即整幅画面。"""
    low = max(0.0, min(0.5, inset / 2.0))
    high = 1.0 - low
    return [(low, low), (high, low), (high, high), (low, high)]


def safe_area_rects(title: float = TITLE_SAFE,
                    action: float = ACTION_SAFE) -> List[List[ScreenPoint]]:
    """安全框：外圈 action-safe，内圈 title-safe（大的在前，便于先画外圈）。"""
    outer = max(title, action)
    inner = min(title, action)
    return [screen_rect(1.0 - outer), screen_rect(1.0 - inner)]


def dashed_segments(start: WorldPoint, end: WorldPoint,
                    dashes: int = 12) -> List[Segment3D]:
    """把一条世界线切成虚线（轴线按 §13.4 要求画成绿色虚线）。

    均匀分成 ``2*dashes-1`` 个槽位，虚线占偶数槽——这样**最后一段正好落在
    终点**，读起来是一条完整的虚线，而不是差一截的尾巴。``dashes=1`` 即实线。
    """
    if dashes < 1:
        return [(start, end)]
    slots = 2 * dashes - 1
    segments: List[Segment3D] = []
    for index in range(dashes):
        t0 = (2 * index) / float(slots)
        t1 = (2 * index + 1) / float(slots)
        segments.append((
            tuple(start[i] + (end[i] - start[i]) * t0 for i in range(3)),
            tuple(start[i] + (end[i] - start[i]) * t1 for i in range(3)),
        ))
    return segments


def frustum_lines(position: Sequence[float], target: Sequence[float],
                  lens: float, sensor_width: float = 36.0,
                  aspect: float = 16.0 / 9.0,
                  depth: float | None = None) -> List[WorldPoint]:
    """相机视锥线框：四条棱 + 远端四边形，返回折线（每段两点）。"""
    origin = tuple(float(v) for v in position)
    focus = tuple(float(v) for v in target)
    direction = tuple(focus[i] - origin[i] for i in range(3))
    distance = math.sqrt(sum(component * component for component in direction))
    if distance <= 1e-9 or lens <= 0:
        return []
    forward = tuple(component / distance for component in direction)
    # 相机朝上方向固定为世界 Z（Track To 约束的实际行为），再正交化
    up_world = (0.0, 0.0, 1.0)
    right = (forward[1] * up_world[2] - forward[2] * up_world[1],
             forward[2] * up_world[0] - forward[0] * up_world[2],
             forward[0] * up_world[1] - forward[1] * up_world[0])
    right_norm = math.sqrt(sum(component * component for component in right))
    if right_norm <= 1e-9:
        right = (1.0, 0.0, 0.0)
        right_norm = 1.0
    right = tuple(component / right_norm for component in right)
    up = (right[1] * forward[2] - right[2] * forward[1],
          right[2] * forward[0] - right[0] * forward[2],
          right[0] * forward[1] - right[1] * forward[0])

    reach = float(depth) if depth else distance
    sensor_height = sensor_width / aspect
    half_h = reach * (sensor_height / 2.0) / lens
    half_w = half_h * aspect
    apex = origin
    corners = []
    for sign_w, sign_h in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        corners.append(tuple(
            apex[i] + forward[i] * reach + right[i] * half_w * sign_w
            + up[i] * half_h * sign_h for i in range(3)))

    lines: List[WorldPoint] = []
    for corner in corners:                      # 四条棱
        lines.extend([apex, corner])
    for index in range(4):                      # 远端四边形
        lines.extend([corners[index], corners[(index + 1) % 4]])
    return lines


def build_overlay(*, show_thirds: bool = True, show_safe_area: bool = True,
                  axis: Sequence[Sequence[float]] | None = None,
                  paths: Iterable[Sequence[Sequence[float]]] = (),
                  frustums: Iterable[Sequence[object]] = (),
                  violations: Iterable[Sequence[Sequence[float]]] = ()
                  ) -> OverlayGeometry:
    """按开关与当前场景数据组装一次叠加几何。

    ``frustums`` 每项是 ``(position, target, lens)``（或带 sensor/aspect 的更长
    元组）；``violations`` 每项是屏幕空间的矩形框（违规元素红框闪烁用）。
    """
    geometry = OverlayGeometry()
    if show_thirds:
        geometry.thirds = thirds_grid()
    if show_safe_area:
        geometry.safe_areas = safe_area_rects()
    if axis is not None and len(axis) >= 2:
        geometry.axis_lines = dashed_segments(tuple(axis[0]), tuple(axis[1]))
    for path in paths:
        points = [tuple(float(v) for v in point) for point in path]
        if len(points) >= 2:
            geometry.paths.append(points)
    for item in frustums:
        values = list(item)
        if len(values) < 3:
            continue
        geometry.frustums.append(
            frustum_lines(values[0], values[1], float(values[2]),
                          float(values[3]) if len(values) > 3 else 36.0,
                          float(values[4]) if len(values) > 4 else 16.0 / 9.0,
                          float(values[5]) if len(values) > 5 else None))
    for box in violations:
        points = [tuple(float(v) for v in point) for point in box]
        if len(points) >= 3:
            geometry.violations.append(points)
    return geometry
