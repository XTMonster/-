"""这一轮真实运行里，**被注入的那些边**到底带了哪些 kind？（解释 vocabulary_gap 的空集合）"""

from __future__ import annotations

import collections
import io
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

edges = {}
for line in (ROOT / "knowledge/hypergraph.edges.jsonl").read_text(encoding="utf-8").split("\n"):
    line = line.strip()
    if line:
        row = json.loads(line)
        edges[str(row.get("edge_id"))] = row

kinds = collections.Counter()
types = collections.Counter()
for line in (ROOT / "docs/evidence/20261006-long21/audit_log.jsonl").read_text(
        encoding="utf-8").split("\n"):
    line = line.strip()
    if not line:
        continue
    row = json.loads(line)
    if str(row.get("kind")) != "retrieval_call":
        continue
    for edge_id in (row.get("data") or {}).get("edge_ids") or []:
        edge = edges.get(str(edge_id))
        if edge is None:
            kinds["<missing>"] += 1
            continue
        types[str(edge.get("type"))] += 1
        for member in edge.get("members") or []:
            kinds[str(member[1])] += 1
print("injected edge types:", dict(types))
print("injected member kinds:", dict(kinds.most_common()))
