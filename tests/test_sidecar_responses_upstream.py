"""sidecar 的 OpenAI Responses 上游适配（goaichat 中转 / kimi-k3）。

goaichat 只提供 ``/responses``、不提供 ``/chat/completions``（实测上游 401），
所以 sidecar 需要把插件的 ChatPayload 转成 Responses 请求体，再把 Responses
的 ``output[]`` 转回 ``ChatReply``。本测试钉住两种形状转换 + 一条端到端链路
（mock Responses 上游 → sidecar → 插件 SidecarTransport）。
"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]


def _load_sidecar():
    spec = importlib.util.spec_from_file_location(
        "bd_sidecar_responses_under_test",
        ROOT / "tools" / "sidecar_server.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sidecar = _load_sidecar()


def _config(tmp_path: Path, upstream: str = "http://127.0.0.1:1"):
    args = sidecar.parse_args(
        ["--upstream-kind", "responses",
         "--upstream", upstream,
         "--model", "kimi-k3",
         "--runs-dir", str(tmp_path / "runs"),
         "--knowledge-dir", str(tmp_path / "knowledge"),
         "--cases-backend", "off"])
    return sidecar.SidecarConfig(args)


def _payload() -> Dict[str, Any]:
    """带完整多轮形状的 ChatPayload（含历史 tool_calls 与 tool 应答）。"""
    return {
        "messages": [
            {"role": "system", "content": "你是导演"},
            {"role": "user", "content": "拍开场"},
            {"role": "assistant", "content": "好的",
             "tool_calls": [
                 {"id": "call_1", "type": "function",
                  "function": {"name": "move_character",
                               "arguments": '{"id":"a"}'}}]},
            {"role": "tool", "tool_call_id": "call_1", "name": "move_character",
             "content": '{"ok": true}'},
            {"role": "user", "content": "继续"},
        ],
        "tools": [
            {"type": "function",
             "function": {"name": "move_character",
                          "description": "移动角色",
                          "parameters": {"type": "object",
                                         "properties": {"id": {"type": "string"}}}}},
        ],
        "tool_choice": "required",
        "temperature": 0.0,
        "max_tokens": 4096,
        "purpose": "plan",
    }


def test_responses_body_shape(tmp_path):
    cfg = _config(tmp_path)
    body = sidecar._responses_body(cfg, _payload())
    assert body["model"] == "kimi-k3"
    assert body["max_output_tokens"] == 4096
    assert body["tool_choice"] == "required"
    # input 是平铺 item 序列：system → user → assistant 文本 + function_call
    # → function_call_output → user
    kinds = [item.get("type") or item.get("role") for item in body["input"]]
    assert kinds == ["system", "user", "assistant", "function_call",
                     "function_call_output", "user"]
    fc = body["input"][3]
    assert fc["call_id"] == "call_1"
    assert fc["name"] == "move_character"
    assert json.loads(fc["arguments"]) == {"id": "a"}
    out = body["input"][4]
    assert out["type"] == "function_call_output"
    assert out["call_id"] == "call_1"
    assert out["output"] == '{"ok": true}'
    # 工具声明拍平
    tool = body["tools"][0]
    assert tool == {"type": "function", "name": "move_character",
                    "description": "移动角色",
                    "parameters": {"type": "object",
                                   "properties": {"id": {"type": "string"}}}}


def test_responses_body_vision_content(tmp_path):
    cfg = _config(tmp_path)
    payload = {
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": "看这张图"},
                {"type": "image_url",
                 "image_url": {"url": "data:image/png;base64,AAAA"}},
            ],
        }],
    }
    body = sidecar._responses_body(cfg, payload)
    content = body["input"][0]["content"]
    assert content[0] == {"type": "input_text", "text": "看这张图"}
    assert content[1] == {"type": "input_image",
                          "image_url": "data:image/png;base64,AAAA"}


def test_responses_reply(tmp_path):
    data = {
        "id": "resp_1", "object": "response", "model": "kimi-k3",
        "status": "completed",
        "output": [
            {"type": "message", "role": "assistant",
             "content": [
                 {"type": "reasoning", "text": "思考中"},
                 {"type": "output_text", "text": "我调工具了"},
             ]},
            {"type": "function_call", "id": "fc_1", "call_id": "fc_1",
             "name": "move_camera", "arguments": '{"dx":1}'},
        ],
        "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
    }
    reply = sidecar._responses_reply(data)
    assert reply.content == "我调工具了"
    assert reply.reasoning == "思考中"
    assert reply.finish_reason == "tool_calls"
    assert len(reply.tool_calls) == 1
    assert reply.tool_calls[0].function.name == "move_camera"
    assert reply.tool_calls[0].function.arguments == '{"dx":1}'
    assert reply.model == "kimi-k3"
    assert reply.usage.prompt_tokens == 10
    assert reply.usage.completion_tokens == 20


def test_responses_reply_incomplete(tmp_path):
    data = {"id": "r", "model": "m", "status": "incomplete", "output": [],
            "usage": {"input_tokens": 1, "output_tokens": 4096,
                      "total_tokens": 4097}}
    reply = sidecar._responses_reply(data)
    assert reply.finish_reason == "length"


def test_end_to_end_via_sidecar_http(tmp_path):
    """mock Responses 上游 → sidecar /v1/chat → SidecarTransport.chat。"""
    captured: Dict[str, Any] = {}

    class ResponsesHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            captured.update(body)
            payload = {
                "id": "resp_mock", "object": "response", "model": "kimi-k3",
                "status": "completed",
                "output": [
                    {"type": "message", "role": "assistant",
                     "content": [{"type": "output_text", "text": "已建镜头"}]},
                    {"type": "function_call", "id": "fc_9", "call_id": "fc_9",
                     "name": "create_camera", "arguments": '{"shot":"s1"}'},
                ],
                "usage": {"input_tokens": 5, "output_tokens": 7,
                          "total_tokens": 12},
            }
            encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, *args):
            pass

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), ResponsesHandler)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    upstream_url = f"http://127.0.0.1:{upstream.server_address[1]}"

    try:
        cfg = _config(tmp_path, upstream=upstream_url)
        httpd = ThreadingHTTPServer(
            ("127.0.0.1", 0), sidecar.make_handler(cfg))
        sidecar_thread = threading.Thread(target=httpd.serve_forever,
                                          daemon=True)
        sidecar_thread.start()
        sidecar_url = f"http://127.0.0.1:{httpd.server_address[1]}"

        from block_director.contracts.messages import ChatPayload
        from block_director.contracts.transport import SidecarTransport

        transport = SidecarTransport(base_url=sidecar_url, timeout=20)
        payload = ChatPayload.from_dict(_payload())
        reply = transport.chat(payload)
        assert reply.content == "已建镜头"
        assert len(reply.tool_calls) == 1
        assert reply.tool_calls[0].function.name == "create_camera"
        assert reply.usage.completion_tokens == 7
        # 上游收到的就是 Responses 形状
        assert captured["model"] == "kimi-k3"
        assert captured["tools"][0]["type"] == "function"
        assert captured["tools"][0]["name"] == "move_character"
        assert captured["max_output_tokens"] == 4096
        kinds = [item.get("type") or item.get("role")
                 for item in captured["input"]]
        assert kinds == ["system", "user", "assistant", "function_call",
                         "function_call_output", "user"]
    finally:
        httpd.shutdown()
        upstream.shutdown()
