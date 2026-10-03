"""Q5 的**实读数**：按"这一镜真的召回了哪条边"对齐（诊断，不参与门）。

为什么必须有一条这样的读数（2026-10-03 实测）：§4.1b 的 Q5 join 是"发出的查询串
与本条 `q` 的键值对集合**逐字相等**"。真实发出的串的键集由**计划**决定、标注者的
`q` 由**卡片**决定，两边几乎不可能相等——64 镜那一跑的 64 条发出串与 4539 条 `q`
**一条都不相等**（分母 0），于是那条判据量不到任何东西。

实读数把对齐键换成"本条目的 `must[0]` 边**真的被这一镜检索到了**"：分子/分母的
语义与门限一个字没改，只换对齐键。实测可达性：6 镜那一跑 13 对、64 镜那一跑 31 对。
它**只作诊断**（样本会被单条条目主导），所以本文件钉三件事：

* 召回对齐能算出来，且分子按"这一镜的运镜是否落在期望集合里"判；
* 一条都没对齐时如实记 0/0，**不得**读成 0% 采纳率；
* 没有图、审计缺失时记 `not_measured` 并说明原因（缺证据不是通过）。
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.holdout_score import load_graph  # noqa: E402
from tools.knowledge import quality as Q  # noqa: E402

LIVE_MANIFEST = ROOT / "knowledge" / "hypergraph.manifest.json"
LIVE_CASES = ROOT / "knowledge" / "cases.jsonl"


def _live_graph():
    return load_graph(ROOT / "knowledge" / "hypergraph.nodes.jsonl",
                      ROOT / "knowledge" / "hypergraph.edges.jsonl")


def _spec_of(edge) -> str:
    """把索引里那条边还原成标注侧的写法（`TYPE:kind=value,…`）。"""
    parts = [f"{member.kind}={str(member.node_id).split(':', 1)[-1]}"
             for member in edge.members if member.role != "forbid"]
    return f"{edge.type}:" + ",".join(parts)


def _intent_edge(graph):
    for edge in graph.edges:
        if str(edge.type) == "INTENT_PACK":
            return edge
    raise AssertionError("现行索引里没有 INTENT_PACK 边（用例失去前提）")


def _movement_of(edge) -> str:
    for member in edge.members:
        if str(member.kind) == "movement":
            return str(member.node_id).split(":", 1)[-1]
    raise AssertionError("这条边没有 movement 成员（用例失去前提）")


def _entry(edge, expect):
    return {"id": "ut_0001", "from_card": "ut", "q": "景别=MS；意图=铺垫；运镜=固定",
            "must": [_spec_of(edge)], "top1": [], "never": [],
            "expect_movements": list(expect)}


def _shot(shot_id, movement=None):
    return {"shot_id": shot_id, "shot_type": "MS",
            "movements": ([{"kind": movement}] if movement else [])}


def test_the_recall_join_counts_adoption_over_recalled_edges():
    graph = _live_graph()
    edge = _intent_edge(graph)
    movement = _movement_of(edge)
    entry = _entry(edge, [movement])
    mirror = {"status": "ok", "edges": {"shot_001": [edge.edge_id]}}
    detail = Q.q5_retrieval_join([entry], mirror, [_shot("shot_001", movement)],
                                 graph)
    assert detail["denominator"] == 1 and detail["numerator"] == 1
    assert detail["value"] == 1.0
    assert detail["by_entry"]["ut_0001"] == {"shots": 1, "hits": 1}
    assert detail["examples"][0]["edge_id"] == edge.edge_id
    #: 它**不是**门：状态恒为 not_measured。
    assert detail["status"] == "not_measured"


def test_a_shot_that_ignored_the_recalled_expectation_is_a_miss():
    graph = _live_graph()
    edge = _intent_edge(graph)
    movement = _movement_of(edge)
    entry = _entry(edge, [movement])
    mirror = {"status": "ok", "edges": {"shot_001": [edge.edge_id]}}
    #: 这一镜最后排的是另一个运镜（或干脆没排 ⇒ 视作 `固定`）：
    other = "dolly_in" if movement != "dolly_in" else "固定"
    detail = Q.q5_retrieval_join([entry], mirror, [_shot("shot_001", other)],
                                 graph)
    assert detail["denominator"] == 1 and detail["numerator"] == 0
    assert detail["value"] == 0.0


def test_no_recalled_edge_is_reported_as_zero_over_zero():
    graph = _live_graph()
    edge = _intent_edge(graph)
    entry = _entry(edge, [_movement_of(edge)])
    mirror = {"status": "ok", "edges": {"shot_001": ["hg:000000000000"]}}
    detail = Q.q5_retrieval_join([entry], mirror, [_shot("shot_001")], graph)
    assert detail["denominator"] == 0 and detail["value"] is None
    assert "不得" in detail["note"], detail["note"]


def test_missing_inputs_are_not_measured_and_say_why():
    graph = _live_graph()
    edge = _intent_edge(graph)
    entry = _entry(edge, [_movement_of(edge)])
    assert Q.q5_retrieval_join([entry], {"status": "ok", "edges": {}},
                               [_shot("shot_001")], None)["status"] == "not_measured"
    absent = Q.q5_retrieval_join([entry], {"status": "not_measured", "note": "没有审计"},
                                 [_shot("shot_001")], graph)
    assert absent["status"] == "not_measured" and "审计" in absent["note"]


def test_the_chain_shaped_call_carries_the_readout(tmp_path):
    """链上的调用形状（shots.json ＋ audit_log ＋ 现行索引）里必须带出这份读数。"""
    graph = _live_graph()
    edge = _intent_edge(graph)
    movement = _movement_of(edge)
    entry = _entry(edge, [movement])
    from block_director.knowledge.cases import manifest_fingerprint as cases_fp
    from block_director.knowledge.hypergraph import (
        manifest_fingerprint as hg_fp,
    )

    shots_path = tmp_path / "shots.json"
    shots_path.write_text(json.dumps({
        "shots": [_shot("shot_001", movement)],
        "knowledge": {"hypergraph_fingerprint": hg_fp(LIVE_MANIFEST.parent),
                      "cases_index_fingerprint": cases_fp(LIVE_CASES.parent),
                      "cases_backend": "hybrid"}}, ensure_ascii=False),
        encoding="utf-8")
    audit = tmp_path / "audit_log.jsonl"
    audit.write_text(json.dumps({
        "kind": "retrieval_call", "run_id": "ut", "level": "info",
        "data": {"scope": "shot", "shot_id": "shot_001",
                 "query": Q.plan_query_of_shot(_shot("shot_001", movement)),
                 "edge_ids": [edge.edge_id]}}, ensure_ascii=False) + "\n",
        encoding="utf-8")
    detail = Q.q5_run_join([entry], shots_path, audit_path=audit,
                           manifest_path=LIVE_MANIFEST, cases_path=LIVE_CASES,
                           graph=graph)
    assert detail["retrieval_join"]["denominator"] == 1
    assert detail["retrieval_join"]["numerator"] == 1
    #: 逐字相等的 join 仍然是它自己的算术（这一条只加读数，不改判据）。
    assert "denominator" in detail and "subset_denominator" in detail
