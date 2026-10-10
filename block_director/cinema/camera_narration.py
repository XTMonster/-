"""运镜文字化器（v1.7 卡 I2 / TDD §13.2，R-痛点 M1 的 P3 件）。

纯函数、无 bpy：把每镜相机采样（``cinema/camera_motion.py::movement_samples``
的既有产物，本模块**不重新采样**）＋主体锚点/朝向，写成一句人读的运镜描述。
多主体质心由调用方算（本函数只吃一个锚点，TDD 钉死）。
"""

from __future__ import annotations

import math
from typing import Any, Dict, Sequence

#: 判定阈值（模块常量，非用户调节项）。
MOVE_EPS = 0.05       # 米：总位移小于它 → 静止/变焦分支
LENS_EPS = 2.0        # mm：|首末 lens 差| 达到它才算变焦（先于静止判定）
BEARING_HALF_WIDTH = 22.5   # 八方位每扇区半宽（度）
NEAR_M = 2.0          # 距离带：小于它 → "近"
FAR_M = 6.0           # 距离带：大于它 → "远"；中间不缀词

#: v1.7.6 钉死的 24 词动词表（逐词映射 ``contracts/enums.py::Movement``；
#: 测试对拍 ``set(MOVEMENT_VERB) == {m.value for m in Movement}``）。
MOVEMENT_VERB: Dict[str, str] = {
    "dolly_in": "推进",
    "dolly_out": "拉远",
    "track_left": "左移",
    "track_right": "右移",
    "crane_up": "升",
    "crane_down": "降",
    "push_through": "穿越",
    "dolly_zoom": "滑动变焦",
    "pan_left": "左摇",
    "pan_right": "右摇",
    "tilt_up": "上摇",
    "tilt_down": "下摇",
    "whip_pan_left": "快甩左",
    "whip_pan_right": "快甩右",
    "orbit_cw": "顺时针环绕",
    "orbit_ccw": "逆时针环绕",
    "crane_arc_up": "弧形升",
    "crane_arc_down": "弧形降",
    "zoom_in": "变焦推近",
    "zoom_out": "变焦拉远",
    "handheld": "手持",
    "steadicam": "稳定器",
    "follow_subject": "跟随",
    "lead_subject": "引导",
}

#: 八方位扇区（角度 = atan2(侧向, 前方)，0° = 主体正前，正值 = 主体左侧）。
_SECTORS = (
    (-180.0, -157.5, "后"),
    (-157.5, -112.5, "后右"),
    (-112.5, -67.5, "右"),
    (-67.5, -22.5, "前右"),
    (-22.5, 22.5, "前"),
    (22.5, 67.5, "前左"),
    (67.5, 112.5, "左"),
    (112.5, 157.5, "后左"),
    (157.5, 180.0, "后"),
)


def _facing_xy(facing: Sequence[float]) -> "tuple[float, float]":
    fx, fy = float(facing[0]) if len(facing) > 0 else 0.0, \
        float(facing[1]) if len(facing) > 1 else 1.0
    length = math.hypot(fx, fy)
    if length < 1e-9:
        return 0.0, 1.0
    return fx / length, fy / length


def _bearing(anchor: Sequence[float], facing: Sequence[float],
             point: Sequence[float]) -> str:
    """``point`` 相对锚点在主体朝向坐标系里的八方位。

    朝向约定与 ``cinema/framing.py::side_vector`` 同源：front = facing、
    right = facing 顺时针 90°（XY 平面内）。
    """
    dx = float(point[0]) - float(anchor[0])
    dy = float(point[1]) - float(anchor[1])
    fx, fy = _facing_xy(facing)
    lateral = dx * fy + dy * (-fx)   # dot(right)，正值 = 主体左侧
    forward = dx * fx + dy * fy      # dot(front)
    angle = math.degrees(math.atan2(lateral, forward))
    for low, high, name in _SECTORS:
        if low <= angle < high:
            return name
    return "后"


def _band(anchor: Sequence[float], point: Sequence[float]) -> str:
    distance = math.hypot(float(point[0]) - float(anchor[0]),
                          float(point[1]) - float(anchor[1]))
    if distance < NEAR_M:
        return "（近）"
    if distance > FAR_M:
        return "（远）"
    return ""


def _sample_dict(sample: Any) -> Dict[str, Any]:
    if isinstance(sample, dict):
        return sample
    values = list(sample) if isinstance(sample, (list, tuple)) else []
    return {"position": [float(v) for v in values[:3]],
            "lens": None, "movement": None}


def _distance(a: Sequence[float], b: Sequence[float]) -> float:
    return math.hypot(float(b[0]) - float(a[0]), float(b[1]) - float(a[1]))


def narrate(camera_samples: Sequence[Any], subject_anchor: Sequence[float],
            subject_facing: Sequence[float]) -> str:
    """把相机采样文字化成一句运镜描述（数据源 = ``movement_samples`` 产物）。"""
    samples = [_sample_dict(item) for item in camera_samples or ()]
    if not samples:
        return "固定机位"
    positions = [sample["position"] for sample in samples]
    total = sum(_distance(positions[index - 1], positions[index])
                for index in range(1, len(positions)))
    lens_first = samples[0].get("lens")
    lens_last = samples[-1].get("lens")
    if total < MOVE_EPS:
        if (isinstance(lens_first, (int, float))
                and isinstance(lens_last, (int, float))
                and abs(float(lens_last) - float(lens_first)) >= LENS_EPS):
            direction = "推近" if lens_last > lens_first else "拉远"
            return (f"变焦{direction}（{float(lens_first):.0f}mm→"
                    f"{float(lens_last):.0f}mm）")
        return "固定机位"
    #: 主运镜词：按 movement 值分段、取位移最大的段（多段运镜拼接时）。
    segments: Dict[Any, float] = {}
    current = samples[0].get("movement")
    for index in range(1, len(samples)):
        segment_key = samples[index].get("movement")
        distance = _distance(positions[index - 1], positions[index])
        segments[current] = segments.get(current, 0.0) + distance
        current = segment_key
    main = max(segments, key=segments.get) if segments else current
    verb = MOVEMENT_VERB.get(str(main), "移动")
    start = _bearing(subject_anchor, subject_facing, positions[0])
    end = _bearing(subject_anchor, subject_facing, positions[-1])
    return (f"从{start}{_band(subject_anchor, positions[0])}{verb}"
            f"到{end}{_band(subject_anchor, positions[-1])}")


__all__ = [
    "BEARING_HALF_WIDTH",
    "FAR_M",
    "LENS_EPS",
    "MOVE_EPS",
    "MOVEMENT_VERB",
    "NEAR_M",
    "narrate",
]
