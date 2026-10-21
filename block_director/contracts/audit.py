"""审核结果契约（执行文档 v1.2 §16.3）。

定向修复（§7.1 阶段 B4）依赖这里的结构化违规项：只有
``code/rule/target/message/suggestion`` 这种颗粒度，LLM 才能一次改对，
而不是收到一句"构图不好，改改"。
"""

from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from .enums import ErrorCode, Severity


def canonical_fingerprint(data: Any) -> str:
    """可复现的规范指纹（单一真源：快照/粗排等审计事件共用）。

    算法：``sort_keys`` 规范序列化（``ensure_ascii=False``、``default=str``）
    后取 SHA-256——同一产物两次指纹一致，跨进程稳定，供零 LLM 重放对拍。
    """
    payload = json.dumps(data, sort_keys=True, ensure_ascii=False,
                         default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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

#: R2 S2（精修身份冻结）：精修草案改写镜头身份（shot_type /
#: characters / framing_target）被拒绝的 finding 码。取值单一真源是
#: ``ErrorCode.IDENTITY_001``，这里只做审计契约层的登记与形状。
IDENTITY_FINDING_CODE = str(ErrorCode.IDENTITY_001)


def env_finding(label: str, reason: str) -> str:
    """渲染一条环境件 finding：``E_ENV_001: <label>: <reason>``。

    生产侧与（未来的）消费侧共用这一个形状，避免两边各自拼前缀漂移。
    """
    return (f"{ENV_FINDING_CODE}: {str(label or '').strip()}: "
            f"{str(reason or '').strip()}")


def identity_finding(shot_id: str, conflicts) -> str:
    """渲染一条镜头身份冻结 finding：``E_IDENTITY_001: <shot_id>: <…>``。

    精修路径用它把"草案试图改景别/主体集合/拍对象"的冲突清单带回计划
    保持原值的决策（spec_r2 §S2）。生产侧与消费侧共用这一个形状。
    """
    detail = "；".join(str(item) for item in (conflicts or ()))
    return (f"{IDENTITY_FINDING_CODE}: {str(shot_id or '').strip()}: "
            f"{detail}")


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
    #: vlm-feedback：VLM 评委能力探测（模型是否支持图像输入）。
    "vlm_capability": ("model", "supports_image", "evidence"),
    #: vlm-feedback：每镜每轮结构化判词快照（raw/parsed 同时留证）。
    "vlm_review_round": ("shot_id", "round", "schema", "raw", "parsed"),
    #: 决策树投影：react/repair 阶段的越界工具参数进该镜决策树投影后的留痕。
    #: ``record`` 字段与 ``decision_tree.ProjectionRecord.to_dict()`` 同构。
    "react_projected": ("shot_id", "stage", "tool", "records"),
    "repair_projected": ("shot_id", "stage", "tool", "records", "repair_invalid"),
    #: 决策树投影：B1 草案阶段的越界字段进该镜决策树投影后的留痕。
    #: ``records[]`` 是 ``ProjectionRecord`` 全量（一次草案多处越界 = 多条，
    #: 不再"每镜每轮最多一条"）。
    "draft_projected": ("shot_id", "stage", "records"),
    #: 决策树投影：构建期异常（真源漂移等）不得静默放行，记审计并回灌本轮。
    "projection_error": ("shot_id", "stage", "tool"),
    #: 方案 B：场景/元素就位（环境、角色、道具、群众）一次，不烘焙动作/机位。
    "scene_prepared": ("characters", "cameras", "props", "crowd", "prepared_at"),
    #: 方案 B：每镜每轮剧情预演（build/audit/repair/opt）的迭代留痕。
    "shot_iteration": ("shot_id", "round", "action", "result",
                       "warnings", "protected"),
    #: 方案 B：当前镜通过后移入下一镜（decision_trees 同机 evict）。
    "shot_advanced": ("shot_id", "next_shot_id", "decision_trees_evicted"),
    #: 数值层：每次候选评测（value=-inf 表示硬违规，reason 记录哪条规则）。
    "opt_candidate": ("shot_id", "round", "stage", "x", "clamped",
                      "value", "reason"),
    #: 数值层：每镜每轮优化结果（method_choice/method_reason 是 agent 原始
    #: 声明，method 是实际执行的方法；method_inapplicable 时 method 为空；
    #: refit_by ∈ {agent,user,none}，绝不伪称 human）。
    "opt_result": ("shot_id", "round", "stage", "x0", "value0", "best_x",
                   "best_value", "step_scale", "calls", "method_choice",
                   "method_reason", "method", "improved", "refit_by"),
    #: 数值层：优化器试图改离散键/剧本硬值被拒。
    "opt_rejected": ("shot_id", "key", "attempt", "reason"),
    "shot_version_saved": ("shot_id", "version", "reason", "path"),
    "shot_version_restored": ("shot_id", "version", "reason"),
    "shot_version_restore_failed": ("shot_id", "version", "reason"),
    "adversarial_review": ("shot_id", "version", "disposition", "issues", "rationale"),
}


def missing_event_fields(kind: str, data: Dict[str, Any]) -> List[str]:
    """登记过的事件缺了哪些必有字段（未登记的事件名返回 ``["<unregistered>"]``）。"""
    required = V16_EVENT_FIELDS.get(kind)
    if required is None:
        return ["<unregistered>"]
    return [name for name in required if name not in (data or {})]


def _redact_data_uri(url: str) -> Dict[str, Any]:
    """把一条 ``data:<mime>;base64,<payload>`` 折成占位信息（丢弃原载荷）。"""
    if ";base64," not in url:
        raise ValueError(f"data URL 缺少 ;base64, 分隔符：{url[:64]!r}")
    head, payload = url.split(";base64,", 1)
    mime = head[len("data:"):] if head.startswith("data:") else ""
    try:
        decoded = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"data URL 的 base64 解码失败：{url[:64]!r}") from exc
    return {"redacted": True, "mime": mime, "bytes": len(decoded),
            "sha256": hashlib.sha256(decoded).hexdigest()}


def redact_image_parts(messages: Any) -> List[Any]:
    """深拷贝消息列表，把 ``data:`` 图像分片替换为占位信息（vlm-feedback）。

    - 只替换 ``type=="image_url"`` 且 ``image_url`` 为 dict 且 ``url`` 为 str
      且以 ``data:`` 开头的分片；http(s) url、文本分片、非 dict 分片、
      ``image_url`` 为字符串的分片、字符串形 content、tool_calls 一律原样。
    - 占位形状 ``{"redacted": True, "mime", "bytes", "sha256"}`` 丢弃原
      ``url``（base64 不落盘），但保留 ``type`` 与 ``image_url`` 包装层。
    - 缺 ``;base64,`` 分隔或 base64 解码失败 ⇒ :class:`ValueError`（不吞）。
    """
    redacted: List[Any] = []
    for message in (messages or []):
        copied = copy.deepcopy(message)
        if isinstance(copied, dict):
            content = copied.get("content")
        else:
            content = getattr(copied, "content", None)
        if isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                image_url = part.get("image_url")
                if (part.get("type") == "image_url"
                        and isinstance(image_url, dict)):
                    url = image_url.get("url")
                    if isinstance(url, str) and url.startswith("data:"):
                        part["image_url"] = _redact_data_uri(url)
        redacted.append(copied)
    return redacted


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
    #: vlm-feedback 卡 V12：画面/空间测量摘要（``{"framing": …, "spatial": …}``，
    #: 由 ``cinema/spatial_digest.py::scene_digest`` 产出）。只进 VLM 评审提示
    #: 与修复提示，**不进任何门**（不影响 passed/score/errors/warnings）。
    #: 缺省 ``None`` ⇒ guard 关闭、空镜或采样失败时 ``to_dict()`` 与改动前
    #: 逐字节一致（零形状差）。
    scene_digest: Optional[Dict[str, Any]] = None
    #: 2026-10-12 D1: 逐镜对抗审查快照 (adversarial_review.to_dict())。
    #: 可选、缺省 ``None`` 使 ``to_dict()`` 与改动前逐字节一致（零形状差）。
    #: 审查只作证据与建议，不改 passed/score/errors；越轴 escalate 由既有
    #: 人工 gate 处理，不在这里放行。
    adversarial_review: Optional[Dict[str, Any]] = None
    #: 空间尺转正：本镜的六层评测汇总（``RulerReview.to_dict()`` 形状的普通
    #: dict；逐镜审核时 continuity 层如实标"未核验"，序列级复核时补全场链）。
    #: 缺省 ``None`` ⇒ 未接入/未采集时 ``to_dict()`` 不出这个键（零形状差）；
    #: 其 ``hard_gates`` 是 CHECKING 阶段的**新增阻断条件**（旧 passed 之后
    #: 再查），但**不参与 passed/score**（与 guard_warnings 同纪律）。
    ruler_review: Optional[Dict[str, Any]] = None

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
        #: vlm-feedback 卡 V12：同一条零形状差纪律——没生成摘要就不多这个键。
        if self.scene_digest is not None:
            payload["scene_digest"] = dict(self.scene_digest)
        #: D1 对抗审查：同一条零形状差纪律——没审查就不多这个键。
        if self.adversarial_review is not None:
            payload["adversarial_review"] = dict(self.adversarial_review)
        #: 同一条零形状差纪律：只有真的跑出空间尺六层评测才多这个键。
        if self.ruler_review is not None:
            payload["ruler_review"] = dict(self.ruler_review)
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
