"""灯光语义 → 预设矩阵（执行文档 v1.5 TDD §3.4 / §4.5）。**纯计算，不依赖 bpy。**

为什么不把灯光参数暴露给 LLM（TDD §3.4 的原话）：白模参考视频的观感由**形体质感**
决定，而 energy/color/size 这些数值是"一写错整片就废"的连续量、且不可语义校验。
所以契约面只留三个**语义**字段（``time_of_day`` / ``mood`` / ``key_direction``），
它们的组合落进一张**设计表**，由引擎翻译成五个基础光照预设 + 每基础预设三个
方向变体（v1.6 卡 G1 / D-18 起；此前变体表是空表，见下方注释）。

矩阵（TDD §4.5，行=时间，列=情绪组）::

               bright        neutral        gloomy/tense   soft
    day        outdoor_sun   clay_studio    indoor_soft    indoor_soft
    night      studio3p      night          night          night
    dusk/dawn  outdoor_sun   indoor_soft    indoor_soft    indoor_soft

**调表不动结构**：改这张表只改观感，不改代码形状。未知/不完整的组合一律回落
``clay_studio`` 并**记一条说明**（不是静默）：裁判通道要看得见"我按哪条规则选了什么"。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

from ..contracts.beats import (
    KEY_DIRECTION_VALUES,
    LIGHT_MOOD_VALUES,
    TIME_OF_DAY_VALUES,
)

#: 回落预设（未知组合、缺字段、闭集外取值都回这里）。
DEFAULT_LIGHTING_PRESET = "clay_studio"

#: 引擎侧预设表的**键名契约**。纯层不能 import bpy（红线 R-1），所以这里只
#: 留键名、不留灯的参数（energy/color/size）：判据是"两边键名逐键相同"，
#: 由 Blender 侧探针 `tools/blender_tests/test_anchor_staging.py` **双向断言**
#: （矩阵只能映射到这张表里的名字；预设表的键集也只能等于这张表）。
LIGHTING_PRESET_NAMES: Tuple[str, ...] = (
    "clay_studio", "indoor_soft", "outdoor_sun", "night", "studio3p",
    #: 方向变体（`<基础预设>_<key_direction>`；共 5 × 3 = 15 个）。
    "clay_studio_front", "clay_studio_side", "clay_studio_back",
    "indoor_soft_front", "indoor_soft_side", "indoor_soft_back",
    "outdoor_sun_front", "outdoor_sun_side", "outdoor_sun_back",
    "night_front", "night_side", "night_back",
    "studio3p_front", "studio3p_side", "studio3p_back",
)

#: 情绪 → 矩阵列。``gloomy``/``tense`` 共用一列（§4.5 的 "gloomy/tense"）。
_MOOD_COLUMN: Dict[str, str] = {
    "bright": "bright", "neutral": "neutral",
    "gloomy": "shade", "tense": "shade", "soft": "soft",
}

#: 设计表本体（**唯一真源**；改观感改这里）。
LIGHT_MATRIX: Dict[Tuple[str, str], str] = {
    ("day", "bright"): "outdoor_sun",
    ("day", "neutral"): "clay_studio",
    ("day", "shade"): "indoor_soft",
    ("day", "soft"): "indoor_soft",
    ("night", "bright"): "studio3p",
    ("night", "neutral"): "night",
    ("night", "shade"): "night",
    ("night", "soft"): "night",
    ("dusk", "bright"): "outdoor_sun",
    ("dusk", "neutral"): "indoor_soft",
    ("dusk", "shade"): "indoor_soft",
    ("dusk", "soft"): "indoor_soft",
    ("dawn", "bright"): "outdoor_sun",
    ("dawn", "neutral"): "indoor_soft",
    ("dawn", "shade"): "indoor_soft",
    ("dawn", "soft"): "indoor_soft",
}

#: ``key_direction`` 三个合法值的**主光方位角**（度；世界 XY 平面，
#: 0° = +X、90° = +Y、270° = -Y）。这是"side = 垂直于相机轴"这条判据的
#: **唯一真源**：Blender 侧探针按它读引擎侧每盏主光（``LIGHTING_PRESETS``
#: 列表第一盏）的方位角，超出容差即红。
#:
#: 参考系：机位放在被摄主体 +Y 侧朝 -Y 看（``cinema/framing.py`` 的
#: ``side_vector(facing, "front")``，默认 facing=(0,1,0)），所以：
#:   * ``front`` = 相机侧（+Y，顺光，反差最小）；
#:   * ``side`` = 垂直于相机轴（+X，90° 侧光，形体可读——D-18 的落点）；
#:   * ``back`` = 被摄主体背后（-Y，逆光/轮廓光）。
KEY_DIRECTION_AZIMUTH_DEG: Dict[str, float] = {
    "front": 90.0,
    "side": 0.0,
    "back": 270.0,
}

#: ``key_direction`` 的**变体表**：``(基础预设, 方向) → 变体预设名``。
#:
#: v1.5 时这里是**空表**（当时的注释说"哪些方向该有什么变体是设计而非实现"，
#: 声明方向会在 trace 里记"我忽略了它"）——E-video P2-3 实测 13 帧全平灰、
#: ``key_direction=side 无对应预设变体，已忽略``，v1.6 卡 G1 / D-18 拍板补全：
#: 五个基础预设 × 三个合法方向各造一个变体，**每个合法值都必须命中预设**
#: （不许再对合法值记"已忽略"）。引擎侧灯位在
#: ``layer3_engine/scene_executor.py::LIGHTING_PRESETS``，方位角语义见
#: :data:`KEY_DIRECTION_AZIMUTH_DEG`。补变体只改这张表，不改函数。
LIGHT_DIRECTION_VARIANTS: Dict[Tuple[str, str], str] = {
    ("clay_studio", "front"): "clay_studio_front",
    ("clay_studio", "side"): "clay_studio_side",
    ("clay_studio", "back"): "clay_studio_back",
    ("indoor_soft", "front"): "indoor_soft_front",
    ("indoor_soft", "side"): "indoor_soft_side",
    ("indoor_soft", "back"): "indoor_soft_back",
    ("outdoor_sun", "front"): "outdoor_sun_front",
    ("outdoor_sun", "side"): "outdoor_sun_side",
    ("outdoor_sun", "back"): "outdoor_sun_back",
    ("night", "front"): "night_front",
    ("night", "side"): "night_side",
    ("night", "back"): "night_back",
    ("studio3p", "front"): "studio3p_front",
    ("studio3p", "side"): "studio3p_side",
    ("studio3p", "back"): "studio3p_back",
}


def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _fields(spec: Any) -> Dict[str, str]:
    if hasattr(spec, "to_dict"):
        data = spec.to_dict()
    elif isinstance(spec, Mapping):
        data = dict(spec)
    else:
        data = {}
    return {key: _text(data.get(key)) for key in
            ("time_of_day", "mood", "key_direction")}


def resolve_lighting(spec: Any, *,
                     variants: Optional[Mapping[Tuple[str, str], str]] = None
                     ) -> Tuple[str, List[str]]:
    """语义灯光 → ``(预设名, 说明清单)``。

    说明清单是**审计**用的（进 ``shots.json`` 的 warnings 与 python 日志），
    空的语义声明不会出现在里面——那是"没声明"，不是"我忽略了什么"。
    """
    fields = _fields(spec)
    notes: List[str] = []
    if not any(fields.values()):
        return DEFAULT_LIGHTING_PRESET, notes

    time_of_day = fields["time_of_day"]
    mood = fields["mood"]
    problems: List[str] = []
    if time_of_day and time_of_day not in TIME_OF_DAY_VALUES:
        problems.append(f"time_of_day={time_of_day!r} 不在闭集内"
                        f"（{'、'.join(TIME_OF_DAY_VALUES)}）")
    if mood and mood not in LIGHT_MOOD_VALUES:
        problems.append(f"mood={mood!r} 不在闭集内（{'、'.join(LIGHT_MOOD_VALUES)}）")
    if problems:
        notes.append("light 声明非法，回落 " + DEFAULT_LIGHTING_PRESET + "："
                     + "；".join(problems))
        return DEFAULT_LIGHTING_PRESET, notes

    if not time_of_day or not mood:
        missing = "time_of_day" if not time_of_day else "mood"
        notes.append(f"light 只声明了一半（缺 {missing}），无法定位矩阵格，"
                     f"回落 {DEFAULT_LIGHTING_PRESET}")
        return DEFAULT_LIGHTING_PRESET, notes

    cell = (time_of_day, _MOOD_COLUMN.get(mood, ""))
    preset = LIGHT_MATRIX.get(cell)
    if preset is None:
        notes.append(f"light 组合 (time_of_day={time_of_day}, mood={mood}) "
                     f"不在矩阵里，回落 {DEFAULT_LIGHTING_PRESET}")
        return DEFAULT_LIGHTING_PRESET, notes

    direction = fields["key_direction"]
    if direction:
        if direction not in KEY_DIRECTION_VALUES:
            notes.append(f"key_direction={direction!r} 不在闭集内（"
                         f"{'、'.join(KEY_DIRECTION_VALUES)}），已忽略")
        else:
            mapped = dict(LIGHT_DIRECTION_VARIANTS if variants is None
                          else variants).get((preset, direction))
            if mapped:
                notes.append(f"key_direction={direction} → 预设变体 {mapped}")
                return mapped, notes
            notes.append(f"key_direction={direction} 无对应预设变体，已忽略"
                         f"（沿用 {preset}）")
    return preset, notes


def resolve_lighting_preset(spec: Any, *,
                            variants: Optional[Mapping[Tuple[str, str], str]] = None
                            ) -> str:
    """:func:`resolve_lighting` 的取预设那一半（TDD §4.5 的签名）。"""
    return resolve_lighting(spec, variants=variants)[0]


__all__ = [
    "DEFAULT_LIGHTING_PRESET", "LIGHT_MATRIX", "LIGHT_DIRECTION_VARIANTS",
    "KEY_DIRECTION_AZIMUTH_DEG", "LIGHTING_PRESET_NAMES",
    "resolve_lighting", "resolve_lighting_preset",
]
