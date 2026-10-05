"""D10 的**证据工具**：把两种分母口径并排算出来（**只报数，不改判据**）。

背景（`ADJUDICATIONS_v4.md` D10）：E1 的分母是"面板条目数"（`e1_panel.summarise`
里 `len(rows)`）。某臂对某查询**一条都没召回**时，它**不是记 0 分，而是整行消失**
——于是召回差的臂分母更小、每行更值钱。实测三臂（同一面板、`--top-k 3`）：
hybrid／lexical 各 **64/64** 条查询有行；lightrag 只有 **59/64**、平均 2.4 行/查询。

本工具**只报数**：

* `A` ＝ 现行算法（分母＝实际打出来的行数）——**与历史读数同口径**；
* `B` ＝ 固定分母（查询数 × top-k，召回为空记 0）——**语义更对**。

它**不动** `e1_panel`（那件仪器已按 R9 冻结），也不替用户选口径——D10 归用户裁。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Dict, List, Optional, Sequence

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

#: 判"相关"的下限：与 `tools/knowledge/e1_panel.py::RELEVANT` 同源（**只读**，不改）。
RELEVANT = 4.0


def read_rows(path: pathlib.Path) -> List[Dict]:
    try:
        from tools.kb_fetch import common  # noqa: PLC0415
    except ImportError:  # pragma: no cover
        common = None
    if common is not None:
        return common.read_jsonl(pathlib.Path(path))
    out: List[Dict] = []
    for line in pathlib.Path(path).read_text(encoding="utf-8").split("\n"):
        if line.strip():
            out.append(json.loads(line))
    return out


def queries_in(path: pathlib.Path) -> List[str]:
    """按**首次出现顺序**列出某臂出现过的查询（三臂共用同一批查询）。"""
    seen: List[str] = []
    for row in read_rows(path):
        query = str(row.get("query") or "")
        if query and query not in seen:
            seen.append(query)
    return seen


def two_denominators(rows: Sequence[Dict], *, queries: Sequence[str], top_k: int) -> Dict:
    """并排给出 `A`（现行分母）与 `B`（固定分母）。纯函数。"""
    query_list = [str(query) for query in queries]
    scored = len(rows)
    relevant = sum(1 for row in rows if float(row.get("score") or 0) >= RELEVANT)
    per_query: Dict[str, int] = {query: 0 for query in query_list}
    for row in rows:
        query = str(row.get("query") or "")
        if query in per_query:
            per_query[query] += 1
    missing = sum(1 for query in query_list if per_query[query] == 0)
    fixed = max(1, len(query_list) * int(top_k))
    return {
        "relevant": relevant,
        "queries": len(query_list),
        "top_k": int(top_k),
        "queries_with_no_rows": missing,
        "rows_missing": sum(max(0, int(top_k) - per_query[query]) for query in query_list),
        #: A：现行口径（分母＝实际打出来的行数）——与历史读数可比。
        "A": {"denominator": scored,
              "value": round(relevant / scored, 6) if scored else None},
        #: B：固定分母（召回为空记 0）——语义更对，但**不是**历史读数的口径。
        "B": {"denominator": fixed, "value": round(relevant / fixed, 6)},
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="knowledge.e1_two_denominators")
    parser.add_argument("--reviews", action="append", required=True,
                        help="`reviews.<臂>.rep<n>.jsonl`（可给多个）")
    parser.add_argument("--queries-from", default="",
                        help="查询全集的来源臂（默认用第一个 --reviews）")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--out", default="")
    args = parser.parse_args(list(argv) if argv is not None else None)

    reference = pathlib.Path(args.queries_from or args.reviews[0])
    queries = queries_in(reference)
    report: Dict[str, Dict] = {"reference": str(reference), "query_count": len(queries),
                               "arms": {}}
    for spec in args.reviews:
        path = pathlib.Path(spec)
        arm = path.name.split(".")[1] if "." in path.name else path.stem
        report["arms"][arm] = two_denominators(read_rows(path), queries=queries,
                                               top_k=args.top_k)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        out = pathlib.Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
