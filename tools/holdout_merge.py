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
from tools.check_holdout import EntryError, query_shortfall, validate_entry  # noqa: E402
from tools.holdout_fill import unknown_values_in  # noqa: E402

DEFAULT_OUT = ROOT / "fixtures" / "knowledge_holdout.jsonl"
DEFAULT_VOCAB = ROOT / "knowledge" / "hypergraph.vocab.json"


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
        for line in path.read_text(encoding="utf-8").split("\n"):
            if line.strip():
                rows.append(json.loads(line))
    return rows


def dedupe_key(row: Dict) -> Tuple[str, str, Tuple[str, ...]]:
    return (str(row.get("from_card", "")), str(row.get("q", "")),
            tuple(sorted(str(spec) for spec in (row.get("must") or []))))


def load_vocab(path: pathlib.Path | str = DEFAULT_VOCAB) -> Dict[str, Sequence[str]]:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))["holdout_vocab"]


def merge(rows: Sequence[Dict],
          vocab: Dict[str, Sequence[str]] | None = None
          ) -> Tuple[List[Dict], Dict[str, object]]:
    """去重 → 校验 → 重新编号。返回 (合规条目, 计数)。

    **校验用的是门自己的那套判据**，一处都不另写：

    * 门②：`check_holdout.validate_entry`（写法、必填槽位、`top1 ⊆ must`…）；
    * 门③ 的 unknown 侧：`holdout_fill.unknown_values_in`（用了词表外的取值）；
    * 门⑨：`check_holdout.query_shortfall`（`q` 够不着自己的 `must` 边）。

    后两条原先只有产出侧（`holdout_fill.absorb`）在拦。合并是 oracle 的**唯一入口**，
    它若只判格式，任何来路的"格式正确但语义不可达"的分片都会被写进库，再由门③/门⑨
    在收尾时整份判红——那时已经分不清是哪一批产出的了。所以这里补上，逐类计数并
    如实报告（不静默丢弃）。
    """
    seen, unique = set(), []
    for row in rows:
        key = dedupe_key(row)
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    valid: List[Dict] = []
    rejected: List[Dict] = []
    unreachable: List[Dict] = []
    unknown: List[Dict] = []
    for row in unique:
        candidate = dict(row)
        candidate["id"] = f"hq_{len(valid) + 1:04d}"
        try:
            validate_entry(candidate)
        except EntryError as exc:
            rejected.append({"from_card": str(row.get("from_card", "")),
                             "q": str(row.get("q", "")), "reason": str(exc)})
            continue
        if vocab:
            bad_values = unknown_values_in(candidate, vocab)
            if bad_values:
                unknown.append({"from_card": str(row.get("from_card", "")),
                                "q": str(row.get("q", "")),
                                "reason": ",".join(sorted(set(bad_values))[:4])})
                continue
        short = query_shortfall(candidate)
        if short:
            unreachable.append({"from_card": str(row.get("from_card", "")),
                                "q": str(row.get("q", "")),
                                "reason": ",".join(short[:4])})
            continue
        valid.append(candidate)
    return valid, {"raw": len(rows), "after_dedupe": len(unique),
                   "valid": len(valid), "invalid": len(rejected),
                   "unreachable": len(unreachable), "unknown_values": len(unknown),
                   "rejected_examples": (rejected + unknown + unreachable)[:5]}


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
        dry_run: bool = False, cards: Sequence[str] | None = None,
        vocab: Dict[str, Sequence[str]] | None = None) -> Dict:
    paths = expand(patterns)
    rows = load_rows(paths)
    if vocab is None and DEFAULT_VOCAB.is_file():
        vocab = load_vocab(DEFAULT_VOCAB)
    entries, counts = merge(rows, vocab)
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
    parser.add_argument("--vocab", default=str(DEFAULT_VOCAB),
                        help="冻结词表：用来在合并时就拦下词表外取值与不可达查询"
                             "（与门③/门⑨ 同一套判据）")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    vocab_path = pathlib.Path(args.vocab)
    vocab = load_vocab(vocab_path) if vocab_path.is_file() else None
    if vocab is None:
        print(f"warning: 词表 {vocab_path} 不存在，合并只做格式校验（门③/门⑨ 仍会在收尾判）")
    report = run(args.inputs, pathlib.Path(args.out), args.dry_run, vocab=vocab)
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
