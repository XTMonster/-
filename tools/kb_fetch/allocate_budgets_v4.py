"""P6 A 路：按来源的**实测可引用量**定 `chunk_budget`。

归因证据（`work/_case_reject_diag.py`）：v4 案例层的 `reject_ratio 0.0753` 全部来自
`quote_gate` 117 条，其中**两份 MIT OCW 讲义 PDF 占 34 条**——讲义多是标题/条目，
没有可引用的句子。根因是生成 `knowledge/sources.v4.yaml` 时给**所有**来源统一
`chunk_budget: 20`，没有按"这一段能不能引用"区分。

规则（写死，见 `tests/test_allocate_budgets_v4.py`）：

* 配额 ＝ 可引用段数（`pick_excerpt(segment) is not None` 的段数）；
* 下端 `min_budget` 兜底、上端 `max_budget` 封顶；
* 可引用段为 0 的来源给 `min_budget`（**不是 0**——"这个来源不可引用"本身是要被
  看见的事实，抹掉它就看不见了）；
* 每条配额旁记 `budget_basis`（`quotable_segments:<n>`），拍脑袋来的配额一眼可辨。

**不许以"把 reject_ratio 压到 5% 以下"为目标**——目标是"配额与内容可引用量匹配"。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Dict, List, Optional, Sequence

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

try:
    from . import build_cases as bc  # type: ignore
    from . import chunk as chunk_mod  # type: ignore
    from . import common  # type: ignore
except ImportError:  # pragma: no cover - 直跑
    from tools.kb_fetch import build_cases as bc  # type: ignore
    from tools.kb_fetch import chunk as chunk_mod  # type: ignore
    from tools.kb_fetch import common  # type: ignore

DEFAULT_MIN_BUDGET = 2
DEFAULT_MAX_BUDGET = 40


def allocate(quotable: Dict[str, int], *, min_budget: int = DEFAULT_MIN_BUDGET,
             max_budget: int = DEFAULT_MAX_BUDGET) -> Dict[str, int]:
    """`来源 → 可引用段数` 变成 `来源 → 配额`。纯函数，确定性。"""
    out: Dict[str, int] = {}
    for slug, count in quotable.items():
        value = int(count or 0)
        out[str(slug)] = max(int(min_budget), min(int(max_budget), value or int(min_budget)))
    return out


def allocate_with_basis(quotable: Dict[str, int], *,
                        min_budget: int = DEFAULT_MIN_BUDGET,
                        max_budget: int = DEFAULT_MAX_BUDGET) -> Dict[str, Dict]:
    budgets = allocate(quotable, min_budget=min_budget, max_budget=max_budget)
    return {slug: {"budget": budgets[slug],
                   "basis": "quotable_segments:%d" % int(quotable.get(slug) or 0)}
            for slug in budgets}


def measure_quotable(records: Sequence[Dict], *, chunk_fn=None,
                     excerpt_fn=None) -> Dict[str, int]:
    """逐来源量"可引用段数"：分段之后有多少段能过 `pick_excerpt`。"""
    chunker = chunk_fn or chunk_mod.run
    excerpt = excerpt_fn or bc.pick_excerpt
    per_source: Dict[str, int] = {}
    for chunk in chunker(list(records)):
        slug = str(common.source_slug({"url": (chunk.get("source_ref") or {}).get("url", "")}))
        per_source.setdefault(slug, 0)
        try:
            if excerpt(str(chunk.get("text") or "")) is not None:
                per_source[slug] += 1
        except Exception:  # noqa: BLE001 - 单段失败不吞掉整批
            continue
    return per_source


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="kb_fetch.allocate_budgets_v4")
    parser.add_argument("--corpus", default=str(common.WORK / "corpus_v4"))
    parser.add_argument("--input", default="",
                        help="**量测的输入**：默认 `--corpus/fetched.jsonl`；"
                             "给案例层用时应指向许可门后的 `licensed.jsonl`"
                             "（那才是案例构建真正看到的集合）")
    parser.add_argument("--out", required=True, help="写 `来源 → {budget,basis}` 的 JSON")
    parser.add_argument("--apply-to", default="",
                        help="把配额写回这份 sources YAML（就地替换 chunk_budget）")
    parser.add_argument("--applied-out", default="",
                        help="写回的目标（默认覆盖 --apply-to）")
    parser.add_argument("--min-budget", type=int, default=DEFAULT_MIN_BUDGET)
    parser.add_argument("--max-budget", type=int, default=DEFAULT_MAX_BUDGET)
    args = parser.parse_args(list(argv) if argv is not None else None)

    source = (pathlib.Path(args.input) if args.input
              else pathlib.Path(args.corpus) / "fetched.jsonl")
    records = common.read_jsonl(source)
    quotable = measure_quotable(records)
    report = allocate_with_basis(quotable, min_budget=args.min_budget,
                                 max_budget=args.max_budget)
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
                   encoding="utf-8")
    zero = sorted(slug for slug, count in quotable.items() if not count)
    applied = ""
    if args.apply_to:
        target = pathlib.Path(args.applied_out or args.apply_to)
        applied = str(apply_plan(pathlib.Path(args.apply_to), target, report))
    print(json.dumps({"overall": "pass", "sources": len(report),
                      "zero_quotable": len(zero),
                      "zero_examples": zero[:5], "applied_to": applied,
                      "out": str(out)},
                     ensure_ascii=False))
    return 0


def apply_plan(sources_path: pathlib.Path, out_path: pathlib.Path,
               plan: Dict[str, Dict]) -> pathlib.Path:
    """把 `source_slug → {budget,basis}` 写回 sources YAML 的 `chunk_budget`。

    找不到对应 slug 的来源**保持原样**并计数（不静默改），返回写回后的路径。
    """
    import yaml
    payload = yaml.safe_load(pathlib.Path(sources_path).read_text(encoding="utf-8"))
    rows = payload.get("sources") or []
    touched = 0
    for row in rows:
        slug = str(common.source_slug({"url": row.get("url", "")}))
        entry = plan.get(slug)
        if not entry:
            continue
        row["chunk_budget"] = int(entry["budget"])
        row["chunk_budget_basis"] = str(entry["basis"])
        touched += 1
    out = pathlib.Path(out_path)
    out.write_text(yaml.safe_dump({"sources": rows}, allow_unicode=True,
                                  sort_keys=False), encoding="utf-8")
    print(json.dumps({"applied": touched, "sources": len(rows),
                      "out": str(out)}, ensure_ascii=False))
    return out


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
