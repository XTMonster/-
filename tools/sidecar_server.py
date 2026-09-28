"""sidecar 参考实现（执行文档 v1.2 §2.5）。

插件侧早就有 `SidecarTransport` 与 `specs/openapi.yaml`，"sidecar 是可选的一等
公民"只差这一半：**没有人提供这个服务**。本文件用标准库把它补齐——零依赖、
只监听回环地址，并承担插件不该承担的两件事：

1. **供应商差异**：本地模型（Ollama）需要 `num_ctx` 与 `think: false` 这类
   原生参数；OpenAI 兼容层表达不了它们。实测：qwen3-vl:30b 的默认 `num_ctx`
   是 4096，思维链会把预算全部吃掉，`finish_reason` 直接是 `length`——把它当
"模型不听话"会误导排查方向。
2. **检索**：BM25 语料本来就在插件侧，sidecar 只是把它暴露成 `/v1/retrieve`，
   让"向量检索必须由 sidecar 提供"（§6.1）有落点。

用法：
  python tools/sidecar_server.py --upstream http://127.0.0.1:11434 \\
      --model qwen3-vl:30b --num-ctx 32768 --think off --max-tokens 8192
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.contracts.enums import Capability  # noqa: E402
from block_director.contracts.errors import (  # noqa: E402
    ErrorCode,
    TransportError,
)
from block_director.contracts.knowledge import Card  # noqa: E402
from block_director.contracts.messages import (  # noqa: E402
    ChatReply,
    FunctionCall,
    ToolCall,
)
from block_director.knowledge import default_retriever  # noqa: E402

CONTRACT_VERSION = "1.2.0"
LOOPBACK = "127.0.0.1"


class SidecarConfig:
    def __init__(self, args) -> None:
        self.upstream = args.upstream.rstrip("/")
        self.model = args.model
        self.kind = args.upstream_kind
        self.num_ctx = args.num_ctx
        self.think = args.think
        self.max_tokens = args.max_tokens
        self.temperature = args.temperature
        self.token = args.token
        self.timeout = args.timeout
        self.capabilities = [Capability.LLM, Capability.BM25]
        if self.kind == "ollama":
            # Ollama 的原生接口是 {host}/api/chat，OpenAI 兼容层在 {host}/v1
            if self.upstream.endswith("/v1"):
                self.upstream = self.upstream[:-3]


def detect_kind(upstream: str) -> str:
    return "ollama" if (":11434" in upstream or "/api" in upstream) else "openai"


# --------------------------------------------------------------------------- #
# 上游调用
# --------------------------------------------------------------------------- #
def _post_json(url: str, body: Dict[str, Any], timeout: float,
               headers: Optional[Dict[str, str]] = None
               ) -> Tuple[int, str]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def _ollama_body(config: "SidecarConfig", payload: Dict[str, Any]
                 ) -> Dict[str, Any]:
    options: Dict[str, Any] = {"num_ctx": config.num_ctx,
                               "temperature": payload.get("temperature",
                                                          config.temperature)}
    limit = payload.get("max_tokens") or config.max_tokens
    if limit:
        options["num_predict"] = int(limit)
    body: Dict[str, Any] = {"model": config.model,
                            "messages": payload.get("messages", []),
                            "stream": False, "options": options}
    if payload.get("tools"):
        body["tools"] = payload["tools"]
    if config.think == "off":
        body["think"] = False
    elif config.think == "on":
        body["think"] = True
    return body


def _ollama_reply(data: Dict[str, Any]) -> ChatReply:
    """Ollama 原生响应 → 我们的 ChatReply。

    注意两点差异：tool_calls 的 ``arguments`` 在原生接口里是**对象**（不是
    JSON 字符串），且思维链字段叫 ``thinking``。
    """
    message = data.get("message") or {}
    calls: List[ToolCall] = []
    for index, raw in enumerate(message.get("tool_calls") or []):
        function = raw.get("function") or {}
        arguments = function.get("arguments")
        if not isinstance(arguments, str):
            arguments = json.dumps(arguments or {}, ensure_ascii=False)
        calls.append(ToolCall(id=str(raw.get("id") or f"call_{index}"),
                              function=FunctionCall(
                                  name=str(function.get("name", "")),
                                  arguments=arguments)))
    usage = None
    if data.get("prompt_eval_count") is not None or data.get("eval_count"):
        from block_director.contracts.messages import Usage

        usage = Usage(prompt_tokens=int(data.get("prompt_eval_count") or 0),
                      completion_tokens=int(data.get("eval_count") or 0))
    done_reason = str(data.get("done_reason") or "")
    return ChatReply(content=message.get("content"),
                     tool_calls=calls,
                     reasoning=message.get("thinking"),
                     usage=usage, model=data.get("model"),
                     finish_reason="length" if done_reason == "length" else
                     ("tool_calls" if calls else "stop"))


def _openai_reply(data: Dict[str, Any]) -> ChatReply:
    from block_director.contracts.transport import parse_chat_response

    return parse_chat_response(data)


def call_upstream(config: "SidecarConfig", payload: Dict[str, Any]
                  ) -> ChatReply:
    """把插件侧的请求转发给上游模型。"""
    if config.kind == "ollama":
        status, text = _post_json(f"{config.upstream}/api/chat",
                                  _ollama_body(config, payload),
                                  config.timeout)
        if not 200 <= status < 300:
            raise TransportError(_code_for(status),
                                 f"上游返回 {status}", http_status=status,
                                 body=text[:2000])
        return _ollama_reply(json.loads(text))
    status, text = _post_json(f"{config.upstream}/chat/completions",
                              _openai_body(config, payload), config.timeout)
    if not 200 <= status < 300:
        raise TransportError(_code_for(status), f"上游返回 {status}",
                             http_status=status, body=text[:2000])
    return _openai_reply(json.loads(text))


def _openai_body(config: "SidecarConfig", payload: Dict[str, Any]
                 ) -> Dict[str, Any]:
    body: Dict[str, Any] = {"model": config.model,
                            "messages": payload.get("messages", []),
                            "temperature": payload.get("temperature",
                                                       config.temperature)}
    if payload.get("tools"):
        body["tools"] = payload["tools"]
    if payload.get("tool_choice"):
        body["tool_choice"] = payload["tool_choice"]
    limit = payload.get("max_tokens") or config.max_tokens
    if limit:
        body["max_tokens"] = int(limit)
    return body


def _code_for(status: int) -> ErrorCode:
    return ErrorCode.LLM_001 if 500 <= status <= 599 else ErrorCode.LLM_002


# --------------------------------------------------------------------------- #
# HTTP 服务
# --------------------------------------------------------------------------- #
def make_handler(config: "SidecarConfig"):
    retriever = default_retriever()
    cancelled: set = set()
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):        # 静音：日志走 stdout 的显式记录
            return

        # -- 工具 ---------------------------------------------------------- #
        def _json(self, status: int, payload: Dict[str, Any]) -> None:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _authorised(self) -> bool:
            if not config.token:
                return True
            return self.headers.get("Authorization") == f"Bearer {config.token}"

        def _body(self) -> Dict[str, Any]:
            length = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(length) or b"{}")

        # -- 路由 ---------------------------------------------------------- #
        def do_GET(self):
            if self.path != "/health":
                self._json(404, {"error": "not found"})
                return
            self._json(200, {"status": "ok", "version": CONTRACT_VERSION,
                             "capabilities": [str(item)
                                              for item in config.capabilities]})

        def do_POST(self):
            if not self._authorised():
                self._json(401, {"error": "unauthorized"})
                return
            try:
                body = self._body()
            except json.JSONDecodeError:
                self._json(400, {"error": "invalid json"})
                return
            try:
                self._route(body)
            except TransportError as exc:
                self._json(502, {"error": str(exc), "code": str(exc.code)})
            except Exception as exc:                     # noqa: BLE001
                self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

        def _route(self, body: Dict[str, Any]) -> None:
            if self.path == "/v1/chat":
                self._json(200, call_upstream(config, body).to_dict())
                return
            if self.path == "/v1/retrieve":
                cards = retriever.retrieve(str(body.get("query", "")),
                                           body.get("domain"),
                                           int(body.get("top_k", 5) or 5))
                self._json(200, {"cards": [_card_payload(card)
                                           for card in cards]})
                return
            if self.path == "/v1/embed":
                self._json(501, {"error": "本 sidecar 未配置向量嵌入；"
                                          "§6.1 允许退回 bm25"})
                return
            if self.path == "/v1/cancel":
                with lock:
                    cancelled.add(str(body.get("request_id", "")))
                self._json(200, {"cancelled": True})
                return
            self._json(404, {"error": "not found"})

    def _card_payload(card: Card) -> Dict[str, Any]:
        return card.to_dict()

    return Handler


def parse_args(argv):
    parser = argparse.ArgumentParser(prog="sidecar_server")
    parser.add_argument("--host", default=LOOPBACK,
                        help="监听地址；§2.5 要求只监听回环")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--upstream", default="http://127.0.0.1:11434")
    parser.add_argument("--upstream-kind", choices=("auto", "ollama", "openai"),
                        default="auto")
    parser.add_argument("--model", default="qwen3-vl:30b")
    parser.add_argument("--num-ctx", type=int, default=32768,
                        help="Ollama 的上下文窗口；默认 4096 会装不下思维链")
    parser.add_argument("--think", choices=("off", "on", "default"),
                        default="off",
                        help="思维链：结构化工具调用任务关掉更省预算")
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--token", default="")
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--once", action="store_true",
                        help="处理一个请求后退出（测试用）")
    args = parser.parse_args(argv)
    if args.upstream_kind == "auto":
        args.upstream_kind = detect_kind(args.upstream)
    if args.host not in (LOOPBACK, "localhost"):
        parser.error("§2.5 要求 sidecar 只监听回环地址（127.0.0.1）")
    return args


def main(argv) -> int:
    args = parse_args(argv)
    config = SidecarConfig(args)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(config))
    print(json.dumps({"sidecar": "listening", "host": args.host,
                      "port": server.server_address[1],
                      "upstream": config.upstream, "kind": config.kind,
                      "model": config.model, "num_ctx": config.num_ctx,
                      "think": config.think,
                      "url": f"http://{args.host}:{args.port}"},
                     ensure_ascii=False), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
