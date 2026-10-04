"""Locate **every** held-out gap and write the three gap lists the fill rounds eat.

Why this exists
===============

`tools/holdout_pool.py` has three gap-round filters and each one closes a
different gate:

* ``--only-values``  -> gate 3 (a vocabulary value with fewer than 3 supports)
* ``--only-cards``   -> gate 6 (an indexed card with no entry at all)
* ``--only-types``   -> gate 4 (an edge type short of ``min(30, assertable)`` pairs)

They are not interchangeable - a round that misses one of the three leaves a
whole class of gap untouched, which is exactly how three successive gap rounds
closed gates 6/3/4 one at a time instead of together (see
``docs/knowledge/ACCEPTANCE_STATUS.md``).  The lists were also rebuilt by hand
each round, from a report whose card list is truncated to 20 entries.

This tool derives all three lists from the **same** predicates the checker uses
(it imports them; it does not re-implement them), so "run the gap rounds" is one
command and the result cannot disagree with the gate that motivated it.

``unknown_values`` (gate 3's other half) is reported as a *hard error*: a value
outside the frozen vocabulary cannot be fixed by a fill round - the oracle has
to be rebuilt or the entry filtered at merge time.  Silently returning an empty
gap list would hide it.

Usage::

    python tools/knowledge/gap_report.py \
        --holdout fixtures/knowledge_holdout.jsonl \
        --cards   fixtures/knowledge_holdout.cards.json \
        --vocab   fixtures/knowledge_holdout.vocab.json \
        --assertable fixtures/knowledge_holdout.assertable.json \
        --out-dir work/gaps

Exit code: 0 = no gap at all; 1 = gaps found (lists written); 2 = the input
cannot support a gap round (unknown values / vocabulary without a fingerprint).
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Dict, List, Sequence

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import check_holdout  # noqa: E402
from block_director.utils.console import force_utf8_streams  # noqa: E402

PASS, FAIL, NA = "pass", "fail", "not_measured"


def _write_lines(path: pathlib.Path, values: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{value}\n" for value in values),
                    encoding="utf-8", newline="\n")


def value_gap(parsed_q, vocab, must_values, support,
              min_support: int) -> Dict[str, object]:
    """Gate 3's fillable half: values that are missing or under-supported.

    ``unknown_values`` is deliberately **not** in here - see the module docstring.
    """
    status, detail = check_holdout.gate_seed_coverage(
        parsed_q, vocab, must_values, True, min_support, support)
    if status == NA:                                   # vocabulary not bound to a build
        return {"_status": NA, "_reason": detail.get("reason", ""), "_unknown": {}}
    if detail.get("missing_kinds"):
        # 词表缺一个 kind 时 gate_seed_coverage **不产出** missing/thin（那个 kind 免检），
        # 于是缺口表会是空的 —— 那不是"没有缺口"，是输入本身有缺陷。
        raise ValueError(
            "词表缺 kind，缺口无法定义（缺哪个 kind 哪个 kind 就免检）："
            f"{detail['missing_kinds']}")
    merged: Dict[str, List[str]] = {}
    for bucket in ("missing_values", "thin_values"):
        for kind, values in (detail.get(bucket) or {}).items():
            merged.setdefault(kind, [])
            merged[kind] = sorted(set(merged[kind]) | set(values))
    merged["_status"] = status
    merged["_unknown"] = detail.get("unknown_values") or {}
    return merged


def card_gap(entries, cards: Sequence[str]) -> List[str]:
    """Gate 6's missing cards, **untruncated**.

    `gate_sources` reports only the first 20 (the report stays readable); the
    fill round needs all of them.  The two are cross-checked so the local rule
    cannot drift from the gate's.
    """
    status, detail = check_holdout.gate_sources(entries, cards)
    used = {str(entry.get("from_card", "")) for entry in entries}
    gap = [str(card) for card in cards if str(card) not in used]
    preview = list(detail.get("missing_cards") or [])
    if preview != gap[:len(preview)]:
        raise AssertionError(
            "gap_report 的卡片缺口与 check_holdout.gate_sources 不一致："
            f"{preview[:3]} vs {gap[:3]}（判据已经漂移，先修单一真源）")
    assert status in (PASS, FAIL), status
    return gap


def type_gap(pairs: Dict[str, int], cards: Dict[str, int], per_type: int,
             min_cards: int, assertable: Dict[str, int] | None) -> List[str]:
    """Gate 4's short types, in schema order."""
    _status, detail = check_holdout.gate_edge_types(pairs, cards, per_type,
                                                    min_cards, assertable=assertable)
    short = set((detail.get("short_pairs") or {}).keys())
    order = [etype for etype in check_holdout.EDGE_TYPES if etype in short]
    #: 任何出现在报告里、但不在 schema 顺序里的类型都要报出来，不能静默丢。
    return order + sorted(short - set(order))


def build_gaps(*, entries, cards: Sequence[str], vocab, min_support: int,
               per_type: int, min_cards: int,
               assertable: Dict[str, int] | None) -> Dict[str, object]:
    fstatus, fdetail = check_holdout.gate_entries(entries)
    values = value_gap(fdetail["_parsed_q"], vocab,
                       check_holdout.must_values_from(entries),
                       check_holdout.support_from(entries), min_support)
    unknown = values.pop("_unknown", {})
    values.pop("_status", None)
    return {
        "format_status": fstatus,
        "values": values,
        "unknown": unknown,
        "cards": card_gap(entries, cards),
        "types": type_gap(fdetail["must_pairs_per_type"], fdetail["must_cards_per_type"],
                          per_type, min_cards, assertable),
    }


def main(argv: Sequence[str] | None = None) -> int:
    # 缺口清单里有中文取值；stdout 固定 UTF-8（见 block_director/utils/console.py）。
    force_utf8_streams()
    parser = argparse.ArgumentParser(prog="gap_report")
    parser.add_argument("--holdout", default="fixtures/knowledge_holdout.jsonl")
    parser.add_argument("--cards", default="fixtures/knowledge_holdout.cards.json")
    parser.add_argument("--vocab", default="fixtures/knowledge_holdout.vocab.json")
    #: 缺省就用**入库的那份**（`holdout_pool --assertable-out` 产出）。
    #: 空缺省会把"索引侧本来就够不到 30 对"的类型报成缺口 —— 实测
    #: `IMPACT_PACK 17 / SOUND_PACK 19 / MUSIC_PACK 16` 会被列进 `--only-types` 轮，
    #: 而那一轮既跑不出东西（组内 nowhere 可加）、又白烧 GLM 调用；门④ 的口径
    #: 早已是 `min(30, 该类可断言对数)`，工具缺省必须与验收链同源。
    parser.add_argument("--assertable",
                        default="fixtures/knowledge_holdout.assertable.json",
                        help="门④ 的索引侧上限（同 check_holdout）；缺省用入库的那份。")
    parser.add_argument("--min-support", type=int, default=3)
    parser.add_argument("--min-per-type", type=int, default=30)
    parser.add_argument("--min-cards-per-type", type=int, default=10)
    parser.add_argument("--out-dir", default="work/gaps")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    entries = check_holdout.load_entries(pathlib.Path(args.holdout))
    cards = json.loads(pathlib.Path(args.cards).read_text(encoding="utf-8"))
    vocab, fingerprint = check_holdout.load_vocab(args.vocab, pilot=False)
    if vocab is None or not fingerprint:
        print(json.dumps({"error": "词表没有 _fingerprint：无法与索引构建绑定，"
                                   "先重建 fixtures/knowledge_holdout.vocab.json"},
                         ensure_ascii=False))
        return 2
    assertable = None
    if args.assertable:
        path = pathlib.Path(args.assertable)
        if not path.is_file():
            print(json.dumps(
                {"warning": f"--assertable {path} 不存在：门④ 退回名义上限 "
                            f"{args.min_per_type}，可能把'索引侧本来就够不到'的类型"
                            f"报成缺口（会白烧一轮补跑）"},
                ensure_ascii=False), file=sys.stderr)
        else:
            payload = json.loads(path.read_text(encoding="utf-8"))
            assertable = payload.get("assertable_pairs_per_type", payload)

    gaps = build_gaps(entries=entries, cards=cards, vocab=vocab,
                      min_support=args.min_support, per_type=args.min_per_type,
                      min_cards=args.min_cards_per_type, assertable=assertable)

    out_dir = pathlib.Path(args.out_dir)
    flat_values = sorted({value for values in gaps["values"].values()
                          for value in values})
    _write_lines(out_dir / "gap_values.txt", flat_values)
    _write_lines(out_dir / "gap_cards.txt", list(gaps["cards"]))
    _write_lines(out_dir / "gap_types.txt", list(gaps["types"]))
    (out_dir / "gap_report.json").parent.mkdir(parents=True, exist_ok=True)
    (out_dir / "gap_report.json").write_text(
        json.dumps(gaps, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n")

    summary = {"values": flat_values, "cards": gaps["cards"], "types": gaps["types"],
               "unknown_values": gaps["unknown"], "out_dir": str(out_dir)}
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"门③ 缺口取值 {len(flat_values)} 个"
              f"（{'、'.join(flat_values[:12])}{'…' if len(flat_values) > 12 else ''}）")
        print(f"门⑥ 缺口卡片 {len(gaps['cards'])} 张")
        print(f"门④ 缺口类型 {len(gaps['types'])} 类：{'、'.join(gaps['types'])}")
        if gaps["unknown"]:
            print("门③ 词表外取值（补跑修不了，必须重标或按 merge 过滤）："
                  f"{json.dumps(gaps['unknown'], ensure_ascii=False)}")
        #: 模型名从 `holdout_pool.GLM_MODEL` 取（**同一份真源**）：写死一个型号
        #: 会在换包之后点出一条**注定 429** 的补跑命令（2026-10-04：本账号只有
        #: `glm-5.3` 还有额度，旧字面 `glm-4.7-flash` 已经打不通）。
        from tools import holdout_pool
        base = ("python -m tools.holdout_pool --provider glm --model %s "
                "--cards %s --vocab %s"
                % (holdout_pool.GLM_MODEL, args.cards, args.vocab))
        for flag, name in (("--only-values", "gap_values.txt"),
                           ("--only-cards", "gap_cards.txt")):
            target = out_dir / name
            if target.read_text(encoding="utf-8").strip():
                #: 路径写成 `/` 的绝对形式：这两个开关**只认 `@文件`**，而中文取值
                #: 走命令行会被 PowerShell 按本地码页转码（仓库里踩过两次）。
                print(f"{base} {flag} @{target.resolve().as_posix()} "
                      f"--out work/glm_pool/{name[:-4]}.jsonl")
        #: `--only-types` 没有 `@文件` 分支（类型名是 ASCII，不存在转码问题），
        #: 所以这里必须**内联**给出——打一条 `@` 前缀的命令是跑不通的。
        if gaps["types"]:
            print(f"{base} --only-types {','.join(gaps['types'])} "
                  "--out work/glm_pool/gap_types.jsonl")

    if gaps["unknown"]:
        return 2
    if flat_values or gaps["cards"] or gaps["types"]:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
