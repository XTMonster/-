"""排序质量独立测量（开发侧）：**查询取自索引本身**时，top-1/top-3 能到多少？

为什么需要它：held-out 的 `q` 是**看不到索引**的标注方写的，实测其 `must` 边
只有 ~37% 进得了候选集（`tools/knowledge/expansion_caps.py`）——那里的 Q1/Q2
测的是"两个盲读者猜得对不对"，不是"排序好不好"。这个工具把查询**从边自己的
成员派生**（检索评测的常规做法：查询取自被索引文档的自身内容），于是候选集
可达性不再是变量，剩下的就纯粹是排序。

两者**必须分开报、不得互相冒充**：

* 独立 oracle 的 Q1/Q2（`tools/holdout_score.py`）：测"召得回吗"；
* 本工具的 Q1/Q2：测"召回了以后排得对吗"。

    python tools/knowledge/ranking_quality.py --limit 300
"""

from __future__ import annotations

import argparse
import json
import pathlib
import random
import sys
from typing import Dict, List, Sequence

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge import hypergraph as hg  # noqa: E402


def load_graph(knowledge_dir: pathlib.Path | str = ROOT / "knowledge") -> hg.Hypergraph:
    root = pathlib.Path(knowledge_dir)
    nodes = [hg.Node.from_dict(json.loads(line)) for line in
             (root / "hypergraph.nodes.jsonl").read_text(encoding="utf-8").splitlines()
             if line.strip()]
    edges = [hg.HyperEdge.from_dict(json.loads(line)) for line in
             (root / "hypergraph.edges.jsonl").read_text(encoding="utf-8").splitlines()
             if line.strip()]
    return hg.Hypergraph(nodes, edges)


def query_for(edge: hg.HyperEdge, nodes: Dict[str, hg.Node],
              key_for: Dict[str, str], wanted: int = 3) -> str:
    """从边的成员派生查询串：只取**有查询键**的成员，最多 `wanted` 个。

    与检索器同一套键（`hg.QUERY_KEYS`），因此能被 `parse_query` 原样解析。
    `wanted` 默认 3（现实中人一次也就写得出两三个约束）；把它调大可以回答
    "再加一个查询键值不值"——**只取前 3 个成员会掩盖新键的价值**（新键可能排在
    第 4 位而被截掉），这正是我先前判错 `强度` 之外的第二个方法学坑。
    """
    pairs: List[str] = []
    for member in edge.members:
        if member.role == "forbid":
            continue
        node = nodes.get(member.node_id)
        key = key_for.get(member.kind)
        if key is None or node is None:
            continue
        value = node.value or node.name
        if value:
            pairs.append(f"{key}={value}")
        if len(pairs) >= wanted:
            break
    return "；".join(pairs)


def run(graph: hg.Hypergraph, limit: int = 300, top_k: int = 3,
        seed: int = 0, members: int = 3) -> dict:
    key_for = {kind: zh for zh, kind in hg.QUERY_KEYS.items()}
    edges = sorted(graph.edges, key=lambda edge: edge.edge_id)
    if limit and limit < len(edges):
        edges = random.Random(seed).sample(edges, limit)
    top1 = top3 = asked = 0
    ranks: List[int] = []
    for edge in edges:
        query = query_for(edge, graph.nodes, key_for, wanted=members)
        if not query:
            continue
        asked += 1
        selected, _text, _trace = graph.retrieve(query, top_k=top_k,
                                                 token_limit=10 ** 6)
        ids = [item.edge_id for item in selected]
        if ids and ids[0] == edge.edge_id:
            top1 += 1
        if edge.edge_id in ids:
            top3 += 1
            ranks.append(ids.index(edge.edge_id) + 1)
    return {"edges_in_index": len(graph.edges), "sampled": len(edges), "queried": asked,
            "top1": top1, "top3": top3,
            "Q1": round(top1 / asked, 4) if asked else 0.0,
            "Q2": round(top3 / asked, 4) if asked else 0.0,
            "mean_rank_when_found": round(sum(ranks) / len(ranks), 3) if ranks else 0.0}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ranking_quality")
    parser.add_argument("--knowledge-dir", default=str(ROOT / "knowledge"))
    parser.add_argument("--limit", type=int, default=300)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--json", default="")
    args = parser.parse_args(list(argv) if argv is not None else None)

    report = run(load_graph(args.knowledge_dir), args.limit, args.top_k, args.seed)
    print(json.dumps(report, ensure_ascii=False))
    if args.json:
        pathlib.Path(args.json).write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - 开发侧度量
    raise SystemExit(main())
