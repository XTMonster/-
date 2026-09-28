"""Level 2 自我审核（执行文档 v1.2 §11.1 / §7.10）。

v1.0 把 self_review 做成"工具内部发起 LLM 调用"，会在主线程上冻结 UI。
v1.1/v1.2 改成**独立的一次 LLM 回合**：驱动器进入 REVIEWING 状态，后台线程
发请求，主线程轮询；结论作为观察回灌，需要改就走 B4 修复。

规则能查的（轴线、碰撞、在画…）已经由 Level 1 查过；这一层问的是规则查不到
的东西：这个镜头**是否真的表达了它的意图**。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..contracts.audit import AuditError, AuditResult
from ..contracts.enums import Purpose, Severity, ToolChoice
from ..contracts.messages import (
    ChatPayload,
    ChatReply,
    Message,
    MessageRole,
    new_request_id,
)

REVIEW_TOOL_NAME = "submit_review"

REVIEW_TOOL_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict"],
    "properties": {
        "verdict": {"type": "string", "enum": ["ok", "needs_fix"]},
        "notes": {"type": "string"},
        "issues": {"type": "array", "items": {"type": "string"},
                   "maxItems": 5},
        "suggestion": {"type": "string"},
    },
}

REVIEW_SYSTEM_PROMPT = """\
你是白模预演的执行导演，正在复核**自己刚做完的**这个镜头。

规则校验已经通过（轴线、碰撞、可见性、构图分都在允许范围内），所以不要再
重复规则问题。请只判断一件规则查不到的事：

**这个镜头是否真的表达了它的意图？**

镜头意图：{intent}
镜头信息：{shot_type}，{duration_frames} 帧

规则校验结果：
{audit}

当前场景：
{scene_state}

判定标准：
- 如果机位、景别与调度足以支撑该意图，返回 verdict=ok；
- 如果明显表达不出来（例如意图是"孤立感"却拍了双人中景、意图是"压迫感"
  却用了平视远景），返回 verdict=needs_fix，并在 issues 里写清具体问题、
  在 suggestion 里给出**可执行**的修改方向。

必须调用 submit_review 工具提交结论，不要只输出文字。
"""


@dataclass
class ReviewVerdict:
    verdict: str = "ok"
    notes: str = ""
    issues: List[str] = field(default_factory=list)
    suggestion: str = ""

    @property
    def needs_fix(self) -> bool:
        return self.verdict == "needs_fix"

    def to_audit(self, target: str) -> AuditResult:
        """把复核结论转成与 Level 1 同构的结果，好复用 B4 修复通路。"""
        findings = [AuditError(rule="SELF_REVIEW", code="E_CORR_001",
                               severity=Severity.ERROR, target=target,
                               message=issue, suggestion=self.suggestion)
                    for issue in self.issues] or [
            AuditError(rule="SELF_REVIEW", code="E_CORR_001",
                       severity=Severity.ERROR, target=target,
                       message=self.notes or "自我审核认为该镜头未表达意图",
                       suggestion=self.suggestion)]
        return AuditResult.from_findings(findings, level="llm", target=target)


def build_review_payload(*, intent: str, shot_type: str, duration_frames: int,
                         audit: Optional[AuditResult] = None,
                         scene_state: str = "", temperature: float = 0.2,
                         request_id: Optional[str] = None) -> ChatPayload:
    system_text = REVIEW_SYSTEM_PROMPT.format(
        intent=intent or "（未说明）", shot_type=shot_type,
        duration_frames=duration_frames,
        audit=audit.format_for_llm() if audit else "（无）",
        scene_state=scene_state or "（尚未采集）")
    return ChatPayload(
        messages=[Message(role=MessageRole.SYSTEM, content=system_text),
                  Message(role=MessageRole.USER,
                          content="请复核这个镜头并调用 submit_review。")],
        tools=[{"type": "function",
                "function": {"name": REVIEW_TOOL_NAME,
                             "description": "提交自我审核结论",
                             "parameters": REVIEW_TOOL_PARAMETERS}}],
        tool_choice=ToolChoice.REQUIRED,
        temperature=temperature,
        purpose=Purpose.REVIEW,
        request_id=request_id or new_request_id(),
    )


def parse_review(reply: ChatReply) -> ReviewVerdict:
    """从回复里取 submit_review 的结论；没有就抛 ValueError。"""
    for call in reply.tool_calls or []:
        if call.function.name != REVIEW_TOOL_NAME:
            continue
        try:
            args = call.function.parsed_arguments()
        except ValueError as exc:
            raise ValueError(f"submit_review 参数不是合法 JSON: {exc}") from exc
        return ReviewVerdict(
            verdict=str(args.get("verdict", "ok")),
            notes=str(args.get("notes", "")),
            issues=[str(item) for item in (args.get("issues") or [])],
            suggestion=str(args.get("suggestion", "")))
    names = [c.function.name for c in reply.tool_calls or []] or ["（无工具调用）"]
    raise ValueError(f"回复中没有 {REVIEW_TOOL_NAME} 调用，实际调用: "
                     f"{', '.join(names)}")
