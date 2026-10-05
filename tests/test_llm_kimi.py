"""第三方裁决 / 难题攻坚通道（`kimi`，月之暗面 Moonshot 兼容模式）的契约。

用户 2026-10-06 换的通道："qwen 不方便，改成用 kimi k3 做第三方裁定和难题攻坚"。
它既不是**抽取器**（deepseek）也不是**标注器**（zhipu），所以与 qwen 一样是
"真·第三方"；与两位**评委**（deepseek-chat / glm-5.3）也都不同族。

实测（`work/_probe_kimi.py`）：端点 `https://api.moonshot.cn/v1`，
`GET /models` → `kimi-k2.6` / `kimi-k3` / `kimi-k2.7-code` / `kimi-k2.7-code-highspeed`；
`kimi-k3` 一次小调用 5.3 s，响应同时带 `reasoning_content`（思考）与 `content`（正文）。
密钥只从 `KIMI_API_KEY` 读，**绝不进仓库**。
"""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.kb_fetch import llm  # noqa: E402


def test_kimi_is_a_third_family_not_the_extractor_nor_the_annotator():
    client = llm.KimiClient("kimi-k3", api_key="test-key")
    assert client.family == "kimi"
    assert client.family != llm.FAMILIES["deepseek"], "抽取器是 deepseek"
    assert client.family != llm.FAMILIES["glm"], "标注器是 zhipu"
    assert client.family != llm.FAMILIES["qwen"], "旧的第三方通道是 qwen"
    assert llm.make_client("kimi").__class__ is llm.KimiClient
    assert llm.make_client("kimi").model_id == "kimi-k3"
    # `moonshot` 是同一族的别名，指到同一个类。
    assert llm.make_client("moonshot").__class__ is llm.KimiClient


def test_temperature_is_forced_to_one_because_the_upstream_only_allows_one(monkeypatch):
    """实测：`kimi-k3` 传 0 ⇒ HTTP 400 `invalid temperature: only 1 is allowed`。

    这是上游硬约束：客户端**显式**盖成 1（不是"传 0 被拒再重试"），
    并把这个决定写进 `decode_tag`，免得读判词的人以为我们放宽了采样条件。
    """
    captured = {}

    def fake_post(url, payload, headers, timeout):
        captured.update(payload)
        return {"model": "kimi-k3",
                "choices": [{"message": {"content": "{\"ok\": true}",
                                         "reasoning_content": "……"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 9}}

    monkeypatch.setattr(llm, "_post_json", fake_post)
    client = llm.KimiClient("kimi-k3", api_key="test-key")
    assert client.chat_json("SYS", "USER", 0.0, 0, 256) == {"ok": True}
    assert captured["temperature"] == 1, "调用方给 0 也必须落成 1"
    assert "temperature=1" in client.decode_tag


def test_a_missing_key_is_named_not_silently_swapped(monkeypatch):
    monkeypatch.setattr(llm, "KIMI_API_KEY", "")
    client = llm.KimiClient("kimi-k3")
    with pytest.raises(llm.LLMError) as excinfo:
        client.chat_json("s", "u", 0.0, 0, 64, retries=1)
    assert "KIMI_API_KEY" in str(excinfo.value)


def test_the_payload_is_the_openai_shape_and_the_json_is_parsed(monkeypatch):
    captured = {}

    def fake_post(url, payload, headers, timeout):
        captured.update({"url": url, "payload": payload, "headers": headers,
                         "timeout": timeout})
        return {"model": "kimi-k3",
                "choices": [{"message": {"content": "{\"best\": [\"c1\"]}"}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7}}

    monkeypatch.setattr(llm, "_post_json", fake_post)
    client = llm.KimiClient("kimi-k3", api_key="test-key")
    reply = client.chat_json("SYS", "USER", 0.0, 0, 512)
    assert reply == {"best": ["c1"]}
    assert captured["url"].endswith("/chat/completions")
    assert "api.moonshot.cn" in captured["url"]
    payload = captured["payload"]
    assert payload["model"] == "kimi-k3"
    assert payload["messages"][0] == {"role": "system", "content": "SYS"}
    assert payload["messages"][1] == {"role": "user", "content": "USER"}
    assert payload["max_tokens"] == 512 and payload["stream"] is False
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert client.last_usage == {"prompt_tokens": 11, "completion_tokens": 7}
    assert client.model_version == "kimi-k3"


def test_an_empty_body_is_a_failure_not_an_empty_dict(monkeypatch):
    """思考吃光预算 ⇒ 正文为空 ⇒ 具名失败，绝不返回 `{}` 当真结果。"""
    monkeypatch.setattr(llm, "_post_json", lambda *a, **k: {
        "choices": [{"message": {"content": "", "reasoning_content": "想了很久"}}],
        "usage": {}})
    monkeypatch.setattr(llm.time, "sleep", lambda *_: None)
    client = llm.KimiClient("kimi-k3", api_key="test-key")
    with pytest.raises(llm.LLMError) as excinfo:
        client.chat_json("s", "u", 0.0, 0, 64, retries=2)
    assert "空正文" in str(excinfo.value)


def test_a_failure_is_reported_with_the_model_name(monkeypatch):
    def deny(*args, **kwargs):
        raise llm.LLMError("HTTP 401 Invalid Authentication")

    monkeypatch.setattr(llm, "_post_json", deny)
    monkeypatch.setattr(llm.time, "sleep", lambda *_: None)
    client = llm.KimiClient("kimi-k3", api_key="test-key")
    with pytest.raises(llm.LLMError) as excinfo:
        client.chat_json("s", "u", 0.0, 0, 64, retries=1)
    assert "kimi-k3" in str(excinfo.value)
    assert "Invalid Authentication" in str(excinfo.value)


def test_the_base_url_is_overridable_so_the_endpoint_is_not_hard_wired(monkeypatch):
    captured = {}

    def fake_post(url, payload, headers, timeout):
        captured["url"] = url
        return {"choices": [{"message": {"content": "{}"}}], "usage": {}}

    monkeypatch.setattr(llm, "_post_json", fake_post)
    client = llm.KimiClient("kimi-k3", api_key="k", base="https://example.test/v1/")
    client.chat_json("s", "u", 0.0, 0, 8)
    assert captured["url"] == "https://example.test/v1/chat/completions"
