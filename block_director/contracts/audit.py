"""审核结果契约（执行文档 v1.2 §16.3）。

定向修复（§7.1 阶段 B4）依赖这里的结构化违规项：只有
``code/rule/target/message/suggestion`` 这种颗粒度，LLM 才能一次改对，
而不是收到一句"构图不好，改改"。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from .enums import ErrorCode, Severity


#: v1.6 A6（D-08）：`scene_built` 事件的 `reason` 闭集。
#: initial = 首次构建；repair_rebuild = 修复重提草案改了计划后就地重建；
#: rollback_rebuild = 修复引入新违规被回滚后就地重建。
SCENE_BUILT_REASONS = ("initial", "repair_rebuild", "rollback_rebuild")

#: `scene_built` 事件自己拥有的字段；构建摘要里的同名键不得覆盖它们。
SCENE_BUILT_RESERVED_KEYS = frozenset({"reason", "duration_s"})

#: v1.6 A7（D-19）：标签烘焙后全帧自检事件名称。
LABEL_OVERLAP_REPORT = "label_overlap_report"

#: v1.6 C2（FR-A1 / D-10）：环境件闭集解析失败的 finding 码。
#: 生产侧（``layer3_engine/scene_executor.py``）把它写进
#: ``Environment.unresolved_anchors``——与 ``unresolved_anchor`` 同一条审计
#: 通路（经 ``BuildSummary.warnings`` 进 build_summary），只是**不再静默**：
#: 驱动器按 ``E_ENV_001`` 前缀识别并带回计划重问。取值单一真源是
#: ``ErrorCode.ENV_001``，这里只做审计契约层的登记与形状。
ENV_FINDING_CODE = str(ErrorCode.ENV_001)


def env_finding(label: str, reason: str) -> str:
    """渲染一条环境件 finding：``E_ENV_001: <label>: <reason>``。

    生产侧与（未来的）消费侧共用这一个形状，避免两边各自拼前缀漂移。
    """
    return (f"{ENV_FINDING_CODE}: {str(label or '').strip()}: "
            f"{str(reason or '').strip()}")


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
    #: F2（D-09）：断点续跑。必填字段是事件的最小形状；其余字段（如 status、
    #: pending_drafts、delivered_shots）由发出方按需附带。
    "resume_checkpoint": ("stage", "shot_id", "path"),
    "resume_checkpoint_failed": ("path", "stage"),
    "wall_clock_exhausted": ("llm_calls", "terminal_shots",
                             "resume_state_path"),
    "run_resumed": ("version", "terminal_shots", "first_shot"),
    "shot_resumed_skipped": ("shot_id", "status"),
    #: G2 #8（用户 2026-10-11 裁决）：计划多轮就地调整后仍不完整，用剧本
    #: 声明确定性补齐缺镜继续跑（不整轮作废）。filled_shots=补齐的镜数，
    #: attempts=已用的调整次数，problem=最后一次拒绝原因。
    "plan_adjusted": ("filled_shots", "attempts", "problem"),
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
class SkippedFinding:
    """v1.7 F1（TDD §4.4）：被 ``rules_disabled`` 关闭的规则**哨兵**。

    不是真 Finding（不进 errors/warnings）；定义在 contracts（它是 DTO），
    ``rule_checker.py`` import 它——反过来会让 contracts 依赖 layer3，撞依赖
    红线（守则 18）。
    """

    rule: str
    skipped: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {"rule": self.rule, "skipped": self.skipped}


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
    #: v1.6 B4（FR-C5）：视锥采样的结构化告警（``guard.GuardWarning`` 对象，
    #: 与构图分并置，不只给分数）。缺省空 ⇒ ``to_dict()`` 与升级前逐字节一致
    #: （``guard.enabled=false`` 缺省时审核器恒给空表）。
    guard_warnings: List[Any] = field(default_factory=list)
    #: 本次审核实际采到的帧数（0 = 没采样：guard 关闭或空镜）。
    guard_frames_sampled: int = 0
    #: 采样失败（E_GUARD_001）的 ``{"code", "message"}``；``None`` = 没失败。
    guard_sampling_error: Optional[Dict[str, Any]] = None
    #: v1.7 F1：被 ``rules_disabled`` 关闭的规则哨兵。缺省空 ⇒ ``to_dict()``
    #: 与升级前逐字节一致（零形状差纪律）。
    skipped: List[Any] = field(default_factory=list)
    #: v1.7 J4（R025）：校验层产的实测运镜数据（``{narration, start, end}``）。
    #: 缺省 ``None`` ⇒ 开关关/无采样时 ``to_dict()`` 不出这个键（零形状差）；
    #: 非空时供 review payload 组装与 R025 裁决用，**不参与 passed/score**。
    measured_camera: Optional[Dict[str, Any]] = None
    #: 空间尺（Ticket 04+）：本镜的观测测量（契约层 measurement 形状的普通
    #: dict 列表）。缺省 ``None`` ⇒ 尚未接入/未采集时 ``to_dict()`` 不出这个
    #: 键（零形状差纪律）；非空时供交付层写 ``ruler_measurements`` 证据，
    #: **不参与 passed/score**。
    ruler_measurements: Optional[List[Dict[str, Any]]] = None

    @property
    def total(self) -> int:
        return len(self.errors) + len(self.warnings)

    @classmethod
    def from_findings(cls, findings: Iterable[AuditError], *,
                      level: str = "rule", score: Optional[float] = None,
                      target: str = "") -> "AuditResult":
        items = list(findings)
        skipped = [i for i in items if isinstance(i, SkippedFinding)]
        real = [i for i in items if not isinstance(i, SkippedFinding)]
        errors = [i for i in real if i.is_error]
        warnings = [i for i in real if not i.is_error]
        suggestions = [i.suggestion for i in real if i.suggestion]
        return cls(passed=not errors, level=level, errors=errors,
                   warnings=warnings, suggestions=suggestions, score=score,
                   target=target, skipped=skipped)

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
        #: v1.6 B4：同一条零形状差纪律——没跑视锥采样就不多这三个键。
        if self.guard_warnings:
            payload["guard_warnings"] = [
                item.to_dict() if hasattr(item, "to_dict") else dict(item)
                for item in self.guard_warnings]
        if self.guard_frames_sampled:
            payload["guard_frames_sampled"] = int(self.guard_frames_sampled)
        if self.guard_sampling_error is not None:
            payload["guard_sampling_error"] = dict(self.guard_sampling_error)
        #: 同一条零形状差纪律：只有真的关了规则才多这个键。
        if self.skipped:
            payload["skipped"] = [
                item.to_dict() if hasattr(item, "to_dict") else dict(item)
                for item in self.skipped]
        #: 同一条零形状差纪律：只有真的采到实测运镜才多这个键。
        if self.measured_camera is not None:
            payload["measured_camera"] = dict(self.measured_camera)
        #: 同一条零形状差纪律：只有真的采到空间尺测量才多这个键。
        if self.ruler_measurements:
            payload["ruler_measurements"] = [
                dict(item) for item in self.ruler_measurements]
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
