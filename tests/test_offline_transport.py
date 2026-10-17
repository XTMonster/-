"""离线替身传输的阶段契约（回归：D1 离线 ReAct 死循环）。"""

from __future__ import annotations

import json

from block_director.contracts.enums import MessageRole, Purpose, ToolChoice
from block_director.contracts.messages import ChatPayload, Message
from block_director.contracts.tools import FINISH_SHOT, PLAN_TOOL
from block_director.layer5_orchestrator.offline import OfflineTransport


def _react_payload() -> ChatPayload:
    return ChatPayload(
        messages=[Message(role=MessageRole.USER, content="请精修")],
        tools=[],
        tool_choice=ToolChoice.AUTO,
        purpose=Purpose.REACT,
        request_id="react-test",
    )


def test_offline_react_returns_finish_shot_without_emit_plan():
    transport = OfflineTransport()
    reply = transport.chat(_react_payload())

    assert reply.tool_calls, "REACT 阶段必须给出一个工具调用，否则驱动无法收敛"
    names = [call.function.name for call in reply.tool_calls]
    assert FINISH_SHOT in names
    assert PLAN_TOOL not in names, (
        "REACT 阶段工具集不含 emit_plan，离线替身不能回兜底计划")


def test_offline_react_finish_shot_arguments_validate():
    """finish_shot 的参数必须是合法 JSON 且只含可选 summary。"""
    transport = OfflineTransport()
    reply = transport.chat(_react_payload())

    call = next(c for c in reply.tool_calls
                if c.function.name == FINISH_SHOT)
    args = json.loads(call.function.arguments)
    assert isinstance(args, dict)
    assert set(args) <= {"summary"}


def test_offline_purpose_dispatches_by_stage():
    """各阶段的离线回答必须落在该阶段的工具上（防再犯兜底错配）。"""
    transport = OfflineTransport()

    review = transport.chat(ChatPayload(
        messages=[Message(role=MessageRole.USER, content="审核")],
        purpose=Purpose.REVIEW, request_id="review-test"))
    assert review.tool_calls[0].function.name == "submit_review"

    react = transport.chat(_react_payload())
    assert react.tool_calls[0].function.name == FINISH_SHOT

    edited = transport.chat(ChatPayload(
        messages=[Message(role=MessageRole.USER, content="该镜草案")],
        purpose=Purpose.EDITOR, request_id="editor-test"))
    assert edited.tool_calls[0].function.name == "emit_shot_draft"

    planned = transport.chat(ChatPayload(
        messages=[Message(role=MessageRole.USER, content="读剧本出计划")],
        purpose=Purpose.PLAN, request_id="plan-test"))
    assert planned.tool_calls[0].function.name == PLAN_TOOL
