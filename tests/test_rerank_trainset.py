"""重排训练集的**构造**：标签口径、按查询切分（防泄漏）、账目。

为什么值得单独钉：GPT-6A 会诊（`docs/evidence/20261006-gpt6a-consult/`）给的下一步是
"用原两位评委的标签微调交叉编码重排器"，而它自己没点到的前提是——**训练与测试必须按分镜隔离**。
这条不钉住，训出来的"高分"很可能只是"记住了这批分镜"。
"""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.knowledge import rerank_trainset as rt  # noqa: E402


def _row(query, case_id, score, excerpt="e"):
    return {"query": query, "case_id": case_id, "score": score, "excerpt": excerpt}


def test_the_threshold_is_shared_with_the_panel():
    assert rt.RELEVANT == 4.0


def test_samples_use_the_frozen_threshold_and_skip_unscored_rows():
    rows = [_row("q1", "c1", 4.0), _row("q1", "c2", 3.5), _row("q1", "c3", 5.0),
            {"query": "q1", "case_id": "c4", "excerpt": "e"},        # 没分 ⇒ 不进样本
            {"query": "q1", "case_id": "c5", "score": 5.0, "excerpt": "  "}]  # 空正文
    items = rt.samples(rows)
    assert [(i["case_id"], i["label"]) for i in items] == [("c1", 1), ("c2", 0), ("c3", 1)]


def test_the_split_is_by_query_so_no_query_leaks_across_train_and_test():
    items = []
    for n in range(1, 6):                       # 5 条查询 × 3 行
        items += [{"query": "q%d" % n, "case_id": "c%d-%d" % (n, k),
                   "passage": "p", "label": k % 2} for k in range(3)]
    train, test, train_ids, test_ids = rt.split_by_query(items, 2)
    assert train_ids == ["q1", "q2", "q3"] and test_ids == ["q4", "q5"]
    assert len(train) == 9 and len(test) == 6, "账目要对得上（行数）"
    assert {item["query"] for item in train}.isdisjoint(
        {item["query"] for item in test}), "同一条查询不许同时出现在训练与测试里"


def test_an_impossible_test_size_is_refused():
    items = [{"query": "q1", "case_id": "c1", "passage": "p", "label": 1}]
    for bad in (0, 1, 5):
        with pytest.raises(ValueError):
            rt.split_by_query(items, bad)
