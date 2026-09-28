"""§2.5 / §3.4 会话协议契约测试。

重点：把 v1.0 那个"漏掉 assistant.tool_calls / tool_call_id 导致 API 400"的
缺陷固化成回归测试。
"""

from __future__ import annotations

from block_director.contracts.enums import MessageRole, Purpose, ToolChoice
from block_director.contracts.messages import (
    ChatPayload,
    ChatReply,
    FunctionCall,
    Message,
    ToolCall,
    Usage,
    assistant_message,
    tool_message,
    validate_conversation,
)


def _sample_tool_call(call_id: str = "call_1", name: str = "place_character") -> ToolCall:
    return ToolCall(id=call_id,
                    function=FunctionCall(name=name, arguments='{"character_id": "char_001"}'))


def test_tool_call_roundtrip_and_arguments():
    call = _sample_tool_call()
    restored = ToolCall.from_dict(call.to_dict())
    assert restored == call
    assert restored.function.parsed_arguments() == {"character_id": "char_001"}


def test_message_roundtrip_keeps_tool_call_id():
    msg = tool_message(_sample_tool_call(), "已放置角色")
    restored = Message.from_dict(msg.to_dict())
    assert restored.role is MessageRole.TOOL
    assert restored.tool_call_id == "call_1"
    assert restored.name == "place_character"
    assert restored == msg


def test_valid_conversation_has_no_problems():
    call = _sample_tool_call()
    messages = [
        Message(role=MessageRole.SYSTEM, content="system"),
        Message(role=MessageRole.USER, content="剧本"),
        assistant_message(ChatReply(content=None, tool_calls=[call])),
        tool_message(call, "ok"),
    ]
    assert validate_conversation(messages) == []


def test_missing_tool_call_id_is_reported():
    """v1.0 的缺陷：只发 role=tool 的纯文本，不带 tool_call_id。"""
    call = _sample_tool_call()
    messages = [
        assistant_message(ChatReply(content=None, tool_calls=[call])),
        Message(role=MessageRole.TOOL, content="ok"),
    ]
    problems = validate_conversation(messages)
    assert any("tool_call_id" in p for p in problems)


def test_tool_message_without_preceding_assistant_is_reported():
    messages = [Message(role=MessageRole.TOOL, content="ok", tool_call_id="ghost")]
    problems = validate_conversation(messages)
    assert any("找不到对应的 assistant.tool_calls" in p for p in problems)


def test_unanswered_tool_call_is_reported():
    call = _sample_tool_call()
    messages = [assistant_message(ChatReply(content=None, tool_calls=[call]))]
    problems = validate_conversation(messages)
    assert any("尚未应答" in p for p in problems)


def test_empty_assistant_message_is_reported():
    messages = [Message(role=MessageRole.ASSISTANT)]
    problems = validate_conversation(messages)
    assert any("既无 content 也无 tool_calls" in p for p in problems)


def test_chat_payload_serialization():
    call = _sample_tool_call()
    payload = ChatPayload(
        messages=[
            Message(role=MessageRole.SYSTEM, content="sys"),
            assistant_message(ChatReply(content=None, tool_calls=[call])),
            tool_message(call, "ok"),
        ],
        tools=[{"type": "function", "function": {"name": "place_character"}}],
        tool_choice=ToolChoice.REQUIRED,
        temperature=0.2,
        purpose=Purpose.REPAIR,
        max_tokens=1024,
    )
    data = payload.to_dict()
    assert data["request_id"] == payload.request_id
    assert data["tool_choice"] == "required"
    assert data["purpose"] == "repair"
    assert data["max_tokens"] == 1024
    assert data["messages"][1]["tool_calls"][0]["id"] == "call_1"
    assert ChatPayload.from_dict(data).to_dict() == data


def test_chat_reply_roundtrip_with_usage():
    reply = ChatReply(
        content="ok",
        tool_calls=[_sample_tool_call()],
        usage=Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        request_id="req_1",
        model="gpt-4o",
        finish_reason="tool_calls",
    )
    assert ChatReply.from_dict(reply.to_dict()) == reply


def test_request_id_is_unique_by_default():
    assert ChatPayload(messages=[]).request_id != ChatPayload(messages=[]).request_id
