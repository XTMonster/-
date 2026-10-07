"""LLM 会话消息契约（执行文档 v1.2 §2.5 / §3.4）。

本模块把 §3.4 用文字描述的"会话协议"变成**可执行的不变量**：
assistant 的 ``tool_calls`` 必须保留，且每个 ``role="tool"`` 消息必须携带
与之一一对应的 ``tool_call_id``。v1.0 正是漏掉这一点导致 API 直接返回 400。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from .enums import MessageRole, Purpose, ToolChoice


def new_request_id() -> str:
    """生成请求 ID（§2.5 要求每个请求可被 /v1/cancel 定位）。"""
    return uuid.uuid4().hex


@dataclass
class FunctionCall:
    """工具调用载荷。``arguments`` 是 JSON 字符串（与 OpenAI 一致）。"""

    name: str
    arguments: str = "{}"

    def parsed_arguments(self) -> Dict[str, Any]:
        """解析参数；非法 JSON 抛 ValueError（由调用方转成工具错误回灌 LLM）。"""
        try:
            value = json.loads(self.arguments or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError(f"参数不是合法 JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError("参数必须是 JSON 对象")
        return value

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "arguments": self.arguments}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FunctionCall":
        return cls(name=data["name"], arguments=data.get("arguments", "{}"))


@dataclass
class ToolCall:
    """一次工具调用。``id`` 是 assistant 消息与 tool 消息之间的唯一纽带。"""

    id: str
    function: FunctionCall
    type: str = "function"

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "type": self.type, "function": self.function.to_dict()}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolCall":
        return cls(
            id=data["id"],
            type=data.get("type", "function"),
            function=FunctionCall.from_dict(data["function"]),
        )


@dataclass
class Message:
    """一条会话消息。字段与 OpenAI Chat Completions 对齐。"""

    role: MessageRole
    #: v1.5 §5.5（P6-T1）：vision 请求体要求 ``content`` 是**分片数组**
    #: （``[{"type": "text", ...}, {"type": "image_url", ...}]``）。类型标注与
    #: ``specs/openapi.yaml`` 的 ``Message.content`` 因此放宽为
    #: ``string | array | null``；纯文本路径一个字节都没变（仍是 str）。
    content: Optional[Union[str, List[Dict[str, Any]]]] = None
    tool_calls: Optional[List[ToolCall]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"role": str(self.role)}
        if self.content is not None:
            out["content"] = self.content
        if self.tool_calls:
            out["tool_calls"] = [tc.to_dict() for tc in self.tool_calls]
        if self.tool_call_id is not None:
            out["tool_call_id"] = self.tool_call_id
        if self.name is not None:
            out["name"] = self.name
        return out

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        calls = data.get("tool_calls")
        return cls(
            role=MessageRole(data["role"]),
            content=data.get("content"),
            tool_calls=[ToolCall.from_dict(c) for c in calls] if calls else None,
            tool_call_id=data.get("tool_call_id"),
            name=data.get("name"),
        )


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Usage":
        return cls(
            prompt_tokens=int(data.get("prompt_tokens", 0)),
            completion_tokens=int(data.get("completion_tokens", 0)),
            total_tokens=int(data.get("total_tokens", 0)),
        )


@dataclass
class ChatPayload:
    """``POST /v1/chat`` 的请求体（§2.5）。"""

    messages: List[Message]
    tools: List[Dict[str, Any]] = field(default_factory=list)
    tool_choice: ToolChoice = ToolChoice.AUTO
    temperature: float = 0.7
    purpose: Purpose = Purpose.REACT
    max_tokens: Optional[int] = None
    request_id: str = field(default_factory=new_request_id)
    #: v1.5：**厂商无关的调用元数据**（可选）。当前唯一的使用者是"长分镜表分块出
    #: 计划"：`plan_chunk` 记录这一问覆盖分镜表的哪一段（`index/total/start/stop`
    #: ＋原镜号）。它**不是提示词**——模型看不到，sidecar/直连会照原样忽略；
    #: 它的消费者是离线替身（要按同一规则切片，否则离线链路与真实链路分叉）
    #: 与审计（"这次截断发生在第几段"是排障的第一问）。
    #: 空字典时**不进 wire**，既有调用的报文逐字节不变。
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "request_id": self.request_id,
            "messages": [m.to_dict() for m in self.messages],
            "tools": self.tools,
            "tool_choice": str(self.tool_choice),
            "temperature": self.temperature,
            "purpose": str(self.purpose),
        }
        if self.max_tokens is not None:
            out["max_tokens"] = self.max_tokens
        if self.metadata:
            out["metadata"] = dict(self.metadata)
        return out

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatPayload":
        return cls(
            messages=[Message.from_dict(m) for m in data.get("messages", [])],
            tools=data.get("tools", []),
            tool_choice=ToolChoice(data.get("tool_choice", "auto")),
            temperature=float(data.get("temperature", 0.7)),
            purpose=Purpose(data.get("purpose", "react")),
            max_tokens=data.get("max_tokens"),
            request_id=data.get("request_id", new_request_id()),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass
class ChatReply:
    """``POST /v1/chat`` 的响应体（OpenAI 兼容子集）。"""

    content: Optional[str] = None
    tool_calls: List[ToolCall] = field(default_factory=list)
    #: 思维链（qwen3 这类模型的 ``message.reasoning``）。协议里不是必须的，
    #: 但排查"模型把预算全花在思考上、没来得及调工具"时必须看得到。
    reasoning: Optional[str] = None
    usage: Optional[Usage] = None
    request_id: Optional[str] = None
    model: Optional[str] = None
    finish_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "content": self.content,
            "tool_calls": [tc.to_dict() for tc in self.tool_calls],
        }
        if self.reasoning is not None:
            out["reasoning"] = self.reasoning
        if self.usage is not None:
            out["usage"] = self.usage.to_dict()
        if self.request_id is not None:
            out["request_id"] = self.request_id
        if self.model is not None:
            out["model"] = self.model
        if self.finish_reason is not None:
            out["finish_reason"] = self.finish_reason
        return out

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatReply":
        usage = data.get("usage")
        return cls(
            content=data.get("content"),
            tool_calls=[ToolCall.from_dict(c) for c in data.get("tool_calls", []) or []],
            reasoning=data.get("reasoning"),
            usage=Usage.from_dict(usage) if usage else None,
            request_id=data.get("request_id"),
            model=data.get("model"),
            finish_reason=data.get("finish_reason"),
        )


# --------------------------------------------------------------------------- #
# §3.4 会话构造与校验：让"正确写法"成为唯一的写法
# --------------------------------------------------------------------------- #
def assistant_message(reply: ChatReply) -> Message:
    """把 LLM 回复转成 assistant 消息（**保留 tool_calls**，§3.4 第 1 条）。"""
    return Message(
        role=MessageRole.ASSISTANT,
        content=reply.content,
        tool_calls=list(reply.tool_calls) or None,
    )


def tool_message(tool_call: ToolCall, result: str) -> Message:
    """把工具结果转成 tool 消息（**携带 tool_call_id**，§3.4 第 2 条）。"""
    return Message(
        role=MessageRole.TOOL,
        content=result,
        tool_call_id=tool_call.id,
        name=tool_call.function.name,
    )


def validate_conversation(messages: List[Message]) -> List[str]:
    """校验会话结构是否符合 §3.4；返回问题列表（空列表表示合法）。

    规则：
    1. ``role="tool"`` 的消息必须带 ``tool_call_id``。
    2. 该 ``tool_call_id`` 必须能在**此前**的 assistant 消息的 ``tool_calls`` 中找到。
    3. 每个已声明的 ``tool_call`` 都必须有对应的 tool 应答（否则下一轮会 400）。
    4. assistant 消息不得只有空内容和空 tool_calls。
    """
    problems: List[str] = []
    pending: Dict[str, int] = {}       # tool_call_id -> 声明它的 assistant 下标
    answered: set[str] = set()

    for index, msg in enumerate(messages):
        if msg.role is MessageRole.ASSISTANT:
            declared = [tc.id for tc in (msg.tool_calls or [])]
            if not declared and not (msg.content or "").strip():
                problems.append(f"#{index} assistant 消息既无 content 也无 tool_calls")
            for call_id in declared:
                if call_id in pending:
                    problems.append(f"#{index} tool_call id 重复: {call_id}")
                pending[call_id] = index

        elif msg.role is MessageRole.TOOL:
            if not msg.tool_call_id:
                problems.append(f"#{index} tool 消息缺少 tool_call_id（会导致 API 400）")
                continue
            if msg.tool_call_id not in pending:
                problems.append(
                    f"#{index} tool_call_id={msg.tool_call_id} 找不到对应的 assistant.tool_calls"
                )
                continue
            answered.add(msg.tool_call_id)

    for call_id, index in pending.items():
        if call_id not in answered:
            problems.append(
                f"assistant(#{index}) 的 tool_call {call_id} 尚未应答"
                "（必须先回灌 tool 消息再发起下一次请求）"
            )
    return problems
