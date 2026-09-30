"""剔掉 oracle 里**断言了不可能存在的边**的条目（`type` 上不允许的槽位）。

为什么需要单独一刀：门② 早就判红这类条目（实测 435 条，如
`AXIS_RULE:…,camera_angle=骑轴`——AXIS_RULE 没有 camera_angle 槽位），
产出侧（`holdout_fill.absorb` → `check_holdout.validate_entry`）与合并侧
（`holdout_merge`）现在都会拦，但**已经写进 fixtures 的历史条目**还在。
等重标整轮替换太慢，先把这批明确坏掉的条目摘掉：门② 立刻转绿，其余门几乎不受
影响（这些条目的 `must` 本来就永远解析不到，对覆盖率没有正贡献）。

**这不是放宽门**：判据仍然来自 `check_holdout` 的 `validate_entry`，
只是把"已知坏条目"从产物里移除；门本身一条没动。

    python tools/knowledge/prune_holdout.py --holdout fixtures/knowledge_holdout.jsonl
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

DEFAULT_HOLDOUT = ROOT / "fixtures" / "knowledge_holdout.jsonl"


def read_entries(path: pathlib.Path) -> List[dict]:
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


def prune(entries: Sequence[dict]) -> Tuple[List[dict], List[dict]]:
    """返回 (保留, 剔除)。剔除的每条都带**来自校验器**的原因。"""
    kept: List[dict] = []
    dropped: List[dict] = []
    for entry in entries:
        try:
            validate_entry(dict(entry))
        except EntryError as exc:
            dropped.append({"id": str(entry.get("id", "")),
                            "from_card": str(entry.get("from_card", "")),
                            "reason": str(exc)})
            continue
        kept.append(entry)
    return kept, dropped


def run(path: pathlib.Path = DEFAULT_HOLDOUT, *, write: bool = True,
        cards: Sequence[str] | None = None) -> Dict:
    entries = read_entries(path)
    kept, dropped = prune(entries)
    for index, entry in enumerate(kept, 1):   # id 必须连续（协议 §2.2）
        entry["id"] = f"hq_{index:04d}"
    report = {"path": str(path), "before": len(entries), "kept": len(kept),
              "dropped": len(dropped)}
    reasons: Dict[str, int] = {}
    for row in dropped:
        key = row["reason"].split(":")[0]
        reasons[key] = reasons.get(key, 0) + 1
    report["reasons"] = reasons
    report["examples"] = dropped[:5]
    if write:
        path.write_text("".join(json.dumps(entry, ensure_ascii=False) + "\n"
                                for entry in kept), encoding="utf-8", newline="\n")
        covered = sorted({str(entry["from_card"]) for entry in kept})
        (path.with_suffix(".cards.covered.json")).write_text(
            json.dumps(covered, ensure_ascii=False, indent=0),
            encoding="utf-8", newline="\n")
        if cards is not None:
            (path.with_suffix(".cards.json")).write_text(
                json.dumps(sorted(cards), ensure_ascii=False, indent=0),
                encoding="utf-8", newline="\n")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="prune_holdout")
    parser.add_argument("--holdout", default=str(DEFAULT_HOLDOUT))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", default="")
    args = parser.parse_args(list(argv) if argv is not None else None)
    report = run(pathlib.Path(args.holdout), write=not args.dry_run)
    if args.json:
        pathlib.Path(args.json).write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in report.items() if k != "examples"},
                     ensure_ascii=False))
    for row in report["examples"]:
        print("  剔除:", row["id"], row["reason"][:90])
    return 0


if __name__ == "__main__":  # pragma: no cover - 开发侧工具
    raise SystemExit(main())
