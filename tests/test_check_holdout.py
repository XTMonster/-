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

#: kind -> allowed values; all 14 kinds must be present or the gate is not_measured
VOCAB = {"emotion": ["气急败坏"], "action": ["跺脚"], "movement": ["固定"],
         "shot_size": ["中景"], "lens": ["50mm"], "pacing": ["短镜硬切"],
         "vfx": ["石化"], "sfx": ["浪声"], "camera_angle": ["平视"], "lighting": ["逆光"],
         "composition_rule": ["三分法"], "axis_topic": ["过肩"], "genre": ["film"],
         "beat_type": ["反转"]}

#: one query string that exercises every kind above (keeps gate ③ satisfiable)
Q_ALL = ("情绪=气急败坏；动作=跺脚；运镜=固定；景别=中景；镜头=50mm；节奏=短镜硬切；"
         "特效=石化；音效=浪声；机位=平视；光线=逆光；构图=三分法；轴线=过肩；"
         "题材=film；桥段=反转")


def entry(idx: int = 1, **over: object) -> dict:
    base = {
        "id": f"hq_{idx:04d}",
        "from_card": f"card_{idx}",
        "q": Q_ALL,
        "must": ["EMOTION_PACK:emotion=气急败坏,intensity=high,movement=固定"],
        "top1": ["EMOTION_PACK:emotion=气急败坏,intensity=high,movement=固定"],
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


def q7_entry(idx: int = 1, **over: object) -> dict:
    """A record whose `q` names a value its own `must` forbids (Q7 冲突条目)."""
    return entry(idx,
                 must=["EMOTION_PACK:emotion=气急败坏,intensity=high,forbid_shot_size=中景"],
                 top1=["EMOTION_PACK:emotion=气急败坏,intensity=high,forbid_shot_size=中景"],
                 q=Q_ALL, **over)


def valid_records() -> list:
    """A minimal set that satisfies all six gates under `--pilot`.

    It covers all six edge types (gate ④), every vocabulary value (gate ③) and one
    Q7 conflict (gate ⑤) — i.e. what a real pilot batch has to look like.
    """
    specs = [
        ("EMOTION_PACK:emotion=气急败坏,intensity=high,movement=固定", Q_ALL),
        ("SHOT_PATTERN:shot_size=中景,lens=50mm,headroom_policy=board", Q_ALL),
        ("AXIS_RULE:pair=any_two,axis_side=right", Q_ALL),
        ("TROPE:genre=film,emotion=气急败坏", Q_ALL),
        ("EDIT_RHYTHM:pacing=短镜硬切,avg_shot_len=2.0", Q_ALL),
        ("LIGHT_PACK:lighting=逆光,intensity=mid", Q_ALL),
    ]
    review = {"reviewed_by": "human", "verdict": "accepted"}
    out = [entry(i, must=[spec], top1=[spec], q=q, review=review)
           for i, (spec, q) in enumerate(specs, 1)]
    out.append(q7_entry(7, review=review))
    return out


# ---------------------------------------------------------------- 门② 逐条格式

def test_valid_pilot_set_passes_every_gate(tmp_path):
    assert full_run(tmp_path, valid_records()) == 0


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


def test_q_key_must_come_from_the_frozen_key_set(tmp_path):
    """协议 §2.1 冻结了 q 的键集；自造键必须当场失败。"""
    assert full_run(tmp_path, [entry(q="心情=气急败坏")]) == 1


def test_review_block_shape_is_checked(tmp_path):
    bad = [q7_entry(1, review={"reviewed_by": "human", "verdict": "maybe"})]
    assert full_run(tmp_path, bad) == 1
    good = valid_records()
    good[0]["review"] = {"reviewed_by": "human", "verdict": "accepted"}
    assert full_run(tmp_path, good) == 0


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


def test_forbid_member_coverage_is_its_own_gate(tmp_path):
    """门⑤b：每个 forbid 成员都得有 ≥1 条冲突用例（否则"从不召回某个禁忌"永远测不到）。"""
    data = report(write(tmp_path, [q7_entry()]))
    assert data["gate_5b_forbid_members"]["status"] == "pass"
    assert data["gate_5b_forbid_members"]["members"] == 1


def test_q7_kind_must_match_not_only_the_value(tmp_path):
    """只比值会让 `景别=中景` 撞上 `forbid_movement=中景`——必须同类同值。"""
    rec = entry(must=["EMOTION_PACK:emotion=气急败坏,intensity=high,forbid_movement=中景"],
                top1=["EMOTION_PACK:emotion=气急败坏,intensity=high,forbid_movement=中景"],
                q="情绪=气急败坏；景别=中景")
    data = report(write(tmp_path, [rec]))
    assert data["gate_5_forbid"]["q7_conflicts"] == 0


def test_human_review_gate_flags_unreviewed_q5_q7_entries(tmp_path):
    data = report(write(tmp_path, [q7_entry()]))  # 有 expect_movements 且是 Q7，却没人裁
    assert data["gate_7_human_review"]["status"] == "fail"
    assert data["gate_7_human_review"]["human_reviewed"] == 0


def test_pilot_entries_do_not_count_towards_the_1200(tmp_path):
    rec = q7_entry(review={"reviewed_by": "human", "verdict": "accepted"}, pilot=True)
    data = report(write(tmp_path, [rec]), pilot=False)
    assert data["gate_1_total"]["entries"] == 0
    assert data["gate_1_total"]["entries_pilot"] == 1
    assert data["gate_1_total"]["status"] == "fail"


# ---------------------------------------------------------------- 门④ 边类覆盖

def test_edge_type_coverage_gate_flags_short_types(tmp_path):
    data = report(write(tmp_path, [q7_entry()]))
    assert data["gate_4_edge_types"]["status"] == "fail"
    for missing in ("SHOT_PATTERN", "AXIS_RULE", "TROPE", "EDIT_RHYTHM", "LIGHT_PACK"):
        assert missing in data["gate_4_edge_types"]["short_pairs"]


def test_edge_type_coverage_counts_distinct_card_query_pairs(tmp_path):
    """同一条 q 复制 30 次不算覆盖——必须来自 ≥30 个不同的 (卡片,查询) 对。"""
    copies = [q7_entry(i) for i in range(1, 4)]
    data = report(write(tmp_path, copies), "--pilot")
    assert data["gate_4_edge_types"]["short_pairs"]["SHOT_PATTERN"] == 0
    assert data["gate_4_edge_types"]["must_pairs_per_type" if False else "status"] == "fail"
    # 三张不同的卡 + 同一个查询 → EMOTION_PACK 有 3 对
    assert data["gate_2_format"]["must_pairs_per_type"]["EMOTION_PACK"] == 3


def test_edge_type_coverage_counts_distinct_cards(tmp_path):
    """同一张卡刷 30 条也不算——每类边至少来自 10 张不同的卡。"""
    same_card = [q7_entry(i) for i in range(1, 4)]
    for rec in same_card:
        rec["from_card"] = "card_1"
    data = report(write(tmp_path, same_card),
                  "--min-cards-per-type", "2", pilot=False)
    assert data["gate_4_edge_types"]["thin_cards"]["EMOTION_PACK"] == 1


# ---------------------------------------------------------------- 门③ 种子覆盖

def test_seed_coverage_not_measured_without_vocab(tmp_path):
    data = report(write(tmp_path, valid_records()))
    assert data["gate_3_seed_coverage"]["status"] == "not_measured"
    assert data["overall"] == "not_measured"


def test_seed_coverage_detects_missing_value(tmp_path):
    vocab = tmp_path / "vocab.json"
    widened = dict(VOCAB, emotion=["气急败坏", "狂喜"])
    vocab.write_text(json.dumps(widened, ensure_ascii=False), encoding="utf-8")
    data = report(write(tmp_path, valid_records()), "--vocab", str(vocab))
    assert data["gate_3_seed_coverage"]["status"] == "fail"
    assert data["gate_3_seed_coverage"]["missing_values"]["emotion"] == ["狂喜"]


def test_seed_coverage_is_two_directional(tmp_path):
    """用了词表外的值 → 必须失败（这就是 norm_key 对不上、Q4 归零的那个坑）。"""
    vocab = tmp_path / "vocab.json"
    narrowed = dict(VOCAB)
    narrowed["emotion"] = ["别的情绪"]
    vocab.write_text(json.dumps(narrowed, ensure_ascii=False), encoding="utf-8")
    data = report(write(tmp_path, valid_records()), "--vocab", str(vocab))
    assert data["gate_3_seed_coverage"]["status"] == "fail"
    assert "气急败坏" in data["gate_3_seed_coverage"]["unknown_values"]["emotion"]


def test_q_value_that_contradicts_must_is_rejected(tmp_path):
    """自洽门：q 说"特写"而必须边说"中景"——查询与约束互相打架，必须当场失败。"""
    rec = q7_entry()
    rec["q"] = "情绪=气急败坏；景别=特写"
    data = report(write(tmp_path, [rec]))
    assert data["gate_2_format"]["status"] == "fail"
    assert "不一致" in " ".join(data["gate_2_format"]["problems"])


def test_same_value_required_and_forbidden_in_one_edge_is_rejected(tmp_path):
    rec = entry(must=["EMOTION_PACK:emotion=气急败坏,intensity=high,shot_size=中景,"
                      "forbid_shot_size=中景"])
    data = report(write(tmp_path, [rec]))
    assert data["gate_2_format"]["status"] == "fail"
    assert "自相矛盾" in " ".join(data["gate_2_format"]["problems"])


def test_must_values_must_come_from_the_vocabulary(tmp_path):
    """must 的取值不在词表里 → Q4 会静默归零，门③ 必须抓住。"""
    vocab = tmp_path / "vocab.json"
    narrowed = dict(VOCAB, lens=["35mm"])          # valid_records 用的是 50mm
    vocab.write_text(json.dumps(narrowed, ensure_ascii=False), encoding="utf-8")
    data = report(write(tmp_path, valid_records()), "--vocab", str(vocab))
    assert data["gate_3_seed_coverage"]["status"] == "fail"
    assert "50mm" in data["gate_3_seed_coverage"]["unknown_values"]["lens"]


def test_seed_support_gate_needs_more_than_one_use(tmp_path):
    """一个取值只被用了一次不算覆盖（要求 ≥N 个不同的 (卡片,查询) 对）。"""
    vocab = tmp_path / "vocab.json"
    vocab.write_text(json.dumps({"_fingerprint": "sha256:abc", "kinds": VOCAB},
                                ensure_ascii=False), encoding="utf-8")
    # 单条记录 → 每个取值只在 1 个 (卡片,查询) 对上出现 → 低于 --min-seed-support 2
    data = report(write(tmp_path, [q7_entry(1)]), "--vocab", str(vocab),
                  "--min-seed-support", "2", pilot=False)
    assert data["gate_3_seed_coverage"]["status"] == "fail"
    assert data["gate_3_seed_coverage"]["thin_values"]


def test_vocab_fingerprint_is_required_outside_pilot(tmp_path):
    """正式集必须把词表绑到索引构建上；缺指纹只能记 not_measured。"""
    vocab = tmp_path / "vocab.json"
    vocab.write_text(json.dumps(VOCAB, ensure_ascii=False), encoding="utf-8")
    buf = io.StringIO()
    with redirect_stdout(buf):
        check_holdout.main([str(write(tmp_path, valid_records())),
                            "--vocab", str(vocab), "--json"])
    data = json.loads(buf.getvalue())
    assert data["gate_3_seed_coverage"]["status"] == "not_measured"
    assert "fingerprint" in data["gate_3_seed_coverage"]["reason"]


def test_vocab_fingerprint_form_is_accepted(tmp_path):
    vocab = tmp_path / "vocab.json"
    vocab.write_text(json.dumps({"_fingerprint": "sha256:abc", "kinds": VOCAB},
                                ensure_ascii=False), encoding="utf-8")
    cards = tmp_path / "cards.json"
    cards.write_text(json.dumps(sorted({r["from_card"] for r in valid_records()})),
                     encoding="utf-8")
    rc = check_holdout.main([str(write(tmp_path, valid_records())), "--pilot",
                             "--vocab", str(vocab), "--cards", str(cards)])
    assert rc == 0


def test_missing_vocab_file_is_a_clean_error(tmp_path):
    """坏路径必须给出 JSON 错误 + 退出码 1，不能抛 traceback。"""
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = check_holdout.main([str(write(tmp_path, valid_records())), "--pilot",
                                 "--vocab", str(tmp_path / "nope.json"), "--json"])
    assert rc == 1
    assert "error" in json.loads(buf.getvalue())


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
        check_holdout.main([str(write(tmp_path, valid_records())), "--pilot"])
    text = buf.getvalue()
    assert "gate_1_total" in text
    assert "overall" in text
