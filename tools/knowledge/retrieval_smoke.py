"""消费侧冒烟：**检索到的超边真的被注入给 LLM 了吗**（开发侧探针，只读）。

索引好不等于知识到得了模型。这个探针按超图后端跑一组查询，打印
检索条数、注入文本长度与 trace 的降级/截断标志。用法：

    python tools/knowledge/retrieval_smoke.py
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Sequence

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.contracts.enums import RagBackend  # noqa: E402
from block_director.knowledge.corpus import CARDS  # noqa: E402
from block_director.knowledge.hypergraph import HyperEdge, Hypergraph, Node  # noqa: E402
from block_director.knowledge.retriever import KnowledgeRetriever  # noqa: E402

QUERIES: Sequence[str] = (
    "情绪=荒诞；强度=high；运镜=固定",
    "构图=rule_of_thirds；景别=MS；机位=低机位",
    "意图=反转；景别=CU；运镜=推镜",
    "特效=impact_frame；音效=低频；运镜=手持",
    "轴线=越轴；景别=MS",
    "节奏=short；平均镜长=<1s",
    "题材=anime；情绪=孤独",
    "光线=逆光；机位=低机位",
)


def load_index(knowledge_dir: pathlib.Path | str = ROOT / "knowledge") -> Hypergraph:
    root = pathlib.Path(knowledge_dir)
    nodes = [Node.from_dict(json.loads(line)) for line in
             (root / "hypergraph.nodes.jsonl").read_text(encoding="utf-8").splitlines()
             if line.strip()]
    edges = [HyperEdge.from_dict(json.loads(line)) for line in
             (root / "hypergraph.edges.jsonl").read_text(encoding="utf-8").splitlines()
             if line.strip()]
    return Hypergraph(nodes, edges)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="retrieval_smoke")
    parser.add_argument("--knowledge-dir", default=str(ROOT / "knowledge"))
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--json", default="")
    args = parser.parse_args(list(argv) if argv is not None else None)

    engine = KnowledgeRetriever(cards=list(CARDS), backend=RagBackend.HYPERGRAPH,
                                capabilities={"hypergraph"},
                                hypergraph=load_index(args.knowledge_dir))
    rows = []
    for query in QUERIES:
        edges = engine.hypergraph_edges(query, top_k=args.top_k)
        block = engine.edge_block(query)
        trace = engine.last_trace or {}
        rows.append({"q": query, "edges": len(edges), "block_chars": len(block),
                     "degraded": bool(trace.get("degraded")),
                     "seed_miss": bool(trace.get("seed_miss")),
                     "expansion_truncated": bool(trace.get("expansion_truncated")),
                     "dropped": len(trace.get("dropped_edge_ids") or [])})
        print("%-34s 检索 %2d 边 | 注入 %4d 字符 | 丢 %d | 降级 %s | seed_miss %s"
              % (query, len(edges), len(block), rows[-1]["dropped"],
                 rows[-1]["degraded"], rows[-1]["seed_miss"]))
    if args.json:
        pathlib.Path(args.json).write_text(
            json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8", newline="\n")
    return 0 if all(row["edges"] for row in rows) else 1


if __name__ == "__main__":  # pragma: no cover - 开发侧探针
    raise SystemExit(main())
