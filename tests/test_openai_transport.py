"""直连（OpenAI 兼容）传输的对抗性测试。

两条路线都测：单元级注入假 opener（精确断言请求体与错误映射），
以及起一个真的本地 HTTP 服务端跑一次完整往返。
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from block_director.contracts.enums import Capability, ErrorCode, MessageRole, Purpose, ToolChoice
from block_director.contracts.errors import TransportError
from block_director.contracts.messages import (
    ChatPayload,
    ChatReply,
    FunctionCall,
    Message,
    ToolCall,
    assistant_message,
    tool_message,
)
from block_director.contracts.transport import (
    LLMTransport,
    OpenAICompatibleTransport,
    build_chat_body,
    parse_chat_response,
)

from test_transport import make_opener


def _payload() -> ChatPayload:
    call = ToolCall(id="call_1",
                    function=FunctionCall(name="emit_plan", arguments='{"shots":[]}'))
    return ChatPayload(
        messages=[
            Message(role=MessageRole.SYSTEM, content="sys"),
            Message(role=MessageRole.USER, content="剧本"),
            assistant_message(ChatReply(content=None, tool_calls=[call])),
            tool_message(call, "ok"),
        ],
        tools=[{"type": "function", "function": {"name": "emit_plan"}}],
        tool_choice=ToolChoice.REQUIRED, temperature=0.2,
        purpose=Purpose.PLAN, max_tokens=1024,
    )


def _reply_body() -> str:
    return json.dumps({
        "model": "gpt-4o-2026-01-01",
        "choices": [{
            "finish_reason": "tool_calls",
            "message": {"content": None, "tool_calls": [{
                "id": "call_9", "type": "function",
                "function": {"name": "emit_plan",
                             "arguments": '{"shots":[{"shot_id":"shot_001"}]}'}}]},
        }],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
    })


# --------------------------------------------------------------------------- #
# 请求体构造
# --------------------------------------------------------------------------- #
def test_assistant_tool_call_message_keeps_explicit_null_content():
    body = build_chat_body(_payload(), "gpt-4o")
    assistant = body["messages"][2]
    assert assistant["role"] == "assistant"
    assert "content" in assistant and assistant["content"] is None
    assert assistant["tool_calls"][0]["id"] == "call_1"


def test_tool_message_carries_tool_call_id():
    body = build_chat_body(_payload(), "gpt-4o")
    assert body["messages"][3]["tool_call_id"] == "call_1"


def test_body_carries_model_tools_and_choices():
    body = build_chat_body(_payload(), "deepseek-chat")
    assert body["model"] == "deepseek-chat"
    assert body["tool_choice"] == "required"
    assert body["temperature"] == 0.2
    assert body["max_tokens"] == 1024
    assert body["tools"][0]["function"]["name"] == "emit_plan"


def test_tools_and_max_tokens_can_be_omitted():
    payload = ChatPayload(messages=[Message(role=MessageRole.USER, content="hi")])
    body = build_chat_body(payload, "m")
    assert "tools" not in body and "max_tokens" not in body
    assert body["tool_choice"] == "auto"


# --------------------------------------------------------------------------- #
# 响应解析
# --------------------------------------------------------------------------- #
def test_parse_reply_with_tool_calls():
    reply = parse_chat_response(json.loads(_reply_body()))
    assert reply.content is None
    assert reply.tool_calls[0].id == "call_9"
    assert reply.tool_calls[0].function.name == "emit_plan"
    assert reply.usage.total_tokens == 18
    assert reply.finish_reason == "tool_calls"
    assert reply.model.startswith("gpt-4o")


@pytest.mark.parametrize("bad", [{}, {"choices": []}, {"choices": [None]}])
def test_missing_choices_is_reported(bad):
    with pytest.raises(TransportError) as excinfo:
        parse_chat_response(bad)
    assert excinfo.value.code is ErrorCode.LLM_002


def test_parse_reply_without_usage_or_content():
    reply = parse_chat_response({"choices": [{"message": {"content": "ok"}}]})
    assert reply.content == "ok" and reply.usage is None
    assert reply.tool_calls == []


# --------------------------------------------------------------------------- #
# 真实 HTTP 往返
# --------------------------------------------------------------------------- #
class _Server:
    def __init__(self, responder):
        self.responder = responder
        self.requests = []

    def __enter__(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                outer.requests.append({"path": self.path, "body": body,
                                       "headers": dict(self.headers)})
                status, text = outer.responder(self.path, body)
                raw = text.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


def test_chat_round_trip_over_real_http():
    with _Server(lambda path, body: (200, _reply_body())) as server:
        transport = OpenAICompatibleTransport(
            base_url=f"http://127.0.0.1:{server.port}/v1", api_key="sk-test",
            model="gpt-4o", timeout=5.0)
        reply = transport.chat(_payload(), timeout=5.0)

    sent = server.requests[0]
    assert sent["path"] == "/v1/chat/completions"
    assert sent["headers"]["Authorization"] == "Bearer sk-test"
    assert sent["body"]["model"] == "gpt-4o"
    assert sent["body"]["messages"][2]["content"] is None
    assert reply.tool_calls[0].function.name == "emit_plan"


def test_no_auth_header_without_key():
    with _Server(lambda path, body: (200, _reply_body())) as server:
        OpenAICompatibleTransport(
            base_url=f"http://127.0.0.1:{server.port}/v1", api_key="").chat(_payload())
    assert "Authorization" not in server.requests[0]["headers"]


def test_embed_parses_vectors():
    body = json.dumps({"data": [{"embedding": [0.1, 0.2]},
                                {"embedding": [0.3, 0.4]}]})
    with _Server(lambda path, payload: (200, body)) as server:
        vectors = OpenAICompatibleTransport(
            base_url=f"http://127.0.0.1:{server.port}/v1").embed(["a", "b"])
    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert server.requests[0]["path"] == "/v1/embeddings"


# --------------------------------------------------------------------------- #
# 错误映射
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("status, code", [
    (400, ErrorCode.LLM_002), (429, ErrorCode.LLM_002),
    (500, ErrorCode.LLM_001), (503, ErrorCode.LLM_001),
])
def test_http_errors_map_to_documented_codes(status, code):
    with _Server(lambda path, body: (status, "boom")) as server:
        transport = OpenAICompatibleTransport(
            base_url=f"http://127.0.0.1:{server.port}/v1")
        with pytest.raises(TransportError) as excinfo:
            transport.chat(_payload())
    assert excinfo.value.code is code
    assert excinfo.value.http_status == status


def test_malformed_json_maps_to_llm_002():
    with _Server(lambda path, body: (200, "not-json")) as server:
        transport = OpenAICompatibleTransport(
            base_url=f"http://127.0.0.1:{server.port}/v1")
        with pytest.raises(TransportError) as excinfo:
            transport.chat(_payload())
    assert excinfo.value.code is ErrorCode.LLM_002


def test_retrieve_is_not_supported_on_direct_endpoint():
    with pytest.raises(TransportError) as excinfo:
        OpenAICompatibleTransport().retrieve("轴线")
    assert excinfo.value.code is ErrorCode.LLM_002


def test_health_advertises_llm_capability():
    status = OpenAICompatibleTransport(base_url="http://x/v1").health()
    assert status.ok and status.has(Capability.LLM)


def test_satisfies_transport_protocol():
    assert isinstance(OpenAICompatibleTransport(), LLMTransport)


def test_opener_injection_still_works_for_unit_tests():
    """不依赖网络：注入假 opener 也能完整走一遍。"""
    opener = make_opener({("POST", "/v1/chat/completions"): (200, _reply_body())})
    reply = OpenAICompatibleTransport(base_url="http://fake/v1",
                                      opener=opener).chat(_payload())
    assert reply.tool_calls[0].id == "call_9"
    assert opener.calls[0]["path"] == "/v1/chat/completions"
