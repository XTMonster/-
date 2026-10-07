"""Stage gate G4: replay the recorded real-run retrieval queries against the
current retrieval stack and measure the forbid guard (FR-9 / B7), plus prove the
ranking did not move (Q1's contract).

Why replay instead of a fresh model run: a model run costs money and its
retrieval queries are a deterministic function of the plan; the frozen runs
recorded their *actual* `retrieval_call` queries in `audit_log.jsonl`, and all
of them pin the SAME index generation the worktree ships
(`c796a5a87018631d…`).  So replaying those queries IS the same-generation
measurement the gate asks for - no LLM involved.

Read-only: it never writes into the runs it reads.
"""

from __future__ import annotations

import collections
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
while not (ROOT / "pyproject.toml").is_file() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge.hypergraph import (  # noqa: E402
    HyperEdge,
    Hypergraph,
    Node,
)

RUNS = ("20261003_chunked_long9", "20261004_chunked_long11",
        "20261004_chunked_long12", "20261006-long21")
TOP_K = 3
TOKEN_LIMIT = 400


def load_index() -> Hypergraph:
    def rows(name: str):
        for line in (ROOT / "knowledge" / name).read_text(
                encoding="utf-8").split("\n"):
            line = line.strip()
            if line:
                yield json.loads(line)

    nodes = [Node.from_dict(item) for item in rows("hypergraph.nodes.jsonl")]
    edges = [HyperEdge.from_dict(item) for item in rows("hypergraph.edges.jsonl")]
    return Hypergraph(nodes, edges)


def recorded_queries(run: str):
    path = ROOT / "docs" / "evidence" / run / "audit_log.jsonl"
    for line in path.read_text(encoding="utf-8").split("\n"):
        line = line.strip()
        if not line:
            continue
        event = json.loads(line)
        if event.get("kind") != "retrieval_call":
            continue
        data = event.get("data") or {}
        query = str(data.get("query") or "")
        if query:
            yield query, [str(e) for e in (data.get("edge_ids") or [])]


def main() -> int:
    graph = load_index()
    summary = {"top_k": TOP_K, "token_limit": TOKEN_LIMIT, "runs": []}
    totals = collections.Counter()

    for run in RUNS:
        seen = set()
        rows = []
        for query, recorded_ids in recorded_queries(run):
            if query in seen:
                continue
            seen.add(query)
            selected, _text, trace = graph.retrieve(
                query, top_k=TOP_K, token_limit=TOKEN_LIMIT)
            current_ids = [edge.edge_id for edge in selected]
            backfilled = set(trace.forbid_backfilled)
            row = {
                "query": query[:60],
                "recorded_top1": recorded_ids[0] if recorded_ids else "",
                "current_top1": current_ids[0] if current_ids else "",
                "top1_preserved": bool(recorded_ids and current_ids
                                       and recorded_ids[0] == current_ids[0]),
                "top1_is_backfilled": bool(current_ids and current_ids[0] in backfilled),
                "forbid_members_seen": int(trace.forbid_members_seen),
                "forbid_backfilled": len(backfilled),
                "recorded_ids": recorded_ids,
                "current_ids": current_ids,
            }
            rows.append(row)

        totals["queries"] += len(rows)
        totals["with_backfill"] += sum(1 for r in rows if r["forbid_backfilled"])
        totals["forbid_members_seen"] += sum(r["forbid_members_seen"] for r in rows)
        totals["backfilled_edges"] += sum(r["forbid_backfilled"] for r in rows)
        totals["top1_preserved"] += sum(1 for r in rows if r["top1_preserved"])
        totals["top1_is_backfilled"] += sum(1 for r in rows if r["top1_is_backfilled"])
        summary["runs"].append({
            "run": run, "queries": len(rows),
            "with_backfill": sum(1 for r in rows if r["forbid_backfilled"]),
            "forbid_members_seen": sum(r["forbid_members_seen"] for r in rows),
            "top1_preserved": sum(1 for r in rows if r["top1_preserved"]),
            "top1_is_backfilled": sum(1 for r in rows if r["top1_is_backfilled"]),
            "details": rows,
        })

    summary["totals"] = dict(totals)
    summary["gate_g4"] = {
        "forbid_members_seen_gt_0": totals["forbid_members_seen"] > 0,
        "ranking_preserved": totals["top1_is_backfilled"] == 0,
    }
    out = Path(__file__).with_name("g4_forbid_guard.json")
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(json.dumps({"totals": summary["totals"],
                      "gate_g4": summary["gate_g4"]}, ensure_ascii=False))
    for block in summary["runs"]:
        print(f"  {block['run']:26} queries={block['queries']:3} "
              f"with_backfill={block['with_backfill']:3} "
              f"forbid_members_seen={block['forbid_members_seen']:3} "
              f"top1_preserved={block['top1_preserved']:3} "
              f"top1_is_backfilled={block['top1_is_backfilled']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
