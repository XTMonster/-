"""消费侧回归：**仓库里那份索引**在超图后端下能不能真的把边交给调用方。

索引产物与检索器分属两个lane，很容易出现"索引重建了、消费侧却没接上"——
实测过的一种形态是默认后端 `bm25` 下 `hypergraph_edges()` 恒返回 `[]`，
于是 683 条边一条都用不到。这条测试用随仓库入库的产物跑一次真实检索。
"""

from __future__ import annotations

from block_director.contracts.enums import RagBackend
from block_director.knowledge.corpus import CARDS
from block_director.knowledge.retriever import KnowledgeRetriever
from tools.knowledge.retrieval_smoke import QUERIES, load_index


def test_shipped_index_serves_the_hypergraph_path():
    index = load_index()
    assert len(index.edges) > 100, "随仓库入库的索引不该是空的"

    engine = KnowledgeRetriever(cards=list(CARDS), backend=RagBackend.HYPERGRAPH,
                                capabilities={"hypergraph"}, hypergraph=index)
    for query in QUERIES:
        edges = engine.hypergraph_edges(query, top_k=8)
        assert edges, f"{query} 在超图后端下一条边都没取到"
        block = engine.edge_block(query)
        assert block.strip(), f"{query} 取到边却注入了空文本"
        trace = engine.last_trace or {}
        assert not trace.get("degraded"), f"{query} 发生了降级：{trace.get('degraded_reason')}"
        assert not trace.get("seed_miss"), f"{query} 没有命中任何种子"
