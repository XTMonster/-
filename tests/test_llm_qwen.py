"""第三方裁决通道（`qwen`，阿里云百炼兼容模式）的契约。

用户裁决（2026-10-05）："如果需要人工裁决，这边我想用第三方的ai进行裁决"，
指定 `qwen3.8-max-0902`。它既不是**抽取器**（deepseek）也不是**标注器**（zhipu），
所以它是本项目里唯一能当"真·第三方"的族。

实测（`work/_probe_qwen_endpoint.py`／`work/_list_qwen_models.py`）：
端点 `https://dashscope.aliyuncs.com/compatible-mode/v1`；key 有**按模型的白名单**
（`qwen3-max` 会被 `403 access_denied`，`qwen3.8-max-0902` 可用）——
所以这条通道**不许静默换型号**，失败要具名。密钥只从 `QWEN_API_KEY` 读，**绝不进仓库**。
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.kb_fetch import llm  # noqa: E402


def test_qwen_is_a_third_family_not_the_extractor_nor_the_annotator():
    client = llm.QwenClient("qwen3.8-max-0902", api_key="test-key")
    assert client.family == "qwen"
    assert client.family != llm.FAMILIES["deepseek"], "抽取器是 deepseek"
    assert client.family != llm.FAMILIES["glm"], "标注器是 zhipu"
    assert llm.make_client("qwen").__class__ is llm.QwenClient
    assert llm.make_client("qwen").model_id == "qwen3.8-max-0902"


def test_a_missing_key_is_named_not_silently_swapped(monkeypatch):
    monkeypatch.setattr(llm, "QWEN_API_KEY", "")
    client = llm.QwenClient("qwen3.8-max-0902")
    with pytest.raises(llm.LLMError) as excinfo:
        client.chat_json("s", "u", 0.0, 0, 64, retries=1)
    assert "QWEN_API_KEY" in str(excinfo.value)


def test_the_payload_is_the_openai_shape_and_the_json_is_parsed(monkeypatch):
    captured = {}

    def fake_post(url, payload, headers, timeout):
        captured.update({"url": url, "payload": payload, "headers": headers,
                         "timeout": timeout})
        return {"model": "qwen3.8-max-0902",
                "choices": [{"message": {"content": "{\"keep\": [\"c1\"]}"}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7}}

    monkeypatch.setattr(llm, "_post_json", fake_post)
    client = llm.QwenClient("qwen3.8-max-0902", api_key="test-key")
    reply = client.chat_json("SYS", "USER", 0.0, 0, 512)
    assert reply == {"keep": ["c1"]}
    assert captured["url"].endswith("/chat/completions")
    assert "dashscope.aliyuncs.com" in captured["url"]
    payload = captured["payload"]
    assert payload["model"] == "qwen3.8-max-0902"
    assert payload["messages"][0] == {"role": "system", "content": "SYS"}
    assert payload["messages"][1] == {"role": "user", "content": "USER"}
    assert payload["max_tokens"] == 512 and payload["stream"] is False
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert client.last_usage == {"prompt_tokens": 11, "completion_tokens": 7}
    assert client.decode_tag == "thinking=default;max_tokens=num_ctx"


def test_an_empty_body_is_a_failure_not_an_empty_dict(monkeypatch):
    """空正文＝调用失败（端点陷阱那一类），绝不返回 `{}` 当真结果。"""
    monkeypatch.setattr(llm, "_post_json", lambda *a, **k: {
        "choices": [{"message": {"content": ""}}], "usage": {}})
    monkeypatch.setattr(llm.time, "sleep", lambda *_: None)
    client = llm.QwenClient("qwen3.8-max-0902", api_key="test-key")
    with pytest.raises(llm.LLMError) as excinfo:
        client.chat_json("s", "u", 0.0, 0, 64, retries=2)
    assert "空正文" in str(excinfo.value)


def test_a_restricted_model_is_reported_by_name(monkeypatch):
    """key 的白名单拒了型号时，错误里必须带型号——不然会被读成"整个账户没钱"。"""
    def deny(*args, **kwargs):
        raise llm.LLMError("HTTP 403 access_denied")

    monkeypatch.setattr(llm, "_post_json", deny)
    monkeypatch.setattr(llm.time, "sleep", lambda *_: None)
    client = llm.QwenClient("qwen3-max", api_key="test-key")
    with pytest.raises(llm.LLMError) as excinfo:
        client.chat_json("s", "u", 0.0, 0, 64, retries=1)
    assert "qwen3-max" in str(excinfo.value)
    assert "access_denied" in str(excinfo.value)
