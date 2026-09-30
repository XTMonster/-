"""扩展上限的敏感度探针（开发侧，只读）：放大检索上限能不能把 `must` 边拉进候选集？

结论（2026-10-01 实测，4539 条 held-out × 683 条边的索引）：**几乎不能**。

    baseline（hops 2 / edges 40 / nodes 120）   候选集命中 1703/4539 = 0.375，平均 37 条候选
    上限 ×2                                     0.380，平均 70
    上限 ×4                                     0.380，平均 116
    上限 ×4 ＋ hops 3                           0.386，平均 149

也就是说候选集天花板卡在**种子可达性**上，不在扩展预算上：查询里的取值
（标注方写的）与索引边里的取值（抽取器写的）对不上时，扩多远都到不了。
这条探针的意义是**阻止一个看起来很合理的错误改动**——把上限调大只会
拿精度换 0.5 个百分点。

    python tools/knowledge/expansion_caps.py
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import List, Sequence

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge import hypergraph as hg  # noqa: E402
from tools.holdout_score import spec_to_norm_key  # noqa: E402


def load_graph(knowledge_dir: pathlib.Path | str = ROOT / "knowledge") -> hg.Hypergraph:
    root = pathlib.Path(knowledge_dir)
    nodes = [hg.Node.from_dict(json.loads(line)) for line in
             (root / "hypergraph.nodes.jsonl").read_text(encoding="utf-8").split("\n")
             if line.strip()]
    edges = [hg.HyperEdge.from_dict(json.loads(line)) for line in
             (root / "hypergraph.edges.jsonl").read_text(encoding="utf-8").split("\n")
             if line.strip()]
    return hg.Hypergraph(nodes, edges)


def ceiling(graph: hg.Hypergraph, entries: Sequence[dict]) -> dict:
    hit = 0
    truncated = 0
    sizes: List[int] = []
    for entry in entries:
        seeds = graph.seeds_for(hg.parse_query(str(entry.get("q", ""))))
        if not seeds:
            continue
        candidates, was_truncated = graph.expand(seeds)
        truncated += 1 if was_truncated else 0
        sizes.append(len(candidates))
        wanted = set()
        for spec in entry.get("must") or []:
            key = spec_to_norm_key(spec, graph)
            if key:
                wanted.add(key)
        if any(edge.norm_key in wanted for edge in candidates):
            hit += 1
    return {"entries": len(entries), "hits": hit,
            "ratio": hit / max(1, len(entries)),
            "avg_candidates": (sum(sizes) // max(1, len(sizes))) if sizes else 0,
            "truncated": truncated}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="expansion_caps")
    parser.add_argument("--holdout", default=str(ROOT / "fixtures" / "knowledge_holdout.jsonl"))
    parser.add_argument("--knowledge-dir", default=str(ROOT / "knowledge"))
    parser.add_argument("--json", default="")
    args = parser.parse_args(list(argv) if argv is not None else None)

    entries = [json.loads(line) for line in
               pathlib.Path(args.holdout).read_text(encoding="utf-8").split("\n")
               if line.strip()]
    graph = load_graph(args.knowledge_dir)
    base = (hg.MAX_HOPS, hg.MAX_EDGES_TOTAL, hg.MAX_NODES, hg.MAX_EDGES_PER_NODE)
    rows = [{"label": "baseline", **ceiling(graph, entries)}]
    for factor in (2, 4):
        hg.MAX_HOPS, hg.MAX_EDGES_TOTAL, hg.MAX_NODES, hg.MAX_EDGES_PER_NODE = (
            base[0], base[1] * factor, base[2] * factor, base[3] * factor)
        rows.append({"label": f"caps x{factor}", **ceiling(graph, entries)})
    hg.MAX_HOPS, hg.MAX_EDGES_TOTAL, hg.MAX_NODES, hg.MAX_EDGES_PER_NODE = (
        base[0] + 1, base[1] * 4, base[2] * 4, base[3] * 4)
    rows.append({"label": "caps x4 + 3 hops", **ceiling(graph, entries)})
    for row in rows:
        print("%-16s 候选集命中 %4d/%4d = %.3f | 平均候选 %4d | 触顶 %4d"
              % (row["label"], row["hits"], row["entries"], row["ratio"],
                 row["avg_candidates"], row["truncated"]))
    if args.json:
        pathlib.Path(args.json).write_text(
            json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - 开发侧探针
    raise SystemExit(main())
