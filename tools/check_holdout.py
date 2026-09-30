"""Validate `fixtures/knowledge_holdout.jsonl` against the held-out coverage gates.

Spec: execution plan v1.4 §4.1b (held-out 覆盖门) + `fixtures/knowledge_holdout.protocol.md`.

Pure stdlib, no bpy, no repo imports: it can run anywhere.

Gates
    ① total          — ≥1200 **non-pilot** entries
    ② format         — field shape, required slots, `top1 ⊆ must`, `must ∩ never = ∅`,
                       no self-contradictory edge, and **q ↔ must consistency**
                       (a query value that contradicts the required edges is rejected)
    ③ seed coverage  — both directions, all 14 kinds, `must`/`never` values inside the
                       vocabulary, and (outside pilot) a bound vocabulary fingerprint
    ④ edge types     — every type carried by ≥N *distinct* (card, query) pairs from ≥M cards
    ⑤ forbid count   — ≥60 Q7 conflict entries
    ⑤b forbid members— every forbidden value has ≥1 conflict case
    ⑥ sources        — card set and `from_card` set match both ways
    ⑦ human review   — Q5/Q7 entries carry a human verdict

Exit codes
    0  every gate passed
    1  at least one gate failed
    2  at least one gate is `not_measured` — per the plan's hard rule 1, missing evidence
       must never be reported as a pass
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys
from typing import Dict, List, Sequence, Tuple

#: **单一真源**：边类型/节点 kind/必填槽位一律从超图 schema 读。
#: 这里原先各抄了一份（六类型、16 个 kind 硬编码），新增边类型时两边会漂——
#: v1.5 扩到 13 类时正是这么暴露的：校验器认不出新类型，抽取器却已经在产。
#: 直接 `python tools/check_holdout.py …` 运行时 `sys.path[0]` 是 `tools/`，
#: 所以先把仓库根挂上去——否则 CLI 会 ModuleNotFoundError（文档里的验收命令就是这么跑的）。
_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from block_director.knowledge import hypergraph as _hg  # noqa: E402

EDGE_TYPES = tuple(_hg.EDGE_TYPES)
NODE_KINDS = tuple(_hg.NODE_TYPES)
QUALIFIER_KINDS = tuple(_hg.QUALIFIER_KINDS)
ALLOWED_KINDS = frozenset(_hg.ALLOWED_KINDS)

#: required slots per edge type (execution plan §2.3 validation gate ④)
REQUIRED_SLOTS = {
    etype: tuple(kind for _role, kind in _hg.REQUIRED_MEMBERS[etype])
    for etype in EDGE_TYPES
}

#: protocol §2.1 — the frozen Chinese query keys.
#: **单一真源 = `hypergraph.QUERY_KEYS`**：检索器、生成器与校验器必须逐键一致，
#: 所以这里读它而不是再抄一份——抄的那份已经漂过一次（它带 `意图→intent`，
#: 而 schema 当时还没有这个键）。
Q_KEY_TO_KIND = dict(_hg.QUERY_KEYS)

#: the kinds a vocabulary must cover — every node kind. Kinds reached only through a
#: qualifier (e.g. `scene_type` via the 对白 key) are checked only when present.
REQUIRED_VOCAB_KINDS = frozenset(NODE_KINDS)

KNOWN_TYPES = frozenset(EDGE_TYPES)
PASS, FAIL, NA = "pass", "fail", "not_measured"
ID_RE = re.compile(r"^hq_\d{4,}$")

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
        if key not in Q_KEY_TO_KIND:
            raise EntryError(f"q 的键 {key!r} 不在协议 §2.1 的冻结键集里")
        if key in pairs and pairs[key] != value:
            raise EntryError(f"q 的键 {key!r} 出现了两个不同取值")
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
    clash = sorted(set(plain) & set(forbid))
    if clash:
        raise EntryError(f"同一条边里 {clash} 同时被要求和禁止（自相矛盾）")
    return etype, plain, forbid


def spec_key(spec: str) -> Tuple[str, frozenset]:
    """Normalised identity of one edge spec — used for set comparisons.

    Comparing raw strings (the old behaviour) both misses "same edge written with
    different slot order" and can report "no overlap" for two spellings of the very
    same edge.
    """
    etype, plain, forbid = parse_spec(spec)
    items = frozenset([("allow", k, v) for k, v in plain.items()] +
                      [("forbid", k, v) for k, v in forbid.items()])
    return etype, items


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


def validate_entry(record: dict) -> Tuple[Dict[str, str], int]:
    """Raise EntryError, or return (parsed q, number of Q7 conflict hits)."""
    for field in ("id", "from_card", "q", "must", "top1", "never", "annotator", "independence"):
        if field not in record:
            raise EntryError(f"缺字段 {field!r}")
    if not ID_RE.match(str(record["id"]).strip()):
        raise EntryError("id 必须形如 hq_0001")
    if not str(record["from_card"]).strip():
        raise EntryError("from_card 为空")
    ann = record["annotator"]
    if not isinstance(ann, dict):
        raise EntryError("annotator 必须是对象")
    for field in ("model_id", "family", "model_version"):
        if not str(ann.get(field) or "").strip():
            raise EntryError(f"annotator.{field} 不得为空（换族的证据链，见协议 §5.1）")
    if record["independence"] not in ("strong", "weak"):
        raise EntryError("independence 只能是 strong/weak")
    review = record.get("review")
    if review is not None:
        if not isinstance(review, dict) or not review.get("reviewed_by"):
            raise EntryError("review 若存在，必须是 {reviewed_by, verdict}")
        if review.get("verdict") not in ("accepted", "rejected", "amended"):
            raise EntryError("review.verdict 只能是 accepted/rejected/amended")
    must = record["must"]
    if not isinstance(must, list) or not 1 <= len(must) <= 3:
        raise EntryError("must 必须是 1–3 条")
    top1 = record["top1"]
    if not isinstance(top1, list):
        raise EntryError("top1 必须是数组")
    if not {spec_key(s) for s in top1} <= {spec_key(s) for s in must}:
        raise EntryError("top1 必须 ⊆ must")
    never = record["never"]
    if not isinstance(never, list):
        raise EntryError("never 必须是数组")
    if {spec_key(s) for s in never} & {spec_key(s) for s in must}:
        raise EntryError("must 与 never 不得相交")
    parsed_must = []
    for spec in list(must) + list(never):
        if not isinstance(spec, str):
            raise EntryError("must/never 的条目必须是字符串")
        parsed_must.append(parse_spec(spec))
    q = parse_q(record["q"])

    # q ↔ must 一致性：q 里的某个 kind，只要 must 里有该 kind 的槽位，
    # 就必须有一个取值相同。挡住"把词表整段抄进 q、而边说的是另一回事"。
    must_kinds: Dict[str, set] = {}
    for _etype, plain, forbid in [parse_spec(s) for s in must]:
        for kind, value in list(plain.items()) + list(forbid.items()):
            must_kinds.setdefault(kind, set()).add(value)
    for key, value in q.items():
        kind = Q_KEY_TO_KIND[key]
        if kind in must_kinds and value not in must_kinds[kind]:
            raise EntryError(
                f"q 的 {key}={value} 与 must 里的 {kind} 取值不一致"
                f"（must 说的是 {sorted(must_kinds[kind])}）")

    hits = 0
    for spec in must:
        _etype, _plain, forbid = parse_spec(spec)
        for kind, value in forbid.items():
            for zh, qvalue in q.items():
                # 「同类同值」：kind 必须对上（协议 §3.3 / 文档 §4.1b），
                # 只比值会让 `景别=中景` 撞上 `forbid_movement=中景`。
                if Q_KEY_TO_KIND.get(zh) == kind and qvalue == value:
                    hits += 1
    return q, hits


def gate_entries(entries: Sequence[dict]) -> Tuple[str, dict]:
    if not entries:
        # 硬规则 1：空集不得判"格式通过"——against a zero-entry file every
        # per-entry check is vacuously true, which is exactly the trap the rule names.
        return FAIL, {"entries": 0, "valid": 0, "problems": ["空集：没有任何条目可验"],
                      "problem_count": 1, "q7_conflicts": 0,
                      "must_pairs_per_type": {t: 0 for t in EDGE_TYPES},
                      "must_cards_per_type": {t: 0 for t in EDGE_TYPES},
                      "q7_forbid_members": {}, "needs_human": 0, "human_reviewed": 0,
                      "q7_member_count": 0, "_parsed_q": []}
    problems: List[str] = []
    seen: Dict[str, int] = {}
    q7 = 0
    q7_members: Dict[str, int] = {}
    needs_human = 0
    human_reviewed = 0
    type_pairs: Dict[str, set] = {t: set() for t in EDGE_TYPES}
    type_cards: Dict[str, set] = {t: set() for t in EDGE_TYPES}
    parsed_q: List[Dict[str, str]] = []
    for record in entries:
        try:
            q, hits = validate_entry(record)
        except EntryError as exc:
            problems.append(f"line {record.get('__line__')}: {exc}")
            continue
        ident = str(record["id"])
        if ident in seen:
            problems.append(f"line {record.get('__line__')}: id {ident!r} 重复"
                            f"（首次在 line {seen[ident]}）")
        seen[ident] = record.get("__line__", 0)
        q7 += 1 if hits else 0
        parsed_q.append(q)
        qsig = tuple(sorted(q.items()))
        for spec in record["must"]:
            etype, _plain, forbid = parse_spec(spec)
            # 计数以「去重后的 (卡片, 查询)」为单位：同一条 q 复制 30 次不算覆盖
            type_pairs[etype].add((str(record["from_card"]), qsig))
            type_cards[etype].add(str(record["from_card"]))
            for kind, value in forbid.items():
                q7_members[f"{kind}={value}"] = q7_members.get(f"{kind}={value}", 0) + 1
        if hits or (record.get("expect_movements") or []):
            needs_human += 1
            if str(((record.get("review") or {}).get("reviewed_by") or "")).lower() == "human":
                human_reviewed += 1
    detail = {"entries": len(entries), "valid": len(parsed_q), "problems": problems[:20],
              "problem_count": len(problems), "q7_conflicts": q7,
              "must_pairs_per_type": {t: len(s) for t, s in type_pairs.items()},
              "must_cards_per_type": {t: len(s) for t, s in type_cards.items()},
              "q7_forbid_members": q7_members, "needs_human": needs_human,
              "human_reviewed": human_reviewed, "q7_member_count": len(q7_members),
              "_parsed_q": parsed_q}
    return (FAIL if problems else PASS), detail


def gate_total(entries: Sequence[dict], min_entries: int) -> Tuple[str, dict]:
    """Only non-pilot entries count towards the 1200 (protocol §2)."""
    pilot = [e for e in entries if e.get("pilot") is True]
    formal = [e for e in entries if e.get("pilot") is not True]
    n = len(formal)
    return (PASS if n >= min_entries else FAIL), {
        "entries": n, "entries_pilot": len(pilot), "min_entries": min_entries}


def gate_edge_types(pairs: Dict[str, int], cards: Dict[str, int],
                    per_type: int, min_cards: int) -> Tuple[str, dict]:
    short = {t: n for t, n in pairs.items() if n < per_type}
    thin = {t: n for t, n in cards.items() if n < min_cards}
    return (PASS if not short and not thin else FAIL), {
        "min_pairs_per_type": per_type, "min_cards_per_type": min_cards,
        "short_pairs": short, "thin_cards": thin}


def gate_forbid(q7: int, min_forbid: int) -> Tuple[str, dict]:
    return (PASS if q7 >= min_forbid else FAIL), {"q7_conflicts": q7, "min": min_forbid}


def gate_forbid_members(members: Dict[str, int], minimum: int = 1) -> Tuple[str, dict]:
    """Every `forbid` member must appear in ≥1 Q7 conflict case (§4.1b 门⑤)."""
    short = {k: v for k, v in members.items() if v < minimum}
    if not members:
        return FAIL, {"members": 0, "under_covered": {}}
    return (PASS if not short else FAIL), {"members": len(members), "under_covered": short}


def gate_human_review(needs: int, reviewed: int, minimum: int) -> Tuple[str, dict]:
    """Q5/Q7 entries must carry a human verdict (protocol §5.5)."""
    detail = {"needs_human": needs, "human_reviewed": reviewed, "min_human_review": minimum}
    if needs == 0:
        return NA, detail
    return (PASS if reviewed >= min(needs, minimum) else FAIL), detail


def gate_independence(entries: Sequence[dict], extractor_family: str) -> Tuple[str, dict]:
    """`independence: strong` has to be true, not just claimed.

    R49's whole point is that the annotator must not share the extractor's family;
    the field is an assertion about two *different* artefacts, so the checker has to
    compare it against the extractor's identity rather than trust the label.
    """
    if not extractor_family:
        return NA, {"reason": "未提供 --extractor-family / --extractor-manifest：无法核对换族"}
    families = {str((e.get("annotator") or {}).get("family") or "") for e in entries}
    liars = sorted({str(e.get("id")) for e in entries
                    if e.get("independence") == "strong"
                    and str((e.get("annotator") or {}).get("family") or "") == extractor_family})
    detail = {"extractor_family": extractor_family, "annotator_families": sorted(families),
              "strong_but_same_family": liars[:20], "liar_count": len(liars)}
    return (PASS if not liars else FAIL), detail


def gate_seed_coverage(parsed_q: Sequence[Dict[str, str]], vocab: Dict[str, Sequence[str]],
                       must_values: Dict[str, set], has_fingerprint: bool,
                       min_support: int, support: Dict[str, Dict[str, set]]
                       ) -> Tuple[str, dict]:
    """Word-list coverage, **both directions**, over `q` **and** over `must`/`never`.

    Unused vocabulary value      -> the seed space has a blind spot.
    Used value outside the list  -> the label is not expressed in the index namespace,
                                    which silently sends Q4 to zero (the protocol's trap).
    A missing kind               -> whatever the vocabulary omits is simply never checked.
    No vocabulary fingerprint     -> the vocabulary cannot be bound to the index build.
    """
    missing_kinds = sorted(REQUIRED_VOCAB_KINDS - set(vocab))
    if missing_kinds:
        return NA, {"reason": f"词表缺 kind：{missing_kinds}（缺哪个 kind，哪个 kind 就免检）",
                    "missing_kinds": missing_kinds}
    if not has_fingerprint:
        return NA, {"reason": "词表没有 _fingerprint：无法与索引构建绑定（协议 §6）"}

    used: Dict[str, set] = {}
    for q in parsed_q:
        for key, value in q.items():
            used.setdefault(Q_KEY_TO_KIND[key], set()).add(value)

    # 「用到了吗」只对**既能用查询键表达、又有边类型接受**的 kind 检查：
    #   * character/object 是索引侧节点类型，`q` 没有对应的中文键；
    #   * axis_topic 之类即使有键，也没有任何边类型收它 —— 要求它出现在 q 里
    #     等于要求标注者写一条永远命中不了种子的查询。
    # 两类都会在 `unreachable_kinds` 里显式报出来，**不静默忽略**（§0.5 第 2 条）。
    slotted = {kind for etype in EDGE_TYPES
               for group in (REQUIRED_SLOTS.get(etype) or (),)
               for kind in group}

    queryable = set(Q_KEY_TO_KIND.values()) & slotted
    unreachable = sorted((set(Q_KEY_TO_KIND.values()) - slotted) | (set(vocab) - slotted))
    missing: Dict[str, List[str]] = {}
    thin: Dict[str, List[str]] = {}
    for kind, values in vocab.items():
        if kind not in queryable:
            continue
        gap = [v for v in values if v not in used.get(kind, set())]
        if gap:
            missing[kind] = gap
        weak = [v for v in values
                if len(support.get(kind, {}).get(v, set())) < min_support]
        if weak:
            thin[kind] = weak

    unknown: Dict[str, List[str]] = {}
    for kind, values in list(used.items()) + list(must_values.items()):
        allowed = set(vocab.get(kind, []))
        if not allowed:
            continue
        extra = sorted(v for v in values if v not in allowed)
        if extra:
            unknown.setdefault(kind, [])
            unknown[kind] = sorted(set(unknown[kind]) | set(extra))

    detail = {"missing_values": missing, "unknown_values": unknown, "thin_values": thin,
              "min_support": min_support, "kinds_checked": len(vocab),
              "vocab_fingerprint": True, "unreachable_kinds": unreachable}
    return (PASS if not missing and not unknown and not thin else FAIL), detail


def gate_sources(entries: Sequence[dict], cards: Sequence[str]) -> Tuple[str, dict]:
    """Both directions: every card has ≥1 entry, and no entry cites a ghost card."""
    used = {str(e.get("from_card", "")) for e in entries}
    gap = [c for c in cards if c not in used]
    ghost = sorted(used - set(cards))
    return (PASS if not gap and not ghost else FAIL), {
        "cards": len(cards), "missing_cards": gap[:20], "missing_count": len(gap),
        "ghost_cards": ghost[:20], "ghost_count": len(ghost)}


def load_vocab(path: str, pilot: bool) -> Tuple[Dict[str, Sequence[str]] | None, bool]:
    """Accept either `{kind: [...]}` or `{"_fingerprint": str, "kinds": {kind: [...]}}`."""
    payload = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("--vocab 必须是对象")
    if "kinds" in payload:
        fingerprint = bool(str(payload.get("_fingerprint") or "").strip())
        kinds = payload["kinds"]
    else:
        fingerprint = False
        kinds = payload
    if not isinstance(kinds, dict) or not all(
            isinstance(k, str) and isinstance(v, list) for k, v in kinds.items()):
        raise ValueError("--vocab 的 kinds 必须是 {kind: [value, ...]}")
    if pilot:
        # 试点阶段还没有索引可绑定；把指纹要求放行，但正式集必须带指纹
        return kinds, True
    if not fingerprint:
        return None, False
    return kinds, fingerprint


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="check_holdout")
    parser.add_argument("path", nargs="?", default="fixtures/knowledge_holdout.jsonl")
    parser.add_argument("--min-entries", type=int, default=1200)
    parser.add_argument("--min-per-type", type=int, default=30,
                        help="每类边至少被多少条 **去重后的 (卡片,查询)** 要求")
    parser.add_argument("--min-cards-per-type", type=int, default=10,
                        help="每类边的支撑条目至少来自多少张不同的卡")
    parser.add_argument("--min-forbid", type=int, default=60)
    parser.add_argument("--min-seed-support", type=int, default=3,
                        help="每个词表取值至少出现在多少条不同的 (卡片,查询) 里")
    parser.add_argument("--min-human-review", type=int, default=120,
                        help="Q5/Q7 条目里必须带人裁决的条数（协议 §5.5；pilot 时为 1）")
    parser.add_argument("--vocab", default="", help="JSON: {kind: [value, ...]}"
                                                   " 或 {_fingerprint, kinds:{...}}（P14-1 产出）")
    parser.add_argument("--cards", default="", help="JSON: 卡片 id 数组（来源覆盖门）")
    parser.add_argument("--extractor-family", default="",
                        help="抽取器的 family（或给 --extractor-manifest）；门⑧ 用它核对换族是否属实")
    parser.add_argument("--extractor-manifest", default="",
                        help="knowledge/hypergraph.manifest.json；自动读它的 extractor.family")
    parser.add_argument("--pilot", action="store_true",
                        help="试点模式：门限放宽到 1，便于在语料落地前跑通管道")
    parser.add_argument("--json", action="store_true", help="只打印 JSON 报告")
    args = parser.parse_args(list(argv) if argv is not None else None)

    path = pathlib.Path(args.path)
    if not path.is_file():
        print(json.dumps({"error": f"{path} 不存在"}, ensure_ascii=False))
        return 1

    min_entries = 1 if args.pilot else args.min_entries
    per_type = 1 if args.pilot else args.min_per_type
    min_cards = 1 if args.pilot else args.min_cards_per_type
    min_forbid = 1 if args.pilot else args.min_forbid
    min_support = 1 if args.pilot else args.min_seed_support
    min_review = 1 if args.pilot else args.min_human_review

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

    fstatus, fdetail = gate_entries(entries)
    statuses.append(fstatus)
    report["gate_2_format"] = {"status": fstatus,
                               **{k: v for k, v in fdetail.items() if k != "_parsed_q"}}

    tstatus, tdetail = gate_edge_types(fdetail["must_pairs_per_type"],
                                       fdetail["must_cards_per_type"], per_type, min_cards)
    statuses.append(tstatus)
    report["gate_4_edge_types"] = {"status": tstatus, **tdetail}

    gstatus, gdetail = gate_forbid(fdetail["q7_conflicts"], min_forbid)
    statuses.append(gstatus)
    report["gate_5_forbid"] = {"status": gstatus, **gdetail}

    mstatus, mdetail = gate_forbid_members(fdetail["q7_forbid_members"], 1)
    statuses.append(mstatus)
    report["gate_5b_forbid_members"] = {"status": mstatus, **mdetail}

    rstatus, rdetail = gate_human_review(fdetail["needs_human"], fdetail["human_reviewed"],
                                         min_review)
    statuses.append(rstatus)
    report["gate_7_human_review"] = {"status": rstatus, **rdetail}

    extractor_family = args.extractor_family
    if not extractor_family and args.extractor_manifest:
        try:
            man = json.loads(pathlib.Path(args.extractor_manifest).read_text(encoding="utf-8"))
            extractor_family = str((man.get("extractor") or {}).get("family") or "")
        except (OSError, json.JSONDecodeError) as exc:
            print(json.dumps({"error": f"读不到 --extractor-manifest: {exc}"}, ensure_ascii=False))
            return 1
    istatus, idetail = gate_independence(entries, extractor_family)
    statuses.append(istatus)
    report["gate_8_independence"] = {"status": istatus, **idetail}

    if args.vocab:
        try:
            vocab, fingerprint = load_vocab(args.vocab, args.pilot)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            print(json.dumps({"error": f"读不到 --vocab {args.vocab}: {exc}"},
                             ensure_ascii=False))
            return 1
        if vocab is None:
            sstatus, sdetail = NA, {"reason": "词表没有 _fingerprint：无法与索引构建绑定"}
        else:
            sstatus, sdetail = gate_seed_coverage(fdetail["_parsed_q"], vocab,
                                                  must_values_from(entries), fingerprint,
                                                  min_support, support_from(entries))
    else:
        sstatus, sdetail = NA, {"reason": "未提供 --vocab"}
    statuses.append(sstatus)
    report["gate_3_seed_coverage"] = {"status": sstatus, **sdetail}

    if args.cards:
        try:
            cards = json.loads(pathlib.Path(args.cards).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(json.dumps({"error": f"读不到 --cards {args.cards}: {exc}"},
                             ensure_ascii=False))
            return 1
        if not isinstance(cards, list) or not cards or not all(
                isinstance(c, str) for c in cards):
            print(json.dumps({"error": "--cards 必须是非空的卡片 id 字符串数组"},
                             ensure_ascii=False))
            return 1
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
                print(f"[{value['status']:>13}] {key}")
        print(json.dumps({k: v for k, v in report.items() if not isinstance(v, dict)},
                         ensure_ascii=False))
        print(f"overall: {report['overall']}")
    return 0 if report["overall"] == PASS else (2 if report["overall"] == NA else 1)


def must_values_from(entries: Sequence[dict]) -> Dict[str, set]:
    """Every value that appears in a `must`/`never` slot, per kind."""
    out: Dict[str, set] = {}
    for record in entries:
        for spec in list(record.get("must") or []) + list(record.get("never") or []):
            try:
                _etype, plain, forbid = parse_spec(spec)
            except EntryError:
                continue
            for kind, value in list(plain.items()) + list(forbid.items()):
                out.setdefault(kind, set()).add(value)
    return out


def support_from(entries: Sequence[dict]) -> Dict[str, Dict[str, set]]:
    """kind -> value -> set of (card, query) pairs that used it (for the support gate)."""
    out: Dict[str, Dict[str, set]] = {}
    for record in entries:
        try:
            q = parse_q(record.get("q", ""))
        except EntryError:
            continue
        card = str(record.get("from_card"))
        qsig = tuple(sorted(q.items()))
        for key, value in q.items():
            out.setdefault(Q_KEY_TO_KIND[key], {}).setdefault(value, set()).add((card, qsig))
    return out


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
