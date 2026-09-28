"""审核结果契约（执行文档 v1.2 §16.3）。

定向修复（§7.1 阶段 B4）依赖这里的结构化违规项：只有
``code/rule/target/message/suggestion`` 这种颗粒度，LLM 才能一次改对，
而不是收到一句"构图不好，改改"。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from .enums import Severity


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
        return {
            "passed": self.passed, "level": self.level, "target": self.target,
            "score": self.score,
            "errors": [e.to_dict() for e in self.errors],
            "warnings": [w.to_dict() for w in self.warnings],
            "suggestions": list(self.suggestions),
        }

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
