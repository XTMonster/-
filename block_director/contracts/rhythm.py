"""节奏闭集与 DTO（v1.6 D1，FR-B1；TDD §3.1）。

一切 LLM 可见的节奏自由度都是**闭集词**，编译层（``beat_compiler``）把词确定性地
折成帧长倍率与插值轮廓——模型永不直接写插值参数（"连续数值是幻觉温床"，
见 ``contracts/beats.py`` 模块说明）。节奏读数只作 **info 级诊断**，不是通过门（红线 R-5）。

禁止 import bpy。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

from .beats import PACE_VALUES

CURVE_VALUES: tuple = ("linear", "smooth", "ease_in", "ease_out", "sharp")
DEFAULT_CURVE = "smooth"

#: 镜长档案（ASL 参考带，秒）——统计参考，**不是规则**（PRD FR-B2）。
PACING_PROFILES: Dict[str, Dict[str, Any]] = {
    "contemplative": {"asl_band_s": (8.0, 12.0)},
    "standard":      {"asl_band_s": (4.0, 8.0)},
    "urgent":        {"asl_band_s": (2.0, 4.0)},
}

#: 关键帧插值枚举名（bpy 枚举，纯层只存字符串）。
#: ease_in/ease_out 与 smooth 的区别在编译层的"位移时间轮廓"；
#: sharp = 前 15% 帧完成 85% 位移（蓄-发-收的"发"），编译层折帧实现。
CURVE_TO_INTERPOLATION: Dict[str, str] = {
    "linear": "LINEAR", "smooth": "BEZIER", "ease_in": "BEZIER",
    "ease_out": "BEZIER", "sharp": "LINEAR",
}

TENSION_MIN = 1
TENSION_MAX = 5


def curve_problems(curve: Any, where: str = "curve") -> List[str]:
    """非法曲线词列问题、**不猜**（写法与 ``action_param_problems`` 同形）。空值合法 ⇒ 缺省 smooth。"""
    if curve in (None, ""):
        return []
    if not isinstance(curve, str) or curve not in CURVE_VALUES:
        return [f"{where}={curve!r} 不在闭集内（{'、'.join(CURVE_VALUES)}）"]
    return []


def pacing_profile_problems(name: Any, where: str = "pacing_profile") -> List[str]:
    if name not in PACING_PROFILES:
        return [f"{where}={name!r} 不在闭集内（{'、'.join(PACING_PROFILES)}）"]
    return []


def _tension_problems(value: Any, where: str) -> List[str]:
    if isinstance(value, bool) or not isinstance(value, int) \
            or not TENSION_MIN <= value <= TENSION_MAX:
        return [f"{where}={value!r} 必须是 {TENSION_MIN}–{TENSION_MAX} 的整数"]
    return []


@dataclass
class ShotRhythm:
    """一镜的节奏三元组（进 ``shots.json`` 的 ``rhythm{}``）。"""
    tension: int = 3
    pace: str = "normal"
    curve: str = DEFAULT_CURVE

    def problems(self, where: str = "rhythm") -> List[str]:
        found = _tension_problems(self.tension, f"{where}.tension")
        if self.pace not in PACE_VALUES:
            found.append(f"{where}.pace={self.pace!r} 不在闭集内（{'、'.join(PACE_VALUES)}）")
        found += curve_problems(self.curve, f"{where}.curve")
        return found

    def to_dict(self) -> Dict[str, Any]:
        return {"tension": int(self.tension), "pace": self.pace, "curve": self.curve}

    @classmethod
    def from_dict(cls, data: Optional[Mapping[str, Any]]) -> "ShotRhythm":
        data = dict(data or {})
        return cls(tension=data.get("tension", 3), pace=data.get("pace", "normal"),
                   curve=data.get("curve") or DEFAULT_CURVE)


@dataclass
class RhythmArc:
    """剧本节奏弧上的一拍（``SceneBrief.rhythm_arc[]`` 的元素）。"""
    shot_id: str
    tension: int
    note: str = ""

    def problems(self, where: str = "rhythm_arc") -> List[str]:
        found = [] if str(self.shot_id or "").strip() else [f"{where}.shot_id 为空"]
        return found + _tension_problems(self.tension, f"{where}.tension")

    def to_dict(self) -> Dict[str, Any]:
        return {"shot_id": self.shot_id, "tension": int(self.tension), "note": self.note}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RhythmArc":
        return cls(shot_id=str(data.get("shot_id") or ""),
                   tension=data.get("tension"), note=str(data.get("note") or ""))


def rhythm_arc_problems(items: Any) -> List[str]:
    """``rhythm_arc[]`` 的问题清单（空列表合法 ＝ 没有节奏弧）。镜号重复也算问题。"""
    if items in (None, []):
        return []
    if not isinstance(items, list):
        return [f"rhythm_arc 必须是列表（当前 {type(items).__name__}）"]
    found: List[str] = []
    seen = set()
    for index, raw in enumerate(items, start=1):
        where = f"rhythm_arc[{index}]"
        if not isinstance(raw, Mapping):
            found.append(f"{where} 必须是对象")
            continue
        arc = RhythmArc.from_dict(raw)
        found += arc.problems(where)
        if arc.shot_id in seen:
            found.append(f"{where}.shot_id={arc.shot_id!r} 重复")
        seen.add(arc.shot_id)
    return found


__all__ = [
    "CURVE_VALUES", "DEFAULT_CURVE", "PACING_PROFILES", "CURVE_TO_INTERPOLATION",
    "TENSION_MIN", "TENSION_MAX", "ShotRhythm", "RhythmArc", "curve_problems",
    "pacing_profile_problems", "rhythm_arc_problems",
]
