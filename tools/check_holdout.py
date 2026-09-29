"""Validate `fixtures/knowledge_holdout.jsonl` against the six coverage gates.

Spec: execution plan v1.4 §4.1b (held-out 覆盖门) + `fixtures/knowledge_holdout.protocol.md`.

Pure stdlib, no bpy, no repo imports: it can run anywhere.

Exit codes
    0  every gate passed
    1  at least one gate failed
    2  at least one gate is `not_measured` (missing external input) — per the plan's
       hard rule 1, missing evidence must never be reported as a pass
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from typing import Dict, List, Sequence, Tuple

EDGE_TYPES = ("EMOTION_PACK", "SHOT_PATTERN", "AXIS_RULE", "TROPE", "EDIT_RHYTHM", "LIGHT_PACK")

NODE_KINDS = (
    "emotion", "movement", "shot_size", "lens", "pacing", "vfx", "sfx", "composition_rule",
    "axis_topic", "character", "object", "action", "genre", "beat_type", "camera_angle", "lighting",
)
QUALIFIER_KINDS = (
    "pair", "axis_side", "intensity", "applies_to_genre", "applies_to_shot_size",
    "headroom_policy", "avg_shot_len", "transition", "scene_type", "example_shot",
)
ALLOWED_KINDS = frozenset(NODE_KINDS) | frozenset(QUALIFIER_KINDS)

#: required slots per edge type (execution plan §2.3 validation gate ④)
REQUIRED_SLOTS = {
    "EMOTION_PACK": ("emotion", "intensity"),
    "SHOT_PATTERN": ("shot_size", "lens", "headroom_policy"),
    "AXIS_RULE": ("pair", "axis_side"),
    "TROPE": ("genre", "emotion"),
    "EDIT_RHYTHM": ("pacing", "avg_shot_len"),
    "LIGHT_PACK": ("lighting", "intensity"),
}

KNOWN_TYPES = frozenset(EDGE_TYPES)
PASS, FAIL, NA = "pass", "fail", "not_measured"

SPEC_RE = re.compile(r"^(?P<etype>[A-Za-z_]+):(?P<slots>.+)$")
SLOT_RE = re.compile(r"^(?P<forbid>forbid_)?(?P<kind>[a-z_]+)=(?P<value>.+)$")


class EntryError(ValueError):
    """A single record violates the frozen protocol."""


def parse_q(text: str) -> Dict[str, str]:
    """``情绪=荒诞；动作=跺脚`` -> {``情绪``: ``荒诞``, ``动作``: ``跺脚``}."""
    if not isinstance(text, str) or not text.strip():
        raise EntryError("q 为空")
    pairs: Dict[str, str] = {}
    for chunk in re.split(r"[；;]", text):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" not in chunk:
            raise EntryError(f"q 片段缺少 '=': {chunk!r}")
        key, _, value = chunk.partition("=")
        key, value = key.strip(), value.strip()
        if not key or not value:
            raise EntryError(f"q 片段为空键或空值: {chunk!r}")
        pairs[key] = value
    if not pairs:
        raise EntryError("q 解析后为空")
    return pairs


def parse_spec(spec: str) -> Tuple[str, Dict[str, str], Dict[str, str]]:
    """Return (edge_type, plain_slots, forbid_slots) for one `must`/`never` entry."""
    m = SPEC_RE.match(spec.strip())
    if not m:
        raise EntryError(f"边写法不合法（应为 TYPE:槽位=取值,…）: {spec!r}")
    etype = m.group("etype")
    if etype not in KNOWN_TYPES:
        raise EntryError(f"未知边类型 {etype!r}（只允许 {sorted(KNOWN_TYPES)}）")
    plain: Dict[str, str] = {}
    forbid: Dict[str, str] = {}
    for raw in m.group("slots").split(","):
        raw = raw.strip()
        if not raw:
            continue
        sm = SLOT_RE.match(raw)
        if not sm:
            raise EntryError(f"槽位写法不合法: {raw!r}（在 {spec!r} 内）")
        kind = sm.group("kind")
        if kind not in ALLOWED_KINDS:
            raise EntryError(f"未知 kind {kind!r}（在 {spec!r} 内）")
        (forbid if sm.group("forbid") else plain)[kind] = sm.group("value").strip()
    missing = [s for s in REQUIRED_SLOTS[etype] if s not in plain]
    if missing:
        raise EntryError(f"{etype} 缺必填槽位 {missing}（在 {spec!r} 内）")
    return etype, plain, forbid


def load_entries(path: pathlib.Path) -> List[dict]:
    entries: List[dict] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        raw = raw.strip()
        if not raw:
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise EntryError(f"{path.name}:{lineno} 不是合法 JSON: {exc}") from exc
        if not isinstance(record, dict):
            raise EntryError(f"{path.name}:{lineno} 顶层不是对象")
        record["__line__"] = lineno
        entries.append(record)
    return entries


def validate_entry(record: dict) -> Tuple[Dict[str, Dict[str, str]], int]:
    """Raise EntryError, or return (parsed q, number of Q7 conflict hits)."""
    for field in ("id", "from_card", "q", "must", "top1", "never", "annotator", "independence"):
        if field not in record:
            raise EntryError(f"缺字段 {field!r}")
    if not str(record["id"]).strip():
        raise EntryError("id 为空")
    if not str(record["from_card"]).strip():
        raise EntryError("from_card 为空")
    ann = record["annotator"]
    if not isinstance(ann, dict) or not ann.get("model_id") or not ann.get("family"):
        raise EntryError("annotator 必须含 model_id 与 family")
    if record["independence"] not in ("strong", "weak"):
        raise EntryError("independence 只能是 strong/weak")
    must = record["must"]
    if not isinstance(must, list) or not 1 <= len(must) <= 3:
        raise EntryError("must 必须是 1–3 条")
    top1 = record["top1"]
    if not isinstance(top1, list) or not set(top1) <= set(must):
        raise EntryError("top1 必须 ⊆ must")
    never = record["never"]
    if not isinstance(never, list):
        raise EntryError("never 必须是数组")
    if set(never) & set(must):
        raise EntryError("must 与 never 不得相交")
    for spec in list(must) + list(never):
        if not isinstance(spec, str):
            raise EntryError("must/never 的条目必须是字符串")
        parse_spec(spec)
    q = parse_q(record["q"])

    hits = 0
    for spec in must:
        _etype, _plain, forbid = parse_spec(spec)
        for kind, value in forbid.items():
            for zh, qvalue in q.items():
                if qvalue == value:
                    hits += 1
    return q, hits


def gate_entries(entries: Sequence[dict], min_entries: int) -> Tuple[str, dict]:
    problems: List[str] = []
    seen: Dict[str, int] = {}
    q7 = 0
    type_counts: Dict[str, int] = {t: 0 for t in EDGE_TYPES}
    parsed_q: List[Dict[str, str]] = []
    for record in entries:
        try:
            q, hits = validate_entry(record)
        except EntryError as exc:
            problems.append(f"line {record.get('__line__')}: {exc}")
            continue
        ident = str(record["id"])
        if ident in seen:
            problems.append(f"line {record.get('__line__')}: id {ident!r} 重复（首次在 line {seen[ident]}）")
        seen[ident] = record.get("__line__", 0)
        q7 += 1 if hits else 0
        parsed_q.append(q)
        for spec in record["must"]:
            type_counts[parse_spec(spec)[0]] += 1
    detail = {"entries": len(entries), "valid": len(parsed_q), "problems": problems[:20],
              "problem_count": len(problems), "q7_conflicts": q7, "must_per_type": type_counts,
              "_parsed_q": parsed_q}
    return (FAIL if problems else PASS), detail


def gate_total(entries: Sequence[dict], min_entries: int) -> Tuple[str, dict]:
    n = len(entries)
    return (PASS if n >= min_entries else FAIL), {"entries": n, "min_entries": min_entries}


def gate_edge_types(type_counts: Dict[str, int], per_type: int) -> Tuple[str, dict]:
    short = {t: c for t, c in type_counts.items() if c < per_type}
    return (PASS if not short else FAIL), {"min_per_type": per_type, "short": short}


def gate_forbid(q7: int, min_forbid: int) -> Tuple[str, dict]:
    return (PASS if q7 >= min_forbid else FAIL), {"q7_conflicts": q7, "min": min_forbid}


def gate_seed_coverage(parsed_q: Sequence[Dict[str, str]], vocab: Dict[str, Sequence[str]]) -> Tuple[str, dict]:
    missing: Dict[str, List[str]] = {}
    used_values = {value for q in parsed_q for value in q.values()}
    for kind, values in vocab.items():
        gap = [v for v in values if v not in used_values]
        if gap:
            missing[kind] = gap
    return (PASS if not missing else FAIL), {"missing_values": missing, "kinds_checked": len(vocab)}


def gate_sources(entries: Sequence[dict], cards: Sequence[str]) -> Tuple[str, dict]:
    used = {str(e.get("from_card", "")) for e in entries}
    gap = [c for c in cards if c not in used]
    return (PASS if not gap else FAIL), {"cards": len(cards), "missing_cards": gap[:20],
                                         "missing_count": len(gap)},


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="check_holdout")
    parser.add_argument("path", nargs="?", default="fixtures/knowledge_holdout.jsonl")
    parser.add_argument("--min-entries", type=int, default=1200)
    parser.add_argument("--min-per-type", type=int, default=30)
    parser.add_argument("--min-forbid", type=int, default=60)
    parser.add_argument("--vocab", default="", help="JSON: {kind: [value, ...]}（P14-1 产出）")
    parser.add_argument("--cards", default="", help="JSON: 卡片 id 数组（来源覆盖门）")
    parser.add_argument("--pilot", action="store_true",
                        help="试点模式：门限放宽到 1/1/1，便于在语料落地前跑通管道")
    parser.add_argument("--json", action="store_true", help="只打印 JSON 报告")
    args = parser.parse_args(list(argv) if argv is not None else None)

    path = pathlib.Path(args.path)
    if not path.is_file():
        print(json.dumps({"error": f"{path} 不存在"}, ensure_ascii=False))
        return 1

    min_entries = 1 if args.pilot else args.min_entries
    per_type = 1 if args.pilot else args.min_per_type
    min_forbid = 1 if args.pilot else args.min_forbid

    try:
        entries = load_entries(path)
    except EntryError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1

    report: Dict[str, object] = {"path": str(path), "pilot": bool(args.pilot)}
    statuses: List[str] = []

    status, detail = gate_total(entries, min_entries)
    statuses.append(status)
    report["gate_1_total"] = {"status": status, **detail}

    fstatus, fdetail = gate_entries(entries, min_entries)
    statuses.append(fstatus)
    report["gate_2_format"] = {"status": fstatus,
                               **{k: v for k, v in fdetail.items() if k != "_parsed_q"}}

    tstatus, tdetail = gate_edge_types(fdetail["must_per_type"], per_type)
    statuses.append(tstatus)
    report["gate_4_edge_types"] = {"status": tstatus, **tdetail}

    gstatus, gdetail = gate_forbid(fdetail["q7_conflicts"], min_forbid)
    statuses.append(gstatus)
    report["gate_5_forbid"] = {"status": gstatus, **gdetail}

    if args.vocab:
        vocab = json.loads(pathlib.Path(args.vocab).read_text(encoding="utf-8"))
        sstatus, sdetail = gate_seed_coverage(fdetail["_parsed_q"], vocab)
    else:
        sstatus, sdetail = NA, {"reason": "未提供 --vocab"}
    statuses.append(sstatus)
    report["gate_3_seed_coverage"] = {"status": sstatus, **sdetail}

    if args.cards:
        cards = json.loads(pathlib.Path(args.cards).read_text(encoding="utf-8"))
        cstatus, cdetail = gate_sources(entries, cards)
    else:
        cstatus, cdetail = NA, {"reason": "未提供 --cards"}
    statuses.append(cstatus)
    report["gate_6_sources"] = {"status": cstatus, **cdetail}

    report["overall"] = FAIL if FAIL in statuses else (NA if NA in statuses else PASS)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for key, value in report.items():
            if isinstance(value, dict) and "status" in value:
                print(f"[{value['status']:>13}] {key.replace('gate_', '门')}")
        print(json.dumps({k: v for k, v in report.items() if not isinstance(v, dict)},
                         ensure_ascii=False))
        print(f"overall: {report['overall']}")
    return 0 if report["overall"] == PASS else (2 if report["overall"] == NA else 1)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
