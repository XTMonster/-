"""`OllamaClient` 的 assistant 预填（思考税的**实测**解法，v1.4 §6）。

本机实测（`work/` 下的探针）：`qwen3-vl:30b` 是思考模型，官方三条关闭开关
（`/no_think` 写 user、`/no_think` 写 system、`think:false`）在本机**全部无效**，
`num_predict=2048` 时一律 `content_len=0 / thinking_len≈3400 / done_reason=length`；
给到 6144 也一样（thinking 16000 字符、content 仍空）。

但把答案的开头当**助手回合预填**交给 `/api/chat`，就能让模型直接续写：
实测 `4.7s / eval_count=355 / content_len=962 / thinking_len=0 / done_reason=stop`。
这几个用例钉住预填的收发两半，以及"预填不会关掉空正文的失败判据"。
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

PREFILL = '{"entries": ['


def _reply(content: str, thinking: str = "", reason: str = "stop") -> dict:
    return {"model": "qwen3-vl:30b",
            "message": {"role": "assistant", "content": content, "thinking": thinking},
            "done_reason": reason, "prompt_eval_count": 1309, "eval_count": 355}


def test_prefill_puts_the_answer_head_in_the_messages(monkeypatch):
    seen = {}

    def fake_post(url, payload, headers, timeout):
        seen["payload"] = payload
        # 实测：Ollama **不回显**预填，只回续写（head 是 `\n { "from_card": …`）
        return _reply('\n {"from_card": "c1", "q": "情绪=荒诞", "must": [],'
                      ' "top1": [], "never": []}\n]}')

    monkeypatch.setattr(llm, "_post_json", fake_post)
    client = llm.OllamaClient("qwen3-vl:30b", prefill=PREFILL)
    out = client.chat_json("sys", "user", 0.0, 0, 8192)

    messages = seen["payload"]["messages"]
    assert [m["role"] for m in messages] == ["system", "user", "assistant"]
    assert messages[-1]["content"] == PREFILL
    assert out["entries"][0]["from_card"] == "c1"
    assert client.last_usage == {"prompt_tokens": 1309, "completion_tokens": 355}


def test_echoed_prefill_is_also_accepted(monkeypatch):
    body = json.dumps({"entries": [{"from_card": "c1"}]})
    monkeypatch.setattr(llm, "_post_json",
                        lambda *a, **k: _reply(body))
    client = llm.OllamaClient("qwen3-vl:30b", prefill=PREFILL)
    assert client.chat_json("sys", "user", 0.0, 0, 8192)["entries"] == [{"from_card": "c1"}]


def test_prefill_defaults_to_off(monkeypatch):
    monkeypatch.setattr(llm, "OLLAMA_PREFILL", "")
    seen = {}

    def fake_post(url, payload, headers, timeout):
        seen["payload"] = payload
        return _reply('{"entries": []}')

    monkeypatch.setattr(llm, "_post_json", fake_post)
    llm.OllamaClient("qwen3-vl:30b").chat_json("sys", "user", 0.0, 0, 8192)
    assert [m["role"] for m in seen["payload"]["messages"]] == ["system", "user"]


def test_env_var_supplies_the_prefill(monkeypatch):
    monkeypatch.setattr(llm, "OLLAMA_PREFILL", PREFILL)
    seen = {}

    def fake_post(url, payload, headers, timeout):
        seen["payload"] = payload
        return _reply('\n {"from_card": "c9"}\n]}')

    monkeypatch.setattr(llm, "_post_json", fake_post)
    out = llm.OllamaClient("qwen3-vl:30b").chat_json("sys", "user", 0.0, 0, 8192)
    assert seen["payload"]["messages"][-1] == {"role": "assistant", "content": PREFILL}
    assert out["entries"] == [{"from_card": "c9"}]


def test_empty_content_with_thinking_is_still_a_failure(monkeypatch):
    """预填不许把"只有思考没有正文"洗成成功——那正是 §6 的具名负例。"""
    monkeypatch.setattr(llm, "_post_json",
                        lambda *a, **k: _reply("", thinking="思" * 500, reason="length"))
    client = llm.OllamaClient("qwen3-vl:30b", prefill=PREFILL)
    with pytest.raises(llm.LLMError):
        client.chat_json("sys", "user", 0.0, 0, 8192)


def test_garbage_content_fails_even_with_prefill(monkeypatch):
    monkeypatch.setattr(llm, "_post_json",
                        lambda *a, **k: _reply("这不是 JSON"))
    client = llm.OllamaClient("qwen3-vl:30b", prefill=PREFILL)
    with pytest.raises(llm.LLMError):
        client.chat_json("sys", "user", 0.0, 0, 8192)
