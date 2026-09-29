"""取景解算：景别 + 焦距 → 距离与机位（执行文档 v1.2 §10.1 / §10.6）。

**对 §10.5 的一处修正**：文档给的"取景比例（主体占画面高）"四个数字互相矛盾——
按它换算，MCU 的有效画面比 CU 更窄、MLS 比 LS 更宽，等于把景别顺序搞反了。
本模块改用一张**单调**的"画面高度"表（单位：Blender 单位 / 米）。

    景别越紧 → frame_height 越小 → 相机越近

并把"取景比例"的含义固定为：``frame_height = 被摄范围高度 / 取景比例``。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from ..contracts.enums import SHOT_TYPES, ShotType

SENSOR_WIDTH = 36.0
ASPECT_16_9 = 16.0 / 9.0

# 角色身高常量（与 §9.1 一致）
SUBJECT_HEIGHT = 1.45
HEAD_TOP = 1.45
EYE_Z = 1.10
CHEST_Z = 0.95
WAIST_Z = 0.70
KNEE_Z = 0.20
FLOOR_Z = 0.0


@dataclass(frozen=True)
class ShotFrame:
    """一种景别的取景参数。"""

    frame_height: float     # 画面纵向覆盖的高度（越小越紧）
    target_z: float         # 镜头中心对准的高度
    camera_z: float         # 机位高度
    lens: float             # 建议焦距
    note: str = ""


# 单调递增：越靠后越"远"
SHOT_FRAME: Dict[str, ShotFrame] = {
    "ECU": ShotFrame(0.35, EYE_Z, EYE_Z, 85.0, "大特写：眼睛/局部占满"),
    "CU": ShotFrame(0.90, EYE_Z, EYE_Z, 85.0, "特写：头部≈80%"),
    "MCU": ShotFrame(1.00, 1.12, 1.05, 50.0, "中近景：胸部以上≈60%"),
    "MS": ShotFrame(1.60, 1.00, 1.05, 50.0, "中景：腰部以上≈45%"),
    "MLS": ShotFrame(2.30, 0.80, CHEST_Z, 35.0, "中远景：膝盖以上≈30%"),
    "LS": ShotFrame(3.00, 0.72, CHEST_Z, 35.0, "全景：全身≈60%"),
    "ELS": ShotFrame(6.50, 0.72, CHEST_Z, 24.0, "大远景：人物<20%"),
    # OTS/POV 复用邻近景别的取景，位置另算
    "OTS": ShotFrame(1.60, 1.12, 1.05, 50.0, "过肩：复用中景取景"),
    "POV": ShotFrame(1.60, 1.10, EYE_Z, 35.0, "主观：机位落在角色眼睛"),
}


@dataclass
class FramingResult:
    shot_type: str
    lens: float
    distance: float
    position: Tuple[float, float, float]
    target: Tuple[float, float, float]
    camera_height: float
    frame_height: float
    warnings: List[str] = field(default_factory=list)
    clamped: bool = False


def vertical_fov(lens: float, sensor_width: float = SENSOR_WIDTH,
                 aspect: float = ASPECT_16_9) -> float:
    """垂直视场角（弧度）。传感器横向尺寸 / 宽高比 = 纵向尺寸。"""
    sensor_height = sensor_width / aspect
    return 2.0 * math.atan(sensor_height / (2.0 * lens))


def required_distance(frame_height: float, lens: float,
                      sensor_width: float = SENSOR_WIDTH,
                      aspect: float = ASPECT_16_9) -> float:
    """让 ``frame_height`` 恰好填满画面所需的相机距离（§10.6）。"""
    return frame_height / (2.0 * math.tan(vertical_fov(lens, sensor_width, aspect) / 2.0))


def side_vector(facing: Sequence[float], side: str) -> Tuple[float, float]:
    """相对**被摄主体朝向**计算机位方向（不是世界轴）。

    facing 默认 (0,1,0)（角色面朝 +Y）；right = facing 在 XY 内顺时针 90°。
    """
    fx, fy = float(facing[0]), float(facing[1])
    length = math.hypot(fx, fy)
    if length < 1e-9:
        fx, fy = 0.0, 1.0
    else:
        fx, fy = fx / length, fy / length
    right_x, right_y = fy, -fx

    table = {
        "front": (fx, fy),
        "back": (-fx, -fy),
        "left": (-right_x, -right_y),
        "right": (right_x, right_y),
        "front_left": (fx - right_x, fy - right_y),
        "front_right": (fx + right_x, fy + right_y),
        "back_left": (-fx - right_x, -fy - right_y),
        "back_right": (-fx + right_x, -fy + right_y),
        "over_shoulder": (fx - 0.6 * right_x, fy - 0.6 * right_y),
    }
    dx, dy = table.get(side, table["front"])
    norm = math.hypot(dx, dy)
    if norm < 1e-9:
        return (fx, fy)
    return (dx / norm, dy / norm)


def _clamp_to_room(position: Tuple[float, float, float],
                   room: Optional[Sequence[float]], margin: float) -> Tuple[
                       Tuple[float, float, float], bool]:
    """把机位夹回房间内（§10.1 实测要求：室内 far 机位不得穿墙）。"""
    if not room or len(room) != 4:
        return position, False
    min_x, max_x, min_y, max_y = (float(v) for v in room)
    x = min(max(position[0], min_x + margin), max_x - margin)
    y = min(max(position[1], min_y + margin), max_y - margin)
    clamped = (abs(x - position[0]) > 1e-9) or (abs(y - position[1]) > 1e-9)
    return (x, y, position[2]), clamped


def solve_framing(subject_pos: Sequence[float],
                  facing: Sequence[float] = (0.0, 1.0, 0.0),
                  shot_type: str = "MS",
                  side: str = "front",
                  lens: Optional[float] = None,
                  room: Optional[Sequence[float]] = None,
                  margin: float = 0.5,
                  sensor_width: float = SENSOR_WIDTH,
                  direction: Optional[Sequence[float]] = None,
                  aspect: float = ASPECT_16_9) -> FramingResult:
    """解算机位与对准点。

    ``room`` 形如 ``(min_x, max_x, min_y, max_y)``；给出时机位会被夹在房间内。

    ``direction`` 是**已经解算好的机位方向**（单位向量，XY 平面）。给出时
    覆盖 ``side``：双人镜头的 ``side`` 必须相对两人连线而不是相对焦点主体
    的朝向解析（否则相机正好落在轴线上，R001 必报），那段语义在
    :mod:`block_director.cinema.station` 里，本函数只负责把它落到坐标上。
    """
    warnings: List[str] = []
    key = str(shot_type).upper()
    if key not in SHOT_FRAME:
        warnings.append(f"未知景别 {shot_type}，按 MS 处理")
        key = "MS"
    frame = SHOT_FRAME[key]
    effective_lens = float(lens if lens else frame.lens)

    base_x, base_y = float(subject_pos[0]), float(subject_pos[1])
    head = (base_x, base_y, EYE_Z)

    if key == "POV":
        position = (base_x, base_y, EYE_Z)
        dx, dy = side_vector(facing, "front")
        target = (base_x + dx * 3.0, base_y + dy * 3.0, EYE_Z)
        return FramingResult(shot_type=key, lens=effective_lens, distance=0.0,
                             position=position, target=target,
                             camera_height=EYE_Z, frame_height=frame.frame_height,
                             warnings=warnings)

    distance = required_distance(frame.frame_height, effective_lens,
                                 sensor_width, aspect)
    if direction is not None:
        dx, dy = float(direction[0]), float(direction[1])
        norm = math.hypot(dx, dy)
        if norm < 1e-9:
            dx, dy = side_vector(facing, side)
        else:
            dx, dy = dx / norm, dy / norm
    else:
        dx, dy = side_vector(facing, side)
    position = (base_x + dx * distance, base_y + dy * distance, frame.camera_z)
    position, clamped = _clamp_to_room(position, room, margin)
    if clamped:
        warnings.append(
            f"机位被房间边界夹回（原距 {distance:.2f}），实际取景将偏离 "
            f"{key} 设定；建议改用更短焦距或扩大房间")

    target = (base_x, base_y, frame.target_z)
    return FramingResult(shot_type=key, lens=effective_lens, distance=distance,
                         position=position, target=target,
                         camera_height=frame.camera_z,
                         frame_height=frame.frame_height,
                         warnings=warnings, clamped=clamped)


def shot_types() -> Tuple[str, ...]:
    return SHOT_TYPES
