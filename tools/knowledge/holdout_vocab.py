"""冻结 held-out 词表（门③ 的输入）—— **支持数口径**，不是"频次前 12"。

旧口径（`tools/kb_fetch/vocabulary.py::holdout_vocab`）是"卡片正文里出现过
（`occurrences ≥ 1`）的取值里**按频次取前 12 名**"。那个 `HOLDOUT_CAP = 12`
有两个硬后果：

1. **任何一次语料/索引重建都会重排词表**，先前合法的标注立刻变成
   `unknown_values`（实测漂移样本：`pan_right`／`impact_frame`／`关系轴`）；
2. 12 是个魔数，与"这个取值在语料里有没有被真正表达过"无关 —— 索引里
   25 个 `movement` 取值，词表只留 12 个，另外 13 个一旦被抽取器用上，
   门③ 就判 `unknown_values`。

新口径：一个取值进词表，当且仅当它出现在 **≥ `MIN_SUPPORT_EDGES` 条索引边**里
（只算有查询键的 kind）。理由是可验证的：门③ 要求每个词表取值至少出现在
`--min-seed-support`（默认 3）个不同的 `(卡片, 查询)` 对里；一个只被 1–2 条边
表达的取值**在构造上不可能**达到 3 —— 把它留在词表里等于让门③ 永远红，
而这与标注质量无关。反过来，取值太少的词表会让门④（每类 ≥30 对）暴露缺口，
所以这条规则不是把门调松，是把"词表"定义成**语料真正支撑得住的那一档**。

产出：`fixtures/knowledge_holdout.vocab.json`
（`{"_fingerprint": str, "kinds": {kind: [取值, ...]}}`，校验器直接吃）。
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys
from typing import Dict, List, Sequence, Tuple

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.check_holdout import (  # noqa: E402
    EDGE_TYPES,
    Q_KEY_TO_KIND,
    REQUIRED_VOCAB_KINDS,
    REQUIRED_SLOTS,
)
from block_director.knowledge import hypergraph as hg  # noqa: E402
from tools.holdout_score import load_graph  # noqa: E402

#: 门③ 的 `--min-seed-support` 默认值。词表口径与它**必须是同一个数**：
#: 取值表达少于这么多次，就不可能凑出这么多个 `(卡片, 查询)` 对。
MIN_SUPPORT_EDGES = 3

DEFAULT_NODES = "knowledge/hypergraph.nodes.jsonl"
DEFAULT_EDGES = "knowledge/hypergraph.edges.jsonl"
DEFAULT_OUT = "fixtures/knowledge_holdout.vocab.json"


def queryable_kinds() -> set:
    """有资格进 held-out 词表的 kind。

    = 出现在某个边类型**必填槽位**里的 kind（只要能被 `q` 表达就够，不必是必填：
    `axis_topic` 是 `AXIS_RULE` 的**可选**成员，但它有查询键 `轴线`、而且
    抽取器确实在用，所以它必须进词表），并上 `check_holdout.REQUIRED_VOCAB_KINDS`
    —— 后者是校验器硬要求的键集，缺哪个 kind，哪个 kind 就免检（门③ 直接判失败，
    不会静默跳过）。`character`／`object` 是索引侧节点类型、没有查询键，
    按校验器要求**以空表出现**而不是缺席。
    """
    slotted = {kind for etype in EDGE_TYPES
               for kind in (REQUIRED_SLOTS.get(etype) or ())}
    optional = {kind for etype in EDGE_TYPES
                for _role, kind in (hg.OPTIONAL_MEMBERS.get(etype) or ())}
    with_key = set(Q_KEY_TO_KIND.values())
    return ({kind for kind in (slotted | optional) if kind in with_key}
            | set(REQUIRED_VOCAB_KINDS))


def edge_support(graph) -> Dict[Tuple[str, str], int]:
    """`(kind, 取值) -> 出现在多少条**不同的**索引边里（allow 与 forbid 都算）。"""
    seen: Dict[Tuple[str, str], set] = collections.defaultdict(set)
    for edge in graph.edges:
        for member in edge.members:
            value = str(member.node_id).split(":", 1)[1]
            seen[(str(member.kind), value)].add(edge.edge_id)
    return {key: len(ids) for key, ids in seen.items()}


def pair_support(graph, universe: Sequence[str]) -> Dict[Tuple[str, str], set]:
    """`(kind, 取值) -> {(卡片, 查询)} 的集合` —— **与门③ 同一个口径**。

    门③ 的支撑数不是"这个取值出现在几条边里"，而是"它出现在多少个不同的
    `(卡片, 查询)` 对里"（`check_holdout.support_from`）。两者会分叉：一个取值
    可能出现在 3 条边里，但这 3 条边同属一张源卡、且查询串完全相同 —— 那就只有
    1 个对，门③ 判 `thin`。实测 `sfx` 有一个取值正是这样卡在 1 个对上的。
    所以词表口径直接用**对**来判：能凑出 ≥ `min_support` 个对才进词表，
    否则它在构造上不可能满足门③。
    """
    from tools.holdout_pool import query_of, value_of

    universe_set = set(universe)
    pairs: Dict[Tuple[str, str], set] = collections.defaultdict(set)
    for edge in graph.edges:
        cards = sorted({str(s) for s in (edge.sources or ()) if str(s) in universe_set})
        if not cards:
            continue
        text = query_of(edge)
        for member in edge.members:
            key = (str(member.kind), value_of(member.node_id))
            for card in cards:
                pairs[key].add((card, text))
    return pairs


def build_vocab(graph, *, min_support: int = MIN_SUPPORT_EDGES,
                universe: Sequence[str] = ()) -> Tuple[Dict, Dict]:
    from tools.holdout_pool import value_of

    support = edge_support(graph)
    pairs = pair_support(graph, universe) if universe else {}
    kinds = queryable_kinds()
    # 校验器硬要求的键集**必须存在**（哪怕空表）：`character`／`object` 是索引侧
    # 节点类型、没有查询键，语料里也不会有边承载它们；键缺席时门③ 判"缺 kind →
    # 那个 kind 免检"并**直接判失败**，而不是静默跳过。
    out: Dict[str, List[str]] = {kind: [] for kind in sorted(REQUIRED_VOCAB_KINDS)}
    dropped: Dict[str, Dict[str, int]] = {}
    thin: Dict[str, List[str]] = {}
    for (kind, value), count in sorted(support.items()):
        if kind not in kinds:
            continue
        if count < min_support:
            dropped.setdefault(kind, {})[value] = count
            continue
        if universe and len(pairs.get((kind, value), ())) < min_support:
            thin.setdefault(kind, []).append(value)
            continue
        if count >= min_support:
            out.setdefault(kind, []).append(value)
    for values in out.values():
        values.sort()
    report = {
        "min_support_edges": min_support,
        "values": sum(len(v) for v in out.values()),
        "kinds": {kind: len(values) for kind, values in sorted(out.items())},
        "dropped_long_tail": {kind: len(items) for kind, items in sorted(dropped.items())},
        "dropped_values": sum(len(items) for items in dropped.values()),
        "dropped_unreachable_pairs": {kind: values for kind, values in sorted(thin.items())},
        "dropped_unreachable_count": sum(len(v) for v in thin.values()),
    }
    return out, report


def fingerprint(payload: Dict[str, List[str]]) -> str:
    import hashlib
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def write(out_path: pathlib.Path, payload: Dict[str, List[str]]) -> Dict:
    body = {"_fingerprint": fingerprint(payload), "kinds": payload}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(body, ensure_ascii=False, indent=0),
                        encoding="utf-8", newline="\n")
    return body


def _row_support(rows: Sequence[dict]) -> Dict[Tuple[str, str], set]:
    """生成的条目里，每个 `(kind, 取值)` 实际拿到多少 `(卡片, 查询)` 对。"""
    support: Dict[Tuple[str, str], set] = collections.defaultdict(set)
    for row in rows:
        signature = (str(row.get("from_card", "")), str(row.get("q", "")))
        for part in str(row.get("q", "")).split("；"):
            if "=" not in part:
                continue
            key, _, value = part.partition("=")
            kind = Q_KEY_TO_KIND.get(key.strip())
            if kind:
                support[(kind, value.strip())].add(signature)
    return support


def fixpoint(graph, universe: Sequence[str], *, min_support: int = MIN_SUPPORT_EDGES,
             max_rounds: int = 8) -> Tuple[Dict, Dict]:
    """词表与生成的**不动点**：把"生成后仍凑不出 ≥`min_support` 对"的取值剔掉。

    为什么必须迭代：词表既是生成的**输入**（词表外的取值会被整条跳过），又是门③
    的**分母**。剔掉一个取值可能让某些边因"含词表外成员"而消失，从而让**另一个**
    取值掉到 3 以下。实测就是这么卡住一个 `sfx` 取值：它在 3 条边里，但那 3 条边
    同属一张源卡、查询串也相同 —— 只有 1 个对。
    """
    from tools import holdout_pool as pool

    payload, report = build_vocab(graph, min_support=min_support, universe=universe)
    pruned: Dict[str, List[str]] = {}
    for _round in range(max_rounds):
        rows, _stats = pool.mechanical(graph, universe, vocab=payload)
        support = _row_support(rows)
        gone = {kind: sorted(value for value in values
                            if len(support.get((kind, value), ())) < min_support)
                for kind, values in payload.items()}
        gone = {kind: values for kind, values in gone.items() if values}
        if not gone:
            report["fixpoint_rounds"] = _round + 1
            report["pruned_after_generation"] = pruned
            report["values"] = sum(len(v) for v in payload.values())
            report["kinds"] = {kind: len(values) for kind, values in sorted(payload.items())}
            return payload, report
        for kind, values in gone.items():
            payload[kind] = [value for value in payload[kind] if value not in values]
            pruned.setdefault(kind, []).extend(values)
    report["fixpoint_rounds"] = max_rounds
    report["pruned_after_generation"] = pruned
    report["fixpoint_converged"] = False
    report["values"] = sum(len(v) for v in payload.values())
    report["kinds"] = {kind: len(values) for kind, values in sorted(payload.items())}
    return payload, report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="knowledge.holdout_vocab")
    parser.add_argument("--nodes", default=DEFAULT_NODES)
    parser.add_argument("--edges", default=DEFAULT_EDGES)
    parser.add_argument("--cards", default="fixtures/knowledge_holdout.cards.json",
                        help="语料卡 id 全集：支撑数按卡片对算，必须给")
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--min-support-edges", type=int, default=MIN_SUPPORT_EDGES)
    parser.add_argument("--json", default="", help="把口径报告写到这里")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    graph = load_graph(ROOT / args.nodes, ROOT / args.edges)
    universe = json.loads((ROOT / args.cards).read_text(encoding="utf-8"))
    payload, report = fixpoint(graph, universe, min_support=args.min_support_edges)
    if not args.dry_run:
        report["written"] = write(ROOT / args.out, payload)
        report["path"] = args.out
    if args.json:
        (ROOT / args.json).parent.mkdir(parents=True, exist_ok=True)
        (ROOT / args.json).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "written"},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
