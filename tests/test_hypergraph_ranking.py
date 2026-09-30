"""排序：**精确匹配的边必须压过超集边**（v1.5 的 precision 项）。

只有 `coverage`（种子被边覆盖了多少）时，一条"把种子成员全带上、另外还多带
几个成员"的超集边能拿到同样的 1.0，再靠 `occurrences`/`confidence` 把精确
匹配的那条挤下去。实测（`tools/knowledge/ranking_quality.py`，300 条索引派生
查询）：加 precision 项后 Q1 0.5167 → 0.5867、Q2 0.7867 → 0.8567。
"""

from __future__ import annotations

from block_director.knowledge import hypergraph as hg


def _edge(members, occurrences: int = 1, confidence: float = 0.7) -> hg.HyperEdge:
    return hg.HyperEdge(
        type="EMOTION_PACK", members=tuple(members), source_kind="theory", hardness="hard",
        occurrences=occurrences, confidence=confidence, confidence_max=confidence,
        sources=("card_1",), source_span={"chunk_id": "c1", "start": 0, "end": 4},
        extractor={"prompt_version": "test"}, provenance_kind="生成卡片")


def _graph() -> tuple[hg.Hypergraph, hg.HyperEdge, hg.HyperEdge]:
    exact = _edge([hg.Member("allow", "emotion", "emotion:荒诞"),
                   hg.Member("qualifier", "intensity", "intensity:high")])
    # 语料支持**相同**（同 occurrences、同 confidence）：这时只有 precision 能把
    # 精确匹配与超集分开。若给超集更高的 occurrences，加权和可以正当地选它。
    superset = _edge([hg.Member("allow", "emotion", "emotion:荒诞"),
                      hg.Member("qualifier", "intensity", "intensity:high"),
                      hg.Member("allow", "movement", "movement:固定")])
    nodes = [hg.Node(node_id="emotion:荒诞", type="emotion", name="荒诞", value="荒诞"),
             hg.Node(node_id="intensity:high", type="intensity", name="high", value="high"),
             hg.Node(node_id="movement:固定", type="movement", name="固定", value="固定")]
    return hg.Hypergraph(nodes, [exact, superset]), exact, superset


def test_exact_edge_outranks_a_superset_that_merely_covers_the_seeds():
    """**同等语料支持**下，精确匹配必须压过"多带一个成员"的超集。

    这正是加 precision 项要修的回归：只有 coverage 时两者同分（都是 1.0），
    排序完全交给 occurrences/confidence。反过来，当超集边的 `occurrences`
    确实高出很多时，加权和仍可能选它——那是"这条耦合在语料里反复出现"的
    信号在起作用，属**有意为之**，不在本测试的射程内。
    """
    graph, exact, superset = _graph()
    query = hg.parse_query("情绪=荒诞")
    seeds = set(graph.seeds_for(query))
    assert seeds, "查询至少要命中一个种子，否则测的不是排序"

    assert graph.score(exact, query, seeds) > graph.score(superset, query, seeds), (
        "超集边靠 occurrences/confidence 抢到第一就是这条测试要挡的回归")

    selected, _text, _trace = graph.retrieve("情绪=荒诞", top_k=2, token_limit=10 ** 6)
    assert [edge.edge_id for edge in selected][0] == exact.edge_id
