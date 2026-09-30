"""扩展上限探针（`tools/knowledge/expansion_caps.py`）的对拍测试。

它存在的理由是**阻止一个看起来很合理的错误改动**（把检索上限调大），
所以测试只需要证明它真的在量"候选集里有没有那条 must 边"。
"""

from __future__ import annotations

from block_director.knowledge import hypergraph as hg
from tools.knowledge.expansion_caps import ceiling


def _edge() -> hg.HyperEdge:
    return hg.HyperEdge(
        type="EMOTION_PACK",
        members=(hg.Member("allow", "emotion", "emotion:荒诞"),
                 hg.Member("qualifier", "intensity", "intensity:high")),
        source_kind="theory", hardness="hard", occurrences=1, sources=("card_1",),
        source_span={"chunk_id": "c1", "start": 0, "end": 4},
        extractor={"prompt_version": "test"}, provenance_kind="生成卡片")


def _graph() -> hg.Hypergraph:
    nodes = [hg.Node(node_id="emotion:荒诞", type="emotion", name="荒诞", value="荒诞"),
             hg.Node(node_id="intensity:high", type="intensity", name="high", value="high")]
    return hg.Hypergraph(nodes, [_edge()])


def test_ceiling_counts_a_reachable_must_edge():
    report = ceiling(_graph(), [{"q": "情绪=荒诞", "must": ["EMOTION_PACK:emotion=荒诞,intensity=high"]}])
    assert report["entries"] == 1 and report["hits"] == 1
    assert report["ratio"] == 1.0 and report["avg_candidates"] >= 1


def test_ceiling_counts_an_unreachable_must_edge_as_a_miss():
    """必须的取值不在索引里 → 种子到不了 → 命中 0（这正是实测 0.375 的成因）。"""
    report = ceiling(_graph(), [{"q": "情绪=压抑", "must": ["EMOTION_PACK:emotion=压抑,intensity=high"]}])
    assert report["hits"] == 0 and report["ratio"] == 0.0
