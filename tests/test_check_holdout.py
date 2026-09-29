"""Adversarial tests for tools/check_holdout.py (the held-out coverage gates).

Each test states the failure it guards against; the point of the file is that a
lying or half-finished held-out set must not be able to report `pass`.
"""
from __future__ import annotations

import io
import json
import pathlib
import sys
from contextlib import redirect_stdout

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import check_holdout  # noqa: E402

VOCAB = {"emotion": ["气急败坏"], "movement": ["跺脚"]}


def entry(idx: int = 1, **over: object) -> dict:
    base = {
        "id": f"hq_{idx:04d}",
        "from_card": f"card_{idx}",
        "q": "情绪=气急败坏；动作=跺脚",
        "must": ["EMOTION_PACK:emotion=气急败坏,intensity=high,movement=跺脚"],
        "top1": ["EMOTION_PACK:emotion=气急败坏,intensity=high,movement=跺脚"],
        "never": [],
        "expect_movements": ["固定"],
        "annotator": {"model_id": "m-a", "family": "fam-a", "model_version": "1",
                      "prompt_sha256": "x"},
        "independence": "strong",
    }
    base.update(over)
    return base


def write(tmp_path: pathlib.Path, records, name: str = "holdout.jsonl") -> pathlib.Path:
    path = tmp_path / name
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
                    encoding="utf-8")
    return path


def full_run(tmp_path: pathlib.Path, records, *extra: str) -> int:
    """A pilot run with both external inputs supplied, so no gate is not_measured."""
    vocab = tmp_path / "vocab.json"
    vocab.write_text(json.dumps(VOCAB, ensure_ascii=False), encoding="utf-8")
    cards = tmp_path / "cards.json"
    cards.write_text(json.dumps(sorted({r["from_card"] for r in records})), encoding="utf-8")
    return check_holdout.main([str(write(tmp_path, records)), "--pilot",
                               "--vocab", str(vocab), "--cards", str(cards), *extra])


def report(path: pathlib.Path, *extra: str, pilot: bool = True) -> dict:
    buf = io.StringIO()
    argv = [str(path), "--json", *extra]
    if pilot:
        argv.insert(1, "--pilot")
    with redirect_stdout(buf):
        check_holdout.main(argv)
    return json.loads(buf.getvalue())


def q7_entry(idx: int = 1) -> dict:
    """A record whose `q` names a value its own `must` forbids (Q7 冲突条目)."""
    return entry(idx,
                 must=["EMOTION_PACK:emotion=气急败坏,intensity=high,forbid_shot_size=中景"],
                 top1=["EMOTION_PACK:emotion=气急败坏,intensity=high,forbid_shot_size=中景"],
                 q="情绪=气急败坏；景别=中景")


# ---------------------------------------------------------------- 门② 逐条格式

def test_valid_pilot_set_passes_every_gate(tmp_path):
    assert full_run(tmp_path, [q7_entry(1), q7_entry(2)]) == 0


def test_empty_must_fails(tmp_path):
    assert full_run(tmp_path, [entry(must=[], top1=[])]) == 1


def test_more_than_three_must_fails(tmp_path):
    spec = q7_entry()["must"][0]
    four = [spec, spec + ",lens=50mm", spec + ",lens=35mm", spec + ",lens=24mm"]
    assert full_run(tmp_path, [entry(must=four)]) == 1


def test_top1_must_be_subset_of_must(tmp_path):
    other = "SHOT_PATTERN:shot_size=中景,lens=50mm,headroom_policy=board"
    assert full_run(tmp_path, [entry(top1=[other])]) == 1


def test_must_and_never_must_not_overlap(tmp_path):
    assert full_run(tmp_path, [entry(never=entry()["must"])]) == 1


def test_unknown_edge_type_fails(tmp_path):
    assert full_run(tmp_path, [entry(must=["TRIPLE:emotion=x,intensity=mid"])]) == 1


def test_missing_required_slot_fails(tmp_path):
    """EMOTION_PACK 缺 intensity —— 与 §2.3 的校验门④同源。"""
    assert full_run(tmp_path, [entry(must=["EMOTION_PACK:emotion=气急败坏"])]) == 1


def test_unknown_kind_fails(tmp_path):
    spec = "EMOTION_PACK:emotion=x,intensity=mid,mood=y"
    assert full_run(tmp_path, [entry(must=[spec])]) == 1


def test_duplicate_id_fails(tmp_path):
    assert full_run(tmp_path, [q7_entry(1), q7_entry(1)]) == 1


def test_annotator_requires_family(tmp_path):
    assert full_run(tmp_path, [entry(annotator={"model_id": "m"})]) == 1


def test_unparseable_q_fails(tmp_path):
    assert full_run(tmp_path, [entry(q="情绪")]) == 1


# ---------------------------------------------------------------- 门⑤ 禁忌覆盖

def test_q7_conflict_is_counted(tmp_path):
    data = report(write(tmp_path, [q7_entry()]))
    assert data["gate_5_forbid"]["q7_conflicts"] == 1
    assert data["gate_5_forbid"]["status"] == "pass"


def test_q7_is_zero_when_the_forbidden_value_is_absent_from_q(tmp_path):
    rec = q7_entry()
    rec["q"] = "情绪=气急败坏；动作=跺脚"
    data = report(write(tmp_path, [rec]))
    assert data["gate_5_forbid"]["q7_conflicts"] == 0
    assert data["gate_5_forbid"]["status"] == "fail"


# ---------------------------------------------------------------- 门④ 边类覆盖

def test_edge_type_coverage_gate_flags_short_types(tmp_path):
    data = report(write(tmp_path, [q7_entry()]))
    assert data["gate_4_edge_types"]["status"] == "fail"
    for missing in ("SHOT_PATTERN", "AXIS_RULE", "TROPE", "EDIT_RHYTHM", "LIGHT_PACK"):
        assert missing in data["gate_4_edge_types"]["short"]


# ---------------------------------------------------------------- 门③ 种子覆盖

def test_seed_coverage_not_measured_without_vocab(tmp_path):
    data = report(write(tmp_path, [q7_entry()]))
    assert data["gate_3_seed_coverage"]["status"] == "not_measured"
    assert data["overall"] == "not_measured"


def test_seed_coverage_detects_missing_value(tmp_path):
    vocab = tmp_path / "vocab.json"
    vocab.write_text(json.dumps({"emotion": ["气急败坏", "狂喜"]}, ensure_ascii=False),
                     encoding="utf-8")
    data = report(write(tmp_path, [q7_entry()]), "--vocab", str(vocab))
    assert data["gate_3_seed_coverage"]["status"] == "fail"
    assert data["gate_3_seed_coverage"]["missing_values"]["emotion"] == ["狂喜"]


# ---------------------------------------------------------------- 门⑥ 来源覆盖

def test_source_coverage_detects_missing_card(tmp_path):
    cards = tmp_path / "cards.json"
    cards.write_text(json.dumps(["card_1", "card_2", "card_3"]), encoding="utf-8")
    data = report(write(tmp_path, [q7_entry()]), "--cards", str(cards))
    assert data["gate_6_sources"]["status"] == "fail"
    assert data["gate_6_sources"]["missing_cards"] == ["card_2", "card_3"]


# ---------------------------------------------------------------- 门① 总量 + CLI

def test_real_thresholds_fail_without_pilot(tmp_path):
    data = report(write(tmp_path, [q7_entry()]), pilot=False)
    assert data["gate_1_total"]["status"] == "fail"
    assert data["gate_1_total"]["min_entries"] == 1200


def test_missing_file_returns_one(tmp_path):
    assert check_holdout.main([str(tmp_path / "nope.jsonl")]) == 1


def test_broken_json_line_is_reported(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text('{"id": "x"\n', encoding="utf-8")
    assert check_holdout.main([str(path)]) == 1


def test_human_readable_output_lists_gate_status(tmp_path):
    buf = io.StringIO()
    with redirect_stdout(buf):
        check_holdout.main([str(write(tmp_path, [q7_entry()])), "--pilot"])
    text = buf.getvalue()
    assert "gate_1_total" in text
    assert "overall" in text
