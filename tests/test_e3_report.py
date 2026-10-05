"""P9②：三条路由的 E3（经验越权）读数（`tools/knowledge/e3_report.py`）。

E3 = "L3 案例层永不产出约束"。本文件钉住：判据与现役**同源**（字段键与线索词表都
不许另抄一份）、层一级的空集**判失败**（不是"没有越权"）、路由一级看的是
**实际召回**、缺录档要具名报出前置步骤。
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.kb_fetch.case_search_zh import CONSTRAINT_WORDS  # noqa: E402
from tools.knowledge import e3_report as e3  # noqa: E402
from tools.knowledge import quality  # noqa: E402


def _case_layer(directory: pathlib.Path, rows) -> None:
    shards = directory / "cases"
    shards.mkdir(parents=True, exist_ok=True)
    (shards / "part-000.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8")


def _reviews(path: pathlib.Path, *, route: str, rows) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                    encoding="utf-8")


def _row(case_id: str, *, zh: str = "") -> dict:
    return {"query": "q", "case_id": case_id, "zh": zh, "excerpt": "e", "score": 5.0,
            "scores": [5, 5], "retrieval_path": "hybrid", "cases_fingerprint": "f" * 64,
            "cases_digest": "d" * 64, "panel": ["a", "b"]}


def test_the_word_list_is_the_generators_own_list_not_a_second_copy():
    """线索的约束词表必须**同源**派生（`case_search_zh.CONSTRAINT_WORDS`）。"""
    assert e3.CONSTRAINT_WORDS is CONSTRAINT_WORDS
    assert "必须" in CONSTRAINT_WORDS
    assert e3.clue_is_overreach("要让观众看懂就必须把轴线讲清楚") == "必须"
    assert e3.clue_is_overreach("镜头缓缓推近市场摊位的货物") is None
    assert e3.clue_is_overreach("") is None


def test_the_field_keys_are_the_same_ones_quality_scans():
    assert e3.CONSTRAINT_KEYS == ("forbid", "forbids", "constraint")
    assert e3.case_field_overreach({"case_id": "x", "forbid": []}) is True
    assert e3.case_field_overreach({"case_id": "x"}) is False


def test_an_empty_layer_fails_instead_of_passing_by_having_nothing_to_scan(tmp_path):
    """§4.1b 硬规则 1：分母为 0 不许当成通过。"""
    layer = tmp_path / "knowledge_v4"
    layer.mkdir()
    reviews = tmp_path / "reviews"
    reviews.mkdir()
    _reviews(reviews / e3.er.rep_name("hybrid", 1), route="hybrid", rows=[_row("c1")])
    report = e3.build_report(layer, reviews, ["hybrid"], [1])
    assert report["layer"]["status"] == quality.FAIL
    assert report["status"] == "fail"


def test_route_e3_counts_the_cases_it_actually_returned(tmp_path):
    """路由一级看的是**召回**：层里有一条越权案例，但只有召回它才算这条路由的账。"""
    layer = tmp_path / "knowledge_v4"
    ok = {"case_id": "case_ok", "case_type": "narrative", "title": "t", "excerpt": "e",
          "beat_sequence": [], "source_ref": {}, "score": 0.0}
    banned = {**ok, "case_id": "case_banned", "forbid": ["不许越轴"]}
    _case_layer(layer, [ok, banned])
    assert quality.e3_cases(layer)["status"] == quality.FAIL      # 层一级当场红

    reviews = tmp_path / "reviews"
    reviews.mkdir()
    #: 这一轮只召回了干净的案例，但它自己的线索里带了约束词 ⇒ 路由一级仍红。
    _reviews(reviews / e3.er.rep_name("hybrid", 1), route="hybrid",
             rows=[_row("case_ok"), _row("case_ok", zh="必须先定轴线再拍")])
    report = e3.build_report(layer, reviews, ["hybrid"], [1])
    entry = report["arms"][e3.er.rep_name("hybrid", 1)]
    assert entry["constraint_fields"] == []
    assert entry["constraint_clues"] == [{"case_id": "case_ok", "word": "必须"}]
    assert entry["status"] == "fail"
    assert report["status"] == "fail"

    #: 召回越权案例：路由一级也要点名。
    _reviews(reviews / e3.er.rep_name("hybrid", 1), route="hybrid",
             rows=[_row("case_banned")])
    report = e3.build_report(layer, reviews, ["hybrid"], [1])
    assert report["arms"][e3.er.rep_name("hybrid", 1)]["constraint_fields"] == ["case_banned"]


def test_a_clean_layer_and_clean_recalls_pass(tmp_path):
    layer = tmp_path / "knowledge_v4"
    _case_layer(layer, [{"case_id": "case_ok", "case_type": "narrative", "title": "t",
                         "excerpt": "e", "beat_sequence": [], "source_ref": {}, "score": 0.0}])
    reviews = tmp_path / "reviews"
    reviews.mkdir()
    for route in ("hybrid", "lexical"):
        _reviews(reviews / e3.er.rep_name(route, 1), route=route,
                 rows=[_row("case_ok", zh="镜头缓缓推近市场摊位")])
    report = e3.build_report(layer, reviews, ["hybrid", "lexical"], [1])
    assert report["status"] == "pass"
    assert report["failing_rounds"] == []


def test_a_missing_review_file_names_the_prerequisite(tmp_path):
    layer = tmp_path / "knowledge_v4"
    _case_layer(layer, [{"case_id": "case_ok", "case_type": "narrative", "title": "t",
                         "excerpt": "e", "beat_sequence": [], "source_ref": {}, "score": 0.0}])
    try:
        e3.build_report(layer, tmp_path / "nope", ["hybrid"], [1])
    except e3.InputError as exc:
        assert "e1_report" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("缺录档竟然没报错")
