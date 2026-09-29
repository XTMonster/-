"""`tools/kb_fetch/llm.py` 的端点与上下文纪律（执行文档 v1.4 §6 的"端点陷阱"）。

本机实测（证据：`work/probe_annotate_speed.py`、`work/probe_holdout_prompt.py`、
`work/probe_compact_ctx.py`、`work/probe_openai_numctx.py`）：

* `qwen3-vl:30b` 是思考模型，答案要 >1000 completion tokens 才出得来；
* Ollama 的 `/v1/chat/completions` **不认 `num_ctx`**，用上次加载的上下文（默认
  4096），于是 thinking 撑爆上下文 → `content` 为空、`finish_reason=length`；
* `/api/chat` 的 `options.num_ctx` 才真正设置上下文，`think:false` 被忽略；
  上下文给够（8192）时，模型思考完会写出正文。

因此本地客户端走 `/api/chat` ＋ 显式 `num_ctx`，并把「`content` 为空而 `thinking`
非空」判成**调用失败**（可重试）——绝不返回 `{}`，也绝不把空串写进索引/标注。
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


def test_ollama_client_sets_the_context_explicitly(monkeypatch):
    seen = {}

    def fake_post(url, payload, headers, timeout):
        seen["url"] = url
        seen["payload"] = payload
        return {"model": "qwen3-vl:30b",
                "message": {"role": "assistant", "content": '{"entries": []}',
                            "thinking": ""},
                "done_reason": "stop",
                "prompt_eval_count": 11, "eval_count": 22}

    monkeypatch.setattr(llm, "_post_json", fake_post)
    client = llm.OllamaClient("qwen3-vl:30b")
    out = client.chat_json("sys", "user", 0.0, 0, 8192, key="c1")

    assert out == {"entries": []}
    assert seen["url"].endswith("/api/chat"), seen["url"]
    options = seen["payload"]["options"]
    assert options["num_ctx"] >= 8192, "默认 4096 会把思考模型截在半路"
    assert options["num_predict"] > 0, "思考税实测 >1000 token，必须给足"
    assert client.last_usage == {"prompt_tokens": 11, "completion_tokens": 22}

    # 调用点给更大的 ctx 时取更大的那个，不会被构造时的值压回去
    client.chat_json("sys", "user", 0.0, 0, 32768, key="c1")
    assert seen["payload"]["options"]["num_ctx"] == 32768


def test_empty_content_with_thinking_is_a_failure(monkeypatch):
    """§6 的具名负例：`response` 为空而 `thinking` 非空 → 判失败，不是空结果。"""
    calls = {"n": 0}

    def fake_post(url, payload, headers, timeout):
        calls["n"] += 1
        return {"model": "qwen3-vl:30b",
                "message": {"role": "assistant", "content": "",
                            "thinking": "我先想一想……" * 20},
                "done_reason": "length",
                "prompt_eval_count": 5, "eval_count": 512}

    monkeypatch.setattr(llm, "_post_json", fake_post)
    monkeypatch.setattr(llm.time, "sleep", lambda _seconds: None)
    client = llm.OllamaClient("qwen3-vl:30b")

    with pytest.raises(llm.LLMError):
        client.chat_json("sys", "user", 0.0, 0, 8192, key="c1")
    assert calls["n"] == 2, "空正文必须触发重试，而不是静默成功"


def test_openai_shaped_body_is_not_accepted_by_the_native_parser():
    """OpenAI 形状的返回体（`choices[]`）在原生路径上**没有** content 可解析。"""
    openai_shape = {"model": "qwen3-vl:30b",
                    "choices": [{"message": {"content": ""},
                                 "finish_reason": "length"}]}
    assert "message" not in openai_shape
    with pytest.raises(llm.LLMError):
        llm.parse_json_content("")


def test_fenced_json_is_parsed_and_blank_payloads_fail():
    assert llm.parse_json_content('```json\n{"ok": true}\n```') == {"ok": True}
    with pytest.raises(llm.LLMError):
        llm.parse_json_content("   ")
    with pytest.raises(llm.LLMError):
        llm.parse_json_content("```json\n```")
    with pytest.raises(llm.LLMError):
        llm.parse_json_content("[1, 2, 3]")
    with pytest.raises(llm.LLMError):
        llm.parse_json_content("{not json}")


def test_scripted_client_contract_is_unchanged(tmp_path):
    """离线替身不受影响：它按 chunk_id 取预置回答，不碰网络。"""
    path = tmp_path / "scripted.json"
    path.write_text(json.dumps({"responses": {"c1": {"entries": [1]}}}), encoding="utf-8")
    client = llm.make_client("scripted", "scripted-v1", str(path))
    assert client.chat_json("s", "u", 0.0, 0, 8192, key="c1") == {"entries": [1]}
    assert client.chat_json("s", "u", 0.0, 0, 8192, key="missing") == {"cards": []}
