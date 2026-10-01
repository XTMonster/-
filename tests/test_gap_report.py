"""Adversarial tests for tools/knowledge/gap_report.py.

The tool exists so that "run the gap rounds" cannot quietly skip one of the
three classes of gap (a value / a card / an edge type).  Each test below names
the failure it guards against; none of them may be satisfied by loosening a
predicate, because the whole point is that the lists agree with the gates that
motivate them.
"""
from __future__ import annotations

import io
import json
import pathlib
import sys
from contextlib import redirect_stdout

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import check_holdout  # noqa: E402
from tools.knowledge import gap_report  # noqa: E402

from block_director.knowledge import hypergraph as hg  # noqa: E402

VALUE = {kind: f"{kind}_v" for kind in set(hg.NODE_TYPES) | set(hg.QUALIFIER_KINDS)}
KEY_FOR = {kind: zh for zh, kind in hg.QUERY_KEYS.items()}


def spec_for(etype: str) -> str:
    slots = [f"{kind}={VALUE[kind]}" for _role, kind in hg.REQUIRED_MEMBERS[etype]]
    return f"{etype}:" + ",".join(slots)


def q_for(spec: str) -> str:
    kinds = {chunk.split("=", 1)[0].replace("forbid_", "")
             for chunk in spec.split(":", 1)[1].split(",")}
    pairs = [f"{KEY_FOR[kind]}={VALUE[kind]}" for kind in sorted(kinds) if kind in KEY_FOR]
    return "；".join(pairs)


SPEC = spec_for("EMOTION_PACK")


def entry(idx: int, card: str = "", **over: object) -> dict:
    base = {
        "id": f"hq_{idx:04d}",
        "from_card": card or f"card_{idx}",
        "q": q_for(SPEC),
        "must": [SPEC],
        "top1": [SPEC],
        "never": [],
        "annotator": {"model_id": "m-a", "family": "fam-a", "model_version": "1",
                      "prompt_sha256": "x"},
        "independence": "strong",
    }
    base.update(over)
    return base


def vocab_for(**over: object) -> dict:
    """A vocabulary naming every required kind - the gate rejects a partial one."""
    kinds = {kind: [VALUE[kind]] for kind in check_holdout.REQUIRED_VOCAB_KINDS}
    kinds.update(over)
    return kinds


def gaps_for(entries, cards, vocab, **kw) -> dict:
    return gap_report.build_gaps(entries=entries, cards=cards, vocab=vocab,
                                 min_support=kw.get("min_support", 3),
                                 per_type=kw.get("per_type", 30),
                                 min_cards=kw.get("min_cards", 10),
                                 assertable=kw.get("assertable"))


# --- the card list -----------------------------------------------------------------

def test_card_gap_returns_every_missing_card_not_just_the_report_preview():
    """`gate_sources` truncates to 20 for readability - the fill round needs all."""
    entries = [entry(1)]
    cards = [f"card_{n}" for n in range(1, 26)]
    _status, detail = check_holdout.gate_sources(entries, cards)
    assert len(detail["missing_cards"]) == 20 and detail["missing_count"] == 24
    assert gap_report.card_gap(entries, cards) == cards[1:]


def test_card_gap_refuses_to_disagree_with_the_gate(monkeypatch):
    """If the two ever drift, the tool must fail loudly instead of emitting a list."""
    entries = [entry(1)]
    cards = [f"card_{n}" for n in range(1, 6)]

    def lying(entries_, cards_):
        return check_holdout.PASS, {"status": "pass", "cards": len(cards_),
                                    "missing_cards": ["not-a-real-card"],
                                    "missing_count": 0, "ghost_cards": [], "ghost_count": 0}

    monkeypatch.setattr(check_holdout, "gate_sources", lying)
    with pytest.raises(AssertionError):
        gap_report.card_gap(entries, cards)


# --- the value list ----------------------------------------------------------------

def test_value_gap_unions_missing_and_under_supported_values():
    """A value the vocabulary lists but nobody queries is as red as a thin one."""
    # 三张不同的卡、同一条 q → `emotion_v` 的支撑数 3，刚好达标；词表里另一个
    # 取值没人用 → 必须进 missing（门③ 的另一半）。
    entries = [entry(n) for n in (1, 2, 3)]
    vocab = vocab_for(emotion=[VALUE["emotion"], "emotion_unused"])
    gaps = gaps_for(entries, [e["from_card"] for e in entries], vocab, min_cards=0)
    assert gaps["values"]["emotion"] == ["emotion_unused"]


def test_value_gap_ignores_a_vocabulary_that_cannot_be_measured():
    """A missing kind makes that kind exempt from the gate - that is an input
    defect, not "no gap", so the tool raises instead of printing an empty list."""
    vocab = vocab_for()
    vocab.pop("movement")
    with pytest.raises(ValueError, match="词表缺 kind"):
        gaps_for([entry(1)], [entry(1)["from_card"]], vocab)


# --- the type list -----------------------------------------------------------------

def test_type_gap_takes_the_index_side_cap_into_account():
    """門④ 的要求是 `min(30, 该类可断言对数)`；忽略上限会点出一条做不到的补跑轮。"""
    entries = [entry(1), entry(2)]
    cards = [entries[0]["from_card"], entries[1]["from_card"]]
    vocab = vocab_for()
    pairs = {"EMOTION_PACK": 2}
    assert gap_report.type_gap(pairs, {"EMOTION_PACK": 2}, 30, 10, None) == ["EMOTION_PACK"]
    assert gap_report.type_gap(pairs, {"EMOTION_PACK": 2}, 30, 10,
                               {"EMOTION_PACK": 2}) == []
    every_type_capped = {etype: 0 for etype in check_holdout.EDGE_TYPES}
    every_type_capped["EMOTION_PACK"] = 2
    assert gaps_for(entries, cards, vocab, assertable=every_type_capped,
                    min_cards=0)["types"] == []


def test_type_gap_keeps_schema_order_and_reports_unknown_types():
    short = {etype: 1 for etype in check_holdout.EDGE_TYPES}
    short["ZZZ_NOT_IN_SCHEMA"] = 1
    out = gap_report.type_gap(short, {etype: 1 for etype in short}, 30, 10, None)
    assert out[:len(check_holdout.EDGE_TYPES)] == list(check_holdout.EDGE_TYPES)
    assert out[-1] == "ZZZ_NOT_IN_SCHEMA"          # 不会静默丢掉


# --- the command the tool tells you to run -----------------------------------------

def test_unknown_value_is_a_hard_error_and_never_a_gap():
    """A value the index can express but the frozen vocabulary omits is **not**
    fixable by a fill round: the fixture itself is out of namespace (门③ 的
    另一半)。门② 放行这种 q（它只查 q 与 must 自洽），所以它会真的发生。"""
    entries = [entry(1)]
    vocab = vocab_for(emotion=["emotion_only_in_vocab"])
    gaps = gaps_for(entries, [entries[0]["from_card"]], vocab, min_cards=0)
    assert gaps["unknown"] == {"emotion": [VALUE["emotion"]]}
    assert VALUE["emotion"] not in gaps["values"].get("emotion", [])
    assert gaps["values"]["emotion"] == ["emotion_only_in_vocab"]


def test_printed_commands_match_what_each_filter_actually_accepts(tmp_path, monkeypatch):
    """`--only-values`/`--only-cards` take `@文件`; `--only-types` has no `@`
    branch (its names are ASCII), so a printed `@`-prefixed type round would be
    a command that cannot run."""
    entries = [entry(1), entry(2)]
    records = tmp_path / "holdout.jsonl"
    records.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in entries),
                       encoding="utf-8")
    cards = tmp_path / "cards.json"
    # card_1 有条目、card_3 没有 → 门⑥ 有一条缺口，卡片轮才会被点出来。
    cards.write_text(json.dumps([entries[0]["from_card"], "card_3"]), encoding="utf-8")
    vocab = tmp_path / "vocab.json"
    vocab.write_text(json.dumps({"_fingerprint": "x", "kinds": vocab_for()},
                                ensure_ascii=False), encoding="utf-8")
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = gap_report.main(["--holdout", str(records), "--cards", str(cards),
                                "--vocab", str(vocab),
                                "--out-dir", str(tmp_path / "gaps")])
    lines = [line for line in buf.getvalue().splitlines()
             if line.startswith("python -m tools.holdout_pool")]
    assert code == 1
    assert len(lines) == 3
    by_flag = {}
    for line in lines:
        flag = line.split("--only-")[1].split()[0]
        by_flag[flag] = line.split(f"--only-{flag} ", 1)[1]
    assert by_flag["values"].startswith("@")
    assert by_flag["cards"].startswith("@")
    assert by_flag["types"] and not by_flag["types"].startswith("@")
    assert (tmp_path / "gaps" / "gap_types.txt").read_text(encoding="utf-8").strip()


def test_a_clean_oracle_reports_no_gap(tmp_path):
    entries = [entry(n) for n in range(1, 13)]
    cards = [e["from_card"] for e in entries]
    vocab = vocab_for()
    report = gaps_for(entries, cards, vocab, per_type=1, min_cards=0,
                      assertable={etype: 0 for etype in check_holdout.EDGE_TYPES})
    assert report["cards"] == []
    assert report["types"] == []
