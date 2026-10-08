"""审核结果契约（执行文档 v1.2 §16.3）。

定向修复（§7.1 阶段 B4）依赖这里的结构化违规项：只有
``code/rule/target/message/suggestion`` 这种颗粒度，LLM 才能一次改对，
而不是收到一句"构图不好，改改"。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from .enums import Severity


#: v1.6 A6（D-08）：`scene_built` 事件的 `reason` 闭集。
#: initial = 首次构建；repair_rebuild = 修复重提草案改了计划后就地重建；
#: rollback_rebuild = 修复引入新违规被回滚后就地重建。
SCENE_BUILT_REASONS = ("initial", "repair_rebuild", "rollback_rebuild")

#: `scene_built` 事件自己拥有的字段；构建摘要里的同名键不得覆盖它们。
SCENE_BUILT_RESERVED_KEYS = frozenset({"reason", "duration_s"})

#: v1.6 A7（D-19）：标签烘焙后全帧自检事件名称。
LABEL_OVERLAP_REPORT = "label_overlap_report"


def scene_built_reason(*, rebuild_in_place: bool, just_rolled_back: bool) -> str:
    """由驱动器已有的两个状态位推出 `scene_built.reason`（纯函数，回滚优先）。"""
    if not rebuild_in_place:
        return "initial"
    return "rollback_rebuild" if just_rolled_back else "repair_rebuild"


#: v1.6 新审计事件契约（TDD §3.6 / §7；红线 R-7：先登记再用）。
#: 事件名 → 必有字段。生产者写事件时必须带齐这些键；测试按此对拍。
V16_EVENT_FIELDS = {
    #: B2/B4：审核采样后的结构化告警（GuardWarning.to_dict() 全量）
    "guard_warning": ("shot_id", "warnings", "frames_sampled"),
    #: B4：LLM 对单条告警的裁决；accept 必须留痕，不得静默
    "guard_verdict": ("shot_id", "warning_type", "accepted", "reason", "fix_action"),
    #: F1：重试阶梯每一步
    "retry_ladder": ("stage", "shot_id", "elapsed_s"),
    #: D3：计划确认后的节奏读数（info 级，不是门）
    "rhythm_reading": ("asl_s", "duration_cv", "monotony", "jump_cut_risks"),
    #: A7：标签烘焙后的全帧自检
    "label_overlap_report": ("max_overlap_ratio", "overlap_frames",
                             "frames_checked", "limit"),
}


def missing_event_fields(kind: str, data: Dict[str, Any]) -> List[str]:
    """登记过的事件缺了哪些必有字段（未登记的事件名返回 ``["<unregistered>"]``）。"""
    required = V16_EVENT_FIELDS.get(kind)
    if required is None:
        return ["<unregistered>"]
    return [name for name in required if name not in (data or {})]


@dataclass
class AuditError:
    rule: str
    message: str
    severity: Severity = Severity.ERROR
    code: str = ""
    suggestion: str = ""
    target: str = ""

    @property
    def is_error(self) -> bool:
        return self.severity is Severity.ERROR

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code, "rule": self.rule,
            "severity": str(self.severity), "target": self.target,
            "message": self.message, "suggestion": self.suggestion,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AuditError":
        return cls(rule=str(data.get("rule", "")),
                   message=str(data.get("message", "")),
                   severity=Severity(data.get("severity", "error")),
                   code=str(data.get("code", "")),
                   suggestion=str(data.get("suggestion", "")),
                   target=str(data.get("target", "")))


@dataclass
class AuditResult:
    passed: bool = True
    level: str = "rule"                     # rule / llm / human
    errors: List[AuditError] = field(default_factory=list)
    warnings: List[AuditError] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    score: Optional[float] = None
    target: str = ""
    #: v1.5 §5.4（P4-T4）：**破例辩护对拍**（声明 vs 实测）。
    #: 可选、缺省 ``None`` ⇒ 老路径（不跑对拍 / 旧审计结果）行为与形状逐字节
    #: 不变；对拍结果**只记录、不参与任何门**（设门属 OPEN_ITEMS D11，须裁决）。
    justification_audit: Optional[Dict[str, Any]] = None
    #: v1.5 §5.5（P6-T1）：**VLM 评审外回路**的逐镜记录。
    #: 可选、缺省 ``None`` ⇒ ``vlm_review.enabled=false``（缺省）时调用方拿到的
    #: ``to_dict()`` 与升级前逐字节一致。评审判词**只进 shots.json 与面板**，
    #: 不参与 ``passed`` / ``score`` / ``errors``，也不接任何既有门。
    vlm_review: Optional[Dict[str, Any]] = None

    @property
    def total(self) -> int:
        return len(self.errors) + len(self.warnings)

    @classmethod
    def from_findings(cls, findings: Iterable[AuditError], *,
                      level: str = "rule", score: Optional[float] = None,
                      target: str = "") -> "AuditResult":
        items = list(findings)
        errors = [i for i in items if i.is_error]
        warnings = [i for i in items if not i.is_error]
        suggestions = [i.suggestion for i in items if i.suggestion]
        return cls(passed=not errors, level=level, errors=errors,
                   warnings=warnings, suggestions=suggestions, score=score,
                   target=target)

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "passed": self.passed, "level": self.level, "target": self.target,
            "score": self.score,
            "errors": [e.to_dict() for e in self.errors],
            "warnings": [w.to_dict() for w in self.warnings],
            "suggestions": list(self.suggestions),
        }
        #: 只在真的有对拍结果时才加这个键——没跑对拍的调用方（可离线/其它
        #: 审核器）拿到的 ``to_dict()`` 与升级前逐字节一致（NFR-4 向后兼容）。
        if self.justification_audit is not None:
            payload["justification_audit"] = dict(self.justification_audit)
        #: 同纪律：没跑外部评审就不多这个键（默认关 ⇒ 零形状差）。
        if self.vlm_review is not None:
            payload["vlm_review"] = dict(self.vlm_review)
        return payload

    def format_for_llm(self) -> str:
        """渲染成修复提示词里可直接使用的结构化文本（§18.3）。"""
        head = (f"审核结果（{self.level}）："
                f"{'通过' if self.passed else '未通过'}"
                f"｜error {len(self.errors)}｜warning {len(self.warnings)}")
        if self.score is not None:
            head += f"｜评分 {self.score:.1f}"
        lines = [head]
        for item in [*self.errors, *self.warnings]:
            target = f" target={item.target}" if item.target else ""
            lines.append(f"- [{item.rule or item.code}] ({item.severity})"
                         f"{target}: {item.message}")
            if item.suggestion:
                lines.append(f"  建议：{item.suggestion}")
        if not self.errors and not self.warnings:
            lines.append("- 无违规项")
        return "\n".join(lines)
