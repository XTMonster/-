"""Route B: two families draft the held-out set, only the disagreements go to a human.

The generator (`tools.kb_fetch.holdout_gen`) writes one family per run, so the
operational recipe is:

    python -m tools.kb_fetch.holdout_gen --provider ollama --model qwen3-vl:30b
    cp fixtures/knowledge_holdout.jsonl work/holdout.qwen.jsonl
    python -m tools.kb_fetch.holdout_gen --provider deepseek --model deepseek-chat
    cp fixtures/knowledge_holdout.jsonl work/holdout.deepseek.jsonl
    python tools/holdout_review.py diff  --a work/holdout.qwen.jsonl \
                                         --b work/holdout.deepseek.jsonl --out-dir work/holdout
    #   人只勾 work/holdout/review.md
    python tools/holdout_review.py apply --entries work/holdout.qwen.jsonl \
                                         --sheet work/holdout/review.md \
                                         --out fixtures/knowledge_holdout.jsonl

Why the sheet also contains the *agreeing* Q5/Q7 entries: the protocol (§5.5) makes a
human verdict mandatory for anything that encodes author intent, and two models
agreeing does not establish intent — it only tells you where to think harder.

Pure stdlib; the entry shape is the frozen protocol §2 shape, so it works on the
generator's output as-is.
"""
from __future__ import annotations

import argparse
import io
import json
import pathlib
import re
import sys
from contextlib import redirect_stdout
from typing import Dict, List, Sequence, Tuple

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import check_holdout  # noqa: E402

COMPARED_FIELDS = ("q", "must", "top1", "never")


def load_jsonl(path: pathlib.Path) -> List[dict]:
    out: List[dict] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        raw = raw.strip()
        if not raw:
            continue
        record = json.loads(raw)
        if not isinstance(record, dict) or "id" not in record:
            raise SystemExit(f"{path.name}:{lineno} 缺少 id")
        out.append(record)
    return out


def by_id(entries: Sequence[dict]) -> Dict[str, dict]:
    return {str(e["id"]): e for e in entries}


def differs(a: dict, b: dict) -> bool:
    for field in COMPARED_FIELDS:
        left, right = a.get(field), b.get(field)
        if isinstance(left, list) or isinstance(right, list):
            if sorted(left or []) != sorted(right or []):
                return True
        elif (left or "") != (right or ""):
            return True
    return False


def needs_human(entry: dict) -> bool:
    """Q5 (has `expect_movements`) or Q7 (any `forbid_*` slot) — protocol §5.5."""
    if entry.get("expect_movements"):
        return True
    for spec in entry.get("must") or []:
        if "forbid_" in str(spec):
            return True
    return False


def split_entries(a: Sequence[dict], b: Sequence[dict]) -> Tuple[List[str], List[str]]:
    """Return (disagreement ids, agreeing-but-mandatory ids), both sorted."""
    ya, yb = by_id(a), by_id(b)
    if set(ya) != set(yb):
        only_a = sorted(set(ya) - set(yb))[:5]
        only_b = sorted(set(yb) - set(ya))[:5]
        raise SystemExit(f"两族的 id 集合不一致：只在 A 的 {only_a}，只在 B 的 {only_b}"
                         "（两次生成必须覆盖同一批卡片）")
    diff, mandatory = [], []
    for ident in sorted(ya):
        if differs(ya[ident], yb[ident]):
            diff.append(ident)
        elif needs_human(ya[ident]):
            mandatory.append(ident)
    return diff, mandatory


def render_review_sheet(a: Sequence[dict], b: Sequence[dict], diff: Sequence[str],
                        mandatory: Sequence[str]) -> str:
    ya, yb = by_id(a), by_id(b)
    lines = [
        "# held-out 裁决表（两族对拍）",
        "",
        f"- **分歧条目 {len(diff)} 条**：必须裁决。",
        f"- **两族一致但涉及作者意图的条目 {len(mandatory)} 条**：协议 §5.5 要求人确认。",
        "",
        "打勾 = 采纳 A（qwen 那一版）；都不对就在末尾写 `rejected: 原因`；"
        "要改就在 `amended:` 后面写清改成什么。",
        "",
        "填入命令：`python tools/holdout_review.py apply --entries <A.jsonl> "
        "--sheet <本文件> --out fixtures/knowledge_holdout.jsonl`",
        "",
    ]

    def section(ident: str, kind: str) -> None:
        left, right = ya[ident], yb[ident]
        lines.append(f"## {ident} · {left.get('from_card')} · {kind}")
        lines.append("")
        lines.append(f"查询 A：`{left.get('q', '')}`")
        if right.get("q") != left.get("q"):
            lines.append(f"查询 B：`{right.get('q', '')}`")
        lines.append("")
        lines.append("| 族 | 必须边 |")
        lines.append("|---|---|")
        for spec in left.get("must") or []:
            lines.append(f"| A | `{spec}` |")
        for spec in right.get("must") or []:
            lines.append(f"| B | `{spec}` |")
        if (left.get("never") or right.get("never")):
            lines.append("")
            lines.append(f"不该召回：A=`{left.get('never')}` B=`{right.get('never')}`")
        if left.get("expect_movements") or right.get("expect_movements"):
            lines.append("")
            lines.append(f"期望运镜：A=`{left.get('expect_movements')}` "
                         f"B=`{right.get('expect_movements')}`")
        lines.append("")
        lines.append("采纳 A ？ [ ]")
        lines.append("")

    if diff:
        lines += ["## 一、两族分歧（必须逐条裁决）", ""]
        for ident in diff:
            section(ident, "分歧")
    if mandatory:
        lines += ["## 二、两族一致但涉及作者意图（请确认）", ""]
        for ident in mandatory:
            section(ident, "一致")
    return "\n".join(lines) + "\n"


def parse_review_sheet(text: str) -> Dict[str, dict]:
    """`## hq_0001 · …` sections -> {id: {verdict, note}}."""
    decisions: Dict[str, dict] = {}
    current: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("## "):
            current = line[3:].split("·")[0].strip()
            continue
        if not current:
            continue
        if line.lower().startswith("rejected:"):
            decisions[current] = {"verdict": "rejected",
                                  "note": line.split(":", 1)[1].strip()}
        elif line.lower().startswith("amended:"):
            decisions[current] = {"verdict": "amended",
                                  "note": line.split(":", 1)[1].strip()}
        elif "采纳 A" in line and re.search(r"\[\s*x\s*\]", line, re.I):
            decisions[current] = {"verdict": "accepted"}
    return decisions


def apply_review(entries: Sequence[dict], decisions: Dict[str, dict],
                 must_touch: Sequence[str]) -> List[dict]:
    """Write verdicts back, drop rejects, and refuse to leave a mandatory line blank."""
    untouched = [i for i in must_touch if i not in decisions]
    if untouched:
        raise SystemExit(f"[apply] 还有 {len(untouched)} 条必须裁决却没填：{untouched[:5]}")
    out: List[dict] = []
    for entry in entries:
        ident = str(entry["id"])
        decision = decisions.get(ident)
        if decision and decision.get("verdict") == "rejected":
            continue
        merged = dict(entry)
        if decision:
            record = {"reviewed_by": "human", "verdict": decision["verdict"]}
            if decision.get("note"):
                record["note"] = decision["note"]
            merged["review"] = record
        out.append(merged)
    return out


def cmd_diff(args: argparse.Namespace) -> int:
    a = load_jsonl(pathlib.Path(args.a))
    b = load_jsonl(pathlib.Path(args.b))
    diff, mandatory = split_entries(a, b)
    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "disagreements.json").write_text(
        json.dumps({"disagreements": diff, "mandatory": mandatory,
                    "entries": len(a)}, ensure_ascii=False, indent=2), encoding="utf-8")
    sheet = render_review_sheet(a, b, diff, mandatory)
    (out_dir / "review.md").write_text(sheet, encoding="utf-8")
    print(json.dumps({"entries": len(a), "disagreements": len(diff),
                      "mandatory": len(mandatory), "sheet": str(out_dir / "review.md")},
                     ensure_ascii=False))
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    entries = load_jsonl(pathlib.Path(args.entries))
    sheet = pathlib.Path(args.sheet).read_text(encoding="utf-8")
    decisions = parse_review_sheet(sheet)
    diff, mandatory = split_entries(
        entries, load_jsonl(pathlib.Path(args.b)) if args.b else entries)
    final = apply_review(entries, decisions, sorted(set(diff) | set(mandatory)))
    path = pathlib.Path(args.out)
    path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in final) + "\n",
                    encoding="utf-8")
    print(json.dumps({"entries": len(entries), "kept": len(final),
                      "reviewed": len(decisions), "out": str(path)}, ensure_ascii=False))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="holdout_review")
    sub = parser.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("diff", help="两族对拍 → 生成人裁决表")
    d.add_argument("--a", required=True)
    d.add_argument("--b", required=True)
    d.add_argument("--out-dir", default="work/holdout")
    d.set_defaults(func=cmd_diff)
    ap = sub.add_parser("apply", help="把打勾的裁决表写回最终 held-out")
    ap.add_argument("--entries", required=True, help="采纳的那一族（A）")
    ap.add_argument("--sheet", required=True)
    ap.add_argument("--b", default="", help="可选的第二族，用来复算必裁集合")
    ap.add_argument("--out", default="fixtures/knowledge_holdout.jsonl")
    ap.set_defaults(func=cmd_apply)
    args = parser.parse_args(list(argv) if argv is not None else None)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
