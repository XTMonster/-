"""§2.5 传输层契约测试：线协议编解码、错误映射、选择策略。"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple
from urllib.parse import urlsplit

import pytest

from block_director.contracts.enums import Capability, ErrorCode, TransportMode
from block_director.contracts.errors import TransportError, error_for_http_status
from block_director.contracts.health import HealthStatus
from block_director.contracts.knowledge import Card
from block_director.contracts.messages import ChatPayload, ChatReply, Message
from block_director.contracts.enums import MessageRole
from block_director.contracts.transport import (
    DirectTransport,
    LLMTransport,
    SidecarTransport,
    select_transport,
)


def make_opener(routes: Dict[Tuple[str, str], Any]):
    """构造假 HTTP 打开器；routes 的值为 (status, body) 或异常实例。"""
    calls: List[Dict[str, Any]] = []

    def opener(method: str, url: str, headers: Dict[str, str],
               body: Any, timeout: float):
        path = urlsplit(url).path
        calls.append({"method": method, "path": path, "headers": headers,
                      "body": body, "timeout": timeout})
        value = routes.get((method, path))
        if value is None:
            return 404, "{}"
        if isinstance(value, Exception):
            raise value
        return value

    opener.calls = calls        # type: ignore[attr-defined]
    return opener


def _chat_reply_body() -> str:
    return json.dumps({
        "content": None,
        "tool_calls": [{"id": "call_1", "type": "function",
                        "function": {"name": "place_character",
                                     "arguments": '{"character_id": "char_001"}'}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
    })


def _health_body() -> str:
    return json.dumps({"status": "ok", "version": "1.2.0",
                       "capabilities": ["llm", "bm25", "unknown_cap"]})


# --------------------------------------------------------------------------- #
# 编解码
# --------------------------------------------------------------------------- #
def test_health_parses_capabilities_and_ignores_unknown():
    opener = make_opener({("GET", "/health"): (200, _health_body())})
    transport = SidecarTransport(opener=opener)
    status = transport.health()
    assert status.ok
    assert status.has(Capability.LLM) and status.has(Capability.BM25)
    assert not status.has(Capability.VECTOR)


def test_chat_roundtrip_over_http():
    opener = make_opener({("POST", "/v1/chat"): (200, _chat_reply_body())})
    transport = SidecarTransport(opener=opener)
    payload = ChatPayload(messages=[Message(role=MessageRole.SYSTEM, content="s")])
    reply = transport.chat(payload, timeout=7.0)
    assert isinstance(reply, ChatReply)
    assert reply.tool_calls[0].function.name == "place_character"
    assert reply.usage is not None and reply.usage.total_tokens == 3

    sent = json.loads(opener.calls[0]["body"].decode("utf-8"))
    assert sent["request_id"] == payload.request_id
    assert opener.calls[0]["timeout"] == 7.0


def test_retrieve_roundtrip():
    body = json.dumps({"cards": [Card(id="c1", domain="d", title="t",
                                      content="x").to_dict()]})
    opener = make_opener({("POST", "/v1/retrieve"): (200, body)})
    cards = SidecarTransport(opener=opener).retrieve("越轴", "axis_theory", 3)
    assert cards and cards[0].id == "c1"


def test_embed_roundtrip_infers_dim():
    body = json.dumps({"vectors": [[0.1, 0.2, 0.3]]})
    opener = make_opener({("POST", "/v1/embed"): (200, body)})
    vectors = SidecarTransport(opener=opener).embed(["a"])
    assert vectors == [[0.1, 0.2, 0.3]]


def test_token_adds_authorization_header():
    opener = make_opener({("GET", "/health"): (200, _health_body())})
    SidecarTransport(token="secret", opener=opener).health()
    assert opener.calls[0]["headers"]["Authorization"] == "Bearer secret"


# --------------------------------------------------------------------------- #
# 错误映射（§2.5）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("status, code", [
    (400, ErrorCode.LLM_002),
    (422, ErrorCode.LLM_002),
    (500, ErrorCode.LLM_001),
    (504, ErrorCode.LLM_001),
])
def test_error_for_http_status(status, code):
    assert error_for_http_status(status) is code


def test_http_error_raises_transport_error_with_code():
    opener = make_opener({("POST", "/v1/chat"): (500, "boom")})
    with pytest.raises(TransportError) as excinfo:
        SidecarTransport(opener=opener).chat(ChatPayload(messages=[]))
    assert excinfo.value.code is ErrorCode.LLM_001
    assert excinfo.value.http_status == 500
    assert "boom" in excinfo.value.body


def test_invalid_json_response_maps_to_llm_002():
    opener = make_opener({("POST", "/v1/chat"): (200, "not-json")})
    with pytest.raises(TransportError) as excinfo:
        SidecarTransport(opener=opener).chat(ChatPayload(messages=[]))
    assert excinfo.value.code is ErrorCode.LLM_002


def test_probe_returns_none_on_failure():
    opener = make_opener({("GET", "/health"): TransportError(ErrorCode.LLM_001, "down")})
    assert SidecarTransport(opener=opener).probe() is None


def test_cancel_swallows_errors():
    opener = make_opener({("POST", "/v1/cancel"): (500, "boom")})
    SidecarTransport(opener=opener).cancel("r1")   # 不应抛异常


# --------------------------------------------------------------------------- #
# 选择策略（§2.5）
# --------------------------------------------------------------------------- #
def _direct() -> DirectTransport:
    return DirectTransport(chat_fn=lambda payload, timeout: ChatReply(content="local"))


def test_auto_prefers_sidecar_when_healthy():
    sidecar = SidecarTransport(opener=make_opener(
        {("GET", "/health"): (200, _health_body())}))
    selection = select_transport(TransportMode.AUTO, direct=_direct(), sidecar=sidecar)
    assert selection.mode is TransportMode.SIDECAR
    assert selection.health is not None and selection.health.ok


def test_auto_falls_back_to_direct_when_unreachable():
    sidecar = SidecarTransport(opener=make_opener(
        {("GET", "/health"): TransportError(ErrorCode.LLM_001, "down")}))
    selection = select_transport(TransportMode.AUTO, direct=_direct(), sidecar=sidecar)
    assert selection.mode is TransportMode.DIRECT
    assert selection.warnings


def test_direct_mode_never_probes_sidecar():
    opener = make_opener({})
    select_transport(TransportMode.DIRECT, direct=_direct(),
                     sidecar=SidecarTransport(opener=opener))
    assert opener.calls == []


def test_explicit_sidecar_falls_back_with_warning():
    sidecar = SidecarTransport(opener=make_opener({}))
    selection = select_transport(TransportMode.SIDECAR, direct=_direct(), sidecar=sidecar)
    assert selection.mode is TransportMode.DIRECT
    assert any("回退" in w for w in selection.warnings)


def test_no_transport_available_raises():
    with pytest.raises(TransportError):
        select_transport(TransportMode.DIRECT, direct=None)


def test_python_implementations_satisfy_protocol():
    assert isinstance(SidecarTransport(), LLMTransport)
    assert isinstance(_direct(), LLMTransport)


def test_direct_transport_reports_health_without_network():
    status = _direct().health()
    assert isinstance(status, HealthStatus) and status.ok
