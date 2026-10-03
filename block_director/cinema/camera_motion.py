"""镜头运动的解算（执行文档 v1.2 §10.2 / v1.3 P7）。

把运镜翻译成**相机位置、对准点与焦距**的逐帧采样。因为场景里的相机是用
Track To 约束对准一个 Empty 的，所以"摇"和"俯仰"不是旋转相机对象，
而是**移动那个对准点**沿弧线走——约束会把旋转算出来。这样：

- 相机对象永远保持"看向目标"的语义，不会因为欧拉角插值出现翻滚；
- 运动轨迹与取景解算共用同一套坐标系（§10.1）。

v1.3 把封闭清单从 10 种补到 24 种。知识库里 ``engine_support`` 的分类以
本模块的 ``MOVEMENT_TYPES`` 为准（``tests/test_knowledge.py`` 逐条对拍）：
标 ``unsupported`` 的条目，在加入这里之前模型不该要求引擎去做。

纯计算，不依赖 bpy，因此可以在 pytest 里逐条断言。
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

from ..contracts.enums import MOVEMENT_TYPES

Vector3 = Tuple[float, float, float]

#: 平移类（amount 单位：米）
TRANSLATIONS = {
    "dolly_in": "forward", "dolly_out": "-forward",
    "track_left": "-right", "track_right": "right",
    "crane_up": "up", "crane_down": "-up",
    "push_through": "forward",
}
#: 旋转类（amount 单位：度）
ROTATIONS = {
    "pan_left": ("up", 1.0), "pan_right": ("up", -1.0),
    "tilt_up": ("right", 1.0), "tilt_down": ("right", -1.0),
    "whip_pan_left": ("up", 1.0), "whip_pan_right": ("up", -1.0),
}
#: 变焦类（amount 单位：毫米）
ZOOMS = {"zoom_in": 1.0, "zoom_out": -1.0}
#: 推拉变焦（amount 单位：米；焦距按距离同比例变化）
DOLLY_ZOOMS = ("dolly_zoom",)
#: 环绕与摇臂弧（amount 单位：度）
ORBITS = {
    "orbit_cw": 1.0, "orbit_ccw": -1.0,
    "crane_arc_up": 1.0, "crane_arc_down": -1.0,
}
#: 稳定器与跟拍（需要 ``subject_path``）
SUBJECT_TRACKING = ("steadicam", "follow_subject", "lead_subject")
#: 手持（确定性噪声，不需要主体路径）
HANDHELD = ("handheld",)

#: 分组表必须与 ``contracts/enums.py`` 的 ``MOVEMENT_TYPES`` 完全一致。
#: 两份真源一旦漂移，知识卡的能力标注、工具 schema 的 enum 与这里的解算
#: 就会各说各话，所以护栏放在导入期，而不是等测试来发现。
_GROUPED_MOVEMENTS = frozenset(
    list(TRANSLATIONS) + list(ROTATIONS) + list(ZOOMS) + list(DOLLY_ZOOMS)
    + list(ORBITS) + list(SUBJECT_TRACKING) + list(HANDHELD))
if _GROUPED_MOVEMENTS != frozenset(MOVEMENT_TYPES):     # pragma: no cover
    raise RuntimeError(
        "camera_motion 的分组表与 contracts 的 MOVEMENT_TYPES 不一致："
        f"{sorted(_GROUPED_MOVEMENTS ^ set(MOVEMENT_TYPES))}")

LOOK_AT_DISTANCE = 3.0
DEFAULT_SAMPLES = 3          # 首 / 中 / 尾，够贝塞尔插值走出平滑弧线

#: 每种运镜的默认强度（声明里只写了 ``type`` 时用它）。
#: 平移类/推拉变焦/跟拍的单位是米，摇与环绕是度，变焦是毫米。
DEFAULT_AMOUNTS: Dict[str, float] = {}
for _key in TRANSLATIONS:
    DEFAULT_AMOUNTS[_key] = 1.0
for _key in ROTATIONS:
    DEFAULT_AMOUNTS[_key] = 15.0
for _key in ZOOMS:
    DEFAULT_AMOUNTS[_key] = 15.0
for _key in DOLLY_ZOOMS:
    DEFAULT_AMOUNTS[_key] = 1.5
for _key in ORBITS:
    DEFAULT_AMOUNTS[_key] = 45.0
for _key in SUBJECT_TRACKING:
    DEFAULT_AMOUNTS[_key] = 2.0
for _key in HANDHELD:
    DEFAULT_AMOUNTS[_key] = 0.05
del _key

#: 每种运镜的 ``amount`` **单位**与**典型区间**——提示词与校验共用这一份真源。
#:
#: 为什么必须有它（2026-10-03 的 64 镜真跑实测）：`amount` 在 schema 里只有一个
#: 0–180 的范围，**没有单位**；模型按"度数"的直觉写了
#: ``{"type": "dolly_in", "amount": 12}`` —— 而平移类的单位是**米**，
#: 于是机位真的往前推了 **12 米、直接穿过主体**（实测相机从 (1.15, 2.05) 飞到
#: (-7.34, -6.44)，构图分 27.6–54.0、这一镜必判失败）。同一个数字在
#: 摇镜里是"15 度"（合理），在跟拍里是"2 米"（合理），只有单位写着才不会撞车。
MOVEMENT_UNITS: Dict[str, Tuple[str, float, float]] = {}
for _key in TRANSLATIONS:
    MOVEMENT_UNITS[_key] = ("米", 0.3, 2.0)
for _key in DOLLY_ZOOMS:
    MOVEMENT_UNITS[_key] = ("米", 0.5, 3.0)
for _key in SUBJECT_TRACKING:
    MOVEMENT_UNITS[_key] = ("米", 0.5, 3.0)
for _key in ROTATIONS:
    MOVEMENT_UNITS[_key] = ("度", 5.0, 45.0)
for _key in ORBITS:
    MOVEMENT_UNITS[_key] = ("度", 15.0, 90.0)
for _key in ZOOMS:
    MOVEMENT_UNITS[_key] = ("毫米", 5.0, 50.0)
for _key in HANDHELD:
    MOVEMENT_UNITS[_key] = ("米", 0.02, 0.1)
del _key

if set(MOVEMENT_UNITS) != frozenset(MOVEMENT_TYPES):    # pragma: no cover
    raise RuntimeError(
        "MOVEMENT_UNITS 与 MOVEMENT_TYPES 漂了："
        f"{sorted(set(MOVEMENT_UNITS) ^ set(MOVEMENT_TYPES))}")


def movement_unit_table() -> List[Tuple[str, str, float, float]]:
    """``[(运镜, 单位, 典型下限, 典型上限), …]``——按单位分组、稳定排序。"""
    order = {"米": 0, "度": 1, "毫米": 2}
    rows = [(name, unit, low, high)
            for name, (unit, low, high) in MOVEMENT_UNITS.items()]
    return sorted(rows, key=lambda row: (order.get(row[1], 9), row[0]))

#: 甩镜与手持的采样密度更高：它们靠"短时间内快速变化"表达，
#: 只有首中尾三个采样点会把变化抹平。
DENSE_SAMPLES = {"whip_pan_left": 5, "whip_pan_right": 5, "handheld": 7}

MIN_LENS = 8.0
MAX_LENS = 300.0


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


def _noise(seed: int, index: int, channel: int) -> float:
    """确定性噪声：同一个 seed 与采样序号永远得到同一个值。

    手持必须可复现——"同一份工程重建两次得到同一段视频"是 v1.3 的硬约束，
    因此这里不用 ``random``，而是用整数哈希。
    """
    value = (int(seed) * 73856093) ^ (int(index) * 19349663) ^ (channel * 83492791)
    value &= 0x7FFFFFFF
    return (value % 20011) / 20011.0 * 2.0 - 1.0     # [-1, 1]


def _trail_offset(position: Sequence[float],
                  target: Sequence[float]) -> Vector3:
    """相机相对被摄目标的初始偏移（跟拍时保持不变）。"""
    return _sub(position, target)


def _path_point(subject_path: Sequence[Sequence[float]],
                ratio: float) -> Vector3:
    """在主体路径上按比例取一点（线性插值，路径本身已由调用方平滑）。"""
    points = list(subject_path)
    if not points:
        return (0.0, 0.0, 0.0)
    if len(points) == 1:
        return tuple(float(v) for v in points[0])
    scaled = ratio * (len(points) - 1)
    low = int(math.floor(scaled))
    high = min(low + 1, len(points) - 1)
    local = scaled - low
    return tuple(float(points[low][i])
                 + (float(points[high][i]) - float(points[low][i])) * local
                 for i in range(3))


def sample_count(movement: str, samples: int = DEFAULT_SAMPLES) -> int:
    """这次运镜要取几个采样点（甩镜与手持更密）。"""
    limit = max(int(samples), 2)
    return max(limit, DENSE_SAMPLES.get(str(movement), 0))


def sample_frames(start_frame: int, end_frame: int,
                  samples: int = DEFAULT_SAMPLES,
                  movement: str = "") -> List[int]:
    """采样点落在哪些帧上。

    bpy 侧要按**同一张时间表**去取被摄主体的位置（跟拍），所以帧号的计算
    必须是共享的纯函数——两处各算一遍迟早会错位。
    """
    start, end = int(start_frame), int(end_frame)
    if end <= start:
        raise ValueError("end_frame 必须大于 start_frame")
    limit = sample_count(movement, samples)
    return [int(round(start + (end - start) * (index / float(limit - 1))))
            for index in range(limit)]


def movement_spec(raw, *, shot_start: int, shot_end: int,
                  default_subject: str = "") -> Dict[str, object]:
    """把计划里的一条运镜声明规整成可执行参数（纯函数，可单测）。

    计划里的帧号是**镜头内局部帧**（与动作、对白一致），这里换算成全局帧
    并夹在镜头范围内：越界的声明不至于把关键帧写到别的镜头里去。
    """
    item = dict(raw) if isinstance(raw, dict) else {"type": str(raw or "")}
    movement = str(item.get("type") or item.get("movement") or "").strip()
    if movement not in MOVEMENT_TYPES:
        raise ValueError(f"未知运镜 {movement!r}。可用: "
                         f"{', '.join(MOVEMENT_TYPES)}")
    amount = item.get("amount")
    try:
        amount_value = float(amount)
    except (TypeError, ValueError):
        amount_value = DEFAULT_AMOUNTS[movement]
    if amount_value <= 0:
        amount_value = DEFAULT_AMOUNTS[movement]
    duration = max(int(shot_end) - int(shot_start) + 1, 2)
    local_start = int(item.get("start_frame") or 1)
    local_end = int(item.get("end_frame") or duration)
    local_start = min(max(local_start, 1), duration)
    local_end = min(max(local_end, local_start + 1), duration)
    start = int(shot_start) + local_start - 1
    end = int(shot_start) + local_end - 1
    if end <= start:                      # 单帧镜头：退回整镜的两端
        start, end = int(shot_start), max(int(shot_end), int(shot_start) + 1)
    seed = item.get("seed")
    try:
        seed_value = max(int(seed), 0)
    except (TypeError, ValueError):
        seed_value = 0
    subject = str(item.get("subject") or "").strip() or str(default_subject or "")
    return {"type": movement, "amount": amount_value,
            "start_frame": start, "end_frame": end,
            "seed": seed_value, "subject": subject}


def movement_samples(position: Sequence[float], target: Sequence[float],
                     movement: str, amount: float,
                     start_frame: int, end_frame: int,
                     samples: int = DEFAULT_SAMPLES,
                     *, lens: float = 50.0,
                     lens_to: Optional[float] = None,
                     subject_path: Optional[Sequence[Sequence[float]]] = None,
                     seed: int = 0
                     ) -> List[Dict[str, object]]:
    """把一次运镜展开成 ``[{frame, position, look_at, lens}]`` 采样。"""
    movement = str(movement or "").strip()
    if movement not in MOVEMENT_TYPES:
        raise ValueError(f"未知运镜 {movement!r}。可用: "
                         f"{', '.join(MOVEMENT_TYPES)}")
    start, end = int(start_frame), int(end_frame)
    if end <= start:
        raise ValueError("end_frame 必须大于 start_frame")
    if movement in SUBJECT_TRACKING and not subject_path:
        raise ValueError(
            f"运镜 {movement} 需要被摄主体的逐帧路径（subject_path）；"
            f"没有主体就没法跟拍。请先指定主体，或改用推拉/横移。")
    limit = sample_count(movement, samples)

    forward, right, up = _basis(position, target)
    distance = max(_length(_sub(target, position)), 1e-6)
    position = tuple(float(v) for v in position)
    target = tuple(float(v) for v in target)
    base_lens = float(lens or 50.0)
    direction = {"forward": forward, "-forward": _scale(forward, -1.0),
                 "right": right, "-right": _scale(right, -1.0),
                 "up": up, "-up": _scale(up, -1.0)}

    result: List[Dict[str, object]] = []
    frames = sample_frames(start, end, samples, movement)
    for index in range(limit):
        ratio = index / float(limit - 1)
        frame = frames[index]
        result.append(_sample_one(
            movement, ratio, frame, position, target, direction, distance,
            base_lens, lens_to, float(amount), subject_path, int(seed), index,
            right, up))
    return result


def _sample_one(movement: str, ratio: float, frame: int,
                position: Vector3, target: Vector3, direction, distance: float,
                base_lens: float, lens_to: Optional[float], amount: float,
                subject_path, seed: int, index: int,
                right: Vector3, up: Vector3) -> Dict[str, object]:
    lens = base_lens

    if movement in TRANSLATIONS:
        moved = _add(position, _scale(direction[TRANSLATIONS[movement]],
                                      amount * ratio))
        return {"frame": frame, "position": moved, "look_at": target,
                "lens": lens}

    if movement in ZOOMS:
        # 机位不动、焦段变化：观众读到的是"凝视/松开"，不是"走近"
        if lens_to is not None:
            lens = base_lens + (float(lens_to) - base_lens) * ratio
        else:
            lens = base_lens + ZOOMS[movement] * amount * ratio
        lens = min(max(lens, MIN_LENS), MAX_LENS)
        return {"frame": frame, "position": position, "look_at": target,
                "lens": lens}

    if movement in DOLLY_ZOOMS:
        # 推近的同时按距离同比例缩短焦距 → 主体大小不变、透视剧烈变化
        moved = _add(position, _scale(direction["forward"], amount * ratio))
        new_distance = max(_length(_sub(target, moved)), 1e-6)
        lens = min(max(base_lens * (new_distance / distance), MIN_LENS),
                   MAX_LENS)
        return {"frame": frame, "position": moved, "look_at": target,
                "lens": lens}

    if movement in ORBITS:
        offset = _sub(position, target)
        if movement.startswith("orbit"):
            # 环绕：绕世界 Z 轴转，方向由 ORBITS 的符号决定
            axis = (0.0, 0.0, 1.0)
            angle = math.radians(amount) * ORBITS[movement] * ratio
        else:
            # 摇臂弧：绕"右轴"转——上升弧绕 -right（相机抬升），
            # 下降弧绕 +right（相机下沉）。方向已经写进轴的符号里，
            # 角度只带大小：若角度也乘一遍符号，两次取反会互相抵消，
            # 上升弧与下降弧会退化成同一个旋转。
            axis = _scale(right, -ORBITS[movement])
            angle = math.radians(amount) * ratio
        moved = _add(target, _rotate(offset, axis, angle))
        return {"frame": frame, "position": moved, "look_at": target,
                "lens": lens}

    if movement in SUBJECT_TRACKING:
        subject = _path_point(subject_path, ratio)
        offset = _trail_offset(position, target)
        if movement == "follow_subject":
            moved = _add(subject, offset)
        elif movement == "lead_subject":
            moved = _sub(subject, offset)
        else:                              # steadicam：跟拍 + 轻微起伏
            moved = _add(subject, offset)
            moved = (moved[0], moved[1],
                     moved[2] + math.sin(math.pi * ratio) * 0.04)
        return {"frame": frame, "position": moved, "look_at": subject,
                "lens": lens}

    if movement in HANDHELD:
        jitter = (right[0] * _noise(seed, index, 1)
                  + up[0] * _noise(seed, index, 2),
                  right[1] * _noise(seed, index, 1)
                  + up[1] * _noise(seed, index, 2),
                  right[2] * _noise(seed, index, 1)
                  + up[2] * _noise(seed, index, 2))
        moved = _add(position, _scale(jitter, amount))
        return {"frame": frame, "position": moved, "look_at": target,
                "lens": lens}

    # 摇与俯仰。甩镜用的是同一套几何：它的"快"来自短时长与更密的采样，
    # 因此这里只额外把中间采样点前移一点，让关键帧之间的插值更像甩。
    axis, sign = ROTATIONS[movement]
    eased = ratio ** 0.6 if movement.startswith("whip_pan") else ratio
    angle = math.radians(amount * sign * eased)
    rotated = _rotate(direction["forward"], direction[axis], angle)
    return {"frame": frame, "position": position,
            "look_at": _add(position, _scale(rotated, distance)),
            "lens": lens}


def describe(movement: str) -> str:
    """给工具返回值与 prompts.md 用的一句人话。"""
    return {
        "dolly_in": "推近", "dolly_out": "拉远", "track_left": "左移",
        "track_right": "右移", "crane_up": "升", "crane_down": "降",
        "pan_left": "左摇", "pan_right": "右摇", "tilt_up": "上摇",
        "tilt_down": "下摇", "zoom_in": "变焦推近", "zoom_out": "变焦拉远",
        "dolly_zoom": "推拉变焦", "orbit_cw": "顺时针环绕",
        "orbit_ccw": "逆时针环绕", "crane_arc_up": "上升弧",
        "crane_arc_down": "下降弧", "whip_pan_left": "左甩",
        "whip_pan_right": "右甩", "handheld": "手持",
        "steadicam": "斯坦尼康", "follow_subject": "跟拍",
        "lead_subject": "前导", "push_through": "穿越推进",
    }.get(str(movement or ""), str(movement or ""))
