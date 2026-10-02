"""Q7 的**两个分母**（§4.1 R52）——把它们混在一起是这条指标曾经的实现错误。

§4.1 的 Q7 行原文：

> **Q7** | **禁忌拦截率** | 查询命中某边 `forbid` 成员时、注入文本里**确实带上该
> `forbid` 成员**的**镜头数** / 该情形镜头数 | **100%** ｜ 质量（**R52：两个分母
> 别混**——**运行期**分母 = "该情形镜头数"；**夹具覆盖门**的分母 = Q7 冲突**条目数
> ≥60**（§4.1b）。照夹具门用镜头数会得**0**）

而实现曾按"**被召回的 top-3 里有 forbid 命中**的条目数"当分母——那是第三种东西：
它掺进了检索名次，既不是夹具覆盖门（`q` × 索引的机械统计），也不是运行期（按镜头）。
实测代价：夹具侧明明有 474 条冲突条目（下界 60），却被报成 27 < 60 而判失败，
而其中两个 `forbid` 成员（`track_left`／`zoom_in`）**根本没有条目能写出它们**，
原因不在这一侧，在词表口径（见 `test_knowledge_holdout_vocab.py`）。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge.hypergraph import HyperEdge, Hypergraph, Member, Node  # noqa: E402
from tools import holdout_score as HS  # noqa: E402


def _graph() -> Hypergraph:
    nodes = [Node(node_id="movement:固定", type="movement", name="固定机位",
                  value="固定", aliases=("固定", "static")),
             Node(node_id="emotion:平静", type="emotion", name="平静", value="平静")]
    edge = HyperEdge(type="EMOTION_PACK", source_kind="theory", hardness="hard",
                     members=(Member("allow", "emotion", "emotion:平静"),
                              Member("qualifier", "intensity", "intensity:low"),
                              Member("forbid", "movement", "movement:固定")))
    return Hypergraph(nodes, [edge])


def _entry(ident: str, query: str) -> dict:
    return {"id": ident, "from_card": "c1", "q": query,
            "must": ["EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定"],
            "top1": [], "never": []}


def test_a_query_that_names_a_forbidden_value_counts_even_before_retrieval():
    """夹具覆盖门是 `q` × 索引的机械统计：**不掺检索名次**。"""
    graph = _graph()
    assert HS.query_names_forbidden("情绪=平静；运镜=固定", graph), \
        "q 点名了索引里被禁的取值，就该算一条冲突用例"
    assert HS.query_names_forbidden("情绪=平静；运镜=dolly_in", graph) == [], \
        "q 没点名被禁取值时不算"
    # 别名同样认（`static` 是 `固定` 的别名）。
    assert HS.query_names_forbidden("情绪=平静；运镜=static", graph)


def test_the_gate_has_two_halves_and_reports_which_member_is_uncovered():
    """两半都要：① 冲突条目数 ≥ 60；② **每个** `forbid` 成员都被点名。"""
    graph = _graph()
    members = HS.forbid_members(graph)
    assert len(members) == 1
    seen = {(members[0]["edge_id"], members[0]["kind"], members[0]["node_id"])}
    ok = HS._q7_gate_metric(graph, HS.MIN_FORBID_ITEMS, seen)
    assert ok["status"] == "pass"
    # 反面一：条目数不够（差一条都不行）。
    short = HS._q7_gate_metric(graph, HS.MIN_FORBID_ITEMS - 1, seen)
    assert short["status"] == "fail"
    # 反面二：条目数够，但有个 forbid 成员**没有任何 q 点名它**。
    uncovered = HS._q7_gate_metric(graph, HS.MIN_FORBID_ITEMS, set())
    assert uncovered["status"] == "fail"
    assert uncovered["uncovered_forbid_members"], "必须逐个点名没被覆盖的成员"
    assert "movement:固定" in str(uncovered["uncovered_forbid_members"])


def test_the_metric_says_the_runtime_denominator_is_a_different_one():
    """R52 的原话要留在报告里：运行期的分母是**镜头数**，不是这里的条目数。"""
    report = HS._q7_gate_metric(_graph(), HS.MIN_FORBID_ITEMS, set())
    assert "运行期" in report["note"] and "镜头" in report["note"]
    assert report["denominator"] == HS.MIN_FORBID_ITEMS


def test_the_shipped_artifacts_satisfy_the_fixture_gate():
    """入库的 oracle × 入库的索引必须真的过这道夹具门（否则这一步是假绿）。"""
    nodes = ROOT / "knowledge" / "hypergraph.nodes.jsonl"
    edges = ROOT / "knowledge" / "hypergraph.edges.jsonl"
    holdout = ROOT / "fixtures" / "knowledge_holdout.jsonl"
    if not (nodes.is_file() and edges.is_file() and holdout.is_file()):
        return
    graph = HS.load_graph(nodes, edges)
    entries = HS.load_holdout(holdout)
    report = HS.score_entries(entries, graph, top_k=3, token_limit=2000)
    q7 = next(item for item in report["metrics"] if item["id"] == "Q7")
    assert q7["status"] == "pass", q7["note"]
    assert q7["numerator"] >= HS.MIN_FORBID_ITEMS
    assert q7["uncovered_forbid_members"] == []
