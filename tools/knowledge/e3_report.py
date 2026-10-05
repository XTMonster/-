"""P9②：三条检索路由的 **E3（经验越权）** 读数（计划里 `e3_report.py` 那一步）。

E3 是什么
=========
§2.3b：**L3 案例层永不产出约束**——返回给模型的参考案例里不许出现
`禁止/必须/不得/务必/一定要` 这类要求或禁令（那会把"参考"变成"指令"）。

判据**不在这里重写**
====================
* 层一级：`quality.e3_cases(<案例层>)`——同一条检查器（含"存在但为空 ⇒ 分母 0 判失败"
  那条硬规则，2026-10-01 的空集通过事故就是它钉住的）；
* 路由一级：数每条路由**实际召回**的案例里有多少条越权。逐行录档由 P9① 留下
  （`e1_report.py` 的 `<out>.reviews/reviews.<route>.rep<N>.jsonl`，每行带
  `case_id`/`excerpt`/`zh`），判据是纯函数，**不重跑一遍判分**（那是 128 次 LLM
  调用的浪费，而且重跑只会让同一份证据多一个随机版本）。
  两个分子分开记：
    - `constraint_fields`：该案例在**案例层**里带 `forbid`/`forbids`/`constraint`
      字段（与 `quality.e3_cases` 同一组键）；
    - `constraint_clues`：这条案例的**中文线索**里出现约束词（产出侧
      `case_search_zh.CONSTRAINT_WORDS` 同源派生，**不另抄一份表**）。

用法（与计划 P9 的验收命令逐字一致；**先跑 ①**）::

    python tools/knowledge/e1_report.py --index-dir knowledge_v4 \\
        --heldout knowledge_v4/eval/heldout_v4.jsonl \\
        --routes lexical,hybrid,lightrag --runs 2 --out work/e1_v4pop_ab.json
    python tools/knowledge/e3_report.py --index-dir knowledge_v4 \\
        --routes lexical,hybrid,lightrag --out work/e3_v4pop.json
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Dict, List, Optional, Sequence

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.utils.console import force_utf8_streams  # noqa: E402
from tools.kb_fetch.case_search_zh import CONSTRAINT_WORDS  # noqa: E402
from tools.knowledge import e1_baseline_summary as ebs  # noqa: E402
from tools.knowledge import e1_report as er  # noqa: E402
from tools.knowledge import quality  # noqa: E402

#: E3 的"越权字段"键——与 `quality.e3_cases` 同一组（那边扫的就是它们）。
CONSTRAINT_KEYS = ("forbid", "forbids", "constraint")
#: P9① 的产物名（默认逐行录档的落点）。
DEFAULT_AB_OUT = pathlib.Path("work") / "e1_v4pop_ab.json"


class InputError(RuntimeError):
    """输入不齐 ⇒ 停，不拿半份 E3 出数。"""


def clue_is_overreach(zh: str) -> Optional[str]:
    """线索里出现约束词 ⇒ 返回命中的那个词（没有则 ``None``）。纯函数。"""
    text = str(zh or "")
    for word in CONSTRAINT_WORDS:
        if word in text:
            return str(word)
    return None


def case_field_overreach(raw: Dict) -> bool:
    """案例行带越权字段 ⇒ True（与 `quality.e3_cases` 同一组键）。"""
    return any(key in raw for key in CONSTRAINT_KEYS)


def raw_cases_by_id(index_dir: pathlib.Path) -> Dict[str, Dict]:
    """案例层的原始行（`case_id -> 行`）。**原始**是因为 E3 要看的字段
    （`forbid` 一类）不在 `Case` 契约里——它是"不许出现"的东西。"""
    rows = quality._raw_case_rows(pathlib.Path(index_dir))  # noqa: SLF001 - 同一条读取口径
    out: Dict[str, Dict] = {}
    for row in rows:
        case_id = str(row.get("case_id") or "")
        if case_id:
            out[case_id] = row
    return out


def route_e3(review_path: pathlib.Path, raw: Dict[str, Dict]) -> Dict:
    """一条路由的 E3：逐行录档里**被召回**的案例过一遍判据。"""
    rows = ebs.read_rows(review_path)
    seen: List[str] = []
    fields: List[str] = []
    clues: List[Dict[str, str]] = []
    for row in rows:
        case_id = str(row.get("case_id") or "")
        if case_id and case_id not in seen:
            seen.append(case_id)
        if case_id and case_field_overreach(raw.get(case_id) or {}):
            if case_id not in fields:
                fields.append(case_id)
        hit = clue_is_overreach(row.get("zh") or "")
        if hit:
            clues.append({"case_id": case_id, "word": hit})
    return {"rows": len(rows), "cases": len(seen),
            "constraint_fields": sorted(fields),
            "constraint_clues": clues,
            "status": "pass" if not fields and not clues else "fail"}


def build_report(index_dir: pathlib.Path, reviews_dir: pathlib.Path,
                 routes: Sequence[str], reps: Sequence[int]) -> Dict:
    """层一级 ＋ 路由一级的 E3。任一路由越权 ⇒ 整体 fail（分母与命中都写清楚）。"""
    layer = quality.e3_cases(pathlib.Path(index_dir))
    raw = raw_cases_by_id(index_dir)
    arms: Dict[str, Dict] = {}
    for route in routes:
        for rep in reps:
            name = er.rep_name(route, rep)
            path = reviews_dir / name
            if not path.is_file():
                raise InputError("缺逐行录档 %s（先跑 P9①：`e1_report.py --out %s`）"
                                 % (path, DEFAULT_AB_OUT))
            arms[name] = route_e3(path, raw)
    failed = [name for name, entry in arms.items() if entry["status"] != "pass"]
    return {"generated_by": "tools/knowledge/e3_report.py",
            "e3_definition": "L3 案例层永不产出约束（§2.3b）",
            "constraint_keys": list(CONSTRAINT_KEYS),
            "constraint_words": list(CONSTRAINT_WORDS),
            "index_dir": str(index_dir),
            "reviews_dir": str(reviews_dir),
            "layer": layer,
            "arms": arms,
            "status": "pass" if layer.get("status") == "pass" and not failed else "fail",
            "failing_rounds": failed}


def main(argv: Optional[Sequence[str]] = None) -> int:
    force_utf8_streams()
    parser = argparse.ArgumentParser(prog="knowledge-e3-report")
    parser.add_argument("--index-dir", default="knowledge_v4")
    parser.add_argument("--routes", default="lexical,hybrid")
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--reviews-dir", default="",
                        help="P9① 的逐行录档目录（默认 <e1 out>.reviews/）")
    parser.add_argument("--ab-out", default=str(DEFAULT_AB_OUT),
                        help="P9① 的产物路径（只用来推默认录档目录）")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)

    routes = er.parse_routes(args.routes)
    reviews_dir = (pathlib.Path(args.reviews_dir) if args.reviews_dir
                   else er.reviews_dir_for(pathlib.Path(args.ab_out)))
    if not pathlib.Path(args.index_dir).is_dir():
        raise InputError("案例层目录不存在：%s" % args.index_dir)
    report = build_report(pathlib.Path(args.index_dir), reviews_dir, routes,
                          list(range(1, int(args.runs) + 1)))
    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8", newline="\n")
    print(json.dumps({"out": str(out_path), "status": report["status"],
                      "layer": report["layer"].get("status"),
                      "arms": {name: entry["status"]
                               for name, entry in report["arms"].items()}},
                     ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
