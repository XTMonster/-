"""180° 轴线与 30° 规则（执行文档 v1.2 §10.3 / R001 / R010）。

坐标系 Z-up：轴线方向与"起点到相机"向量做叉积，取 **Z 分量**的符号即可
判定相机在轴线哪一侧——这正是 §10.3 的算法。本模块把它做成纯函数。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence, Tuple

from ..contracts.enums import SHOT_TYPES

EPS = 1e-9

SIDE_POSITIVE = 1
SIDE_NEGATIVE = -1
SIDE_UNKNOWN = 0

#: 机位相对已确立轴线的三种状态（§10.3 / R001）
AXIS_CORRECT = "correct"
AXIS_NEUTRAL = "neutral"
AXIS_CROSSED = "crossed"

# §10.5 的景别由紧到松，用于 R010 的"景别变化至少一档"
SHOT_SIZE_ORDER: Tuple[str, ...] = ("ECU", "CU", "MCU", "MS", "MLS", "LS", "ELS")

# R010：相邻镜头机位角差小于该值时，必须有景别变化
MIN_ANGLE_DEG = 30.0


@dataclass(frozen=True)
class Axis:
    """一条轴线：两人连线 + 已确立的基准侧。"""

    start: Tuple[float, float]
    end: Tuple[float, float]
    established_side: int = SIDE_POSITIVE
    left_label: str = ""
    right_label: str = ""

    @property
    def direction(self) -> Tuple[float, float]:
        dx = self.end[0] - self.start[0]
        dy = self.end[1] - self.start[1]
        norm = math.hypot(dx, dy)
        if norm < EPS:
            return (0.0, 0.0)
        return (dx / norm, dy / norm)

    @property
    def length(self) -> float:
        return math.hypot(self.end[0] - self.start[0], self.end[1] - self.start[1])

    def side_of(self, point: Sequence[float]) -> int:
        """返回点在轴线的哪一侧：+1 / -1 / 0（落在轴线上）。"""
        dx, dy = self.direction
        if dx == 0.0 and dy == 0.0:
            return SIDE_UNKNOWN
        tx = float(point[0]) - self.start[0]
        ty = float(point[1]) - self.start[1]
        cross_z = dx * ty - dy * tx
        if cross_z > EPS:
            return SIDE_POSITIVE
        if cross_z < -EPS:
            return SIDE_NEGATIVE
        return SIDE_UNKNOWN

    def is_correct_side(self, point: Sequence[float]) -> bool:
        return self.side_of(point) == self.established_side

    def to_dict(self) -> Dict[str, Any]:
        return {"start": list(self.start), "end": list(self.end),
                "established_side": self.established_side,
                "left_label": self.left_label, "right_label": self.right_label}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Axis":
        return cls(start=tuple(data["start"]), end=tuple(data["end"]),
                   established_side=int(data.get("established_side", SIDE_POSITIVE)),
                   left_label=str(data.get("left_label", "")),
                   right_label=str(data.get("right_label", "")))


def axis_from_points(a: Sequence[float], b: Sequence[float],
                     a_label: str = "", b_label: str = "") -> Axis:
    """用两点连线构造轴线（尚未确立基准侧）。"""
    return Axis(start=(float(a[0]), float(a[1])),
                end=(float(b[0]), float(b[1])),
                left_label=a_label, right_label=b_label)


def axis_for_speakers(positions: Sequence[Tuple[Sequence[float], str]]
                      ) -> Optional[Axis]:
    """以当前说话的两人为轴线；第三人及以后不参与（§10.3 多人轴线）。"""
    if len(positions) < 2:
        return None
    (first, first_label), (second, second_label) = positions[0], positions[1]
    axis = axis_from_points(first, second, first_label, second_label)
    return axis if axis.length > EPS else None


def establish_axis(axis: Axis, camera: Sequence[float]) -> Axis:
    """用**首镜机位**确立基准侧（§10.3：首镜决定整场方向感）。"""
    side = axis.side_of(camera)
    if side == SIDE_UNKNOWN:
        side = SIDE_POSITIVE      # 机位正好落在轴线上：退化为 +1，由调用方告警
    return Axis(start=axis.start, end=axis.end, established_side=side,
                left_label=axis.left_label, right_label=axis.right_label)


def axis_status(axis: Axis, camera: Sequence[float]) -> str:
    """机位相对轴线的状态：``correct`` / ``neutral`` / ``crossed``。

    ``neutral`` = 机位恰好落在轴线上，画面没有左右信息。它不是"越轴"，
    而是 §6.2 ``axis_neutral`` 卡片定义的跨轴桥梁。
    """
    side = axis.side_of(camera)
    if side == SIDE_UNKNOWN:
        return AXIS_NEUTRAL
    return AXIS_CORRECT if side == axis.established_side else AXIS_CROSSED


def axis_violation(axis: Axis, camera: Sequence[float]) -> Optional[str]:
    """**越轴**时返回中文建议；合规与中性机位都返回 ``None``（R001）。

    v1.3 修正：v1.2 把"机位落在轴线上"也判为违规。但中性镜头在
    §6.2 的 ``axis_neutral`` 卡片里是**合法**的跨轴桥梁，而且两人相对而立
    （"互相看向对方"）时，任何单人正反打的机位都必然落在轴线上——按旧判据
    这类镜头永远无法通过审核。现在中性不再是违规，改为由
    :func:`axis_neutral_note` 给出的提示（R001 降级为 warning）；
    真正跨到另一侧仍然报错。
    """
    if axis_status(axis, camera) == AXIS_CROSSED:
        return ("相机位置违反 180° 轴线规则，可能导致角色左右方向混乱。"
                "建议将相机移到轴线另一侧，或插入中性镜头过渡。")
    return None


def axis_neutral_note(axis: Axis, camera: Sequence[float]) -> Optional[str]:
    """中性机位的提示文本；非中性返回 ``None``。"""
    if axis_status(axis, camera) != AXIS_NEUTRAL:
        return None
    return ("机位落在轴线上（中性镜头）：画面没有明确的左右信息，"
            "可以作为跨轴桥梁，但连续使用会失去空间感。")


# --------------------------------------------------------------------------- #
# R010：30° 规则
# --------------------------------------------------------------------------- #
def shot_size_index(shot_type: str) -> int:
    key = str(shot_type).upper()
    return SHOT_SIZE_ORDER.index(key) if key in SHOT_SIZE_ORDER else -1


def shot_size_changed(previous: str, current: str) -> bool:
    """两个景别是否至少差一档。"""
    a, b = shot_size_index(previous), shot_size_index(current)
    if a < 0 or b < 0:
        return False
    return abs(a - b) >= 1


def camera_angle_deg(previous_camera: Sequence[float],
                     current_camera: Sequence[float],
                     target: Sequence[float]) -> float:
    """相邻两次机位相对被摄目标的夹角（度）。"""
    ax = float(previous_camera[0]) - float(target[0])
    ay = float(previous_camera[1]) - float(target[1])
    bx = float(current_camera[0]) - float(target[0])
    by = float(current_camera[1]) - float(target[1])
    na, nb = math.hypot(ax, ay), math.hypot(bx, by)
    if na < EPS or nb < EPS:
        return 0.0
    cos_value = max(-1.0, min(1.0, (ax * bx + ay * by) / (na * nb)))
    return math.degrees(math.acos(cos_value))


def thirty_degree_violation(previous_camera: Sequence[float],
                            current_camera: Sequence[float],
                            target: Sequence[float],
                            previous_shot: str,
                            current_shot: str) -> Optional[str]:
    """R010：角差不足 30° 且景别未变化 → 判为跳切隐患。"""
    angle = camera_angle_deg(previous_camera, current_camera, target)
    if angle >= MIN_ANGLE_DEG or shot_size_changed(previous_shot, current_shot):
        return None
    return (f"相邻镜头机位角差仅 {angle:.1f}°（< {MIN_ANGLE_DEG:.0f}°）"
            f"且景别未变化（{previous_shot} → {current_shot}），"
            f"看起来像跳切。建议改变机位角度，或至少变化一档景别。")


def shot_types() -> Tuple[str, ...]:
    return SHOT_TYPES


# --------------------------------------------------------------------------- #
# R019：银幕方向连续性（v1.4 §3.4，替代死字段 screen_direction）
# --------------------------------------------------------------------------- #
#: 判定"符号翻转"时的中性死区：|dot| 小于它视为中性（画面里看不出朝向）。
SCREEN_DIRECTION_EPS = 1e-3


def shared_characters(previous: Sequence[str],
                      current: Sequence[str]) -> list:
    """相邻两镜**都显式声明**的角色 id（保持前一镜的顺序）。"""
    current_set = {str(item) for item in (current or [])}
    return [str(item) for item in (previous or []) if str(item) in current_set]


def flipped_screen_directions(previous_facing: Dict[str, float],
                              current_facing: Dict[str, float],
                              character_ids: Sequence[str],
                              *, eps: float = SCREEN_DIRECTION_EPS) -> list:
    """返回在相邻两镜之间**银幕方向符号翻转**的角色 id。

    只对 ``character_ids``（＝两镜都显式声明、且两镜都算得出朝向）里的角色
    判定；任一镜的 ``|dot| < eps``（中性）都不算翻转——"翻转"必须有左右两侧。
    """
    flipped: list = []
    for character_id in character_ids:
        key = str(character_id)
        before = previous_facing.get(key)
        now = current_facing.get(key)
        if before is None or now is None:
            continue
        if abs(before) < eps or abs(now) < eps:
            continue
        if before * now < 0:
            flipped.append(key)
    return flipped
