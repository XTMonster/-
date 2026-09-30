"""Shared test helper: build a tiny hypergraph index from a held-out fixture.

Gate ⑪ (`tools/check_holdout.py`) asks the *index* whether every
`must`/`top1`/`never` in a fixture really exists, so any test that runs the
gates to completion needs an index to judge against. Deriving it from the
fixture's own specs (instead of hand-writing edges) keeps the two from
drifting apart: the index can only be wrong if the fixture is.

This lives in one place on purpose - two copies of it would be exactly the
"each side keeps its own schema" drift that v1.5's single-source rule forbids.
"""
from __future__ import annotations

import json
import pathlib
import sys
from typing import List, Sequence, Tuple

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import check_holdout  # noqa: E402


def write_index(dirpath: pathlib.Path,
                records: Sequence[dict]) -> Tuple[pathlib.Path, pathlib.Path]:
    """Write `index.nodes.jsonl` / `index.edges.jsonl` under ``dirpath``."""
    nodes: dict = {}
    edges: dict = {}
    for rec in records:
        for spec in (list(rec.get("must") or []) + list(rec.get("top1") or [])
                     + list(rec.get("never") or [])):
            try:
                etype, plain, forbid = check_holdout.parse_spec(spec)
            except check_holdout.EntryError:
                continue          # deliberately broken entries go to the other gates
            members = []
            for kind, value in plain.items():
                node_id = f"{kind}:{value}"
                nodes[node_id] = {"record": "node", "node_id": node_id,
                                  "type": kind, "name": value, "aliases": [],
                                  "value": value}
                role = "allow" if kind in check_holdout.NODE_KINDS else "qualifier"
                members.append([role, kind, node_id])
            for kind, value in forbid.items():
                node_id = f"{kind}:{value}"
                nodes[node_id] = {"record": "node", "node_id": node_id,
                                  "type": kind, "name": value, "aliases": [],
                                  "value": value}
                members.append(["forbid", kind, node_id])
            members.sort()
            edges[(etype, tuple(map(tuple, members)))] = {
                "record": "edge", "type": etype, "members": members,
                "source_kind": "theory", "hardness": "hard"}
    nodes_path = dirpath / "index.nodes.jsonl"
    edges_path = dirpath / "index.edges.jsonl"
    nodes_path.write_text("\n".join(json.dumps(v, ensure_ascii=False)
                                    for v in nodes.values()) + "\n", encoding="utf-8")
    edges_path.write_text("\n".join(json.dumps(v, ensure_ascii=False)
                                    for v in edges.values()) + "\n", encoding="utf-8")
    return nodes_path, edges_path


def index_args(dirpath: pathlib.Path, records: Sequence[dict]) -> List[str]:
    nodes_path, edges_path = write_index(dirpath, records)
    return ["--nodes", str(nodes_path), "--edges", str(edges_path)]


def read_jsonl(path: pathlib.Path) -> List[dict]:
    return [json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]
