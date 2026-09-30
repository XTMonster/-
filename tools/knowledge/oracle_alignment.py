"""量 oracle 与索引的**对齐度**：标注写下的期望边，索引里到底有没有。

为什么需要这个工具：held-out 的 `must` 是**看不到索引**的标注员写的，而门⑪现在
要求 `norm_key` **完全相等**。两者天生错位——实测（2026-10-01）：旧一轮 oracle
的 `must` 只有 31% 能在当前索引里解析，针对当前词表**新写**的条目也只有 55–59%。
天花板一旦在 0.3–0.6，Q1/Q2/Q4/Q6b 再怎么调排序都过不了线。

这里把三种关系分开报，谁都别替谁做决定：

* `exact`   —— 成员集完全相等（**当前门⑪的口径**）；
* `subset`  —— 索引那条边的 plain 成员 ⊇ 标注的 plain 成员，且 forbid 集相等
  （标注方提出的是"至少要含这些约束"的下界）；
* `card_subset` —— 在 `subset` 之上再要求**这条边来自同一张卡**。
  这才是"这张卡表达的知识在索引里有没有边"的原话：它仍然不是同义反复——
  标注方依旧看不到抽取器选了哪些成员，只是把"必须覆盖我写的成员"当作下界。

    python tools/knowledge/oracle_alignment.py --holdout fixtures/knowledge_holdout.jsonl
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Dict, List, Sequence, Tuple

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.check_holdout import EntryError, parse_spec  # noqa: E402

DEFAULT_HOLDOUT = ROOT / "fixtures" / "knowledge_holdout.jsonl"
DEFAULT_EDGES = ROOT / "knowledge" / "hypergraph.edges.jsonl"
RELATIONS = ("exact", "subset", "card_subset")


def node_id(kind: str, value: str) -> str:
    return f"{kind}:{value}"


def load_edges(path: pathlib.Path | str = DEFAULT_EDGES) -> List[Dict]:
    rows = []
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def edge_members(edge: Dict) -> Tuple[Dict[str, str], Dict[str, str]]:
    """返回 (plain, forbid)，键都是 `(kind, value)`。"""
    plain: Dict[str, str] = {}
    forbid: Dict[str, str] = {}
    for role, kind, ident in edge.get("members") or []:
        kind, _, value = str(ident).partition(":")
        target = forbid if str(role) == "forbid" else plain
        target[(str(kind), str(value))] = str(role)
    return plain, forbid


def covers(edge: Dict, etype: str, plain: Dict[str, str],
           forbid: Dict[str, str]) -> bool:
    if str(edge.get("type")) != etype:
        return False
    have_plain, have_forbid = edge_members(edge)
    # `forbid` 是 {kind: value}，`have_forbid` 是 {(kind, value)}——两侧要同构
    # 才能比较（这里曾经直接 `set(dict)`，比的是键，禁集合非空时判据恒假）。
    want_forbid = {(kind, value) for kind, value in forbid.items()}
    if want_forbid != set(have_forbid):
        return False
    want = {(kind, value) for kind, value in plain.items()}
    return want <= set(have_plain)


def match(entry: Dict, spec: str, edges: Sequence[Dict]) -> Dict[str, bool]:
    try:
        etype, plain, forbid = parse_spec(spec)
    except EntryError:
        return {relation: False for relation in RELATIONS}
    want_plain = {(kind, value) for kind, value in plain.items()}
    want_forbid = {(kind, value) for kind, value in forbid.items()}
    card = str(entry.get("from_card", ""))
    out = {relation: False for relation in RELATIONS}
    for edge in edges:
        if str(edge.get("type")) != etype:
            continue
        have_plain, have_forbid = edge_members(edge)
        if want_plain == set(have_plain) and want_forbid == set(have_forbid):
            out["exact"] = True
        if covers(edge, etype, plain, forbid):
            out["subset"] = True
            if card and card in [str(item) for item in edge.get("sources") or []]:
                out["card_subset"] = True
        if all(out.values()):
            break
    return out


def run(entries: Sequence[Dict], edges: Sequence[Dict]) -> Dict:
    totals = {"entries": len(entries), "edges": len(edges)}
    must_hits = {relation: 0 for relation in RELATIONS}
    must_total = 0
    top1_hits = {relation: 0 for relation in RELATIONS}
    top1_total = 0
    entries_covered = {relation: 0 for relation in RELATIONS}
    examples = []
    for entry in entries:
        specs = list(entry.get("must") or [])
        must_total += len(specs)
        covered = {relation: False for relation in RELATIONS}
        for spec in specs:
            result = match(entry, spec, edges)
            for relation, ok in result.items():
                must_hits[relation] += 1 if ok else 0
                covered[relation] = covered[relation] or ok
            if not any(result.values()) and len(examples) < 5:
                examples.append({"id": str(entry.get("id")), "must": spec})
        for relation, ok in covered.items():
            entries_covered[relation] += 1 if ok else 0
        for spec in entry.get("top1") or []:
            top1_total += 1
            result = match(entry, spec, edges)
            for relation, ok in result.items():
                top1_hits[relation] += 1 if ok else 0
    totals["must_total"] = must_total
    totals["top1_total"] = top1_total
    totals["must_hits"] = dict(must_hits)
    totals["top1_hits"] = dict(top1_hits)
    totals["must_ratio"] = {relation: (must_hits[relation] / must_total) if must_total else 0.0
                            for relation in RELATIONS}
    totals["top1_ratio"] = {relation: (top1_hits[relation] / top1_total) if top1_total else 0.0
                            for relation in RELATIONS}
    totals["ceiling_Q2"] = {relation: (entries_covered[relation] / len(entries))
                            if entries else 0.0 for relation in RELATIONS}
    totals["unmatched_examples"] = examples
    return totals


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="oracle_alignment")
    parser.add_argument("--holdout", default=str(DEFAULT_HOLDOUT))
    parser.add_argument("--edges", default=str(DEFAULT_EDGES))
    parser.add_argument("--json", default="")
    args = parser.parse_args(list(argv) if argv is not None else None)

    entries = [json.loads(line) for line in
               pathlib.Path(args.holdout).read_text(encoding="utf-8").splitlines()
               if line.strip()]
    report = run(entries, load_edges(args.edges))
    if args.json:
        pathlib.Path(args.json).write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8", newline="\n")
    print(json.dumps({key: value for key, value in report.items()
                      if key != "unmatched_examples"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover - 开发侧度量工具
    raise SystemExit(main())
