"""§11.3 trace 的完整 prompt / response（含上限与开关）。"""

from __future__ import annotations

import json

from block_director.contracts.messages import (
    ChatPayload,
    ChatReply,
    FunctionCall,
    Message,
    MessageRole,
    ToolCall,
)
from block_director.layer6_audit.audit_logger import (
    DEFAULT_TRACE_MAX_CHARS,
    TRUNCATION_MARK,
    AuditLogger,
    render_messages,
    render_reply,
    truncate_text,
)


def payload(text: str = "写一个三镜头的计划") -> ChatPayload:
    return ChatPayload(messages=[
        Message(role=MessageRole.SYSTEM, content="你是导演"),
        Message(role=MessageRole.USER, content=text)],
        tools=[{"type": "function",
                "function": {"name": "emit_plan", "parameters": {}}}])


def reply(content: str = "", call: bool = True) -> ChatReply:
    calls = ([ToolCall(id="c1", function=FunctionCall(
        name="emit_plan", arguments='{"shots": []}'))] if call else [])
    return ChatReply(content=content or None, tool_calls=calls,
                     request_id="req_1")


def read_trace(tmp_path):
    path = tmp_path / "llm_trace.jsonl"
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


# --------------------------------------------------------------------------- #
# 纯转换
# --------------------------------------------------------------------------- #
def test_render_messages_keeps_roles_and_content():
    rendered = render_messages(payload("你好"))
    assert [item["role"] for item in rendered] == ["system", "user"]
    assert rendered[0]["content"] == "你是导演"
    assert rendered[1]["content"] == "你好"


def test_render_messages_includes_tool_calls():
    from block_director.contracts.messages import assistant_message

    wrapper = type("P", (), {
        "messages": [assistant_message(reply("", call=True))]})()
    messages = render_messages(wrapper)
    assert messages and "emit_plan" in messages[0]["tool_calls"]


def test_render_reply_carries_content_and_calls():
    rendered = render_reply(reply("好的"))
    assert rendered["content"] == "好的"
    assert rendered["tool_calls"][0]["name"] == "emit_plan"
    assert "shots" in rendered["tool_calls"][0]["arguments"]


def test_render_helpers_tolerate_missing_values():
    assert render_messages(None) == []
    assert render_reply(None) == {}
    assert render_reply(ChatReply())["content"] == ""


def test_truncate_respects_the_limit_and_marks_it():
    text = "x" * 50
    cut, did = truncate_text(text, 10)
    assert did and cut.startswith("x" * 10) and cut.endswith(TRUNCATION_MARK)
    same, did_not = truncate_text(text, 50)
    assert same == text and not did_not
    unlimited, _ = truncate_text(text, 0)
    assert unlimited == text


# --------------------------------------------------------------------------- #
# 落盘
# --------------------------------------------------------------------------- #
def test_trace_records_the_full_prompt_and_response(tmp_path):
    audit = AuditLogger(directory=tmp_path)
    audit.log_llm("plan", reply("这是回复"), 1.0, "req_1",
                  payload=payload("写一个三镜头的计划"))
    record = read_trace(tmp_path)[0]
    assert record["purpose"] == "plan"
    assert [item["content"] for item in record["prompt"]] == ["你是导演",
                                                             "写一个三镜头的计划"]
    assert record["response"]["content"] == "这是回复"
    assert record["response"]["tool_calls"][0]["name"] == "emit_plan"
    assert record["truncated"] is False
    # 元数据保留，旧读者不受影响
    assert record["tool_calls"] == ["emit_plan"] and record["error"] == ""


def test_trace_is_truncated_at_the_configured_limit(tmp_path):
    audit = AuditLogger(directory=tmp_path, trace_max_chars=20)
    audit.log_llm("plan", reply("回" * 100), 1.0, "req_1",
                  payload=payload("问" * 100))
    record = read_trace(tmp_path)[0]
    assert record["truncated"] is True
    assert len(record["prompt"][1]["content"]) == 20 + len(TRUNCATION_MARK)
    assert len(record["response"]["content"]) == 20 + len(TRUNCATION_MARK)


def test_prompts_can_be_switched_off(tmp_path):
    audit = AuditLogger(directory=tmp_path, trace_prompts=False)
    audit.log_llm("plan", reply("这是回复"), 1.0, "req_1", payload=payload())
    record = read_trace(tmp_path)[0]
    assert "prompt" not in record and "response" not in record
    assert record["tool_calls"] == ["emit_plan"]      # 元数据仍在


def test_failed_calls_still_record_their_prompt(tmp_path):
    audit = AuditLogger(directory=tmp_path)
    audit.log_llm("repair", None, 0.5, "req_9", error="TimeoutError",
                  payload=payload("修一下"))
    record = read_trace(tmp_path)[0]
    assert record["error"] == "TimeoutError"
    assert record["prompt"][1]["content"] == "修一下"
    assert record["response"] == {"content": "", "tool_calls": []}


def test_default_limit_is_documented():
    assert DEFAULT_TRACE_MAX_CHARS == 8000
