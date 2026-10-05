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
    monkeypatch.setattr(llm, "_post_json", lambda *a, **k: {
        "model": "gpt-6-astra",
        "choices": [{"message": {"content": "# 计划\n\n- 阶段 1"}}],
        "usage": {}})
    client = llm.RelayClient("gpt-6-astra", api_key="k")
    assert client.chat("SYS", "USER").startswith("# 计划")


def test_an_empty_body_is_a_failure_not_an_empty_string(monkeypatch):
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

    monkeypatch.setattr(llm, "_post_json", fake_post)
    client = llm.RelayClient("gpt-6.1-sol", api_key="k", base="https://example.test/v1/")
    client.chat("s", "u")
    assert captured["url"] == "https://example.test/v1/chat/completions"
    assert captured["model"] == "gpt-6.1-sol"
