"""被 `max_tokens` 从中间切断的**工具调用**必须报成"截断"，不是"JSON 写错了"。

现场（2026-10-03 15:5x，长剧本真实运行）：`state=ERROR`、0 镜，审计里只有

    plan_invalid: 参数不是合法 JSON: Unterminated string starting at: line 1 column 16664

两次重试都是同一句——因为它**不是**模型手滑，是这一次请求的**输出预算不够**：
64 镜的 `emit_plan` 参数约 16.5 KB，正好压在 DeepSeek 的输出上限上。旧实现只在
"`finish_reason=length` **且没有任何工具调用**"时报截断（那条是为思维模型写的），
而这一次 `tool_calls` 非空、参数只是被切断——于是真实原因被埋在"JSON 非法"里，
同一个预算白重试两次然后整跑失败。判据：**两者同时成立**才算截断（只凭
`finish_reason=length` 会把"模型多说了几句但计划完整"误报成截断）。
"""

from __future__ import annotations

import pytest

from block_director.contracts.errors import TransportError
from block_director.contracts.transport import parse_chat_response


def _body(finish_reason: str, arguments: str, *, reasoning: str = "") -> dict:
    message = {"content": None,
               "tool_calls": [{"id": "call_1", "type": "function",
                               "function": {"name": "emit_plan",
                                            "arguments": arguments}}]}
    if reasoning:
        message["reasoning"] = reasoning
    return {"model": "deepseek-chat",
            "choices": [{"finish_reason": finish_reason, "message": message}]}


def test_a_truncated_tool_call_is_reported_as_truncation():
    body = _body("length", '{"shots":[{"shot_id":"shot_001","intent":"推进"')
    with pytest.raises(TransportError) as info:
        parse_chat_response(body)
    text = str(info.value)
    assert "截断" in text and "finish_reason=length" in text
    #: 必须给出**可操作**的下一条：提高预算或换输出上限更大的模型。
    assert "max_tokens" in text
    assert "emit_plan" in text
    #: 不许退回成"模型写错了 JSON"那种读法。
    assert "不是合法 JSON" not in text


def test_a_complete_plan_with_a_long_answer_is_not_a_truncation():
    """反向对照：`finish_reason=length` 但工具调用的参数是完整 JSON ⇒ 不是截断。"""
    reply = parse_chat_response(
        _body("length", '{"shots":[{"shot_id":"shot_001"}]}'))
    assert reply.finish_reason == "length"
    assert reply.tool_calls and reply.tool_calls[0].function.name == "emit_plan"


def test_a_truncated_reply_without_tool_calls_still_reports_truncation():
    """思维模型那一路（content 为空、无工具调用）的既有判据不许被这次改动弄丢。"""
    body = {"model": "qwen3", "choices": [{"finish_reason": "length",
                                           "message": {"content": "",
                                                       "reasoning": "想了很久"}}]}
    with pytest.raises(TransportError) as info:
        parse_chat_response(body)
    assert "截断" in str(info.value)
