"""目标模型适配器（v1.7 卡 I4 / TDD §12.3，R-痛点 M2 消费半）。

纯函数、无 bpy：把计划/配置与 ``specs/target_models.yaml`` 对拍，产出**建议**
（warning + 切片建议），只告警不偷改 fps/分辨率，不切镜。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..cinema.schedule import shot_ranges, total_frames
from ..contracts.config import AppConfig, Issue
from ..contracts.enums import Severity
from ..contracts.plan import FPS, Plan
from ..contracts.target_models import (
    ModelSpec,
    TargetModelError,
    load_table,
)


@dataclass
class SliceAdvice:
    """一条切片建议：``cut_frame`` = 新一段的起始绝对帧（前一段到此帧前结束）。"""

    cut_frame: int
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {"cut_frame": self.cut_frame, "reason": self.reason}


def _warning(code: str, field: str, message: str) -> Issue:
    return Issue(code=code, field=field, severity=Severity.WARNING,
                 message=message)


def _resolve_target(config: AppConfig
                    ) -> "tuple[Optional[ModelSpec], List[Issue]]":
    """目标模型 → 规格；未知值回落 seedance_2.5 并记 warning（I4 ④）。"""
    try:
        table = load_table()
    except TargetModelError as exc:
        return None, [_warning("CFG_172", "delivery.target_model",
                               f"目标模型规格表不可读：{exc}")]
    name = str(config.delivery.target_model)
    if name in table:
        return table[name], []
    fallback = table.get("seedance_2.5")
    issues = [_warning(
        "TARGET_001", "delivery.target_model",
        f"未知目标模型 {name!r}，按 seedance_2.5 处理（回落只记档不改值）")]
    return fallback, issues


def _segment_cap(raw: Dict[str, Any]) -> Optional[float]:
    """段上限（秒）：三类键按存在性取——max_segment_s / segment_range_s[hi] /
    segment_choices_s 最大值；都没有 → None（不适用段上限）。"""
    if isinstance(raw.get("max_segment_s"), (int, float)):
        return float(raw["max_segment_s"])
    segment_range = raw.get("segment_range_s")
    if (isinstance(segment_range, (list, tuple)) and len(segment_range) == 2
            and all(isinstance(v, (int, float)) for v in segment_range)):
        return float(max(segment_range))
    choices = raw.get("segment_choices_s")
    if (isinstance(choices, (list, tuple)) and choices
            and all(isinstance(v, (int, float)) for v in choices)):
        return float(max(choices))
    return None


def check_specs(config: AppConfig, plan: Plan) -> List[Issue]:
    """帧率/宽高比/逐镜时长与目标规格不一致 → warning；只告警不改设置。"""
    target, issues = _resolve_target(config)
    if target is None:
        return issues
    raw = target.raw
    aspect_range = raw.get("aspect_range")
    if (isinstance(aspect_range, (list, tuple)) and len(aspect_range) == 2
            and all(isinstance(v, (int, float)) for v in aspect_range)):
        width, height = config.delivery.resolution
        if height:
            ratio = float(width) / float(height)
            if not float(aspect_range[0]) <= ratio <= float(aspect_range[1]):
                issues.append(_warning(
                    "TARGET_002", "delivery.resolution",
                    f"宽高比 {ratio:.3f} 不在目标 {target.label} 的 "
                    f"aspect_range {aspect_range} 内"))
    cap = _segment_cap(raw)
    if cap is not None:
        fps = int(config.animation.fps or FPS)
        for shot in plan.shots:
            seconds = shot.duration_frames / float(fps)
            if seconds > cap:
                issues.append(_warning(
                    "TARGET_003", f"shot.{shot.shot_id}",
                    f"镜头时长 {seconds:.1f}s 超过目标 {target.label} 的"
                    f"段上限 {cap:.0f}s"))
    return issues


def suggest_slices(plan: Plan, target: ModelSpec) -> List[SliceAdvice]:
    """总时长超段上限 → 贪心选切点：优先镜界（累积不超上限的最大前缀）。

    只建议不执行。帧数按 ``contracts/plan.py::FPS``（24）换算段上限——计划层
    时间真源是帧，``Plan`` 不携带 fps；单镜自身超上限时无镜界可切，退化为
    "该镜末帧 + 1"的镜界切点并如实写 reason（镜内静止段切法需要相机采样，
    本函数只吃 plan，不在本卡外推）。
    """
    cap = _segment_cap(target.raw)
    if cap is None:
        return []
    ranges = shot_ranges(plan)
    cap_frames = int(cap * FPS)
    advice: List[SliceAdvice] = []
    running = 0
    for index, shot in enumerate(plan.shots):
        start, end = ranges[shot.shot_id]
        if running + shot.duration_frames > cap_frames:
            if running == 0:
                #: 单镜自身超限：没有合法镜界切点，如实记镜尾（不假装能切好）。
                advice.append(SliceAdvice(
                    cut_frame=end + 1,
                    reason=(f"单镜 {shot.shot_id} 本身 {shot.duration_frames / FPS:.0f}s "
                            f"超过段上限 {cap:.0f}s，无镜界可切")))
                running = 0
            else:
                advice.append(SliceAdvice(
                    cut_frame=start,
                    reason=(f"累计时长将超上限 {cap:.0f}s，"
                            f"切在镜头 {plan.shots[index - 1].shot_id} 之后")))
                running = shot.duration_frames
        else:
            running += shot.duration_frames
    return advice


__all__ = ["SliceAdvice", "check_specs", "suggest_slices"]
