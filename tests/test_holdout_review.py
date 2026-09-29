"""Tests for tools/holdout_review.py (route B: two families, human sees only divergences)."""
from __future__ import annotations

import io
import json
import pathlib
import sys
from contextlib import redirect_stdout

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import holdout_review as hr  # noqa: E402


def entry(ident: str, *, q="情绪=气急败坏；景别=中景", must=None, forbid=False,
          expect=None, card="cine_1"):
    spec = ("EMOTION_PACK:emotion=气急败坏,intensity=high"
            + (",forbid_shot_size=中景" if forbid else ""))
    return {"id": ident, "from_card": card, "q": q,
            "must": must if must is not None else [spec],
            "top1": [spec], "never": [], "expect_movements": expect or [],
            "annotator": {"model_id": "m", "family": "f", "model_version": "1"},
            "independence": "strong"}


def write(tmp_path: pathlib.Path, name: str, rows) -> pathlib.Path:
    path = tmp_path / name
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                    encoding="utf-8")
    return path


def test_diff_splits_disagreements_from_what_agrees():
    a = [entry("hq_0001"), entry("hq_0002")]
    b = [entry("hq_0001"), entry("hq_0002", q="情绪=狂喜；景别=中景")]
    diff, mandatory = hr.split_entries(a, b)
    assert diff == ["hq_0002"]
    assert mandatory == []


def test_agreeing_q5_q7_entries_still_need_a_human():
    """协议 §5.5：两族一致也不等于作者意图——这类条目照样要人确认。"""
    a = [entry("hq_0001", forbid=True), entry("hq_0002", expect=["固定"])]
    diff, mandatory = hr.split_entries(a, list(a))
    assert diff == []
    assert mandatory == ["hq_0001", "hq_0002"]


def test_plain_agreement_needs_no_human():
    a = [entry("hq_0001")]
    diff, mandatory = hr.split_entries(a, list(a))
    assert diff == [] and mandatory == []


def test_diff_rejects_mismatched_id_sets():
    try:
        hr.split_entries([entry("hq_0001")], [entry("hq_0002")])
    except SystemExit as exc:
        assert "id 集合不一致" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("应当 SystemExit")


def test_sheet_lists_both_families_and_prints_the_id():
    a = [entry("hq_0001", forbid=True)]
    b = [entry("hq_0001", forbid=True, q="情绪=暴怒；景别=中景")]
    sheet = hr.render_review_sheet(a, b, ["hq_0001"], [])
    assert "hq_0001" in sheet
    assert "| A |" in sheet and "| B |" in sheet
    assert "采纳 A ？ [ ]" in sheet


def test_parse_sheet_reads_tick_and_reject():
    sheet = ("## hq_0001 · cine_1 · 分歧\n\n采纳 A ？ [x]\n\n"
             "## hq_0002 · cine_1 · 分歧\n\n采纳 A ？ [ ]\nrejected: 两个都不对\n")
    decisions = hr.parse_review_sheet(sheet)
    assert decisions["hq_0001"]["verdict"] == "accepted"
    assert decisions["hq_0002"]["verdict"] == "rejected"
    assert "两个都不对" in decisions["hq_0002"]["note"]


def test_apply_refuses_to_leave_a_mandatory_line_blank():
    entries = [entry("hq_0001", forbid=True)]
    try:
        hr.apply_review(entries, {}, ["hq_0001"])
    except SystemExit as exc:
        assert "必须裁决" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("应当 SystemExit")


def test_apply_writes_review_and_drops_rejects():
    entries = [entry("hq_0001", forbid=True), entry("hq_0002")]
    final = hr.apply_review(entries,
                            {"hq_0001": {"verdict": "accepted"},
                             "hq_0002": {"verdict": "rejected", "note": "重复"}},
                            ["hq_0001"])
    assert [e["id"] for e in final] == ["hq_0001"]
    assert final[0]["review"] == {"reviewed_by": "human", "verdict": "accepted"}


def test_end_to_end_route_b(tmp_path):
    """diff → 打勾 → apply，产物必须过 check_holdout 的门⑦（人裁决）。"""
    a = [entry("hq_0001", forbid=True), entry("hq_0002"),
         entry("hq_0003", card="cine_2")]
    b = [entry("hq_0001", forbid=True), entry("hq_0002", q="情绪=狂喜；景别=中景"),
         entry("hq_0003", card="cine_2")]
    path_a = write(tmp_path, "a.jsonl", a)
    path_b = write(tmp_path, "b.jsonl", b)

    buf = io.StringIO()
    with redirect_stdout(buf):
        assert hr.main(["diff", "--a", str(path_a), "--b", str(path_b),
                        "--out-dir", str(tmp_path)]) == 0
    sheet = (tmp_path / "review.md").read_text(encoding="utf-8")
    assert "hq_0001" in sheet and "hq_0002" in sheet and "hq_0003" not in sheet
    ticked = sheet.replace("采纳 A ？ [ ]", "采纳 A ？ [x]")
    (tmp_path / "review.md").write_text(ticked, encoding="utf-8")

    out = tmp_path / "final.jsonl"
    buf = io.StringIO()
    with redirect_stdout(buf):
        assert hr.main(["apply", "--entries", str(path_a), "--b", str(path_b),
                        "--sheet", str(tmp_path / "review.md"), "--out", str(out)]) == 0
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 3
    assert all(r["review"]["verdict"] == "accepted" for r in rows
               if r["id"] in {"hq_0001", "hq_0002"})

    from tools import check_holdout
    buf = io.StringIO()
    with redirect_stdout(buf):
        check_holdout.main([str(out), "--pilot", "--json"])
    report = json.loads(buf.getvalue())
    assert report["gate_7_human_review"]["status"] == "pass"
