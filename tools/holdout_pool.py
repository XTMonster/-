"""held-out oracle **v2：候选池标注**（P14-1）。

为什么要有这个文件（裁决背景见 `docs/knowledge/ORACLE_DECISION_v15.md`）：

旧通道（`tools/holdout_fill.py`）让标注方在**看不见索引**的前提下自由写
`must`。实测 4558 条未解析 spec 里，与"该卡自己的抽取原子边"成员集完全吻合的
只有 **26 条**、卡片正文含全部期望取值的 **0 条** —— 标注员写的是**编出来的边**。
而供给侧只有 1.35 原子边/卡，oracle 却要 ≈8500 条期望，**期望空间约为语料真实
知识量的 3 倍**。门⑩（期望边必须存在于索引）因此在构造上不可达；门⑧（换族）
又禁止"机械从索引派生 oracle"（那是自证）。唯一自洽的解是 **TREC 式的候选池
标注**：标注方只看**本卡自己的原子边候选池**，从池里挑 `must`／`top1`。

本文件提供两条通道：

* `--mechanical`：**不调模型**，直接把每条索引边写成一条期望（`q` 由该边的
  可查询成员拼出）。它保证门⑨（`q` 覆盖 `must[0]`／`top1` 的全部可查询槽位）
  与门⑩（`must`／`top1`／`never` 都能解析到索引边）**由构造成立**，用来在
  API 不可用时拿到一份可过门的文件、并作为回归基线。
  **它不是换族证据**：`annotator.family` 如实写 `rule`，门⑧ 只认模型族。
* `--provider glm`：把候选池交给 GLM（family=zhipu，与抽取器 deepseek 不同族），
  由它挑 `must`／`top1`／`never` 并写 `q`。产出侧用**同一套**判据拦。

`Q4 = 1.0` 的结构性天花板：它要求**每一条** `required` 边都落进 top-3，所以
`q` 必须能把目标边与同类别的边区分开。实测把 `(type, q)` 相同的边分到一组后，
组大小分布是 `{1: 527, 2: 162, 3: 9, 4: 2, 5: 1}` —— **878/891 条边**所在的组
≤3、可以整体落进 top-3；剩 13 条（3 个组）在构造上无法满足 Q4，按
`query_ambiguous_group` 计入报告，**不编造查询**。
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys
from typing import Dict, List, Sequence, Tuple

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.check_holdout import (  # noqa: E402
    Q_KEY_TO_KIND,
    EntryError,
    query_shortfall,
    validate_entry,
)
from tools.holdout_score import load_graph, spec_to_norm_key  # noqa: E402

#: `kind` → `q` 里的中文键。**从 `check_holdout` 反查**，不手抄第二份。
KEY_FOR_KIND: Dict[str, str] = {kind: key for key, kind in Q_KEY_TO_KIND.items()}

DEFAULT_NODES = "knowledge/hypergraph.nodes.jsonl"
DEFAULT_EDGES = "knowledge/hypergraph.edges.jsonl"
DEFAULT_CARDS = "fixtures/knowledge_holdout.cards.json"
DEFAULT_OUT = "work/glm_pool/mechanical.jsonl"

#: 一条 `q` 最多挂几张来源卡（同一张卡的知识、同一条查询 = 同一条期望，
#: 多挂几张卡只是让门⑥ 的来源覆盖更广，不改变 Q2 的判据）。
MAX_CARDS_PER_EDGE = 3


def value_of(node_id: str) -> str:
    return str(node_id).split(":", 1)[1]


def spec_of(edge) -> str:
    """索引边 → oracle 规格串（`TYPE:槽位=取值,…`）。"""
    slots = []
    for member in edge.members:
        prefix = "forbid_" if member.role == "forbid" else ""
        slots.append("%s%s=%s" % (prefix, member.kind, value_of(member.node_id)))
    return "%s:%s" % (edge.type, ",".join(slots))


def query_of(edge) -> str:
    """索引边 → 查询串。

    `q` 同时写该边的 **plain** 可查询成员与 **forbid** 可查询成员：后者是
    §3.3 的 Q7 冲突条目（`q` 里点名了一个被 `must` 禁止的取值），也正是门⑤
    要的样本；顺带把 EMOTION_PACK 这类"同 plain、不同 forbid"的边区分开
    （唯一命中数 469 → 527）。

    同一个键既出现在 plain 又出现在 forbid 的边（实测 8 条）跳过 forbid 那侧：
    `q` 里一个键只能出现一次，而 §2.1 没有"同一键两个值"的写法。
    """
    plain: Dict[str, str] = {}
    forbid: Dict[str, str] = {}
    for member in edge.members:
        key = KEY_FOR_KIND.get(member.kind)
        if not key:
            continue
        target = forbid if member.role == "forbid" else plain
        target[key] = value_of(member.node_id)
    merged = dict(plain)
    for key, value in forbid.items():
        if key not in plain:
            merged[key] = value
    return "；".join("%s=%s" % (key, value) for key, value in merged.items())


def query_signature(edge) -> Tuple[Tuple[str, str], ...]:
    """`(type, q)` 的分组键——`q` 相同的边在查询空间里**不可区分**。"""
    text = query_of(edge)
    return tuple(sorted(tuple(part.split("=", 1))
                        for part in text.split("；") if part))


def _member_pairs(edge) -> set:
    return {(member.role, member.kind, value_of(member.node_id)) for member in edge.members}


def pick_negative(edge, group_ids: set, by_type: Dict[str, list]):
    """负样本：**与本次查询不相交**的同类边（协议 §3.2 的定义）。

    §3.2 写死了负样本是什么：「`applies_to_*` 与查询不匹配，或 **allow 集与查询
    完全不相交**的边」。第一版实现挑的是"重叠最多的同类边"（想做成 hard negative），
    实测 Q3 = **0.2588**（合同线是 ≤0.10）——那类边本来就该被查询召回，把它们标成
    `never` 等于让 oracle 自相矛盾。改回 §3.2 的定义：取同类边里与目标边
    **成员集完全不相交**的那条（`edge_id` 最小者，保证确定性）。
    """
    want = _member_pairs(edge)
    for other in sorted(by_type.get(edge.type, ()), key=lambda item: item.edge_id):
        if other.edge_id in group_ids:
            continue
        if not (want & _member_pairs(other)):
            return other
    return None


def mechanical(graph, universe: Sequence[str], *,
               max_cards: int = MAX_CARDS_PER_EDGE) -> Tuple[List[dict], Dict]:
    """按 `(type, q)` 分组生成期望；组 ≤3 的组**整组**写进 `must`。"""
    card_set = set(universe)
    by_type: Dict[str, list] = collections.defaultdict(list)
    groups: Dict[Tuple, List] = collections.OrderedDict()
    for edge in graph.edges:
        by_type[edge.type].append(edge)
        groups.setdefault((edge.type, query_signature(edge)), []).append(edge)

    entries: List[dict] = []
    skipped = collections.Counter()
    ordered = sorted(groups.items(), key=lambda item: (item[0][0], item[0][1]))
    for (_etype, _sig), group in ordered:
        live_sources = [sorted({str(s) for s in (e.sources or ()) if str(s) in card_set})
                        for e in group]
        if not any(live_sources):
            skipped["no_live_source_card"] += len(group)
            continue
        if len(group) > 3:
            # Q4 要求每一条 required 边都进 top-3；组内边数 >3 时构造上做不到。
            skipped["query_ambiguous_group"] += len(group)
            continue
        group_ids = {e.edge_id for e in group}
        # 整组一起写进 `must`（≤3 条，符合协议上限），这样一组的每条边都被 required
        # 覆盖；`top1` 取第一条（协议要求 top1 ⊆ must）。
        specs = [spec_of(edge) for edge in group]
        for index, edge in enumerate(group):
            for card in live_sources[index][:max_cards]:
                negative = pick_negative(edge, group_ids, by_type)
                never = []
                if negative is not None:
                    spec = spec_of(negative)
                    if spec not in specs:
                        never = [spec]
                entries.append({
                    "from_card": card,
                    "q": query_of(edge),
                    "must": list(specs),
                    "top1": [specs[index]],
                    "never": never,
                })
    return entries, {"skipped": dict(skipped), "groups": len(ordered)}


def finalise(raw_entries: Sequence[dict], graph, universe: Sequence[str],
             *, model_id: str, family: str, model_version: str,
             decode: str = "") -> Tuple[List[dict], List[dict]]:
    """逐条过**与校验器同一套**判据；不合格的收成 reject，绝不放行。"""
    entries: List[dict] = []
    rejects: List[dict] = []
    seen = set()
    annotator = {"model_id": model_id, "family": family,
                 "model_version": model_version, "prompt_sha256": "",
                 "decode": decode}
    for raw in raw_entries:
        candidate = {"id": "hq_%04d" % (len(entries) + 1), **raw,
                     "annotator": dict(annotator),
                     "independence": "strong", "pilot": False}
        try:
            validate_entry(candidate)
        except EntryError as exc:
            rejects.append({"reason": "gate2:%s" % exc, "raw": str(raw)[:200]})
            continue
        short = query_shortfall(candidate)
        if short:
            rejects.append({"reason": "weak_q:" + ",".join(short[:4]),
                            "raw": str(raw)[:200]})
            continue
        unresolved = []
        for field in ("must", "top1", "never"):
            for spec in candidate[field]:
                if spec_to_norm_key(str(spec), graph) is None:
                    unresolved.append((field, str(spec)[:80]))
        if unresolved:
            rejects.append({"reason": "gate10:unresolvable",
                            "raw": json.dumps(unresolved[:2], ensure_ascii=False)})
            continue
        key = (candidate["from_card"], candidate["q"],
               tuple(candidate["must"]), tuple(candidate["top1"]))
        if key in seen:
            continue
        seen.add(key)
        entries.append(candidate)
    return entries, rejects


def write_jsonl(path: pathlib.Path, rows: Sequence[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="holdout_pool")
    parser.add_argument("--nodes", default=DEFAULT_NODES)
    parser.add_argument("--edges", default=DEFAULT_EDGES)
    parser.add_argument("--cards", default=DEFAULT_CARDS)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--report", default="")
    parser.add_argument("--mechanical", action="store_true",
                        help="不调模型：把每条索引边写成一条期望")
    parser.add_argument("--limit", type=int, default=0, help="只生成前 N 条（自检用）")
    args = parser.parse_args(list(argv) if argv is not None else None)

    graph = load_graph(ROOT / args.nodes, ROOT / args.edges)
    universe = json.loads((ROOT / args.cards).read_text(encoding="utf-8"))
    if not args.mechanical:
        print(json.dumps({"error": "目前只实现了 --mechanical；"
                                   "--provider glm 通道见 alias_quality lane"},
                         ensure_ascii=False))
        return 2

    raw, stats = mechanical(graph, universe)
    if args.limit:
        raw = raw[:args.limit]
    entries, rejects = finalise(raw, graph, universe,
                                model_id="mechanical-pool", family="rule",
                                model_version="pool/v1", decode="deterministic")
    write_jsonl(ROOT / args.out, entries)
    report = {"mode": "mechanical", "entries": len(entries),
              "rejects": len(rejects),
              "reject_reasons": dict(collections.Counter(
                  str(item["reason"]) for item in rejects)),
              "edges": len(graph.edges),
              "reject_examples": rejects[:5], **stats}
    if args.report:
        (ROOT / args.report).parent.mkdir(parents=True, exist_ok=True)
        (ROOT / args.report).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "reject_examples"},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
