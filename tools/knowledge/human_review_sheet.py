"""为门⑦ 生成**单族**人审裁决表（格式与 `tools/holdout_review.py apply` 对齐）。

为什么需要它：`tools/holdout_review.py` 的两条子命令是给**两族对拍**设计的
（`diff` 要 `--a/--b` 两个标注族，`apply` 也按"必裁集合 = 分歧 ∪ 涉意图"来算）。
池通道只有**一**个标注族，对拍无从谈起，但门⑦ 照旧要求
「`needs_human` 里至少 `min(needs, 120)` 条带 `review.reviewed_by == "human"`」。
于是人手里缺的不是工具，是**一张能直接打勾的表**。

判据**与门逐字同一份**：`check_holdout.validate_entry()` 返回的 `hits`
（Q7 冲突命中数）非 0，或 `expect_movements` 非空 —— 与 `gate_entries` 里
`needs_human` 的累加条件完全一致，这里不另写一套。

用法::

  python tools/knowledge/human_review_sheet.py --out docs/knowledge/HUMAN_REVIEW_SHEET.md
  # 人：在每节末尾把 `[ ]` 改成 `[x]`（= 采纳），不对的写 `rejected: 原因`
  python tools/holdout_review.py apply --entries fixtures/knowledge_holdout.jsonl \
      --sheet docs/knowledge/HUMAN_REVIEW_SHEET.md --out fixtures/knowledge_holdout.jsonl
  python tools/check_holdout.py fixtures/knowledge_holdout.jsonl --vocab fixtures/knowledge_holdout.vocab.json \
      --cards fixtures/knowledge_holdout.cards.json
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

from tools.check_holdout import EntryError, validate_entry  # noqa: E402


def needs_human(record: dict) -> Tuple[bool, int]:
    """与 `check_holdout.gate_entries` 同一个判据（Q7 冲突命中 或 期望运镜非空）。"""
    try:
        _parsed_q, hits = validate_entry(record)
    except EntryError:
        return False, 0
    if hits or (record.get("expect_movements") or []):
        return True, hits
    return False, hits


def load(path: pathlib.Path) -> List[dict]:
    out = []
    for line in path.read_text(encoding="utf-8").split("\n"):
        if line.strip():
            out.append(json.loads(line))
    return out


def render(entries: Sequence[dict], limit: int = 0) -> Tuple[str, int, int]:
    """生成裁决表。返回 `(markdown, 需人裁的条数, 表里写了多少节)`。"""
    rows = []
    for record in entries:
        need, hits = needs_human(record)
        if need:
            rows.append((record, hits))
    total = len(rows)
    if limit:
        rows = rows[:limit]
    lines = [
        "# held-out 人审裁决表（门⑦）",
        "",
        f"- 需要人裁决的条目：**{total}** 条（门⑦ 要求其中至少 "
        f"`min(总数, 120)` 条带上 `reviewed_by == \"human\"`）。",
        f"- 本表列出 **{len(rows)}** 条（`--limit` 控制）。",
        "",
        "**怎么填**：每节末尾的打勾位从 `[ ]` 改成 `[x]` 表示这条期望成立；"
        "不成立就删掉那行、改写成 `rejected: 原因`；要改写成别的就写 "
        "`amended: 改成什么`。三种写法 `tools/holdout_review.py apply` 都认。",
        "",
        "填完执行：",
        "",
        "```powershell",
        "python tools/holdout_review.py apply --entries fixtures/knowledge_holdout.jsonl \\",
        "  --sheet docs/knowledge/HUMAN_REVIEW_SHEET.md \\",
        "  --out fixtures/knowledge_holdout.jsonl",
        "```",
        "",
        "（只有当你确认整表都填过之后才跑 `apply` —— 它有 `must_touch` 守卫，"
        "漏填会直接拒绝写回。）",
        "",
    ]
    for index, (record, hits) in enumerate(rows, 1):
        lines.append(f"## {record.get('id')} · {record.get('from_card')} · "
                     f"Q7 冲突 {hits} 处")
        lines.append("")
        lines.append(f"查询 A：`{record.get('q', '')}`")
        lines.append("")
        lines.append("| 族 | 必须边 |")
        lines.append("|---|---|")
        for spec in record.get("must") or []:
            lines.append(f"| A | `{spec}` |")
        if record.get("never"):
            lines.append("")
            lines.append(f"不该召回：`{record['never']}`")
        lines.append("")
        lines.append("**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——"
                     "引擎要能靠它拦住那个取值）")
        lines.append("")
        lines.append("采纳 A ？ [ ]")
        lines.append("")
        if index == len(rows):
            lines.append(f"<!-- {index}/{len(rows)} -->")
    return "\n".join(lines) + "\n", total, len(rows)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="human_review_sheet")
    parser.add_argument("--entries", default="fixtures/knowledge_holdout.jsonl")
    parser.add_argument("--out", default="docs/knowledge/HUMAN_REVIEW_SHEET.md")
    parser.add_argument("--limit", type=int, default=0,
                        help="只写前 N 节（默认全部；门⑦ 只需 ≥120 条）")
    args = parser.parse_args(list(argv) if argv is not None else None)

    entries = load(ROOT / args.entries)
    markdown, total, written = render(entries, args.limit)
    target = ROOT / args.out
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(markdown, encoding="utf-8", newline="\n")
    print(json.dumps({"entries": len(entries), "needs_human": total,
                      "sections": written, "sheet": args.out}, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
