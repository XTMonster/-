"""路径平滑与简化（执行文档 v1.2 §17.1 / §17.2）。

画线工具（§9.5）的数学部分：用户拖出来的是**折线**，直接用它生成关键帧会
又抖又多；先 RDP 简化去掉冗余采样点，再用 Catmull-Rom 平滑成 C1 连续曲线。

顺序很重要：先简化后平滑。反过来的话，平滑会把抖动抹成"看似合理"的曲线，
RDP 再去掉点就带走了原本的形状信息（平滑后的极值点不再落在采样点上）。

纯计算，维度无关（2D/3D 都能用），因此可以在 pytest 里逐条断言。
"""

from __future__ import annotations

import math
from typing import List, Sequence, Tuple

Point = Tuple[float, ...]

SAMPLES_PER_SEGMENT = 10
RDP_EPSILON = 0.05


def _as_points(points: Sequence[Sequence[float]]) -> List[Point]:
    return [tuple(float(value) for value in point) for point in points]


def _lerp(a: Point, b: Point, t: float) -> Point:
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(len(a)))


def catmull_rom(points: Sequence[Sequence[float]],
                samples_per_segment: int = SAMPLES_PER_SEGMENT) -> List[Point]:
    """Catmull-Rom 样条：输入折线，输出 C1 连续的平滑曲线。

    端点用"复制首尾点"的方式处理（虚拟控制点 = 端点自身），这样曲线仍然
    精确穿过第一个与最后一个采样点——画线工具需要这一条，否则起点会漂移。
    """
    pts = _as_points(points)
    if len(pts) < 2:
        return pts
    if samples_per_segment < 1:
        return pts

    extended = [pts[0]] + pts + [pts[-1]]
    curve: List[Point] = []
    for index in range(len(pts) - 1):
        p0, p1, p2, p3 = (extended[index], extended[index + 1],
                          extended[index + 2], extended[index + 3])
        for step in range(samples_per_segment):
            t = step / float(samples_per_segment)
            t2 = t * t
            t3 = t2 * t
            curve.append(tuple(
                0.5 * ((2.0 * p1[i])
                       + (-p0[i] + p2[i]) * t
                       + (2.0 * p0[i] - 5.0 * p1[i] + 4.0 * p2[i] - p3[i]) * t2
                       + (-p0[i] + 3.0 * p1[i] - 3.0 * p2[i] + p3[i]) * t3)
                for i in range(len(p1))))
    curve.append(pts[-1])
    return curve


def _perpendicular_distance(point: Point, start: Point,
                            end: Point) -> float:
    if len(point) < 2:
        return 0.0
    px, py = point[0], point[1]
    ax, ay = start[0], start[1]
    bx, by = end[0], end[1]
    dx, dy = bx - ax, by - ay
    span = dx * dx + dy * dy
    if span <= 1e-12:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / span))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def rdp(points: Sequence[Sequence[float]],
        epsilon: float = RDP_EPSILON) -> List[Point]:
    """Ramer–Douglas–Peucker 简化：保留偏差超过 ``epsilon`` 的点。"""
    pts = _as_points(points)
    if len(pts) <= 2:
        return pts

    def simplify(segment: List[Point]) -> List[Point]:
        if len(segment) <= 2:
            return segment
        worst = 0.0
        worst_index = 0
        for index in range(1, len(segment) - 1):
            distance = _perpendicular_distance(segment[index], segment[0],
                                               segment[-1])
            if distance > worst:
                worst, worst_index = distance, index
        if worst <= epsilon or worst_index == 0:
            return [segment[0], segment[-1]]
        left = simplify(segment[: worst_index + 1])
        right = simplify(segment[worst_index:])
        return left[:-1] + right

    return simplify(pts)


def simplify_and_smooth(points: Sequence[Sequence[float]],
                        epsilon: float = RDP_EPSILON,
                        samples_per_segment: int = SAMPLES_PER_SEGMENT
                        ) -> List[Point]:
    """先 RDP 简化、再 Catmull-Rom 平滑（§9.5 的默认处理链）。"""
    return catmull_rom(rdp(points, epsilon), samples_per_segment)


def tangents(points: Sequence[Sequence[float]]) -> List[Point]:
    """每个点的切线方向（单位向量）；首尾用单侧差分。"""
    pts = _as_points(points)
    if len(pts) < 2:
        return [(0.0, 1.0, 0.0)[: len(pts[0])] if pts else []]
    result: List[Point] = []
    for index in range(len(pts)):
        if index == 0:
            delta = [pts[1][i] - pts[0][i] for i in range(len(pts[0]))]
        elif index == len(pts) - 1:
            delta = [pts[-1][i] - pts[-2][i] for i in range(len(pts[0]))]
        else:
            delta = [pts[index + 1][i] - pts[index - 1][i]
                     for i in range(len(pts[0]))]
        norm = math.sqrt(sum(component * component for component in delta))
        if norm <= 1e-12:
            result.append(tuple(0.0 for _ in delta))
        else:
            result.append(tuple(component / norm for component in delta))
    return result


def facing_along(points: Sequence[Sequence[float]]) -> List[Tuple[float, float]]:
    """沿路径切线求水平朝向（给角色转身用，§9.5）。"""
    facings: List[Tuple[float, float]] = []
    for tangent in tangents(points):
        x = tangent[0] if tangent else 0.0
        y = tangent[1] if len(tangent) > 1 else 1.0
        norm = math.hypot(x, y)
        if norm <= 1e-12:
            facings.append((0.0, 1.0))
        else:
            facings.append((x / norm, y / norm))
    return facings


def path_length(points: Sequence[Sequence[float]]) -> float:
    """折线总长（用于校验"这个走位需要多少帧"）。"""
    pts = _as_points(points)
    total = 0.0
    for index in range(1, len(pts)):
        total += math.dist(pts[index - 1], pts[index])
    return total
