"""L3 的相关性过滤器：**只做减法**、失败不拖垮检索、如实留痕。

为什么需要它（2026-10-03 实测）：E1 是**精确率**——"返回的案例里相关（≥4/5）的比例"。
BM25 只懂词面，top-3 里一半是无关噪声（查询"…表情从困惑转为狂喜"的 top-1 是 1900 年代
一句"银幕明星在每种表情和每个角度下都应同样美丽"）。离线实验（用**已记录**的面板分算）
显示：对 top-8 做一次"只留真的能指导这一镜怎么拍"的过滤，E1 从 **3/18 = 0.167**
升到 **3/7 = 0.429**（`work/zz_e1_rerank_sim.py`）。塞给模型的参考案例里一半是噪声，
对产品本身就是缺陷。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.contracts.knowledge import Case  # noqa: E402
from block_director.knowledge import cases as C  # noqa: E402


def _case(case_id: str, excerpt: str) -> Case:
    return Case(case_id=case_id, case_type="narrative", title="t", excerpt=excerpt,
                source_ref={"title": "src"})


def _corpus():
    """6 篇：BM25 的 IDF 要 N≥3 才为正（见 `test_case_search_zh.py` 的注释）。"""
    return [_case("case_a", "A slow dolly in on the market stalls."),
            _case("case_b", "A slow dolly in on the harbour."),
            _case("case_c", "A static wide shot of an empty room."),
            _case("case_d", "A static wide shot of a corridor."),
            _case("case_e", "Two actors talk across a table."),
            _case("case_f", "Rain falls on a window.")]


def test_without_a_filter_the_lane_is_unchanged():
    index = C.CaseIndex(_corpus(), "hybrid")
    assert index.describe()["cases_filter"] == "off"
    assert index.retrieve("dolly in market", top_k=3), "没过器时照旧返回"


def test_the_filter_can_only_subtract():
    """过滤器**只许做减法**：返回入参之外的案例一律被剔掉（不许凭空造）。"""
    corpus = _corpus()
    stranger = _case("case_zzz", "not in the candidate set")

    def keep_only_a(query, cases):
        return [case for case in cases if case.case_id == "case_a"] + [stranger]

    index = C.CaseIndex(corpus, "hybrid", case_filter=keep_only_a)
    hits = index.retrieve("dolly in market", top_k=3)
    assert [hit.case_id for hit in hits] == ["case_a"], hits
    assert index.describe()["cases_filter"] == "on"


def test_a_filter_that_keeps_nothing_returns_nothing():
    """宁缺勿滥：一个都不合适就返回空——那才是"没有参考案例"的诚实表达。"""
    index = C.CaseIndex(_corpus(), "hybrid", case_filter=lambda query, cases: [])
    assert index.retrieve("dolly in market", top_k=3) == []


def test_a_failing_filter_falls_back_and_says_so():
    """过滤器是增强、不是关键路径：抛错时退回未过滤结果，并把原因写进报告。"""
    def boom(query, cases):
        raise RuntimeError("upstream down")

    index = C.CaseIndex(_corpus(), "hybrid", case_filter=boom)
    hits = index.retrieve("dolly in market", top_k=3)
    assert hits, "过滤失败不该让检索变空"
    info = index.describe()
    assert info["cases_filter"] == "on"
    assert info["cases_filter_reason"] == "cases_filter_failed:RuntimeError"


def test_the_sidecar_filter_is_off_unless_asked_for():
    """`--cases-filter off`（**默认**）⇒ 不装过滤器；`llm` ⇒ 装一个可调用的。

    默认关不是遗漏：三次实测都表明这条滤器**不如不过滤**（见文件头与
    `ACCEPTANCE_STATUS.md` §三十二）。机制留着是因为它是 next 一次尝试的落点，
    不是因为它现在有用。
    """
    sys.path.insert(0, str(ROOT))
    import importlib

    sidecar = importlib.import_module("tools.sidecar_server")
    #: CLI 的默认值就是 `off`。
    parser_default = None
    import argparse

    src = pathlib.Path(sidecar.__file__).read_text(encoding="utf-8")
    assert '"--cases-filter", choices=("off", "llm"), default="off"' in src

    class _Cfg:
        cases_filter = "off"
        upstream = "http://example.invalid"
        model = "m"
        kind = "openai"
        upstream_api_key = ""
        timeout = 1.0

    assert sidecar.make_case_filter(_Cfg()) is None
    _Cfg.cases_filter = "llm"
    made = sidecar.make_case_filter(_Cfg())
    assert callable(made)
    #: 过滤器的提示词就是判据本身：判据必须写明**保留什么、剔除什么**，
    #: 并且**不确定就保留**（2026-10-03 实测：写成"宁缺勿滥"时模型把 6 条查询里的
    #: 5 条清空，E1 的分母直接塌掉——那比不过滤更糟）。
    assert "剔除明显与这一镜无关的" in sidecar.CASE_FILTER_SYSTEM
    assert "不确定就保留" in sidecar.CASE_FILTER_SYSTEM
    assert "keep" in sidecar.CASE_FILTER_SYSTEM


def test_the_upstream_url_is_built_right_for_both_flavours():
    """上游地址 → `chat/completions` 端点。

    **实测踩过**：不判"已经带版本段"就会拼出
    `https://open.bigmodel.cn/api/paas/v4/v1/chat/completions`（404），
    而过滤器失败是**静默回退**——E1 看着"没变化"，其实过滤器一次都没跑。
    """
    import importlib

    sidecar = importlib.import_module("tools.sidecar_server")
    assert sidecar.chat_completions_url("http://127.0.0.1:11434") == \
        "http://127.0.0.1:11434/v1/chat/completions"
    assert sidecar.chat_completions_url("http://127.0.0.1:11434/") == \
        "http://127.0.0.1:11434/v1/chat/completions"
    assert sidecar.chat_completions_url("https://open.bigmodel.cn/api/paas/v4") == \
        "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    assert sidecar.chat_completions_url("https://api.example.com/v1") == \
        "https://api.example.com/v1/chat/completions"
