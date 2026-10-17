"""G8-H：上游 4xx/5xx 必须穿过 sidecar 与插件两层，到达 ``llm_error`` 审计。

此前的两跳各自丢一半信息：

* sidecar 的 502 只序列化 ``str(exc)``（``TransportError.__str__`` 丢 body），
  于是上游的 HTTP 状态与拒绝正文在 sidecar 这一跳就没了；
* 插件 worker 又把异常压成 ``f"{type}: {exc}"`` 字符串，审计里只剩
  ``[E_LLM_001] sidecar 返回 502``。

修法（只加字段、不改任何重试/超时/预算语义）：sidecar 的 502 带上
``upstream_http_status`` 与 ``upstream_body_excerpt``（红化密钥与 Authorization
头、≤2000 字符），插件的 ``llm_error`` 审计事件原样记录这两个字段。
"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Tuple

import pytest

from block_director.contracts.enums import ErrorCode
from block_director.contracts.errors import TransportError
from block_director.contracts.messages import ChatPayload
from block_director.contracts.transport import SidecarTransport
from block_director.layer5_orchestrator.driver import (
    PrevisDriver,
    upstream_error_fields,
)
from block_director.layer5_orchestrator.offline import OfflineTransport
from block_director.layer5_orchestrator.states import DriverState
from block_director.layer6_audit.audit_logger import AuditLogger

ROOT = Path(__file__).resolve().parents[1]


def _load_sidecar():
    spec = importlib.util.spec_from_file_location(
        "bd_sidecar_server_upstream_under_test",
        ROOT / "tools" / "sidecar_server.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sidecar = _load_sidecar()


def _post_capture(base: str, path: str, body: Dict[str, Any]
                  ) -> Tuple[int, str]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        base + path, data=data,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def _start_sidecar(monkeypatch, upstream_status: int, upstream_text: str,
                   api_key: str = "") -> Tuple[ThreadingHTTPServer, str]:
    args = sidecar.parse_args(
        ["--upstream-kind", "openai",
         "--upstream", "https://api.deepseek.com",
         "--model", "deepseek-v4-pro"])
    config = sidecar.SidecarConfig(args)
    config.upstream_api_key = api_key
    monkeypatch.setattr(
        sidecar, "_post_json",
        lambda url, body, timeout, headers=None: (upstream_status, upstream_text))
    httpd = ThreadingHTTPServer(
        ("127.0.0.1", 0), sidecar.make_handler(config))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def _chat_body() -> Dict[str, Any]:
    return {"messages": [{"role": "user", "content": "hi"}],
            "tools": [], "temperature": 0.0, "seed": 0}


# --------------------------------------------------------------------------- #
# 纯函数：红化
# --------------------------------------------------------------------------- #
def test_sanitize_redacts_key_and_authorization_header():
    args = sidecar.parse_args(["--upstream-kind", "openai"])
    config = sidecar.SidecarConfig(args)
    config.upstream_api_key = "sk-secret-123"
    text = ('{"error":{"message":"echoed Authorization: Bearer sk-secret-123 '
            'plus the bare key sk-secret-123"}}')
    cleaned = sidecar.sanitize_upstream_body(text, config)
    assert "sk-secret-123" not in cleaned
    assert "Authorization" not in cleaned
    assert "[REDACTED]" in cleaned


# --------------------------------------------------------------------------- #
# sidecar 502 的形状（上游 stub：400 / 422 / 500）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("status", [400, 422, 500])
def test_sidecar_502_carries_upstream_status_and_excerpt(monkeypatch, status):
    upstream_text = json.dumps(
        {"error": {"message": f"upstream said {status}",
                   "type": "invalid_request_error"}})
    httpd, base = _start_sidecar(monkeypatch, status, upstream_text)
    try:
        response_status, text = _post_capture(base, "/v1/chat", _chat_body())
        assert response_status == 502
        payload = json.loads(text)
        assert payload["code"] == (
            "E_LLM_001" if status >= 500 else "E_LLM_002")
        assert payload["upstream_http_status"] == status
        assert f"upstream said {status}" in payload["upstream_body_excerpt"]
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_sidecar_502_never_leaks_the_upstream_key(monkeypatch):
    key = "sk-top-secret-123"
    upstream_text = ('{"error":{"message":"rejected; request echoed the '
                     'Authorization: Bearer ' + key + ' header"}}')
    httpd, base = _start_sidecar(monkeypatch, 400, upstream_text, api_key=key)
    try:
        _status, text = _post_capture(base, "/v1/chat", _chat_body())
        assert key not in text
        assert "Authorization" not in text
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_sidecar_502_excerpt_is_capped_at_2000_chars(monkeypatch):
    httpd, base = _start_sidecar(monkeypatch, 500, "x" * 5000)
    try:
        _status, text = _post_capture(base, "/v1/chat", _chat_body())
        # 摘录 ≤2000，且**整个 502 正文**也 ≤2000 字符：插件只留前 2000 字符，
        # 正文超了会被截成坏 JSON（G8-H 真跑实证），所以这里钉住"完整 JSON"。
        assert len(text) <= 2000
        payload = json.loads(text)
        excerpt = payload["upstream_body_excerpt"]
        assert len(excerpt) <= 2000
        assert excerpt
        assert payload["upstream_http_status"] == 500
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_call_upstream_logs_the_upstream_error_without_the_key(monkeypatch,
                                                               capsys):
    args = sidecar.parse_args(["--upstream-kind", "openai"])
    config = sidecar.SidecarConfig(args)
    config.upstream_api_key = "sk-top-secret-123"
    monkeypatch.setattr(
        sidecar, "_post_json",
        lambda url, body, timeout, headers=None:
        (500, '{"error":{"message":"boom sk-top-secret-123"}}'))
    with pytest.raises(TransportError):
        sidecar.call_upstream(config, _chat_body())
    captured = capsys.readouterr()
    assert "upstream_error" in captured.err
    assert "500" in captured.err
    assert "sk-top-secret-123" not in captured.err


# --------------------------------------------------------------------------- #
# 插件侧：TransportError.body 里的 sidecar 502 JSON → llm_error 字段
# --------------------------------------------------------------------------- #
def test_upstream_error_fields_extract_from_the_sidecar_502_body():
    body = json.dumps({
        "error": "[E_LLM_002] 响应被截断（思维链已占用全部预算）："
                 "finish_reason=length。请提高 max_tokens",
        "code": "E_LLM_001",
        "upstream_http_status": 422,
        "upstream_body_excerpt": '{"error":{"message":"strict rejected"}}',
    })
    exc = TransportError(ErrorCode.LLM_001, "sidecar 返回 502",
                         http_status=502, body=body)
    fields = upstream_error_fields(exc)
    assert fields["upstream_http_status"] == 422
    assert "strict rejected" in fields["upstream_body_excerpt"]
    assert "响应被截断" in fields["sidecar_error"]
    assert "finish_reason=length" in fields["sidecar_error"]
    # 消息本身一字不改：重试阶梯的 is_timeout 等判定仍然只吃这个短字符串。
    assert "strict rejected" not in str(exc)


def test_upstream_error_fields_ignore_malformed_or_missing_bodies():
    class Bare(Exception):
        pass

    assert upstream_error_fields(Bare()) == {}
    assert upstream_error_fields(TransportError(
        ErrorCode.LLM_001, "boom", body="not json")) == {}
    assert upstream_error_fields(TransportError(
        ErrorCode.LLM_001, "boom",
        body='{"error": "no upstream keys"}')) == {
            "sidecar_error": "no upstream keys"}


def test_upstream_error_fields_survive_a_truncated_sidecar_body():
    """旧版 sidecar / 超长正文：插件把 502 正文截断在摘录中间。

    状态键总在 2000 字符窗口内；摘录取到哪算哪——宁要部分现场，也不把
    上游 5xx 变回"sidecar 返回 502"一句空话。
    """
    body = json.dumps({
        "error": "[E_LLM_002] 响应被截断：finish_reason=length",
        "code": "E_LLM_001",
        "upstream_http_status": 500,
        "upstream_body_excerpt": "x" * 3000,
    })[:2000]
    fields = upstream_error_fields(TransportError(
        ErrorCode.LLM_001, "boom", body=body))
    assert fields["upstream_http_status"] == 500
    assert set(fields["upstream_body_excerpt"]) == {"x"}
    assert 0 < len(fields["upstream_body_excerpt"]) < 3000
    assert "finish_reason=length" in fields["sidecar_error"]


def test_call_upstream_logs_a_truncated_200_reply(monkeypatch, capsys):
    """上游 200 但 finish_reason=length：sidecar 的 stderr 记下关键事实。

    这是 G8-H 真跑里 emit_plan 失败的真实形状：上游不是 5xx，而是思考链
    吃掉输出预算、以 length 停住——`parse_chat_response` 判定后抛错。
    """
    completion = {
        "id": "chatcmpl-x", "object": "chat.completion", "model": "deepseek-v4-pro",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": "",
                        "reasoning_content": "thinking " * 200,
                        "tool_calls": []},
            "finish_reason": "length",
        }],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 24576,
                  "total_tokens": 25576},
    }
    monkeypatch.setattr(
        sidecar, "_post_json",
        lambda url, body, timeout, headers=None:
        (200, json.dumps(completion)))
    args = sidecar.parse_args(["--upstream-kind", "openai"])
    config = sidecar.SidecarConfig(args)
    with pytest.raises(TransportError) as raised:
        sidecar.call_upstream(config, _chat_body())
    assert "finish_reason=length" in str(raised.value)
    assert raised.value.http_status == 200
    captured = capsys.readouterr()
    assert "parse_failed" in captured.err
    assert '"finish_reason": "length"' in captured.err
    assert "24576" in captured.err


def test_502_for_a_truncated_200_reply_carries_the_real_status(monkeypatch):
    """上游 200 + finish_reason=length：502 的 upstream_http_status 是 200，
    不是 null——真实失败分类不能再被误读成"上游 5xx"。"""
    completion = {
        "id": "chatcmpl-x", "object": "chat.completion",
        "model": "deepseek-v4-pro",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": "",
                        "reasoning_content": "thinking " * 200,
                        "tool_calls": []},
            "finish_reason": "length",
        }],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 24576,
                  "total_tokens": 25576},
    }
    httpd, base = _start_sidecar(monkeypatch, 200,
                                 json.dumps(completion))
    try:
        response_status, text = _post_capture(base, "/v1/chat", _chat_body())
        assert response_status == 502
        payload = json.loads(text)
        assert payload["upstream_http_status"] == 200
        assert "finish_reason=length" in payload["error"]
        assert len(text) <= 2000
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_sidecar_transport_keeps_the_sidecar_502_body():
    sidecar_json = json.dumps({
        "error": "[E_LLM_001] sidecar 返回 502",
        "code": "E_LLM_001",
        "upstream_http_status": 400,
        "upstream_body_excerpt": "Invalid tool parameters schema: bad variant",
    })

    def fake_opener(method, url, headers, body, timeout):
        return 502, sidecar_json

    transport = SidecarTransport(base_url="http://127.0.0.1:8765",
                                 opener=fake_opener)
    with pytest.raises(TransportError) as raised:
        transport.chat(ChatPayload(messages=[]))
    assert raised.value.http_status == 502
    assert upstream_error_fields(raised.value) == {
        "sidecar_error": "[E_LLM_001] sidecar 返回 502",
        "upstream_http_status": 400,
        "upstream_body_excerpt": "Invalid tool parameters schema: bad variant",
    }


# --------------------------------------------------------------------------- #
# 端到端：真实 worker → 队列 → llm_error 审计事件
# --------------------------------------------------------------------------- #
SCRIPT = "INT. 咖啡馆 - 日\n\n两人争吵。\n"


class InlineThread:
    def __init__(self, target, name=""):
        self._target = target

    def start(self):
        self._target()


class FailingPlanTransport(OfflineTransport):
    """只在 plan 阶段抛带 sidecar 502 body 的 TransportError。"""

    def __init__(self, body: str):
        super().__init__()
        self._body = body

    def chat(self, payload, timeout=120.0):
        if str(payload.purpose) == "plan":
            raise TransportError(ErrorCode.LLM_001, "sidecar 返回 502",
                                 http_status=502, body=self._body)
        return super().chat(payload, timeout)


def test_llm_error_audit_event_records_upstream_fields():
    sidecar_json = json.dumps({
        "error": "[E_LLM_001] sidecar 返回 502",
        "code": "E_LLM_001",
        "upstream_http_status": 422,
        "upstream_body_excerpt": '{"error":{"message":"strict plan rejected"}}',
    })
    transport = FailingPlanTransport(sidecar_json)
    driver = PrevisDriver(transport=transport, audit=AuditLogger(),
                          script=SCRIPT, thread_factory=InlineThread)
    state = driver.run_to_completion()
    # G2 #8（用户裁决）：计划调整到上限后按剧本声明兜底，不整轮 ERROR。
    assert state is DriverState.DONE
    assert any(event.kind == "plan_adjusted"
               for event in driver.audit.recent())

    errors = [event for event in driver.audit.recent()
              if event.kind == "llm_error"]
    assert errors, "plan 每次失败都该有一条 llm_error"
    for event in errors:
        assert event.data["upstream_http_status"] == 422
        assert "strict plan rejected" in event.data["upstream_body_excerpt"]
        # 既有文案不变：message 仍是短句，正文摘录只落在结构化字段里。
        assert "sidecar 返回 502" in event.message
        assert "strict plan rejected" not in event.message
