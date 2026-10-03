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
from .anchor import DEFAULT_PROFILE

SENSOR_WIDTH = 36.0
ASPECT_16_9 = 16.0 / 9.0

#: 角色身高常量：**全部**从 §2.1 的冻结 profile 派生（v1.4 P10）。
#: v1.3 这里的 1.45 / 1.10 / 0.95 是旧几何，且被当 ``camera_z`` 消费
#: （§1.6 的 #34）——照旧实施会"不报错但一直量错"。
_PROFILE = DEFAULT_PROFILE
SUBJECT_HEIGHT = _PROFILE.total_height
HEAD_TOP = _PROFILE.head_top_z
EYE_Z = _PROFILE.eye_z
CHEST_Z = _PROFILE.chest_z
WAIST_Z = _PROFILE.waist_z
KNEE_Z = _PROFILE.knee_z
FLOOR_Z = _PROFILE.ground_z

#: "含头部"景别的**代码单一真源**（§2.1/§2.2 的冻结枚举）。
#: 头顶留白（RK-15）与头球可见（RK-14）都按这个集合判定。
HEAD_SHOTS: Tuple[str, ...] = ("CU", "ECU", "MCU", "MS", "MLS")

#: board 档的头顶**验收**最小留白（占画面高度的比例，§2.2 / RK-15）。
HEADROOM_MIN = 0.08

#: 取景解算用的**设计**留白：= 验收线 + 抗锯齿/像素量化的允许量。
#: 实测（640×360 渲染）轮廓顶行比几何值低 1–2 px，正好吃掉整条 8% 线；把
#: 设计值抬到 0.10 之后，渲染量出的留白稳定 ≥ 8%，而视觉差异只有画面高的
#: 2%（中景 ≈ 2 cm）。这不是放宽验收，而是把"设计值 ≥ 验收线"写清楚。
HEADROOM_DESIGN = 0.10

#: 宽景（LS/ELS）在脚下留出的地面余量（占身高的比例）：脚正好压在画面下沿
#: 会让"全身入画"的判据落在边界上（浮点误差就能翻转结论）。
GROUND_MARGIN_RATIO = 0.06


@dataclass(frozen=True)
class ShotFrame:
    """一种景别的取景参数。"""

    frame_height: float     # 画面纵向覆盖的高度（越小越紧）
    target_z: float         # 镜头中心对准的高度
    camera_z: float         # 机位高度
    lens: float             # 建议焦距
    note: str = ""


def _frame_from_bottom(bottom_z: float, *, headroom: float = HEADROOM_DESIGN,
                       profile=_PROFILE) -> Tuple[float, float]:
    """由"画面下沿落在身体哪个高度"反推 ``(frame_height, target_z)``。

    冻结规则（§2.2）：**含头部景别头顶不切**——上边距 ≥ ``headroom`` × 画面高。
    于是 ``frame_top = head_top + headroom·h``，而 ``frame_top = target + h/2``、
    ``frame_bottom = target - h/2 = bottom_z``。两式相减解出::

        h        = (head_top - bottom_z) / (1 - headroom)
        target_z = head_top - (0.5 - headroom) · h

    这样"头顶留白"是**推导出来的**，不是手抄的一串数字——手抄的数值在几何
    改成 1.70 之后必然切头（§1.6 的 #1/#34 就是这么来的）。
    """
    h = (profile.head_top_z - float(bottom_z)) / (1.0 - headroom)
    target = profile.head_top_z - (0.5 - headroom) * h
    return h, target


#: 每个景别的**画面高度 ÷ 总身高**（v1.3 那张表按 1.45 归一后的比例）。
#: 保留这组比例很重要：它们是**被构图评分与既有两个镜头夹具校准过**的，
#: 直接改成"按身体部位反推"会让中远景突然收紧、两人镜的构图分掉到线下。
#: 唯一被强制抬高的是 ECU——它必须装得下整个头球（§2.2 的"头顶不切"）。
_FRAME_HEIGHT_RATIO: Dict[str, float] = {
    "ECU": 0.35 / 1.45,
    "CU": 0.90 / 1.45,
    "MCU": 1.00 / 1.45,
    "MS": 1.60 / 1.45,
    "MLS": 2.30 / 1.45,
    "LS": 3.00 / 1.45,
    "ELS": 6.50 / 1.45,
}

#: 含头部景别的最小画面高度：整个头球 + 设计留白。
_MIN_HEAD_FRAME = 1.0 / (1.0 - HEADROOM_DESIGN)

#: 宽景（LS/ELS）的对准高度 ÷ 总身高（v1.3 的 0.72/1.45）。宽景的目标是
#: "把人和环境一起交代清楚"，不是"给头顶留 8%"——照头顶留白反推会把
#: 大远景的对准点推到地面以下（-1.3 m），画面里只剩地面。
_WIDE_TARGET_RATIO = 0.72 / 1.45


def _shot_frames(profile=_PROFILE) -> Dict[str, ShotFrame]:
    """按 profile 重算九宫格的取景参数（单调：越靠后越"远"）。

    ``h = 比例 × 总身高``（比例沿用 v1.3 的表，只是随身高缩放），
    对准高度由"头顶留白 = 设计值"反推：``target_z = head_top -
    (0.5 - headroom)·h``。这样**画面大小**保持既有观感与构图基准，
    **画面位置**严格满足 §2.2 的头顶留白。
    """
    def frame_for(key: str) -> Tuple[float, float]:
        height = _FRAME_HEIGHT_RATIO[key] * profile.total_height
        if key in HEAD_SHOTS:
            # 头球直径 + 设计留白（ECU 尤其需要这条下限，否则会切头）。
            height = max(height, profile.head_d * _MIN_HEAD_FRAME)
            target = profile.head_top_z - (0.5 - HEADROOM_DESIGN) * height
        else:
            target = _WIDE_TARGET_RATIO * profile.total_height
        return height, target

    ec_h, ec_t = frame_for("ECU")
    cu_h, cu_t = frame_for("CU")
    mcu_h, mcu_t = frame_for("MCU")
    ms_h, ms_t = frame_for("MS")
    mls_h, mls_t = frame_for("MLS")
    ls_h, ls_t = frame_for("LS")
    els_h, els_t = frame_for("ELS")
    # **含头部景别**的机位与对准点**同高**（无俯仰）：纯解算器按"被摄平面
    # 垂直于视轴"推导画面高度，一旦机位比对准点高/低就会引入几度的俯仰，
    # 实测头顶留白会因此少 1–2% 的画面高（ECU 上最明显）。同高之后推导
    # 与渲染逐像素一致（用 640×360 的对拍实测过），§2.2 的 8% 才是硬数字。
    return {
        "ECU": ShotFrame(ec_h, ec_t, ec_t, 85.0, "大特写：眼睛/局部占满"),
        "CU": ShotFrame(cu_h, cu_t, cu_t, 85.0, "特写：头部为主"),
        "MCU": ShotFrame(mcu_h, mcu_t, mcu_t, 50.0, "中近景：胸部以上"),
        "MS": ShotFrame(ms_h, ms_t, ms_t, 50.0, "中景：腰部以上"),
        "MLS": ShotFrame(mls_h, mls_t, mls_t, 35.0, "中远景：膝盖以上"),
        "LS": ShotFrame(ls_h, ls_t, profile.chest_z, 35.0, "全景：全身"),
        "ELS": ShotFrame(els_h, els_t, profile.chest_z, 24.0, "大远景：人物<20%"),
        # OTS/POV 复用邻近景别的取景，位置另算
        "OTS": ShotFrame(mcu_h, mcu_t, mcu_t, 50.0, "过肩：复用中近景取景"),
        "POV": ShotFrame(mcu_h, profile.eye_z, profile.eye_z, 35.0,
                         "主观：机位落在角色眼睛"),
    }


#: 单调递增：越靠后越"远"
SHOT_FRAME: Dict[str, ShotFrame] = _shot_frames()


def shot_frame_for(shot_type: str, profile=_PROFILE) -> ShotFrame:
    """按给定 profile 取某一景别的取景参数（默认 profile 时等同查表）。"""
    if profile is _PROFILE:
        return SHOT_FRAME[str(shot_type).upper()]
    return _shot_frames(profile)[str(shot_type).upper()]


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


#: 机位相对主体的**合法方位**（9 个 token，闭集）。
#:
#: 为什么它必须是闭集（2026-10-03 的 64 镜真跑实测）：B1 草案 schema 里
#: `camera.side` 只声明了 `type: string`（场景工具那侧**另有一份手抄的枚举**），
#: 于是模型写了整句中文——"轴线同侧，米迦尔侧前方，较前一镜角度变化大于 30°…"
#: ——而 `side_vector` 对未知取值**静默折成 `front`**（`table.get(side, table["front"])`）。
#: 结果：64 个镜头的机位全被折成"正面"，构图分中位从 **82.7 掉到 58.4**、
#: 64/64 镜判失败。修法就是把两处各写一份的取值表收成这一份真源：
#: 草案 schema 与场景工具都从这里取枚举，提示词也从这里生成。
CAMERA_SIDES: Tuple[str, ...] = (
    "front", "back", "left", "right",
    "front_left", "front_right", "back_left", "back_right",
    "over_shoulder",
)


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
    #: 表就是 `CAMERA_SIDES` 的唯一真源：两边不一致时**当场炸**，而不是悄悄多认/少认一个。
    if set(table) != set(CAMERA_SIDES):  # pragma: no cover - 漂移即构建期错误
        raise AssertionError(
            f"side 取值表与 CAMERA_SIDES 漂了：{sorted(table)} vs {list(CAMERA_SIDES)}")
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
