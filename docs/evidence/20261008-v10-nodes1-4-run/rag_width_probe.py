"""给"检索宽度该设多少"提供判据：在**合法**配置区间里扫参，同时量"注入多大"和"有多准"。

合法区间来自 `contracts.config.AppConfig.validate()`：
  * `rule_top_k`：**3–8**（`CFG_020`，写死）；
  * `top_k`：> 0（无上界）；
  * `cases_top_k`：无校验（注释说 2–5）。

精度代理（都只用仓库里的索引，不调模型）：
  * 超边：命中的查询槽位数 ≥2 的比例（只命中 1 格的多半是"擦边")；
  * 卡片：正文里出现过任一查询取值的比例。
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from block_director.contracts.enums import RagBackend                    # noqa: E402
from block_director.knowledge.cases import load_index                    # noqa: E402
from block_director.knowledge.hypergraph import (                        # noqa: E402
    Hypergraph, HyperEdge, Node, parse_query)
from block_director.knowledge.retriever import KnowledgeRetriever        # noqa: E402
from block_director.knowledge.tokens import estimate_tokens              # noqa: E402

QUERIES = [
    ("plan", "景别=LS；运镜=static；景别=CU；运镜=dolly_in；景别=MS；运镜=follow_subject"),
    ("shot", "景别=CU；意图=铺垫；运镜=dolly_in；对白=dialogue"),
    ("shot", "景别=MS；意图=揭示；运镜=固定；对白=dialogue"),
]


def load_graph() -> Hypergraph:
    nodes = [Node.from_dict(json.loads(line)) for line in
             (ROOT / "knowledge/hypergraph.nodes.jsonl").read_text(
                 encoding="utf-8").split("\n") if line.strip()]
    edges = [HyperEdge.from_dict(json.loads(line)) for line in
             (ROOT / "knowledge/hypergraph.edges.jsonl").read_text(
                 encoding="utf-8").split("\n") if line.strip()]
    return Hypergraph(nodes, edges)


GRAPH = load_graph()


def make(top_k: int, rule_top_k: int, cases_top_k: int) -> KnowledgeRetriever:
    return KnowledgeRetriever(
        cards=[], backend=RagBackend.HYPERGRAPH,
        capabilities=("hypergraph",), hypergraph=GRAPH,
        cases_index=load_index(ROOT / "knowledge", backend="hybrid"),
        cases_backend="hybrid", top_k=top_k, rule_top_k=rule_top_k,
        cases_top_k=cases_top_k, token_limit=50000, plan_token_limit=60000)


def precision_of(edges, query: str) -> tuple:
    seeds = parse_query(query)
    wanted = {f"{kind}:{value}" for kind, values in seeds.items() for value in values}
    multi = 0
    for edge in edges:
        own = {str(member.node_id) for member in getattr(edge, "members", ())}
        if len(own & wanted) >= 2:
            multi += 1
    return multi, len(edges)


def main() -> int:
    print(f"{'top_k':>5} {'rule':>4} {'cases':>5} | "
          f"{'plan tok':>8} {'shot tok':>9} | {'边命中≥2槽':>10} {'卡命中':>7} {'案例':>4}")
    for top_k in (5, 10, 15, 20, 30, 50):
        for rule_top_k in (5, 8):
            for cases_top_k in (3, 5):
                retriever = make(top_k, rule_top_k, cases_top_k)
                sizes = []
                for scope, query in QUERIES:
                    block = (retriever.block_for_plan(query) if scope == "plan"
                             else retriever.block_for_shot(query, analogy=query))
                    sizes.append(estimate_tokens(block))
                plan_tok, shot_tok = sizes[0], max(sizes[1:])
                edges = retriever.hypergraph_edges(
                    QUERIES[1][1], top_k=top_k, token_limit=50000, scope="shot")
                multi, total = precision_of(edges, QUERIES[1][1])
                values = [v for vs in parse_query(QUERIES[1][1]).values() for v in vs]
                cards = retriever.retrieve(QUERIES[1][1], top_k=top_k) or []
                hit = sum(1 for card in cards
                          if any(v in (getattr(card, "content", "") or "")
                                 for v in values))
                cases = len(retriever._last_cases or []) if hasattr(
                    retriever, "_last_cases") else 0
                print(f"{top_k:>5} {rule_top_k:>4} {cases_top_k:>5} | "
                      f"{plan_tok:>8} {shot_tok:>9} | "
                      f"{multi:>3}/{total:<6} {hit:>3}/{len(cards):<3} {cases:>4}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
