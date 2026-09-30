"""智谱 GLM 标注通道（第二族）的契约：换族、关思考、空正文判失败。

实测（raw 探针，`work` 里留了脚本）：

* `glm-4.7` 默认是**思考模型**——不关思考时整段 `max_tokens` 都花在 `reasoning_content`
  上、`content` 恒为空（`finish_reason=length`；4096 与 8192 都一样）；
* `{"thinking": {"type": "disabled"}}` 是它唯一有效的关闭开关（布尔写法返回 400）：
  关掉后 `finish_reason=stop`、`reasoning_len=0`、正文直接给 JSON；
* 关掉思考后的实测通过率：6 张卡一次调用给 18 条，**17–18 条过门**（0.94–1.0）。

换族上：抽取走 deepseek，标注走 zhipu ⇒ `family` 不同 ⇒ `independence: strong`
（协议 §5.1）。密钥只从 `GLM_API_KEY` 读，**绝不进仓库**。
"""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.kb_fetch import llm  # noqa: E402


def test_glm_family_differs_from_the_extractor():
    client = llm.GLMClient("glm-4.7", api_key="test-key")
    assert client.family == "zhipu"
    assert client.family != llm.FAMILIES["deepseek"], "换族是 §2.3c 的第 1 条硬要求"
    assert llm.make_client("glm", "glm-4.7").__class__ is llm.GLMClient


def test_glm_disables_thinking_in_the_payload(monkeypatch):
    seen = {}

    def fake_post(url, payload, headers, timeout):
        seen["url"] = url
        seen["payload"] = payload
        seen["headers"] = headers
        return {"model": "glm-4.7",
                "choices": [{"message": {"role": "assistant",
                                         "content": '{"entries": []}'},
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 22}}

    monkeypatch.setattr(llm, "_post_json", fake_post)
    client = llm.GLMClient("glm-4.7", api_key="test-key")
    out = client.chat_json("sys", "user", 0.0, 0, 8192)

    assert out == {"entries": []}
    assert seen["payload"]["thinking"] == {"type": "disabled"}, \
        "不关思考时 content 恒为空（整段预算被 reasoning_content 吃光）"
    assert seen["url"].endswith("/chat/completions")
    assert seen["headers"]["Authorization"] == "Bearer test-key"
    assert client.last_usage == {"prompt_tokens": 11, "completion_tokens": 22}


def test_glm_empty_content_is_a_failure(monkeypatch):
    """只有 reasoning_content 没有 content → 判失败并重试，绝不当成空结果。"""
    monkeypatch.setattr(llm, "_post_json",
                        lambda *a, **k: {"choices": [{"message": {"content": "",
                                                                  "reasoning_content": "思考" * 100},
                                                      "finish_reason": "length"}]})
    client = llm.GLMClient("glm-4.7", api_key="test-key")
    with pytest.raises(llm.LLMError):
        client.chat_json("sys", "user", 0.0, 0, 8192)


def test_glm_requires_a_key_from_the_environment(monkeypatch):
    monkeypatch.setattr(llm, "GLM_API_KEY", "")
    client = llm.GLMClient("glm-4.7")
    with pytest.raises(llm.LLMError):
        client.chat_json("sys", "user", 0.0, 0, 8192)
