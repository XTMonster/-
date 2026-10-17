"""构图分析（执行文档 v1.2 §10.4）。

文档只写了"返回 0–100 分"，没给公式，会让行为不可复现。本模块把它定死：
六个分项各返回 0–1 的分数与一条建议，按固定权重加权成百分制。

遮挡（occlusion）权重最高（0.25）——它是最致命的构图问题，而且只有射线
检测能算，所以由调用方传入结果（bpy 侧用 ``scene.ray_cast``）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence

from .anchor import DEFAULT_PROFILE as _PROFILE

WEIGHTS: Dict[str, float] = {
    "headroom": 0.15,
    "lead_room": 0.20,
    "rule_of_thirds": 0.15,
    "balance": 0.15,
    "occlusion": 0.25,
    "framing": 0.10,
}

# 空间尺正式门槛：构图分必须严格高于 80 才算通过。
PASS_SCORE = 80.0

# 头部留白的理想区间（占画面高度的比例）
HEADROOM_IDEAL = (0.03, 0.12)

# 头部留白只在"比全身更紧"的景别里才有意义：整身都在画里时，头顶上方的
# 空间是宽景的固有属性，不是构图缺陷（见 §10.4 的实现注记）。
#: v1.4 P10：头顶留白只在"比全身更紧"的景别里才有意义，阈值必须跟着
#: §2.1 的冻结身高走（旧值 1.45 是 v1.3 的几何）。
SUBJECT_HEIGHT_FOR_HEADROOM = _PROFILE.total_height

# 三分线交点
THIRDS = (1.0 / 3.0, 2.0 / 3.0)


def thirds_deviation(cx: float, cy: float) -> float:
    """主体中心到最近三分线交点的欧氏距离（NDC 比例，0–1，可越界）。

    九宫格数字版（用户 2026-10-11）：多模态评委拿它判断"贴不贴三分交点"。
    ``composition._thirds`` 的评分与 ``frustum_metrics.frame_metrics`` 的
    ``thirds_deviation`` 指标都以它为单一真源口径（评分另做非线性映射）。
    """
    return min(math.hypot(float(cx) - tx, float(cy) - ty)
               for tx in THIRDS for ty in THIRDS)


@dataclass
class SubjectBox:
    """被摄主体在归一化视口坐标下的包围盒（§17.4：[0,1] 区间，可越界）。"""

    name: str
    left: float
    right: float
    top: float
    bottom: float
    facing: float = 0.0          # 屏幕空间朝向：-1 向左，+1 向右，0 无方向
    clipped_top: bool = False    # 包围盒被"该景别看到的窗口"从上方截断
    clipped_sides: bool = False  # 主体比这个景别的画面还宽，左右本就该出画

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
        #: 用户 2026-10-18 裁决：构图分必须**严格高于** 80 才算通过，
        #: 恰好等于 80.0 不算过（score == PASS_SCORE 仍为 False）。
        return self.score > PASS_SCORE

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


def _headroom(box: SubjectBox, applies: bool = True) -> CompositionItem:
    if not applies or box.clipped_top:
        # 画面顶边落在身体内部（ECU 这种"局部占满"）或整身都在画里（宽景）：
        # 头顶留白这个概念不适用，不该扣分也不该给建议。
        return CompositionItem("headroom", 1.0, WEIGHTS["headroom"])
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
    suggestion = "" if score >= 0.8 else "视线方向留白不足；建议把主体放到画面偏对侧"
    return CompositionItem("lead_room", score, WEIGHTS["lead_room"], suggestion)


def _thirds(box: SubjectBox) -> CompositionItem:
    best = min(abs(box.center_x - tx) + abs(box.center_y - ty)
               for tx in THIRDS for ty in THIRDS)
    score = _clamp01(1.0 - best / 0.35)
    suggestion = "" if score >= 0.8 else "主体偏离三分线交点；可微调构图让主体落到交点附近"
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
    suggestion = "" if score >= 0.8 else "画面重心偏塌；建议左右重新平衡人物位置"
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
    # 这个景别本来就只拍局部（ECU 的"局部占满"）时，"整身是否在画内"没有意义：
    # 只要主体没有整个跑到画外，就不该按出画扣分，也不该建议"收紧景别"。
    if box.clipped_top or box.clipped_sides:
        inside = 1.0 if box.inside_ratio() > 0.0 else 0.0
    else:
        inside = box.inside_ratio()
    score = inside
    # 0.90 而不是 0.98：透视会让贴着画框的包围盒角点略微越界，把阈值卡在
    # 98% 会让"本来就贴边"的正常景别每次都被建议"收紧景别"。
    suggestion = "" if inside >= 0.90 else "主体部分出画；建议收紧景别或重新构图"
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
                         expected_height: Optional[float] = None,
                         headroom_applies: bool = True
                         ) -> CompositionReport:
    """按 §10.4 的六项加权评分，返回百分制结果与建议。"""
    subjects: List[SubjectBox] = list(boxes)
    if not subjects:
        return CompositionReport(score=0.0, suggestions=["画面里没有被摄主体"])

    #: v1.6 G2（延续"双人镜对准谁"的授权语义）：完全出画的主体不该当构图
    #: 主锚——v10 真跑 4 镜因计划里多声明了一个站在画面外的角色，RK-10 硬闸
    #: 把**画内主体**的合格镜头一起压到 20。主锚取"可见"的最高盒，全可见时
    #: 仍是最高盒（与旧行为一致）；出画者继续参与 balance/occlusion 的计分。
    primary = max(subjects,
                  key=lambda b: (b.inside_ratio() > 0.05, b.height))
    items = {
        "headroom": _headroom(primary, headroom_applies),
        "lead_room": _lead_room(primary),
        "rule_of_thirds": _thirds(primary),
        "balance": _balance(subjects),
        "occlusion": _occlusion(subjects, occluded),
        "framing": _framing(primary, expected_height),
    }
    total_weight = sum(item.weight for item in items.values()) or 1.0
    score = sum(item.score * item.weight for item in items.values()) / total_weight * 100.0
    # v1.4 P16 / RK-10：主体**几乎不在画里**时，其余五项再"干净"也没有意义
    # ——头部留白、遮挡、重心这些判据在"画框里根本没有主体"时都会**真空成立**，
    # 于是把角色挪到 30 米外，构图分还能有 60。这条硬闸把这种情况压到 20 分
    # 以下，让"做坏镜 → 掉 ≥20 分"真的成立（也让阈值不被写死成 -1e9 蒙过）。
    if primary.inside_ratio() <= 0.05:
        score = min(score, 20.0)
    suggestions = [item.suggestion for item in items.values() if item.suggestion]
    return CompositionReport(score=round(score, 1), items=items,
                             suggestions=suggestions)
