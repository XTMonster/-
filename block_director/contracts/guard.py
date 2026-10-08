"""告警契约（v1.6 B2，FR-C1–C4）。

几何层量一件事，LLM 裁决一件事。本模块只做几何层的输出端：
把采样结果折成**结构化告警 DTO**，携带数值证据、声明意图与修复提示，
供 ``shot_auditor`` 挂到 ``AuditResult``，再由修复提示注入到修复回合。

禁止 import bpy / mathutils。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Tuple


GUARD_SCHEMA_VERSION = "guard/v1"


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Confidence(str, Enum):
    HIGH = "high"
    LOW = "low"


#: 告警类型闭集（16 项）。新类型必须先加进这里再用。
WARNING_TYPES: Tuple[str, ...] = (
    "subject_out_of_frame",   # 完全出画（非剧本设计）→ error, high
    "subject_behind_camera",  # z<0 → error, high
    "subject_not_visible",    # 包围盒在画内但可见比例 0 → error, high
    "edge_clip",              # 裁切率超阈 → warning（包围盒虚胖 ⇒ low）
    "occlusion",              # 主体可见比例 <0.8 且未声明前景遮挡 → warning
    "framing_too_tight",      # 头部/主体占比高于景别区间 → warning, high
    "framing_too_loose",      # 低于区间 → warning, high
    "headroom_off",           # 留白出区间 → warning
    "lead_room_short",        # 朝向侧留白 <0.05 → warning
    "thirds_deviation",       # → info
    "size_drift",             # 镜内景别漂移 >±15% → warning
    "sudden_jump",            # 两帧占比跳变超阈 → warning, high
    "unplanned_exit",         # 出画事件与声明时间 diff 超阈 → warning
    "jump_cut_risk",          # 相邻镜占比差<10% 且视角差<30° → warning（由 LLM 裁决）
    "axis_screen_order",      # 银幕左右序翻转（无中性镜桥接）→ error
    "pace_monotony",          # 全片镜长相同 → info
)

_WARNING_TYPE_SET: frozenset = frozenset(WARNING_TYPES)


def warning_type_problems(t: str) -> str:
    """返回非空问题字符串，或空串表示合法。"""
    if t not in _WARNING_TYPE_SET:
        return f"未知告警类型 {t!r}；合法值：{', '.join(WARNING_TYPES)}"
    return ""


# --------------------------------------------------------------------------- #
# 景别区间表（D-12：度量口径两套，不能混用）
# --------------------------------------------------------------------------- #
#: 近景系列：量**头部占画高比**（头顶到下颌的屏幕高度 ÷ 画面高度）
HEAD_HEIGHT_BANDS: Dict[str, Tuple[float, float]] = {
    "MCU": (0.45, 0.60),
    "CU":  (0.55, 0.75),
    "ECU": (0.75, 1.00),
}

#: 中远景系列：量**全身占画高比**（脚底到头顶的屏幕高度 ÷ 画面高度）
BODY_HEIGHT_BANDS: Dict[str, Tuple[float, float]] = {
    "MS":  (0.55, 0.70),
    "MLS": (0.70, 0.88),
    "LS":  (0.35, 0.60),
    "ELS": (0.15, 0.35),
}

ALL_SHOT_BANDS: Dict[str, Tuple[float, float]] = {**HEAD_HEIGHT_BANDS,
                                                    **BODY_HEIGHT_BANDS}


# --------------------------------------------------------------------------- #
# 告警 DTO
# --------------------------------------------------------------------------- #
@dataclass
class GuardWarning:
    """单条结构化告警。

    ``evidence`` 的数值键必须是可 JSON 序列化的（不含 NaN/Inf）。
    ``suggestion_hint`` 只是提示，改不改由 LLM 自己决定（"测量与裁决分离"）。
    """
    shot_id: str
    frame_range: Tuple[int, int]
    type: str                          # WARNING_TYPES 闭集
    subject: str                       # 角色/元素 id；"scene" 表示镜头级
    evidence: Dict[str, Any]           # {实测值, 阈值/区间, ...}
    severity: Severity
    confidence: Confidence
    declared_intent: str = ""
    suggestion_hint: str = ""

    def __post_init__(self):
        if isinstance(self.severity, str):
            self.severity = Severity(self.severity)
        if isinstance(self.confidence, str):
            self.confidence = Confidence(self.confidence)

    def problems(self) -> str:
        """返回非空字符串表示有问题（兼容 AuditError 同名接口）。"""
        p = warning_type_problems(self.type)
        if p:
            return p
        if not isinstance(self.frame_range, (tuple, list)) or len(self.frame_range) != 2:
            return "frame_range 必须是长度为 2 的 (start, end)"
        return ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "shot_id": self.shot_id,
            "frame_range": list(self.frame_range),
            "subject": self.subject,
            "evidence": dict(self.evidence),
            "severity": str(self.severity.value),
            "confidence": str(self.confidence.value),
            "declared_intent": self.declared_intent,
            "suggestion_hint": self.suggestion_hint,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GuardWarning":
        return cls(
            shot_id=str(data.get("shot_id", "")),
            frame_range=tuple(data.get("frame_range", [0, 0])),  # type: ignore[arg-type]
            type=str(data.get("type", "")),
            subject=str(data.get("subject", "")),
            evidence=dict(data.get("evidence", {})),
            severity=Severity(data.get("severity", "warning")),
            confidence=Confidence(data.get("confidence", "high")),
            declared_intent=str(data.get("declared_intent", "")),
            suggestion_hint=str(data.get("suggestion_hint", "")),
        )
