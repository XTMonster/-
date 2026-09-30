"""把分片跑出来的 held-out 条目合并成唯一一份 oracle（开发侧工具）。

分片填充（`tools/holdout_fill.py`）是**并行**跑的：每个进程只写自己的
`partial*.jsonl`。合并这一步必须做四件事，缺一件都会让 oracle 不可信：

1. **去重**：同一张卡 + 同一个查询 + 同一组 `must` 只留一条（分片重叠或
   重试会产生重复，重复会让门②的计数与真实覆盖面脱节）；
2. **逐条过校验器**：用 `check_holdout.validate_entry`，不合规的条目
   **丢掉并计数**，不做"先写进去再说"；
3. **重新编号**：id 必须是连续的 `hq_0001`（协议要求），所以编号发生在
   校验之后；
4. **同时写出卡片全集**（`*.cards.json`）与本次覆盖到的卡（`*.cards.covered.json`），
   这样门③/门⑥ 的输入永远是"实际要求标注的全量"，而不是"产出过的那些"。

    python tools/holdout_merge.py --inputs work/glm_v10/partial*.jsonl work/glm_v11/partial*.jsonl
"""

from __future__ import annotations

import argparse
import glob
import json
import pathlib
import sys
from typing import Dict, List, Sequence, Tuple

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge.corpus import CARDS  # noqa: E402
from tools.check_holdout import EntryError, validate_entry  # noqa: E402

DEFAULT_OUT = ROOT / "fixtures" / "knowledge_holdout.jsonl"


def expand(patterns: Sequence[str]) -> List[pathlib.Path]:
    """把 shell 通配或目录展开成有序的文件列表（目录 = 里面的 partial*.jsonl）。"""
    paths: List[pathlib.Path] = []
    for pattern in patterns:
        candidate = pathlib.Path(pattern)
        if candidate.is_dir():
            paths.extend(sorted(candidate.glob("partial*.jsonl")))
            continue
        if any(char in pattern for char in "*?["):
            paths.extend(sorted(pathlib.Path(p) for p in glob.glob(pattern)))
            continue
        paths.append(candidate)
    seen, out = set(), []
    for path in paths:
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        out.append(path)
    return out


def load_rows(paths: Sequence[pathlib.Path]) -> List[Dict]:
    rows: List[Dict] = []
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def dedupe_key(row: Dict) -> Tuple[str, str, Tuple[str, ...]]:
    return (str(row.get("from_card", "")), str(row.get("q", "")),
            tuple(sorted(str(spec) for spec in (row.get("must") or []))))


def merge(rows: Sequence[Dict]) -> Tuple[List[Dict], Dict[str, int]]:
    """去重 → 校验 → 重新编号。返回 (合规条目, 计数)。"""
    seen, unique = set(), []
    for row in rows:
        key = dedupe_key(row)
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    valid: List[Dict] = []
    rejected: List[Dict] = []
    for row in unique:
        candidate = dict(row)
        candidate["id"] = f"hq_{len(valid) + 1:04d}"
        try:
            validate_entry(candidate)
        except EntryError as exc:
            rejected.append({"from_card": str(row.get("from_card", "")),
                             "q": str(row.get("q", "")), "reason": str(exc)})
            continue
        valid.append(candidate)
    return valid, {"raw": len(rows), "after_dedupe": len(unique),
                   "valid": len(valid), "invalid": len(rejected)}


def write(entries: Sequence[Dict], out: pathlib.Path,
          cards: Sequence[str] | None = None) -> Dict:
    universe = sorted(cards if cards is not None else (c.id for c in CARDS))
    covered = sorted({str(entry["from_card"]) for entry in entries})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(entry, ensure_ascii=False) + "\n"
                           for entry in entries), encoding="utf-8", newline="\n")
    out.with_suffix(".cards.json").write_text(
        json.dumps(universe, ensure_ascii=False, indent=0), encoding="utf-8", newline="\n")
    out.with_suffix(".cards.covered.json").write_text(
        json.dumps(covered, ensure_ascii=False, indent=0), encoding="utf-8", newline="\n")
    return {"entries": len(entries), "cards": len(universe),
            "cards_covered": len(set(covered) & set(universe)),
            "cards_missing": sorted(set(universe) - set(covered)),
            "ghost_cards": sorted(set(covered) - set(universe))}


def run(patterns: Sequence[str], out: pathlib.Path = DEFAULT_OUT,
        dry_run: bool = False, cards: Sequence[str] | None = None) -> Dict:
    paths = expand(patterns)
    rows = load_rows(paths)
    entries, counts = merge(rows)
    report = {"shards": [str(path) for path in paths], **counts}
    if dry_run:
        report["dry_run"] = True
        return report
    report.update(write(entries, out, cards))
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="holdout_merge")
    parser.add_argument("--inputs", nargs="+", required=True,
                        help="分片 partial 文件/通配/目录（目录 = 其中的 partial*.jsonl）")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default="", help="把合并报告写到这个路径")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    report = run(args.inputs, pathlib.Path(args.out), args.dry_run)
    if args.report:
        pathlib.Path(args.report).write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8", newline="\n")
    summary = {k: v for k, v in report.items() if k != "cards_missing"}
    print(json.dumps(summary, ensure_ascii=False))
    missing = report.get("cards_missing") or []
    if missing:
        print(f"cards_missing: {len(missing)} (e.g. {missing[:8]})")
    return 0 if report["valid"] else 1


if __name__ == "__main__":  # pragma: no cover - 开发侧工具
    raise SystemExit(main())
