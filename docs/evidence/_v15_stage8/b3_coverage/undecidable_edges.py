"""Reproduce the per-edge "undecidable" list for B3 (read-only).

Mirrors `tools/knowledge/execution_closure_report.py` by IMPORTING its
`MAPPING` / `NOT_A_CONDITION` (single source of truth - never a second copy),
then walks the run's audit log the same way that tool does.

Usage:
    python docs/evidence/_v15_stage8/b3_coverage/undecidable_edges.py \
        --run docs/evidence/20261006-long21 \
        --edges knowledge/hypergraph.edges.jsonl \
        --out docs/evidence/_v15_stage8/b3_coverage/undecidable_edges.json
"""

from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
while not (ROOT / "pyproject.toml").is_file() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.knowledge.execution_closure_report import (  # noqa: E402
    MAPPING,
    NOT_A_CONDITION,
)


def load_jsonl(path: Path):
    for line in path.read_text(encoding="utf-8").split("\n"):
        line = line.strip()
        if line:
            yield json.loads(line)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--edges", default="knowledge/hypergraph.edges.jsonl")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    index = {}
    for record in load_jsonl(ROOT / args.edges):
        index[str(record.get("edge_id"))] = record

    injected: dict = {}
    for event in load_jsonl(ROOT / args.run / "audit_log.jsonl"):
        data = event.get("data") or {}
        edge_ids = data.get("edge_ids")
        if not edge_ids:
            continue
        key = str(event.get("shot") or data.get("shot_id") or "")
        injected.setdefault(key, []).append(list(edge_ids))

    undecidable: dict = collections.defaultdict(set)
    unmapped_kinds: collections.Counter = collections.Counter()
    for _shot, batches in injected.items():
        for edge_ids in batches:
            for edge_id in edge_ids:
                record = index.get(str(edge_id))
                if record is None:
                    continue
                members = [m for m in (record.get("members") or [])
                           if isinstance(m, (list, tuple)) and len(m) == 3]
                here = [str(m[1]) for m in members
                        if str(m[1]) not in MAPPING
                        and str(m[1]) not in NOT_A_CONDITION]
                if not here:
                    continue
                undecidable[str(edge_id)] = set(here) | undecidable[str(edge_id)]
                for kind in set(here):
                    unmapped_kinds[kind] += 1

    payload = {
        "run": args.run,
        "mapped_kinds": sorted(MAPPING),
        "not_a_condition": sorted(NOT_A_CONDITION),
        "undecidable_edges": len(undecidable),
        "unmapped_member_slots": sum(
            len(kinds) for kinds in undecidable.values()),
        "unmapped_kinds": dict(unmapped_kinds.most_common()),
        "edges": [{"edge_id": edge_id, "unmapped_kinds": sorted(kinds),
                   "type": str((index.get(edge_id) or {}).get("type") or "")}
                  for edge_id, kinds in sorted(undecidable.items())],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(json.dumps({k: v for k, v in payload.items() if k != "edges"},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
