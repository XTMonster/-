"""署名门（`tools/knowledge/authorship_report.py`）的对拍测试。

用户裁决"理论不要自己写，要别人写的"——这条门把裁决变成机器可查的事实：
生成卡必须全部来自 http/https（他人著作），出现 `repo://`（自撰笔记）即判失败。
"""

from __future__ import annotations

import json
import pathlib

from tools.knowledge import authorship_report as ar


def _write(directory: pathlib.Path, rows: list) -> pathlib.Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "cinematography.jsonl"
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                    encoding="utf-8")
    return path


def _card(card_id: str, url: str, license_name: str) -> dict:
    return {"id": card_id, "domain": "cinematography", "title": "t", "content": "c",
            "source_ref": {"url": url, "title": "src", "author": "someone",
                           "license": license_name, "retrieved_at": "2026-10-01",
                           "sha256": "0" * 64}}


def test_external_only_corpus_passes(tmp_path):
    _write(tmp_path, [_card("gen_cine_0001", "https://example.test/book.txt",
                            "PublicDomain")])
    report = ar.run(tmp_path)
    assert report["passed"] is True
    assert report["external_cards"] == 1 and report["self_written_cards"] == 0


def test_self_written_note_fails_the_gate(tmp_path):
    _write(tmp_path, [_card("gen_cine_0001", "https://example.test/book.txt",
                            "PublicDomain"),
                      _card("gen_cine_0002", "repo://knowledge/source_notes/x.md",
                            "OwnWork")])
    report = ar.run(tmp_path)
    assert report["passed"] is False, "自撰笔记混进理论语料必须判失败"
    assert report["self_written_cards"] == 1
    assert report["self_written_examples"][0]["url"].startswith("repo://")


def test_handwritten_engine_rules_are_counted_separately(tmp_path):
    """手写策展卡是本项目的**实现规则**，单独计数，不进"他人著作"分母。"""
    _write(tmp_path, [_card("gen_cine_0001", "https://example.test/book.txt",
                            "PublicDomain")])
    report = ar.run(tmp_path)
    assert report["handwritten_engine_rules"] >= 100
    assert report["generated_cards"] == 1, "手写卡不许混进生成卡计数"
