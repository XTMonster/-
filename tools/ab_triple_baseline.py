"""v1.4 §2.3d T2：超图 vs 二元三元组的对照（**不作验收门，只留档**）。

把每条超边拆成若干**二元**边（一条 allow ＋ 一个 forbid 伙伴），用**同一套**
注入器（`knowledge.hypergraph.render_edges`）、同一份查询、同一个 top_k 与
同一个 token 预算各跑一遍，比较：

* ``dropped_forbid_members_per_query``（主统计量）：超图应恒为 0，
  三元组通常 > 0——因为它的 allow/forbid 分散在多条会被预算截掉的边里；
* ``delta_Q2`` / ``delta_Q6b``：命中率与"n 元约束完整率"的差值。

**诚实口径**（§2.3）：收益只在"注入预算 < 需求"时体现；预算足够时三元组也能
拿满分，``Δ ≈ 0`` 并不说明超图没用。所以本脚本只输出数字，不设通过线。

用法：
  python tools/ab_triple_baseline.py --holdout fixtures/knowledge_holdout.jsonl \
      [--out docs/evidence/<run-id>/ab_triple.json]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_scorer():
    spec = importlib.util.spec_from_file_location(
        "bd_holdout_score", ROOT / "tools" / "holdout_score.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def split_into_triples(graph, *, allow_kinds: Sequence[str] = ("allow",)):
    """把每条超边拆成"一个 allow 成员 ＋ 每个 forbid 成员"的二元边。

    这正是三元组图的形态：约束被拆散、检索时容易丢成员。
    """
    from block_director.knowledge.hypergraph import HyperEdge, Hypergraph

    triples: List[HyperEdge] = []
    for edge in graph.edges:
        allows = [m for m in edge.members if m.role in allow_kinds]
        forbids = [m for m in edge.members if m.role == "forbid"]
        qualifiers = [m for m in edge.members if m.role == "qualifier"]
        if not allows:
            continue
        partners = forbids or [None]
        for allow in allows:
            for forbid in partners:
                members = [allow] + ([forbid] if forbid is not None else [])
                members += [m for m in qualifiers if m.role == "qualifier"]
                triples.append(HyperEdge(
                    type=str(edge.type), members=tuple(members),
                    source_kind=edge.source_kind, hardness=edge.hardness,
                    weight=edge.weight, confidence=edge.confidence,
                    confidence_max=edge.confidence_max,
                    occurrences=edge.occurrences, sources=tuple(edge.sources),
                    source_span=dict(edge.source_span),
                    extractor=dict(edge.extractor),
                    provenance_kind=edge.provenance_kind))
    return Hypergraph(list(graph.nodes.values()), triples)


def dropped_forbid_members(graph, entries, *, top_k: int = 3,
                           token_limit: int = 2000) -> int:
    """统计"因预算被整条丢弃的、带 forbid 成员的边"数量（主统计量）。"""
    total = 0
    for entry in entries:
        query = str(entry.get("q") or "")
        if not query:
            continue
        edges, _text, trace = graph.retrieve(query, top_k=top_k,
                                             token_limit=token_limit)
        dropped = set(getattr(trace, "dropped_edge_ids", []) or [])
        total += sum(1 for edge in edges
                     if edge.edge_id in dropped
                     and any(m.role == "forbid" for m in edge.members))
    return total


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="ab_triple_baseline")
    parser.add_argument("--holdout", default="fixtures/knowledge_holdout.jsonl")
    parser.add_argument("--nodes", default="knowledge/hypergraph.nodes.jsonl")
    parser.add_argument("--edges", default="knowledge/hypergraph.edges.jsonl")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--token-limit", type=int, default=2000)
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv[1:] if argv else sys.argv[1:])

    scorer = _load_scorer()
    graph = scorer.load_graph(ROOT / args.nodes, ROOT / args.edges)
    entries = scorer.load_holdout(ROOT / args.holdout)
    if not entries:
        print("[INCOMPLETE] held-out 为空：对照无法判定（不得据此下结论）")
        return 1

    hyper = scorer.score_entries(entries, graph, top_k=args.top_k,
                                 token_limit=args.token_limit)
    triples = split_into_triples(graph)
    triple = scorer.score_entries(entries, triples, top_k=args.top_k,
                                  token_limit=args.token_limit)

    def value(report, metric_id):
        for item in report["metrics"]:
            if item["id"] == metric_id:
                return item["value"]
        return None

    report: Dict[str, Any] = {
        "queries": hyper["queries"],
        "top_k": args.top_k,
        "token_limit": args.token_limit,
        "edges": {"hypergraph": len(graph.edges), "triples": len(triples.edges)},
        "dropped_forbid_members_per_query": {
            "hypergraph": dropped_forbid_members(
                graph, entries, top_k=args.top_k,
                token_limit=args.token_limit),
            "triples": dropped_forbid_members(
                triples, entries, top_k=args.top_k,
                token_limit=args.token_limit),
        },
        "Q2": {"hypergraph": value(hyper, "Q2"), "triples": value(triple, "Q2")},
        "Q6b": {"hypergraph": value(hyper, "Q6b"), "triples": value(triple, "Q6b")},
        "note": ("§2.3d T2：不设通过线。收益只在预算不足时体现；"
                 "预算足够时三元组也能满分，Δ≈0 不说明超图无用。"),
    }
    report["delta_Q2"] = _delta(report["Q2"])
    report["delta_Q6b"] = _delta(report["Q6b"])
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    return 0


def _delta(pair: Dict[str, Any]):
    left, right = pair.get("hypergraph"), pair.get("triples")
    if left is None or right is None:
        return None
    return round(float(left) - float(right), 4)


if __name__ == "__main__":
    sys.exit(main())
