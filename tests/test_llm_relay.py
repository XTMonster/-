"""中转站通道（`linkai.pics`）—— 用户 2026-10-06 指定它来**写执行计划**。

实测（`work/_probe_linkai.py`）：

* 端点 `https://linkai.pics/v1`（OpenAI 兼容）；`/v1/models` 列出
  `codex-auto-review`／`gpt-5.5`／`gpt-5.6-{luna,sol,terra}`／**`gpt-6-astra`**／
  `gpt-6-luna`／`gpt-6-sol`／`gpt-6.1-sol`，四个 `gpt-6*` 都能答。
* **硬约束**：裸 urllib 的默认 UA 会被 Cloudflare 挡成 `HTTP 403 error code: 1010`
  （"banned your access based on your browser's signature"）⇒ 必须发浏览器 UA。
  这条钉在用例里，因为它是**实测出来的**、且去掉就整个通道不可用。
* 用户说的"gpt6A"在型号表里没有同名字面量 ⇒ 默认取 `gpt-6-astra`（唯一以 A 起名的
  `gpt-6*`），`LINKAI_MODEL` 可一行切换。**主线按现有证据做的最接近解释**，
  用户可点名覆盖（见 `model-routing.md`）。
"""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.kb_fetch import llm  # noqa: E402
from tools import relay_consult  # noqa: E402


def test_consult_bounds_each_attempt_so_a_silent_relay_cannot_hold_the_slot(monkeypatch):
    """2026-10-06 实测：中转站**没有 keepalive** ⇒ "正在思考却不出字"与"请求被丢掉、
    永远不出字"在客户端**无法区分**；而 socket 超时是**每次读**的超时，所以它实际就是
    "多久没收到任何字节就放弃这次尝试"。

    同一秒发出、同样 1.8 KB 的包、同样 `max_tokens`/`reasoning_effort` 的三个请求：
    两个 **3.4 / 5.1 分钟**就回来了，第三个 **137 分钟零字节**（`dRead=0/40s`、`dCpu=0/40s`）。
    没有这个上限，那个静默请求会一直占着位置到**总超时**——那曾经是 **6 小时**（最坏 3 次 = 18 h）。

    这一条钉三件事：① 每次尝试按 `min(timeout, attempt_timeout)` 建客户端；
    ② **每次尝试一个新客户端**（把超时留下的 socket 丢掉，不复用）；③ 上限写进 usage（可审计）。
    """
    seen = []

    class _FakeClient:
        model_version = "fake-model"
        last_usage = {}

        def __init__(self, model, api_key="", timeout=0.0, **kwargs):
            seen.append(timeout)

        def chat(self, *args, **kwargs):
            return "正文"

    monkeypatch.setattr(relay_consult.llm, "RelayClient", _FakeClient)
    text, usage = relay_consult.consult(
        [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
        model="gpt-6-astra", max_tokens=32768, levels=["max"], temperature=0.2,
        timeout=21600.0, attempt_timeout=1800.0)
    assert text == "正文"
    assert seen == [1800.0], "单次尝试必须取 min(总预算, 上限)"
    assert usage["attempt_timeout_s"] == 1800.0
    assert usage["channel"] == "linkai-relay"


def test_consult_can_still_be_asked_for_the_unbounded_old_behaviour(monkeypatch):
    """`attempt_timeout=0` 时**退回旧行为**（只受总预算约束）——给长文生成留的出口，
    但那是调用方显式选的，不是默认。"""
    seen = []

    class _FakeClient:
        model_version = "fake-model"
        last_usage = {}

        def __init__(self, model, api_key="", timeout=0.0, **kwargs):
            seen.append(timeout)

        def chat(self, *args, **kwargs):
            return "正文"

    monkeypatch.setattr(relay_consult.llm, "RelayClient", _FakeClient)
    relay_consult.consult(
        [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
        model="gpt-6-astra", max_tokens=8192, levels=["max"], temperature=0.2,
        timeout=3600.0, attempt_timeout=0)
    assert seen == [3600.0]


def _no_stream(monkeypatch):
    """把这些用例**按原意**钉在非流式那条路上。

    为什么必须补（2026-10-06 自查抓到）：`RelayClient.chat()/chat_json()` 已改成
    **默认先走流式**，而流式走的是 `urllib.request.urlopen`。这些用例只桩了 `_post_json`，
    于是改完之后它们会**真的去连中转站**——测试挂住（实测一次跑了 17 分钟没完）。
    把 `urlopen` 打断 ⇒ 客户端按设计**退回非流式** ⇒ 用例恢复成"只测非流式形状"。
    """
    def boom(request, timeout=None):
        raise llm.LLMError("stream is disabled in this test")

    monkeypatch.setattr(llm.urllib.request, "urlopen", boom)


def test_the_relay_is_its_own_family_and_reachable_by_two_names():
    client = llm.RelayClient(api_key="test-key")
    assert client.family == "relay"
    for other in ("deepseek", "glm", "qwen", "kimi"):
        assert client.family != llm.FAMILIES[other]
    assert llm.make_client("linkai").__class__ is llm.RelayClient
    assert llm.make_client("relay").__class__ is llm.RelayClient
    assert llm.make_client("linkai").model_id == "gpt-6-astra"


def test_the_browser_user_agent_is_sent_because_cloudflare_requires_it(monkeypatch):
    captured = {}

    def fake_post(url, payload, headers, timeout):
        captured.update({"url": url, "payload": payload, "headers": headers})
        return {"model": "gpt-6-astra",
                "choices": [{"message": {"content": "{\"ok\": true}"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 4}}

    _no_stream(monkeypatch)
    monkeypatch.setattr(llm, "_post_json", fake_post)
    client = llm.RelayClient("gpt-6-astra", api_key="test-key")
    assert client.chat_json("SYS", "USER", 0.0, 0, 256) == {"ok": True}
    assert captured["url"] == "https://linkai.pics/v1/chat/completions"
    assert captured["headers"]["User-Agent"] == llm.BROWSER_UA
    assert "Mozilla/5.0" in captured["headers"]["User-Agent"]
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["payload"]["model"] == "gpt-6-astra"
    assert client.last_usage == {"prompt_tokens": 3, "completion_tokens": 4}


def test_chat_returns_raw_markdown_for_plan_writing(monkeypatch):
    """写计划要的是 markdown 正文，不是 JSON —— `chat()` 就是给这条的。"""
    _no_stream(monkeypatch)
    monkeypatch.setattr(llm, "_post_json", lambda *a, **k: {
        "model": "gpt-6-astra",
        "choices": [{"message": {"content": "# 计划\n\n- 阶段 1"}}],
        "usage": {}})
    client = llm.RelayClient("gpt-6-astra", api_key="k")
    assert client.chat("SYS", "USER").startswith("# 计划")


def test_an_empty_body_is_a_failure_not_an_empty_string(monkeypatch):
    _no_stream(monkeypatch)
    monkeypatch.setattr(llm, "_post_json", lambda *a, **k: {
        "choices": [{"message": {"content": ""}}], "usage": {}})
    monkeypatch.setattr(llm.time, "sleep", lambda *_: None)
    client = llm.RelayClient("gpt-6-astra", api_key="k")
    with pytest.raises(llm.LLMError) as excinfo:
        client.chat("s", "u", retries=2)
    assert "空正文" in str(excinfo.value)


def test_a_missing_key_is_named(monkeypatch):
    monkeypatch.setattr(llm, "LINKAI_API_KEY", "")
    client = llm.RelayClient("gpt-6-astra")
    with pytest.raises(llm.LLMError) as excinfo:
        client.chat("s", "u", retries=1)
    assert "LINKAI_API_KEY" in str(excinfo.value)


def test_the_base_and_model_are_overridable(monkeypatch):
    captured = {}

    def fake_post(url, payload, headers, timeout):
        captured.update({"url": url, "model": payload["model"]})
        return {"choices": [{"message": {"content": "x"}}], "usage": {}}

    _no_stream(monkeypatch)
    monkeypatch.setattr(llm, "_post_json", fake_post)
    client = llm.RelayClient("gpt-6.1-sol", api_key="k", base="https://example.test/v1/")
    client.chat("s", "u")
    assert captured["url"] == "https://example.test/v1/chat/completions"
    assert captured["model"] == "gpt-6.1-sol"


class _FakeStream:
    """假 SSE 响应：逐行给出 `data: {...}`（含正文分块与 `[DONE]`）。"""

    def __init__(self, lines):
        self._lines = [line.encode("utf-8") for line in lines]
        self.status = 200

    def __iter__(self):
        return iter(self._lines)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_the_relay_streams_by_default_so_long_generations_survive_cloudflare(monkeypatch):
    """**流式是默认**——这是绕开 Cloudflare `524` 的唯一实测有效的办法。

    实测（`work/_probe_linkai_stream.py`）：同一条"要想一会儿"的问题，非流式**三次全 524**
    （边缘 ~100 s 等不到源站）；流式 **HTTP 200、`text/event-stream`、132.7 s 拿到完整正文**。
    所以"gpt6A 生成很慢"不再是限制——**给它多少时间都行**。
    """
    import json as _json

    captured = {}
    lines = [
        "data: " + _json.dumps({"model": "gpt-6-astra",
                                "choices": [{"delta": {"reasoning_content": "想…"}}]}),
        "data: " + _json.dumps({"choices": [{"delta": {"content": "第一段"}}]}),
        "data: " + _json.dumps({"choices": [{"delta": {"content": "第二段"}}],
                                "usage": {"prompt_tokens": 5, "completion_tokens": 9}}),
        "data: [DONE]",
    ]

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["accept"] = request.headers.get("Accept")
        captured["body"] = _json.loads(request.data.decode("utf-8"))
        return _FakeStream(lines)

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
    client = llm.RelayClient("gpt-6-astra", api_key="k")
    assert client.chat("SYS", "USER") == "第一段第二段"
    assert captured["body"]["stream"] is True, "必须请求流式"
    assert captured["accept"] == "text/event-stream"
    assert client.last_usage == {"prompt_tokens": 5, "completion_tokens": 9}
    assert client.model_version == "gpt-6-astra"
    assert "stream=true" in client.decode_tag


def test_streaming_json_goes_through_the_same_parser(monkeypatch):
    import json as _json

    lines = [
        "data: " + _json.dumps({"choices": [{"delta": {"content": '{"ok":'}}]}),
        "data: " + _json.dumps({"choices": [{"delta": {"content": "true}"}}]}),
        "data: [DONE]",
    ]
    monkeypatch.setattr(llm.urllib.request, "urlopen",
                        lambda request, timeout=None: _FakeStream(lines))
    client = llm.RelayClient("gpt-6-astra", api_key="k")
    assert client.chat_json("SYS", "USER", 0.0, 0, 256) == {"ok": True}


def test_a_broken_stream_falls_back_to_the_non_streaming_path(monkeypatch):
    """流式挂了要**退回**非流式，不许直接把一次调用判死。"""
    def boom(request, timeout=None):
        raise llm.LLMError("stream broken")

    monkeypatch.setattr(llm.urllib.request, "urlopen", boom)
    monkeypatch.setattr(llm, "_post_json", lambda *a, **k: {
        "model": "gpt-6-astra",
        "choices": [{"message": {"content": "退回来的正文"}}], "usage": {}})
    client = llm.RelayClient("gpt-6-astra", api_key="k")
    assert client.chat("s", "u", retries=1) == "退回来的正文"
