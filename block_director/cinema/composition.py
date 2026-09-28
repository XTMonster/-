"""构图分析（执行文档 v1.2 §10.4）。

文档只写了"返回 0–100 分"，没给公式，会让行为不可复现。本模块把它定死：
六个分项各返回 0–1 的分数与一条建议，按固定权重加权成百分制。

遮挡（occlusion）权重最高（0.25）——它是最致命的构图问题，而且只有射线
检测能算，所以由调用方传入结果（bpy 侧用 ``scene.ray_cast``）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence

WEIGHTS: Dict[str, float] = {
    "headroom": 0.15,
    "lead_room": 0.20,
    "rule_of_thirds": 0.15,
    "balance": 0.15,
    "occlusion": 0.25,
    "framing": 0.10,
}

PASS_SCORE = 70.0

# 头部留白的理想区间（占画面高度的比例）
HEADROOM_IDEAL = (0.03, 0.12)

# 三分线交点
THIRDS = (1.0 / 3.0, 2.0 / 3.0)


@dataclass
class SubjectBox:
    """被摄主体在归一化视口坐标下的包围盒（§17.4：[0,1] 区间，可越界）。"""

    name: str
    left: float
    right: float
    top: float
    bottom: float
    facing: float = 0.0          # 屏幕空间朝向：-1 向左，+1 向右，0 无方向

    @property
    def center_x(self) -> float:
        return (self.left + self.right) / 2.0

    @property
    def center_y(self) -> float:
        return (self.top + self.bottom) / 2.0

    @property
    def height(self) -> float:
        return self.top - self.bottom

    @property
    def width(self) -> float:
        return self.right - self.left

    def inside_ratio(self) -> float:
        """包围盒落在画面内的比例（0–1）。"""
        x_overlap = max(0.0, min(self.right, 1.0) - max(self.left, 0.0))
        y_overlap = max(0.0, min(self.top, 1.0) - max(self.bottom, 0.0))
        area = max(self.width, 1e-9) * max(self.height, 1e-9)
        return max(0.0, min(1.0, (x_overlap * y_overlap) / area))


@dataclass
class CompositionItem:
    name: str
    score: float
    weight: float
    suggestion: str = ""


@dataclass
class CompositionReport:
    score: float
    items: Dict[str, CompositionItem] = field(default_factory=dict)
    suggestions: List[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.score >= PASS_SCORE

    def to_dict(self) -> dict:
        return {
            "score": round(self.score, 1),
            "passed": self.passed,
            "items": {k: {"score": round(v.score, 3), "weight": v.weight,
                          "suggestion": v.suggestion}
                      for k, v in self.items.items()},
            "suggestions": list(self.suggestions),
        }


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _headroom(box: SubjectBox) -> CompositionItem:
    top_margin = 1.0 - box.top
    low, high = HEADROOM_IDEAL
    if low <= top_margin <= high:
        return CompositionItem("headroom", 1.0, WEIGHTS["headroom"])
    if top_margin > high:
        excess = top_margin - high
        return CompositionItem("headroom", _clamp01(1.0 - excess / 0.35),
                               WEIGHTS["headroom"],
                               "头顶留白过多、主体偏下；建议抬高机位或收紧景别")
    deficit = low - top_margin
    return CompositionItem("headroom", _clamp01(1.0 - deficit / 0.08),
                           WEIGHTS["headroom"],
                           "头顶被切，注意不要切到发际线之上")


def _lead_room(box: SubjectBox) -> CompositionItem:
    if abs(box.facing) < 1e-6:
        return CompositionItem("lead_room", 0.75, WEIGHTS["lead_room"],
                               "主体没有明确朝向，视线空间不做要求")
    space_right = 1.0 - box.center_x
    space_left = box.center_x
    ahead = space_right if box.facing > 0 else space_left
    behind = space_left if box.facing > 0 else space_right
    if ahead <= 0:
        return CompositionItem("lead_room", 0.0, WEIGHTS["lead_room"],
                               "主体朝画面外，视线方向没有留白；建议反转机位或平移构图")
    ratio = ahead / max(ahead + behind, 1e-9)
    score = _clamp01((ratio - 0.4) / 0.35)
    suggestion = "" if score >= 0.7 else "视线方向留白不足；建议把主体放到画面偏对侧"
    return CompositionItem("lead_room", score, WEIGHTS["lead_room"], suggestion)


def _thirds(box: SubjectBox) -> CompositionItem:
    best = min(abs(box.center_x - tx) + abs(box.center_y - ty)
               for tx in THIRDS for ty in THIRDS)
    score = _clamp01(1.0 - best / 0.35)
    suggestion = "" if score >= 0.7 else "主体偏离三分线交点；可微调构图让主体落到交点附近"
    return CompositionItem("rule_of_thirds", score, WEIGHTS["rule_of_thirds"],
                           suggestion)


def _balance(boxes: Sequence[SubjectBox]) -> CompositionItem:
    """画面重心是否偏塌。

    单个主体时给较大的死区：把唯一主体放在三分线交点是**正确**构图，
    不应该被"重心偏离中心"扣分。主体多于一个时才要求重心靠中间。
    """
    if not boxes:
        return CompositionItem("balance", 0.0, WEIGHTS["balance"], "画面里没有被摄主体")
    mean_x = sum(b.center_x for b in boxes) / len(boxes)
    offset = abs(mean_x - 0.5)
    dead_zone = 0.20 if len(boxes) == 1 else 0.12
    score = _clamp01(1.0 - max(0.0, offset - dead_zone) / 0.30)
    suggestion = "" if score >= 0.7 else "画面重心偏塌；建议左右重新平衡人物位置"
    return CompositionItem("balance", score, WEIGHTS["balance"], suggestion)


def _occlusion(boxes: Sequence[SubjectBox],
               occluded: Optional[Dict[str, bool]]) -> CompositionItem:
    if not boxes or not occluded:
        return CompositionItem("occlusion", 1.0, WEIGHTS["occlusion"])
    blocked = [b.name for b in boxes if occluded.get(b.name)]
    if not blocked:
        return CompositionItem("occlusion", 1.0, WEIGHTS["occlusion"])
    score = 0.0 if len(blocked) == len(boxes) else 0.3
    return CompositionItem("occlusion", score, WEIGHTS["occlusion"],
                           f"主体被前景遮挡：{'、'.join(blocked)}；建议移开机位或调整遮挡物")


def _framing(box: SubjectBox,
             expected_height: Optional[float]) -> CompositionItem:
    inside = box.inside_ratio()
    score = inside
    suggestion = "" if inside >= 0.98 else "主体部分出画；建议收紧景别或重新构图"
    if expected_height and expected_height > 0:
        ratio = box.height / expected_height
        deviation = abs(ratio - 1.0)
        # 允许 ±35% 偏差；偏差越大扣分越多
        score *= _clamp01(1.0 - max(0.0, deviation - 0.35) / 0.65)
        if deviation > 0.35 and not suggestion:
            suggestion = f"主体在画面中的大小与景别不符（实际/预期={ratio:.2f}）"
    return CompositionItem("framing", _clamp01(score), WEIGHTS["framing"], suggestion)


def evaluate_composition(boxes: Iterable[SubjectBox],
                         occluded: Optional[Dict[str, bool]] = None,
                         expected_height: Optional[float] = None
                         ) -> CompositionReport:
    """按 §10.4 的六项加权评分，返回百分制结果与建议。"""
    subjects: List[SubjectBox] = list(boxes)
    if not subjects:
        return CompositionReport(score=0.0, suggestions=["画面里没有被摄主体"])

    primary = max(subjects, key=lambda b: b.height)
    items = {
        "headroom": _headroom(primary),
        "lead_room": _lead_room(primary),
        "rule_of_thirds": _thirds(primary),
        "balance": _balance(subjects),
        "occlusion": _occlusion(subjects, occluded),
        "framing": _framing(primary, expected_height),
    }
    total_weight = sum(item.weight for item in items.values()) or 1.0
    score = sum(item.score * item.weight for item in items.values()) / total_weight * 100.0
    suggestions = [item.suggestion for item in items.values() if item.suggestion]
    return CompositionReport(score=round(score, 1), items=items,
                             suggestions=suggestions)
