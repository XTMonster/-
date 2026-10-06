"""`rerank_finetune` 里**不碰 torch 的那一半**：分组与"代理 E1"的定义。

为什么值得钉：训练本身要 GPU，跑一次两分钟到几十分钟；但**评价口径**（代理 E1 与"完美重排
上限"是不是同一把尺）是可以离线钉死的——本仓已经吃过一次"拿错尺子"的亏
（`docs/evidence/20261006-e1-judge-context/`）。
"""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.knowledge import rerank_finetune as rft  # noqa: E402


def _item(query, case_id, label):
    return {"query": query, "case_id": case_id, "passage": "p", "label": label}


def test_grouping_keeps_file_order():
    grouped = rft.group_by_query([_item("b", "c1", 1), _item("a", "c2", 0),
                                  _item("b", "c3", 0)])
    assert list(grouped) == ["b", "a"], "按文件里第一次出现的顺序"
    assert [i["case_id"] for i in grouped["b"]] == ["c1", "c3"]


def test_the_proxy_uses_the_same_ruler_as_the_perfect_rerank_ceiling():
    """代理 E1 与"完美重排上限"必须同尺：都是 `mean(min(top_k, 相关行数) / top_k)`。"""
    grouped = rft.group_by_query([
        _item("q1", "c1", 1), _item("q1", "c2", 1), _item("q1", "c3", 1),
        _item("q1", "c4", 1), _item("q1", "c5", 0),
        _item("q2", "c6", 1), _item("q2", "c7", 0), _item("q2", "c8", 0),
    ])
    #: 完美重排：q1 取满 3、q2 只有 1 条相关 ⇒ (3+1)/6。
    perfect = rft.proxy_e1({q: [i["case_id"] for i in items]
                            for q, items in grouped.items()}, grouped)
    #: 这两个量都按 4 位小数落盘，所以容差按 1e-4 比。
    assert perfect["perfect_ceiling"] == pytest.approx(4 / 6, abs=1e-4)
    assert perfect["proxy_e1"] == pytest.approx(4 / 6, abs=1e-4), "完美序的代理值＝上限"


def test_a_bad_ranking_scores_below_the_ceiling():
    grouped = rft.group_by_query([
        _item("q1", "c1", 1), _item("q1", "c2", 1), _item("q1", "c3", 1),
        _item("q1", "c4", 0), _item("q1", "c5", 0),
    ])
    ranked = {"q1": ["c4", "c5", "c1"]}       # 前两条都是无关的
    page = rft.proxy_e1(ranked, grouped)
    assert page["proxy_e1"] == pytest.approx(1 / 3, abs=1e-4)
    assert page["perfect_ceiling"] == pytest.approx(1.0, abs=1e-4)
