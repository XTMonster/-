"""D10 的**证据工具**：把两种分母口径并排算出来（不改任何判据）。

背景（`ADJUDICATIONS_v4.md` D10）：E1 的分母是"面板条目数"，而某臂对某查询
**一条都没召回**时，它**不是记 0 分，而是整行消失**——于是召回差的臂分母更小、
每行更值钱。实测三臂：hybrid／lexical 各 64/64 条查询有行；lightrag 只有 59/64。

本工具**只报数**：

* `A` ＝ 现行的算法（分母＝实际打出来的行数）——**与历史读数同口径**；
* `B` ＝ 固定分母（查询数 × top-k，召回为空记 0）——**语义更对**。

它**不动** `e1_panel`（那件仪器已冻结），也不替用户选口径——D10 的裁决仍归用户。
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.knowledge import e1_two_denominators as td  # noqa: E402


def _row(query: str, score: float) -> dict:
    return {"query": query, "case_id": "c", "score": score, "scores": [score, score]}


def test_both_denominators_are_reported_for_a_full_recall_arm():
    rows = [_row("q1", 5.0), _row("q1", 1.0), _row("q2", 5.0), _row("q2", 1.0)]
    report = td.two_denominators(rows, queries=["q1", "q2"], top_k=2)
    #: 两条查询都没缺行 ⇒ 两个口径必须**相等**。
    assert report["A"]["denominator"] == 4 and report["B"]["denominator"] == 4
    assert report["A"]["value"] == report["B"]["value"] == 0.5


def test_the_fixed_denominator_counts_missing_rows_as_misses():
    """缺整条查询 ⇒ A 的分母缩水、B 的分母不变（这正是 D10 要暴露的东西）。"""
    rows = [_row("q1", 5.0), _row("q1", 1.0)]          # q2 一条都没召回
    report = td.two_denominators(rows, queries=["q1", "q2"], top_k=2)
    assert report["A"]["denominator"] == 2 and report["A"]["value"] == 0.5
    assert report["B"]["denominator"] == 4 and report["B"]["value"] == 0.25
    assert report["queries_with_no_rows"] == 1


def test_a_partial_query_keeps_its_reported_values_but_loses_rows():
    rows = [_row("q1", 5.0)]                            # q1 只回来 1 条（top_k=2）
    report = td.two_denominators(rows, queries=["q1"], top_k=2)
    assert report["A"]["denominator"] == 1 and report["A"]["value"] == 1.0
    assert report["B"]["denominator"] == 2 and report["B"]["value"] == 0.5
    assert report["rows_missing"] == 1


def test_the_query_set_can_be_inferred_from_a_reference_arm(tmp_path):
    """没有显式查询表时，用另一臂的行推出查询全集（三臂共用同一批查询）。"""
    path = tmp_path / "reviews.x.rep1.jsonl"
    path.write_text("\n".join(json.dumps(_row("q%d" % index, 5.0))
                              for index in range(3)) + "\n", encoding="utf-8")
    assert td.queries_in(path) == ["q0", "q1", "q2"]


def test_judge_coverage_exposes_silently_missing_judges():
    """**评委缺席必须看得见**：第一轮 A/B 的启动脚本漏设 GLM key，187 行全是
    `scores: [1, None]` —— 静默变成"单评委"，而面板照样报一个像样的数。
    这条把它变成一个可查的字段（`two_judge_rows` / `single_judge_rows`）。
    """
    rows = [{"query": "q1", "score": 5.0, "scores": [5, 5]},
            {"query": "q1", "score": 1.0, "scores": [1, None]},
            {"query": "q2", "score": 5.0, "scores": [None, 5]}]
    report = td.two_denominators(rows, queries=["q1", "q2"], top_k=2)
    assert report["judge_coverage"]["two_judge_rows"] == 1
    assert report["judge_coverage"]["single_judge_rows"] == 2
    assert report["judge_coverage"]["complete"] is False
