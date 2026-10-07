"""oracle 换代：把**因为剪枝而解析不到**的 spec／条目从 held-out 里去掉。

## 为什么需要它（2026-10-07，用户"跑吧"授权的那次换代）

零候选槽位的裁决（`docs/evidence/20261007-v15-zerocand-verdict/verdict.json`，
`reviewed_by: "third-party"`）判了 22 个成员"挂错卡／取错值"。执行它要两步：

1. **索引**：`tools/kb_fetch/rebind.py::prune_members` 摘掉这些成员，**并把因此缺
   必填槽位的边整条去掉**（实测 22 摘 ＋ 17 条边整条去——`ACTION_BEAT` 缺 `beat_type`、
   `IMPACT_PACK` 缺 `vfx` 这类边在 schema 上已经不成立）。
2. **oracle**（本工具）：那些边一没，**断言它们的 spec 就永远解析不到**——门⑩ 的红
   就是这么来的（实测 141 条 spec／6 条条目）。判据一个字不许动，所以动的是**夹具**。

## 规则（确定性；判据与门⑩ **同源**）

逐条 spec 判两件事：

* **新索引上解析得到吗**？用的是 `tools.holdout_score.spec_to_norm_key`——**门⑩ 本身
  就是调它判的**（单一真源，不抄第二份逻辑）；
* **剪枝前解析得到吗**？`--edges` 给的是剪枝前的边表；**只在"剪枝前解析得到 ∧ 剪枝后
  解析不到"时才摘**，而且必须能给出裁决出处（spec 里的 `kind=value` 命中哪几条判决）。
  剪枝前本来就解析不到的、以及判决解释不了的，**一律不动**（那是别的历史欠账，
  不许借这次换代顺手处理），只如实报出来。

去掉 spec 之后若 `must` 或 `top1` 空了 ⇒ **整条条目去掉**（每条至少一条 `must`；
`top1` 与条目一一对应）。**id 不重编号**——`third_party.jsonl` 的 212 行按 `entry_id`
引用条目，重编号会把门⑦ 的 join 打断（`tools/knowledge/prune_holdout.py` 那次重编号
是因为它没有下游引用）。

**这不是放宽门**：门限／判据／分母口径一个字没动；被摘的 spec 在**新索引**上构造性
解析不到（门⑩ 逐条报出来的就是它们），而且每一条都带裁决出处。

    git show HEAD:knowledge/hypergraph.edges.jsonl > work/_before.jsonl
    python tools/knowledge/holdout_drop_pruned.py \
        --holdout fixtures/knowledge_holdout.jsonl \
        --verdict docs/evidence/20261007-v15-zerocand-verdict/verdict.json \
        --edges work/_before.jsonl \
        --json docs/evidence/<run>/holdout_drop_pruned.json
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
from tools.holdout_score import load_graph, spec_to_norm_key  # noqa: E402
from tools.kb_fetch import common  # noqa: E402

DEFAULT_HOLDOUT = ROOT / "fixtures" / "knowledge_holdout.jsonl"
DEFAULT_NODES = ROOT / "knowledge" / "hypergraph.nodes.jsonl"
FIELDS = ("must", "top1", "never")


def read_jsonl(path: pathlib.Path) -> List[dict]:
    #: 读 JSONL **只按 `\n` 切**（`str.splitlines()` 会按 Unicode 行边界切，
    #: `\u0085`/`\u2028`/`\u2029` 会把一行切成两行——`tests/test_jsonl_reading_convention.py`
    #: 就是守这条的）。仓库既有的读法在 `common.read_jsonl`。
    return list(common.read_jsonl(path))


def pruned_pairs(verdict: dict, edges: Sequence[dict]
                 ) -> Dict[Tuple[str, str, str], dict]:
    """裁决记录 ＋ 剪枝前的边 → `{(type, kind, value): 裁决行}`（归因用）。"""
    types = {str(edge.get("edge_id")): str(edge.get("type")) for edge in edges}
    out: Dict[Tuple[str, str, str], dict] = {}
    for row in verdict.get("rows") or []:
        if str(row.get("verdict") or "") in ("keep", "missing"):
            continue
        etype = types.get(str(row.get("edge_id")))
        if not etype:
            continue
        out[(etype, str(row.get("kind")), str(row.get("value")))] = row
    return out


def classify_specs(entry: dict, pairs: Dict[Tuple[str, str, str], dict],
                   graph_new, graph_old, *, require_verdict: bool = False
                   ) -> Tuple[List[dict], List[dict], List[dict]]:
    """→ (可摘的 spec, 原样保留的 spec, 解析不到但**不归因于剪枝**的 spec)。"""
    droppable: List[dict] = []
    keep: List[dict] = []
    unexplained: List[dict] = []
    for field in FIELDS:
        for spec in entry.get(field) or []:
            text = str(spec)
            item = {"field": field, "spec": text}
            if spec_to_norm_key(text, graph_new) is not None:
                keep.append(item)
                continue
            if spec_to_norm_key(text, graph_old) is None:
                unexplained.append({**item, "why": "剪枝前就解析不到（不归因于本次换代）"})
                keep.append(item)
                continue
            try:
                etype, plain, forbid = parse_spec(text)
            except EntryError as exc:
                unexplained.append({**item, "why": f"写法不合法：{exc}"})
                keep.append(item)
                continue
            #: 注意**不能**把 plain 与 forbid 合并成一个 dict —— 同 kind 的
            #: `lighting=高调` 与 `forbid_lighting=正面光` 会互相覆盖（实测：
            #: 这正是第一版把 65 条 `LIGHT_PACK` 负例判成"没有对应的裁决行"的原因）。
            candidates = list(plain.items()) + list(forbid.items())
            hits = []
            for kind, value in candidates:
                pair = (etype, kind, value)
                if pair in pairs and (kind, value) not in hits:
                    hits.append((kind, value))
            if not hits and require_verdict:
                unexplained.append({**item, "why": "解析不到，但没有对应的裁决行"})
                keep.append(item)
                continue
            rows = [pairs[(etype, kind, value)] for kind, value in hits]
            droppable.append({**item, "type": etype,
                              "members": [f"{kind}={value}" for kind, value in hits],
                              "verdicts": [{"edge_id": r.get("edge_id"),
                                            "verdict": r.get("verdict"),
                                            "why": r.get("why")} for r in rows],
                              "cause": ("裁决剪枝" if rows else
                                        "索引换代（重抽取后没这条形状）")})
    return droppable, keep, unexplained


def run(holdout: pathlib.Path, verdict_path: pathlib.Path, edges_path: pathlib.Path,
        nodes_path: pathlib.Path = DEFAULT_NODES, *, write: bool = True,
        require_verdict: bool = False) -> dict:
    entries = read_jsonl(holdout)
    pairs = pruned_pairs(json.loads(verdict_path.read_text(encoding="utf-8")),
                         read_jsonl(edges_path))
    graph_new = load_graph(nodes_path, ROOT / "knowledge/hypergraph.edges.jsonl")
    graph_old = load_graph(nodes_path, edges_path)
    kept_entries: List[dict] = []
    report = {"holdout": str(holdout), "verdict": str(verdict_path),
              "edges_before": str(edges_path),
              "require_verdict": require_verdict,
              "pruned_pairs": len(pairs), "before": len(entries),
              "edited_entries": [], "dropped_entries": [], "unexplained": []}
    for entry in entries:
        droppable, keep, unexplained = classify_specs(
            entry, pairs, graph_new, graph_old, require_verdict=require_verdict)
        if unexplained:
            report["unexplained"].append({"id": str(entry.get("id")),
                                          "rows": unexplained})
        if not droppable:
            kept_entries.append(entry)
            continue
        survivors = {field: [row["spec"] for row in keep if row["field"] == field]
                     for field in FIELDS}
        record = {"id": str(entry.get("id")), "from_card": str(entry.get("from_card")),
                  "dropped_specs": droppable}
        if not survivors["must"] or not survivors["top1"]:
            report["dropped_entries"].append({**record, "reason": "must/top1 被摘空"})
            continue
        new_entry = dict(entry)
        for field, specs in survivors.items():
            if field in entry:
                new_entry[field] = specs
        report["edited_entries"].append(record)
        kept_entries.append(new_entry)
    report["kept"] = len(kept_entries)
    if write:
        holdout.write_text("".join(json.dumps(entry, ensure_ascii=False) + "\n"
                                   for entry in kept_entries),
                           encoding="utf-8", newline="\n")
        covered = sorted({str(entry["from_card"]) for entry in kept_entries})
        holdout.with_suffix(".cards.covered.json").write_text(
            json.dumps(covered, ensure_ascii=False, indent=0),
            encoding="utf-8", newline="\n")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="holdout_drop_pruned")
    parser.add_argument("--holdout", default=str(DEFAULT_HOLDOUT))
    parser.add_argument("--verdict", required=True)
    parser.add_argument("--edges", required=True,
                        help="**剪枝前**的边表（`git show HEAD:knowledge/hypergraph.edges.jsonl`）")
    parser.add_argument("--nodes", default=str(DEFAULT_NODES))
    parser.add_argument("--require-verdict", action="store_true",
                        help="只摘「能归因到裁决行」的 spec（默认关：索引换代造成的失效也摘，"
                             "并如实记 cause）")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", default="")
    args = parser.parse_args(list(argv) if argv is not None else None)
    report = run(pathlib.Path(args.holdout), pathlib.Path(args.verdict),
                 pathlib.Path(args.edges), pathlib.Path(args.nodes),
                 write=not args.dry_run,
                 require_verdict=args.require_verdict)
    if args.json:
        pathlib.Path(args.json).write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in report.items()
                      if k not in ("edited_entries", "dropped_entries",
                                   "unexplained")}, ensure_ascii=False))
    for row in report["dropped_entries"]:
        print("  整条去掉:", row["id"], row["from_card"], row["reason"])
    for row in report["edited_entries"]:
        print("  摘 spec:", row["id"],
              [(item["field"], item["spec"], item["members"])
               for item in row["dropped_specs"]])
    for row in report["unexplained"]:
        print("  未归因:", row["id"], [item["spec"] for item in row["rows"]][:2])
    return 0


if __name__ == "__main__":  # pragma: no cover - 开发侧工具
    raise SystemExit(main())
