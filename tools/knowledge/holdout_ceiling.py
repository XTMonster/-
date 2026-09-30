"""RK-13 的**可达上限**（ceiling）探针：这些线到底能不能被任何检索器达到。

`tools/holdout_score.py` 量的是**实际**值；本脚本量的是**上限**——把检索排序换成
一个"永远猜对"的神谕排序器之后，Q1/Q2/Q4/Q6b 各自最高能到多少。两者的差额把
"检索器还能改进多少"和"这条线在当前 oracle／索引下根本不可达"彻底分开。

每个上限的口径（分子都只依赖 oracle×索引的**同构程度**，与排序无关）：

* ``ceiling(Q1)`` = 期望 top-1 边存在且**能进候选集**的 query 数 / query 数；
* ``ceiling(Q2)`` = 至少有 1 条 required 边能进候选集的 query 数 / query 数；
* ``ceiling(Q4)`` = 能在索引里找到对应边的 required 边数 / ``Σ_q |required(q)|``；
* ``ceiling(Q6b)`` = 同 ``ceiling(Q4)``（注入前必须先有这条边）。

**为什么必须有它**：`holdout_score` 报的下限（Q1 0.14 之类）看起来像"排序不行"，
于是很自然会去调权重；但若 ceiling 本身就低于验收线（Q1 0.70／Q2 0.90／
Q4 1.0／Q6b 1.0），那么调排序**永远**到不了线——§2.3 的 Q6b 前置①写明那种情形
是"索引构建失败"，要先修索引，不是先改检索。

纯 stdlib、无 bpy、不联网。

用法::

  python tools/knowledge/holdout_ceiling.py \
      [--holdout fixtures/knowledge_holdout.jsonl] \
      [--nodes knowledge/hypergraph.nodes.jsonl] \
      [--edges knowledge/hypergraph.edges.jsonl] [--json out.json]
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge.hypergraph import Hypergraph, parse_query  # noqa: E402
from tools.holdout_score import (  # noqa: E402
    build_norm_index,
    entry_key,
    load_graph,
    load_holdout,
)

#: 验收线（§2.3 的质量表／§4.1 的 RK-13 行）。**只读，不在这里放行任何东西。**
LINES: Dict[str, float] = {"Q1": 0.70, "Q2": 0.90, "Q4": 1.0, "Q6b": 1.0}


def _floor(numerator: int, denominator: int) -> float:
    """上限是比率型：分母为 0 时按 §4.1b 硬规则 1 记 0（不是 1，也不是 not_measured）。"""
    return round(numerator / denominator, 4) if denominator else 0.0


def measure(graph: Hypergraph, entries: Sequence[dict]) -> Dict[str, Any]:
    """算出四个上限，并把"每条 required 边在索引里找不找得到"分类记清。"""
    norm_index = build_norm_index(graph)
    per_type = collections.Counter(e.type for e in graph.edges)
    must_total = resolvable_must = must_in_candidates = 0
    queries = 0
    top1_total = top1_resolvable = top1_in_candidates = 0
    seed_miss = 0
    by_type: Dict[str, List[int]] = {}

    for entry in entries:
        query = str(entry.get("q") or "")
        if not query:
            continue
        queries += 1
        seeds = graph.seeds_for(parse_query(query))
        if not seeds:
            seed_miss += 1
        candidates = {e.edge_id for e in graph.expand(seeds)[0]} if seeds else set()

        req_ids = set()
        for spec in entry.get("must") or []:
            must_total += 1
            key = entry_key(spec, graph)
            etype = str(spec).split(":", 1)[0]
            row = by_type.setdefault(etype, [0, 0, 0, 0])
            row[0] += 1
            if key is None or key not in norm_index:
                row[3] += 1
                continue
            resolvable_must += 1
            row[1] += 1
            eid = norm_index[key]
            req_ids.add(eid)
            if eid in candidates:
                row[2] += 1
        if req_ids & candidates:
            must_in_candidates += 1

        for spec in entry.get("top1") or []:
            top1_total += 1
            key = entry_key(spec, graph)
            if key is None or key not in norm_index:
                continue
            top1_resolvable += 1
            if norm_index[key] in candidates:
                top1_in_candidates += 1

    ceilings = {
        "Q1": _floor(top1_in_candidates, queries),
        "Q2": _floor(must_in_candidates, queries),
        "Q4": _floor(resolvable_must, must_total),
        "Q6b": _floor(resolvable_must, must_total),
    }
    return {
        "queries": queries,
        "index_edges": len(graph.edges),
        "must_total": must_total,
        "must_resolvable": resolvable_must,
        "top1_total": top1_resolvable,
        "seed_miss_queries": seed_miss,
        "ceilings": ceilings,
        "lines": dict(LINES),
        "ceilings_below_lines": sorted(
            name for name, value in ceilings.items() if value < LINES[name]),
        "edges_per_type": dict(sorted(per_type.items())),
        "must_per_type": {t: {"demanded": r[0], "resolvable": r[1],
                              "in_candidates": r[2], "absent": r[3]}
                          for t, r in sorted(by_type.items())},
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="holdout_ceiling")
    parser.add_argument("--holdout", default="fixtures/knowledge_holdout.jsonl")
    parser.add_argument("--nodes", default="knowledge/hypergraph.nodes.jsonl")
    parser.add_argument("--edges", default="knowledge/hypergraph.edges.jsonl")
    parser.add_argument("--json", default="")
    # 与 `tools/holdout_score.py` 同一约定：传进来的 argv 是**完整**的 sys.argv，
    # 第 0 项是程序名（测试里习惯写 `["prog", ...]`）。
    args = parser.parse_args(argv[1:] if argv else sys.argv[1:])

    holdout = ROOT / args.holdout
    if not holdout.is_file():
        print(json.dumps({"error": f"{args.holdout} 不存在"}, ensure_ascii=False))
        return 2
    entries = load_holdout(holdout)
    if not entries:
        # 空 oracle：上限恒为 0（硬规则 1），而且**不得**当成"还没判"。
        print(json.dumps({"INCOMPLETE": "held-out 为空", "ceilings": {},
                          "ceilings_below_lines": sorted(LINES)}, ensure_ascii=False))
        return 2
    graph = load_graph(ROOT / args.nodes, ROOT / args.edges)
    report = measure(graph, entries)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json:
        Path(args.json).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
