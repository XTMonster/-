"""重算 R3 的"完美重排上限"，并把**同一条命令的重复跑**放在一起报（可复现性判据）。

为什么要有这个工具：`docs/evidence/20261006-e1-ceiling/` 里的上限 **0.7760** 是
**一次跑**手算出来的。同一条命令（同语料、同 64 条冻结查询、同面板、
`--top-k 20`）再跑一次给出 **0.7188**（见 `docs/evidence/20261006-e1-ceiling-noise/`）——
差 **0.0572**，远超 `e1_baseline_summary` 那条"ΔE1 要跟同臂极差一起看"的噪声带。

根因：上限是从 top-K 候选的**尾部**导出的量（每条查询 `min(3, 相关行数)/3` 的均值），
比 top-3 的 E1 对评委在 **4.0 门限**附近的抖动敏感得多——一次 ±0.5 的评分翻转就能让
一条查询在"≥3 相关"与"不足 3"之间跳变，而上限里每条查询值 1.0 或 <1.0，跳一下就是 1/64。

⇒ 这个上限**必须伴着重复跑一起报，单点值不作结论**。本工具把这一步变成可复算的：

* 判据一个字没动：相关 = 两位评委 1–5 分**取均值 ≥ 4.0**（与
  `tools/knowledge/e1_panel.py::RELEVANT`／`e1_baseline_summary.RELEVANT` 同源）；
* 上限 = `mean(min(top_k, 每条查询的相关行数) / top_k)`，`top_k` 默认 3（E1 的 top-k）；
* `e1_top_k_rows` = 把文件**前 top_k 行**当作检索结果时的 E1。打分记录按检索序落盘
  （`e1_panel` 逐查询块写出），所以**未重排**的文件里这个量就是真实 E1；
* 多给几个文件就报**极差**（`range`）——这是判"跑得稳不稳"的唯一依据。

用法：

    python tools/knowledge/e1_ceiling_report.py <reviews.jsonl> [<reviews2.jsonl> ...]
    python tools/knowledge/e1_ceiling_report.py --json <reviews.jsonl> ...
    python tools/knowledge/e1_ceiling_report.py --per-query <reviews.jsonl>
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections import OrderedDict
from typing import Any, Dict, List, Sequence

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.utils.console import force_utf8_streams  # noqa: E402
from tools.kb_fetch.common import read_jsonl  # noqa: E402

#: 判「相关」的下限：与 `e1_panel.RELEVANT`／`e1_baseline_summary.RELEVANT` 同源。
#: 这里**只能**是 4.0——改它就是把 E1 的门限挪走，属于红线。
RELEVANT = 4.0


def _mean_score(row: Dict[str, Any]):
    """取一条记录的评委分：优先信 `score`（面板写入的两位均值），否则自己算。"""
    score = row.get("score")
    if isinstance(score, (int, float)):
        return float(score)
    scores = [float(s) for s in (row.get("scores") or []) if isinstance(s, (int, float))]
    if not scores:
        return None
    return sum(scores) / len(scores)


def _is_relevant(row: Dict[str, Any]) -> bool:
    mean = _mean_score(row)
    return mean is not None and mean >= RELEVANT


def group_by_query(rows: Sequence[Dict[str, Any]]) -> "OrderedDict[str, List[Dict[str, Any]]]":
    """按查询分组，**保持文件里的先后**（`e1_panel` 逐查询块落盘 ⇒ 块内即检索/重排序）。"""
    grouped: "OrderedDict[str, List[Dict[str, Any]]]" = OrderedDict()
    for row in rows:
        grouped.setdefault(str(row.get("query", "")), []).append(row)
    return grouped


def report(rows: Sequence[Dict[str, Any]], top_k: int = 3) -> Dict[str, Any]:
    """一份打分文件 → 一页读数。判据与 `e1_panel`／`e1_baseline_summary` 逐字同源。"""
    if int(top_k) < 1:
        raise ValueError("top_k 必须 >= 1，收到 %r" % (top_k,))
    top_k = int(top_k)
    grouped = group_by_query(rows)
    queries = len(grouped)

    relevant = 0
    rows_total = 0
    capped = 0
    reach_k = 0
    none_at_all = 0
    hits_in_first_k = 0
    per_query: Dict[str, int] = {}

    for query, items in grouped.items():
        count = sum(1 for item in items if _is_relevant(item))
        relevant += count
        rows_total += len(items)
        capped += min(top_k, count)
        hits_in_first_k += sum(1 for item in items[:top_k] if _is_relevant(item))
        if count >= top_k:
            reach_k += 1
        if count == 0:
            none_at_all += 1
        per_query[query] = count

    denom = top_k * queries
    return {
        "queries": queries,
        "rows": rows_total,
        "relevant": relevant,
        "precision": round(relevant / rows_total, 6) if rows_total else 0.0,
        "e1_top_k_rows": round(hits_in_first_k / denom, 6) if denom else 0.0,
        "queries_with_k_or_more": reach_k,
        "queries_with_none": none_at_all,
        "ceiling": round(capped / denom, 6) if denom else 0.0,
        "relevant_threshold": RELEVANT,
        "top_k": top_k,
        "per_query_relevant": per_query,
    }


def _range_of(reports: Sequence[Dict[str, Any]], key: str):
    values = [r[key] for r in reports]
    return {"min": min(values), "max": max(values), "range": round(max(values) - min(values), 6)}


def main(argv: Sequence[str]) -> int:
    force_utf8_streams()
    parser = argparse.ArgumentParser(prog="knowledge-e1-ceiling-report")
    parser.add_argument("files", nargs="+", help="`e1_panel` 落下的打分 jsonl（可给多份做重复跑）")
    parser.add_argument("--top-k", type=int, default=3, help="E1 的 top-k（默认 3）")
    parser.add_argument("--json", action="store_true", help="只打印 JSON")
    parser.add_argument("--per-query", action="store_true", help="把每条查询的相关行数也打出来")
    args = parser.parse_args(list(argv))

    reports = []
    for name in args.files:
        path = pathlib.Path(name)
        if not path.is_absolute():
            path = ROOT / path
        page = report(read_jsonl(path), top_k=args.top_k)
        page["file"] = name
        if not args.per_query:
            page.pop("per_query_relevant", None)
        reports.append(page)

    summary: Dict[str, Any] = {"files": reports}
    if len(reports) > 1:
        summary["range"] = {
            "ceiling": _range_of(reports, "ceiling"),
            "e1_top_k_rows": _range_of(reports, "e1_top_k_rows"),
            "queries_with_k_or_more": _range_of(reports, "queries_with_k_or_more"),
        }

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=1))
        return 0

    for page in reports:
        print("%s" % page["file"])
        print("  查询 %d / 行 %d；相关（均值≥%.1f）%d；precision=%.4f"
              % (page["queries"], page["rows"], RELEVANT, page["relevant"], page["precision"]))
        print("  E1@前%d行=%.4f；≥%d 条相关的查询 %d；0 条相关的查询 %d；**上限=%.4f**"
              % (page["top_k"], page["e1_top_k_rows"], page["top_k"],
                 page["queries_with_k_or_more"], page["queries_with_none"], page["ceiling"]))
    if "range" in summary:
        band = summary["range"]
        print("跨 %d 跑的极差：" % len(reports))
        print("  上限 %.4f（%s）；E1@%d 行 %.4f；≥%d 相关查询数 %d"
              % (band["ceiling"]["range"],
                 "%s..%s" % (band["ceiling"]["min"], band["ceiling"]["max"]),
                 args.top_k, band["e1_top_k_rows"]["range"], args.top_k,
                 band["queries_with_k_or_more"]["range"]))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
