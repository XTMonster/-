"""量一件事：`rag.max_tokens_per_call` / `rag.plan_prefetch_tokens` **到底约束了什么**。

对同一批真实查询，用真语料把三栏渲染两遍（旧上限 vs 用户新给的 5 万/6 万），
比"实际注入的 token"。再把检索宽度（top_k）也抬一档，看上限能不能被填满。
**不调模型**，只用仓库里的超图索引。
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from block_director.contracts.enums import RagBackend          # noqa: E402
from block_director.knowledge.cases import load_index          # noqa: E402
from block_director.knowledge.hypergraph import Hypergraph, HyperEdge, Node  # noqa: E402
from block_director.knowledge.retriever import KnowledgeRetriever  # noqa: E402
from block_director.knowledge.tokens import estimate_tokens    # noqa: E402

LANES = ("【硬约束（禁/许）】", "【经验建议（软）】", "【参考案例（仅参考）】",
         "【卡片正文补充】")


def load_graph() -> Hypergraph:
    nodes = [Node.from_dict(json.loads(line)) for line in
             (ROOT / "knowledge/hypergraph.nodes.jsonl").read_text(
                 encoding="utf-8").split("\n") if line.strip()]
    edges = [HyperEdge.from_dict(json.loads(line)) for line in
             (ROOT / "knowledge/hypergraph.edges.jsonl").read_text(
                 encoding="utf-8").split("\n") if line.strip()]
    return Hypergraph(nodes, edges)


def make(token_limit: int, plan_limit: int, top_k: int, rule_top_k: int):
    cases = load_index(ROOT / "knowledge", backend="hybrid")
    return KnowledgeRetriever(
        cards=[], backend=RagBackend.HYPERGRAPH,
        capabilities=("hypergraph",), hypergraph=load_graph(),
        cases_index=cases, cases_backend="hybrid", top_k=top_k,
        rule_top_k=rule_top_k, token_limit=token_limit,
        plan_token_limit=plan_limit, cases_top_k=3)


QUERIES = [
    ("plan", "景别=LS；运镜=static；景别=CU；运镜=dolly_in；景别=MS；运镜=follow_subject"),
    ("shot", "景别=CU；意图=铺垫；运镜=dolly_in；对白=dialogue"),
    ("shot", "景别=MS；意图=揭示；运镜=固定；对白=dialogue"),
]


def render(retriever, scope: str, query: str) -> str:
    if scope == "plan":
        return retriever.block_for_plan(query)
    return retriever.block_for_shot(query, analogy=query)


def report(label: str, token_limit: int, plan_limit: int, top_k: int,
           rule_top_k: int) -> None:
    retriever = make(token_limit, plan_limit, top_k, rule_top_k)
    print(f"\n== {label}（shot 上限 {token_limit} / plan 上限 {plan_limit} / "
          f"top_k {top_k} / rule_top_k {rule_top_k}）")
    for scope, query in QUERIES:
        block = render(retriever, scope, query)
        lanes = [lane for lane in LANES if lane in block]
        print(f"   {scope:<4} tokens={estimate_tokens(block):>6}  chars={len(block):>6}  "
              f"栏={'/'.join(lane.strip('【】') for lane in lanes) or '（空）'}")


def main() -> int:
    report("旧上限（发货值）", 800, 2000, 5, 5)
    report("只把上限抬到用户要的 5 万/6 万", 50000, 60000, 5, 5)
    report("上限 5 万/6 万 ＋ 检索也放宽（top_k=50）", 50000, 60000, 50, 20)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
