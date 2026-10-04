"""`1113` 的归因必须落在**型号**上（2026-10-04 的真实误判，见 `docs/knowledge/ACCEPTANCE_STATUS.md` §七十八）。

为什么值得一条用例
==================

`429 code 1113` 的字面是「余额不足 **或** 无可用资源包」——**两个条件命中任一个都会
返回它**。智谱的**资源包按模型分别计费**：本账号的包是 `glm-5.3` 的，而
`glm-4.7` / `glm-4.7-flash` / `glm-4.6` 都不在包内。

2026-10-04 因此发生过一次真实误判：`glm-4.7` 的 429 被读成"这条 key 的账户耗尽、
**需要充值**"，而账户其实并未耗尽。误判之所以可能，是因为两件事同时成立：

1. 错误串 `LLMError: glm 调用失败：…` **不带型号** ⇒ 任何一份日志都看不出"是哪一个
   型号报的 1113"；
2. `tools/kb_fetch/probe_annotator.py` 的 `CHANNELS` 里**没有 `glm-5.3`** ⇒ 那个
   "专门查有没有额度"的探针恰好漏掉了账户里**真正有包**的那个型号。

判据（都从**产物**推，不手填）
==============================

* 三个 provider 客户端的失败串里必须出现**它们自己的 `model_id`**；
* 探针的 `CHANNELS` 必须覆盖 `GLMClient` 的默认型号（否则探针会再次漏掉有包的型号）；
* E1 面板的 glm 族必须与 `GLMClient` 的默认型号一致（否则面板会去打一个没包的型号）。
"""

from __future__ import annotations

import sys
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.kb_fetch import llm  # noqa: E402


_BALANCE_BODY = '{"error":{"code":"1113","message":"余额不足或无可用资源包,请充值。"}}'


def _http_429(url, payload, headers, timeout):  # pragma: no cover - 由用例注入
    raise llm.LLMError(f"HTTP 429: {_BALANCE_BODY}")


def _client(provider, model):
    """直接构造（不走 `make_client` 的环境变量分支）：用例里不碰真实 key。"""
    if provider == "glm":
        return llm.GLMClient(model, api_key="test-key")
    if provider == "deepseek":
        return llm.DeepSeekClient(model, api_key="test-key")
    return llm.OllamaClient(model)


@pytest.mark.parametrize("provider,model", [
    ("glm", "glm-4.7"),
    ("glm", "glm-5.3"),
    ("deepseek", "deepseek-chat"),
    ("ollama", "qwen3-vl:30b"),
])
def test_provider_error_names_the_model(monkeypatch, provider, model):
    """失败串必须带型号——否则 1113 会被读成"整个账户没钱"（§七十八 那次误判）。"""
    monkeypatch.setattr(llm, "_post_json", _http_429)
    #: 客户端对 429 会做长退避（最长 120 s）；用例里不真睡。
    monkeypatch.setattr(llm.time, "sleep", lambda *_: None)

    client = _client(provider, model)
    with pytest.raises(llm.LLMError) as info:
        client.chat_json("system", "user", 0.0, 0, 8192, key="probe")

    text = str(info.value)
    assert model in text, f"{provider} 的失败串必须带型号，实际是：{text!r}"
    assert "1113" in text, f"上游的错误体必须原样保留：{text!r}"


def test_probe_channels_cover_the_default_glm_model():
    """探针通道表必须含 `GLMClient` 的默认型号——2026-10-04 就是这里漏了 `glm-5.3`。"""
    from tools.kb_fetch import probe_annotator as probe

    default_model = llm.GLMClient().model_id
    glm_models = {model for provider, model, _role in probe.CHANNELS
                  if provider == "glm"}
    assert default_model in glm_models, (
        f"探针没覆盖默认 GLM 型号 {default_model!r}（有：{sorted(glm_models)}）"
        "——它会再次把「没有包」读成「账户没钱」")


def test_probe_channels_have_no_duplicates():
    from tools.kb_fetch import probe_annotator as probe

    keys = [(provider, model) for provider, model, _role in probe.CHANNELS]
    assert len(keys) == len(set(keys)), f"通道表里有重复条目：{keys}"


def test_e1_panel_glm_family_matches_the_default_model():
    """面板必须请求**有包**的型号，否则 E1 又会卡在一次注定 1113 的调用上。"""
    from tools.knowledge import e1_panel

    families = dict(zip(e1_panel.DEFAULT_FAMILIES, e1_panel.DEFAULT_PANEL))
    assert families["glm"] == llm.GLMClient(api_key="test-key").model_id
    assert families["deepseek"] == llm.DeepSeekClient(api_key="test-key").model_id


def test_module_docs_name_the_current_default_model():
    """**文档里点名的"默认型号"必须与代码同源**——2026-10-04 换代时这里漂过一次。

    现场：`tools/knowledge/e1_panel.py` 与 `tools/kb_fetch/probe_annotator.py`
    的模块 docstring 当时还写着"默认/仍有额度的是 `glm-4.7`"，而它们的代码已经是
    `glm-5.3`（`DEFAULT_PANEL` / `CHANNELS`）。这份漂移会把下一个人指到一个
    **没有资源包**的型号上——正是本节开头那次 1113 误判的同一形状。

    判据从**产物**推：两个模块各自的 docstring 必须出现它们实际使用的默认型号。
    """
    from tools.kb_fetch import probe_annotator as probe
    from tools.knowledge import e1_panel

    default = llm.GLMClient().model_id
    assert default in (e1_panel.__doc__ or ""), (
        f"e1_panel 的模块文档没点名当前默认型号 {default!r}：{e1_panel.__doc__!r}")
    assert default in (probe.__doc__ or ""), (
        f"probe_annotator 的模块文档没点名当前默认型号 {default!r}：{probe.__doc__!r}")
