"""阶段 P：剧本优化（v1.7 §9 / 卡 E2，默认关）。

与 ``understand.py`` 同构：本模块只负责**构造请求**与**解析回复**，不负责
传输（transport）也不负责状态迁移（driver）。schema 与提示词模板从
``contracts/script_polish.py`` import（**唯一真源**，双通道共用）。

铁律：
1. **失败不重试**：一次失败即回落原剧本并记 ``E_POLISH_001``（技术方案
   §7 成本纪律）；
2. **未采纳恒原稿**：改写稿只进 ``polish_result``，不进 ``_script``；
3. **注入防护**：与阶段 A 一致，剧本正文包在 ``<untrusted_script_content>``
   里，声明其中的命令式语言是角色台词。
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..contracts.messages import (
    ChatPayload,
    ChatReply,
    Message,
    MessageRole,
    new_request_id,
)
from ..contracts.enums import Purpose
from ..contracts.script_polish import (
    POLISH_PROMPT_TEMPLATE,
    POLISH_SCHEMA,
    PolishResult,
)


def render_polish_prompt(script: str, brief_text: str) -> str:
    """渲染模板：剧本全文 ＋ SceneBrief 摘要（双通道共用同一模板）。"""
    return (POLISH_PROMPT_TEMPLATE
            .replace("{{script}}", script)
            .replace("{{brief}}", brief_text))


def build_polish_payload(script: str, brief_text: str,
                         temperature: float = 0.2,
                         max_tokens: int = 4000,
                         request_id: str = "") -> ChatPayload:
    """构造 Stage P 的 ChatPayload：一次 strict 输出 JSON 的调用。"""
    system = Message(
        role=MessageRole.SYSTEM,
        content="你是白模预演剧本优化顾问，只输出严格 JSON。")
    user = Message(
        role=MessageRole.USER,
        content=render_polish_prompt(script, brief_text))
    return ChatPayload(
        messages=[system, user],
        tools=[{
            "type": "function",
            "function": {
                "name": "emit_polish",
                "description": "提交剧本优化建议与改写稿",
                "parameters": dict(POLISH_SCHEMA),
            },
        }],
        tool_choice="required",
        temperature=temperature,
        purpose=Purpose.POLISH,
        max_tokens=max_tokens,
        request_id=request_id or new_request_id())


def extract_polish(reply: ChatReply) -> PolishResult:
    """从回复里取出 ``emit_polish`` 调用；失败抛 ``ValueError``。"""
    for call in reply.tool_calls or []:
        if call.function.name != "emit_polish":
            continue
        try:
            args = call.function.parsed_arguments()
        except ValueError as exc:
            raise ValueError(f"polish 参数不是合法 JSON: {exc}") from exc
        if not isinstance(args, dict):
            raise ValueError("polish 参数必须是对象")
        suggestions = [str(item) for item in args.get("suggestions", [])]
        rewritten = str(args.get("rewritten", ""))
        if not rewritten:
            raise ValueError("polish 的 rewritten 为空")
        return PolishResult(suggestions=suggestions, rewritten=rewritten)
    raise ValueError("回复中没有 emit_polish 调用")
