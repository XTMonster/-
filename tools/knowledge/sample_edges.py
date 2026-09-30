"""§6 取证：从超图索引里抽 N 条边，渲染成**人可复核**的 JSONL。

为什么要有这个脚本
------------------

§6 的"抽取噪声"一行把取证写成 `tools/knowledge/sample_edges.py --n 30` →
`docs/evidence/<run-id>/edge_spotcheck.jsonl`。**人工复核记录**必须成品可交付，
否则那条缓解措施只是口头承诺。本脚本负责：

1. 读**已入库**的索引（`knowledge/hypergraph.{nodes,edges}.jsonl`）；
2. **分层抽样**——六类边轮转取，保证 `--n 30` 不会因为 `EMOTION_PACK` 占多数
   而把 `AXIS_RULE` 之类一次都不抽到（那样"抽查 30 条"是假覆盖）；
3. 逐条写出**同一套 `render_edge`**（与真正注入模型用的渲染**同源**）、
   解析后的成员名/取值、token 成本、来源，以及**留白的复核字段**
   （`verdict` / `reviewer` / `notes`）——复核者只填这三列。

红线
----

* 抽样**不得**过滤 `forbid` 成员：禁忌恰恰是最该被人看一眼的东西；
* `verdict` 一律写 `null`，**绝不**预填 `"ok"`——预填就是"自证"，违反 §4.1b 硬规则 2。

纯 stdlib、不 import bpy、不联网。

用法::

  python tools/knowledge/sample_edges.py --n 30
  python tools/knowledge/sample_edges.py --n 30 --run-id 20260930-051436
"""

from __future__ import annotations

import argparse
import json
import pathlib
import random
import sys
from datetime import datetime
from typing import Dict, List, Optional, Sequence

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge.hypergraph import (  # noqa: E402
    EDGE_TYPES,
    HyperEdge,
    Node,
    render_edge,
    render_tokens,
)

DEFAULT_NODES = ROOT / "knowledge" / "hypergraph.nodes.jsonl"
DEFAULT_EDGES = ROOT / "knowledge" / "hypergraph.edges.jsonl"


def _read_jsonl(path: pathlib.Path) -> List[Dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n")
            if line.strip()]


def load_index(nodes_path: pathlib.Path,
               edges_path: pathlib.Path) -> "tuple[Dict[str, Node], List[HyperEdge]]":
    """读回索引；缺任一文件即报错（**不**静默返回空——空抽样会假装通过）。"""
    if not nodes_path.is_file():
        raise FileNotFoundError(f"缺节点索引：{nodes_path}")
    if not edges_path.is_file():
        raise FileNotFoundError(f"缺超边索引：{edges_path}")
    nodes = {row["node_id"]: Node.from_dict(row) for row in _read_jsonl(nodes_path)}
    edges = [HyperEdge.from_dict(row) for row in _read_jsonl(edges_path)]
    return nodes, edges


def stratified_sample(edges: Sequence[HyperEdge], n: int,
                      rng: Optional[random.Random] = None) -> List[HyperEdge]:
    """六类边轮转取，直到取满 `n` 条；同类内按 `edge_id` 升序（确定性）。

    轮转而不是"整体随机"：索引里 `EMOTION_PACK` 往往占多数，纯随机抽 30 条
    可能一条 `AXIS_RULE` 都不含——那样"抽查覆盖"是假的。
    """
    buckets: Dict[str, List[HyperEdge]] = {t: [] for t in EDGE_TYPES}
    unknown: List[HyperEdge] = []
    for edge in edges:
        (buckets[edge.type] if edge.type in buckets else unknown).append(edge)
    for bucket in buckets.values():
        bucket.sort(key=lambda e: e.edge_id)
    unknown.sort(key=lambda e: e.edge_id)
    if rng is not None:
        for bucket in buckets.values():
            rng.shuffle(bucket)
        rng.shuffle(unknown)

    order: List[List[HyperEdge]] = [buckets[t] for t in EDGE_TYPES if buckets[t]]
    if unknown:
        order.append(unknown)

    picked: List[HyperEdge] = []
    cursor = 0
    while len(picked) < n and order:
        progressed = False
        for bucket in order:
            if cursor < len(bucket):
                picked.append(bucket[cursor])
                progressed = True
                if len(picked) >= n:
                    break
        if not progressed:
            break
        cursor += 1
    return picked


def spotcheck_row(edge: HyperEdge, nodes: Dict[str, Node]) -> Dict:
    """一行复核记录：渲染文本 ＋ 解析后的成员 ＋ **留白**的裁决列。"""
    rendered = render_edge(edge, nodes)
    members = []
    for member in edge.members:
        node = nodes.get(member.node_id)
        members.append({
            "role": member.role,
            "kind": member.kind,
            "node_id": member.node_id,
            "name": node.name if node else "",
            "value": node.value if node else "",
        })
    return {
        "edge_id": edge.edge_id,
        "type": edge.type,
        "source_kind": edge.source_kind,
        "hardness": edge.hardness,
        "weight": edge.weight,
        "confidence": edge.confidence,
        "occurrences": edge.occurrences,
        "sources": list(edge.sources),
        "source_span": dict(edge.source_span),
        "rendered": rendered,
        "tokens": render_tokens(rendered),
        "members": members,
        "forbid_members": [m["node_id"] for m in members if m["role"] == "forbid"],
        # —— 复核者填的三列；**不预填**，见模块 docstring 的红线 ——
        "verdict": None,
        "reviewer": "",
        "notes": "",
    }


def write_spotcheck(rows: Sequence[Dict], out_path: pathlib.Path) -> pathlib.Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    out_path.write_text(text, encoding="utf-8")
    return out_path


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="sample_edges")
    parser.add_argument("--n", type=int, default=30, help="抽多少条（默认 30，§6）")
    parser.add_argument("--nodes", default=str(DEFAULT_NODES))
    parser.add_argument("--edges", default=str(DEFAULT_EDGES))
    parser.add_argument("--seed", type=int, default=0,
                        help="同类内的抽取顺序；默认 0 = 按 edge_id 升序（完全确定）")
    parser.add_argument("--run-id", default="",
                        help="证据目录名；缺省用当前时间戳")
    parser.add_argument("--out", default="", help="显式输出路径（覆盖 --run-id）")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.n < 1:
        print(json.dumps({"error": "--n 必须 ≥ 1"}, ensure_ascii=False))
        return 2

    nodes, edges = load_index(pathlib.Path(args.nodes), pathlib.Path(args.edges))
    rng = random.Random(args.seed) if args.seed else None
    picked = stratified_sample(edges, args.n, rng)
    rows = [spotcheck_row(edge, nodes) for edge in picked]

    if args.out:
        out_path = pathlib.Path(args.out)
    else:
        run_id = args.run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
        out_path = ROOT / "docs" / "evidence" / run_id / "edge_spotcheck.jsonl"
    write_spotcheck(rows, out_path)

    per_type: Dict[str, int] = {}
    for row in rows:
        per_type[row["type"]] = per_type.get(row["type"], 0) + 1
    print(json.dumps({
        "out": str(out_path),
        "sampled": len(rows),
        "index_edges": len(edges),
        "per_type": per_type,
        "unreviewed": len(rows),
        "max_tokens": max((row["tokens"] for row in rows), default=0),
    }, ensure_ascii=False))
    return 0 if rows else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
