"""镜头运动的解算（执行文档 v1.2 §10.2 的运镜部分）。

把"推/拉/摇/移/跟/升降"翻译成**相机位置与对准点的逐帧采样**。因为场景里的
相机是用 Track To 约束对准一个 Empty 的，所以"摇"和"俯仰"不是旋转相机对象，
而是**移动那个对准点**沿弧线走——约束会把旋转算出来。这样：

- 相机对象永远保持"看向目标"的语义，不会因为欧拉角插值出现翻滚；
- 运动轨迹与取景解算共用同一套坐标系（§10.1）。

纯计算，不依赖 bpy，因此可以在 pytest 里逐条断言。
"""

from __future__ import annotations

import math
from typing import Dict, List, Sequence, Tuple

Vector3 = Tuple[float, float, float]

#: 平移类（amount 单位：米）与旋转类（amount 单位：度）
TRANSLATIONS = {
    "dolly_in": "forward", "dolly_out": "-forward",
    "track_left": "-right", "track_right": "right",
    "crane_up": "up", "crane_down": "-up",
}
ROTATIONS = {
    "pan_left": ("up", 1.0), "pan_right": ("up", -1.0),
    "tilt_up": ("right", 1.0), "tilt_down": ("right", -1.0),
}
MOVEMENT_TYPES = tuple(list(TRANSLATIONS) + list(ROTATIONS))

LOOK_AT_DISTANCE = 3.0
DEFAULT_SAMPLES = 3          # 首 / 中 / 尾，够贝塞尔插值走出平滑弧线


def _sub(a: Sequence[float], b: Sequence[float]) -> Vector3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a: Sequence[float], b: Sequence[float]) -> Vector3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _scale(a: Sequence[float], factor: float) -> Vector3:
    return (a[0] * factor, a[1] * factor, a[2] * factor)


def _length(a: Sequence[float]) -> float:
    return math.sqrt(a[0] ** 2 + a[1] ** 2 + a[2] ** 2)


def _normalise(a: Sequence[float]) -> Vector3:
    norm = _length(a)
    if norm <= 1e-12:
        return (0.0, 0.0, 0.0)
    return (a[0] / norm, a[1] / norm, a[2] / norm)


def _cross(a: Sequence[float], b: Sequence[float]) -> Vector3:
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _rotate(vector: Sequence[float], axis: Sequence[float],
            angle: float) -> Vector3:
    """绕单位轴旋转（罗德里格斯公式）。"""
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    dotted = sum(vector[i] * axis[i] for i in range(3))
    crossed = _cross(axis, vector)
    return (vector[0] * cos_a + crossed[0] * sin_a
            + axis[0] * dotted * (1 - cos_a),
            vector[1] * cos_a + crossed[1] * sin_a
            + axis[1] * dotted * (1 - cos_a),
            vector[2] * cos_a + crossed[2] * sin_a
            + axis[2] * dotted * (1 - cos_a))


def _basis(position: Sequence[float], target: Sequence[float]):
    """返回 (forward, right, up) 正交基，right/up 由世界 Z 推出。"""
    forward = _normalise(_sub(target, position))
    world_up = (0.0, 0.0, 1.0)
    right = _cross(forward, world_up)
    if _length(right) <= 1e-9:            # 正上/正下方俯仰：退化时取世界 X
        right = (1.0, 0.0, 0.0)
    right = _normalise(right)
    up = _normalise(_cross(right, forward))
    return forward, right, up


def movement_samples(position: Sequence[float], target: Sequence[float],
                     movement: str, amount: float,
                     start_frame: int, end_frame: int,
                     samples: int = DEFAULT_SAMPLES
                     ) -> List[Dict[str, object]]:
    """把一次运镜展开成 ``[{frame, position, look_at}]`` 采样。"""
    movement = str(movement or "").strip()
    if movement not in MOVEMENT_TYPES:
        raise ValueError(f"未知运镜 {movement!r}。可用: "
                         f"{', '.join(MOVEMENT_TYPES)}")
    start, end = int(start_frame), int(end_frame)
    if end <= start:
        raise ValueError("end_frame 必须大于 start_frame")
    limit = max(int(samples), 2)

    forward, right, up = _basis(position, target)
    distance = max(_length(_sub(target, position)), 1e-6)
    position = tuple(float(v) for v in position)
    target = tuple(float(v) for v in target)
    direction = {"forward": forward, "-forward": _scale(forward, -1.0),
                 "right": right, "-right": _scale(right, -1.0),
                 "up": up, "-up": _scale(up, -1.0)}

    result: List[Dict[str, object]] = []
    for index in range(limit):
        t = index / float(limit - 1)
        frame = int(round(start + (end - start) * t))
        if movement in TRANSLATIONS:
            moved = _add(position, _scale(direction[TRANSLATIONS[movement]],
                                          float(amount) * t))
            result.append({"frame": frame, "position": moved, "look_at": target})
        else:
            axis, sign = ROTATIONS[movement]
            angle = math.radians(float(amount) * sign * t)
            rotated = _rotate(forward, direction[axis], angle)
            result.append({"frame": frame, "position": position,
                           "look_at": _add(position,
                                           _scale(rotated, distance))})
    return result


def describe(movement: str) -> str:
    """给工具返回值用的一句人话。"""
    if movement in TRANSLATIONS:
        return {"dolly_in": "推近", "dolly_out": "拉远", "track_left": "左移",
                "track_right": "右移", "crane_up": "升", "crane_down": "降"
                }.get(movement, movement)
    return {"pan_left": "左摇", "pan_right": "右摇",
            "tilt_up": "上摇", "tilt_down": "下摇"}.get(movement, movement)
