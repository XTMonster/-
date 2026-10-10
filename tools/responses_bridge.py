"""Local Responses-API -> Zhipu chat/completions bridge (stdlib only).

Why: Codex CLI 0.154 only speaks POST {base_url}/responses (SSE). Zhipu GLM has
no /responses (404) but serves /chat/completions with `thinking`. This bridge
lets Codex sub-agents run on GLM-5.3-Flash. Loopback only; the upstream key is
read from ZHIPU_API_KEY and never logged. The inbound bearer is ignored.

Mapping rules (explicit, nothing silently dropped):
* instructions / developer / system messages -> chat system messages;
* user / assistant messages -> chat messages (input_text / output_text joined;
  input_image -> image_url part);
* function_call / function_call_output -> assistant tool_calls / tool messages;
* custom tools (freeform, e.g. apply_patch) -> function tool with one string
  parameter `input`; the model's call comes back as a custom_tool_call item;
  custom_tool_call(_output) in history map the same way back;
* the Codex-local `namespace` (collaboration) and `tool_search` (deferred tool
  search, name=null) tool types are launcher-only and have no Zhipu relay
  equivalent: they are skipped in the forwarded tool list and logged, not
  rejected, so the worker keeps exec_command / apply_patch / view_image etc.;
* `reasoning` input items are the model's own earlier summaries: not resent
  (chat/completions has no field for them) -- documented, not user content;
* any other tool type (web_search, local_shell, ...) or input item type ->
  HTTP 400 naming it. Launch Codex with web_search disabled.
* thinking is always enabled at the strongest level (`level: "max"`).
  NOTE (measured 2026-10-09): Zhipu returns 200 for any `level` value, so the
  API gives no proof that the level is honoured.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = os.environ.get("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
DEFAULT_MODEL = "glm-5.3-flash"
KEEPALIVE_S = 8.0
LOG_PATH = os.environ.get("BRIDGE_LOG", "")


class BridgeError(Exception):
    """Unsupported request shape -> HTTP 400 with this message."""


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for part in content or []:
        kind = part.get("type")
        if kind in ("input_text", "output_text", "text", "summary_text"):
            parts.append(part.get("text", ""))
        elif kind == "refusal":
            parts.append(part.get("refusal", ""))
        elif kind != "input_image":
            raise BridgeError(f"unsupported content part type: {kind}")
    return "".join(parts)


def _user_content(content):
    if isinstance(content, str):
        return content
    images = [p for p in content or [] if p.get("type") == "input_image"]
    if not images:
        return _text_of(content)
    out = []
    for part in content:
        if part.get("type") == "input_image":
            out.append({"type": "image_url", "image_url": {"url": part.get("image_url", "")}})
        else:
            out.append({"type": "text", "text": _text_of([part])})
    return out


def translate_request(body: dict) -> tuple:
    """Responses body -> (chat body, {tool name: 'function'|'custom'})."""
    messages = []
    if body.get("instructions"):
        messages.append({"role": "system", "content": body["instructions"]})
    pending_calls = []

    def flush_calls():
        if pending_calls:
            messages.append({"role": "assistant", "content": None,
                             "tool_calls": list(pending_calls)})
            pending_calls.clear()

    items = body.get("input") or []
    if isinstance(items, str):
        items = [{"type": "message", "role": "user", "content": items}]
    for item in items:
        kind = item.get("type", "message")
        if kind == "message":
            flush_calls()
            role = item.get("role", "user")
            if role in ("developer", "system"):
                messages.append({"role": "system", "content": _text_of(item.get("content"))})
            elif role == "assistant":
                messages.append({"role": "assistant", "content": _text_of(item.get("content"))})
            else:
                messages.append({"role": "user", "content": _user_content(item.get("content"))})
        elif kind in ("function_call", "custom_tool_call"):
            arguments = (item.get("arguments", "") if kind == "function_call"
                         else json.dumps({"input": item.get("input", "")}, ensure_ascii=False))
            pending_calls.append({"id": item.get("call_id"), "type": "function",
                                  "function": {"name": item.get("name"), "arguments": arguments}})
        elif kind in ("function_call_output", "custom_tool_call_output"):
            flush_calls()
            output = item.get("output", "")
            if not isinstance(output, str):
                output = _text_of(output) if isinstance(output, list) else json.dumps(output, ensure_ascii=False)
            messages.append({"role": "tool", "tool_call_id": item.get("call_id"), "content": output})
        elif kind == "reasoning":
            continue
        else:
            raise BridgeError(f"unsupported input item type: {kind}")
    flush_calls()

    tools, kinds = [], {}
    _log({"event": "tool_shape_probe", "tools": [
        {"type": tool.get("type"), "name": tool.get("name"),
         "parameters": str(tool.get("parameters"))[:300]}
        for tool in body.get("tools") or []]})
    for tool in body.get("tools") or []:
        ttype = tool.get("type")
        if ttype == "function":
            kinds[tool["name"]] = "function"
            tools.append({"type": "function", "function": {
                "name": tool["name"], "description": tool.get("description", ""),
                "parameters": tool.get("parameters") or {"type": "object", "properties": {}}}})
        elif ttype in ("namespace", "tool_search"):
            _log({"event": "tool_skipped", "type": ttype,
                  "name": tool.get("name")})
            continue
        elif ttype == "custom":
            kinds[tool["name"]] = "custom"
            fmt = tool.get("format") or {}
            hint = fmt.get("definition") if isinstance(fmt, dict) else ""
            tools.append({"type": "function", "function": {
                "name": tool["name"],
                "description": (tool.get("description", "") + "\nPass the full raw tool input as the string field `input`."
                                + (f"\nGrammar:\n{hint}" if hint else "")),
                "parameters": {"type": "object", "properties": {"input": {"type": "string"}},
                               "required": ["input"]}}})
        else:
            raise BridgeError(f"unsupported tool type: {ttype} (disable it in the Codex launcher)")

    chat = {"model": body.get("model") or DEFAULT_MODEL, "messages": messages, "stream": True,
            "thinking": {"type": "enabled", "level": "max"}}
    if tools:
        chat["tools"] = tools
        choice = body.get("tool_choice")
        if choice in ("auto", "none", "required"):
            chat["tool_choice"] = choice
    if body.get("max_output_tokens"):
        chat["max_tokens"] = int(body["max_output_tokens"])
    return chat, kinds


def _sse(handler, event: dict) -> None:
    data = json.dumps(event, ensure_ascii=False)
    handler.wfile.write(f"event: {event['type']}\ndata: {data}\n\n".encode("utf-8"))
    handler.wfile.flush()


def _log(record: dict) -> None:
    if LOG_PATH:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def stream_response(handler, body: dict) -> None:
    response_id = "resp_" + uuid.uuid4().hex
    chat, kinds = translate_request(body)
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-cache")
    handler.end_headers()
    base = {"id": response_id, "object": "response", "model": chat["model"]}
    _sse(handler, {"type": "response.created", "response": dict(base, status="in_progress")})

    key = os.environ.get("ZHIPU_API_KEY", "")
    request = urllib.request.Request(
        UPSTREAM.rstrip("/") + "/chat/completions",
        data=json.dumps(chat, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    text, reasoning, finish, usage = [], [], None, {}
    calls = {}
    message_id = "msg_" + uuid.uuid4().hex
    last_event = time.monotonic()
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=1800) as upstream:
            for raw in upstream:
                line = raw.decode("utf-8").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                if chunk.get("usage"):
                    usage = chunk["usage"]
                for choice in chunk.get("choices") or []:
                    delta = choice.get("delta") or {}
                    if delta.get("reasoning_content"):
                        reasoning.append(delta["reasoning_content"])
                    if delta.get("content"):
                        text.append(delta["content"])
                        _sse(handler, {"type": "response.output_text.delta", "item_id": message_id,
                                       "output_index": 0, "content_index": 0, "delta": delta["content"]})
                        last_event = time.monotonic()
                    for call in delta.get("tool_calls") or []:
                        slot = calls.setdefault(call.get("index", 0), {"id": "", "name": "", "arguments": ""})
                        slot["id"] = call.get("id") or slot["id"]
                        fn = call.get("function") or {}
                        slot["name"] = fn.get("name") or slot["name"]
                        slot["arguments"] += fn.get("arguments") or ""
                    if choice.get("finish_reason"):
                        finish = choice["finish_reason"]
                if time.monotonic() - last_event > KEEPALIVE_S:
                    _sse(handler, {"type": "response.in_progress", "response": dict(base, status="in_progress")})
                    last_event = time.monotonic()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        _log({"ts": time.time(), "error": f"HTTP {exc.code}", "detail": detail})
        _sse(handler, {"type": "response.failed", "response": dict(
            base, status="failed", error={"code": f"upstream_{exc.code}", "message": detail})})
        return
    except Exception as exc:  # noqa: BLE001 - reported to Codex, not swallowed
        _log({"ts": time.time(), "error": type(exc).__name__, "detail": str(exc)[:500]})
        _sse(handler, {"type": "response.failed", "response": dict(
            base, status="failed", error={"code": "bridge_error", "message": f"{type(exc).__name__}: {exc}"})})
        return

    output, index = [], 0
    if reasoning:
        item = {"type": "reasoning", "id": "rs_" + uuid.uuid4().hex,
                "summary": [{"type": "summary_text", "text": "".join(reasoning)[-4000:]}]}
        output.append(item)
    if text:
        output.append({"type": "message", "id": message_id, "role": "assistant", "status": "completed",
                       "content": [{"type": "output_text", "text": "".join(text), "annotations": []}]})
    for _, call in sorted(calls.items()):
        call_id = call["id"] or "call_" + uuid.uuid4().hex
        if kinds.get(call["name"]) == "custom":
            try:
                raw_input = json.loads(call["arguments"] or "{}").get("input", "")
            except json.JSONDecodeError:
                raw_input = call["arguments"]
            output.append({"type": "custom_tool_call", "id": "ctc_" + uuid.uuid4().hex, "status": "completed",
                           "call_id": call_id, "name": call["name"], "input": raw_input})
        else:
            output.append({"type": "function_call", "id": "fc_" + uuid.uuid4().hex, "status": "completed",
                           "call_id": call_id, "name": call["name"], "arguments": call["arguments"] or "{}"})
    for item in output:
        _sse(handler, {"type": "response.output_item.done", "output_index": index, "item": item})
        index += 1

    details = usage.get("completion_tokens_details") or {}
    mapped_usage = {
        "input_tokens": int(usage.get("prompt_tokens") or 0),
        "input_tokens_details": {"cached_tokens": int((usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)},
        "output_tokens": int(usage.get("completion_tokens") or 0),
        "output_tokens_details": {"reasoning_tokens": int(details.get("reasoning_tokens") or 0)},
        "total_tokens": int(usage.get("total_tokens") or 0),
    }
    _log({"ts": time.time(), "model": chat["model"], "finish": finish, "tools": len(calls),
          "elapsed_s": round(time.monotonic() - started, 1), "usage": mapped_usage})
    if finish == "length":
        _sse(handler, {"type": "response.incomplete", "response": dict(
            base, status="incomplete", output=output, usage=mapped_usage,
            incomplete_details={"reason": "max_output_tokens"})})
        return
    _sse(handler, {"type": "response.completed", "response": dict(
        base, status="completed", output=output, usage=mapped_usage)})


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # quiet; structured log goes to BRIDGE_LOG
        return

    def _json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            self._json(200, {"object": "list", "data": [
                {"id": DEFAULT_MODEL, "object": "model", "owned_by": "zhipu"}]})
        else:
            self._json(404, {"error": {"message": f"unknown path {self.path}"}})

    def do_POST(self):
        if not self.path.rstrip("/").endswith("/responses"):
            self._json(404, {"error": {"message": f"unknown path {self.path}"}})
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError as exc:
            self._json(400, {"error": {"message": f"invalid JSON: {exc}"}})
            return
        try:
            translate_request(body)
        except BridgeError as exc:
            _log({"ts": time.time(), "rejected": str(exc)})
            self._json(400, {"error": {"message": str(exc), "type": "invalid_request_error"}})
            return
        self.close_connection = True
        stream_response(self, body)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=18790)
    args = parser.parse_args(argv)
    if not os.environ.get("ZHIPU_API_KEY"):
        print("ZHIPU_API_KEY is not set", file=sys.stderr)
        return 2
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"responses_bridge listening on http://127.0.0.1:{args.port}/v1", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
