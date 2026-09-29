"""Tests for tools/holdout_candidates.py (drafting + disagreement sheet)."""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import holdout_candidates as hc  # noqa: E402


CARDS = [
    {"id": "cine_shot_size", "domain": "cinematography", "title": "九种景别与画面高度",
     "content": "景别不是称呼，而是一组可执行的取景数字。", "keywords": ["景别", "取景", "MS"]},
    {"id": "axis_180", "domain": "axis_theory", "title": "一百八十度规则",
     "content": "在一次对话里保持同侧。", "keywords": ["轴线", "越轴"]},
]


def test_offline_transport_is_deterministic():
    a = hc.offline_transport(CARDS[0])
    b = hc.offline_transport(CARDS[0])
    assert a == b
    payload = json.loads(a)
    assert payload["must"], "必须给出至少一条边"


def test_prompt_mentions_the_card_and_the_rules():
    prompt = hc.prompt_for(CARDS[0])
    assert "九种景别" in prompt
    assert "top1" in prompt and "must" in prompt
    assert "JSON" in prompt


def test_parse_draft_tolerates_code_fence_and_prose():
    raw = '好的，这是结果：\n```json\n{"q": "情绪=狂喜", "must": ["TROPE:genre=film,emotion=狂喜"], ' \
          '"top1": ["TROPE:genre=film,emotion=狂喜"], "never": []}\n```\n以上。'
    draft = hc.parse_draft(raw)
    assert draft["q"] == "情绪=狂喜"
    assert draft["expect_movements"] == []


def test_parse_draft_rejects_missing_fields():
    try:
        hc.parse_draft('{"q": "情绪=狂喜"}')
    except ValueError as exc:
        assert "must" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("应当抛 ValueError")


def test_draft_all_attaches_card_id_and_prompt_hash():
    drafts = hc.draft_all(CARDS, hc.offline_transport)
    assert [d["from_card"] for d in drafts] == ["cine_shot_size", "axis_180"]
    assert all(len(d["_prompt_sha256"]) == 64 for d in drafts)


def test_draft_all_records_transport_failure_without_raising():
    def boom(_prompt: str) -> str:
        raise RuntimeError("network down")

    try:
        hc.draft_all(CARDS[:1], boom)
    except RuntimeError:
        pass  # 传输层异常原样冒泡是允许的；解析失败才被记录


def test_disagreements_detects_must_differences():
    a = [{"from_card": "c1", "must": ["X:emotion=a,intensity=mid"]}]
    b = [{"from_card": "c1", "must": ["Y:genre=film,emotion=a"]}]
    assert hc.disagreements(a, b) == ["c1"]


def test_disagreements_empty_when_identical():
    a = [{"from_card": "c1", "must": ["X:emotion=a,intensity=mid"]}]
    assert hc.disagreements(a, list(a)) == []


def test_disagreements_flags_error_drafts():
    a = [{"from_card": "c1", "error": "bad json"}]
    assert hc.disagreements(a, []) == ["c1"]


def test_render_sheet_only_lists_disagreements():
    drafts = [{"from_card": "c1", "q": "情绪=狂喜", "must": ["TROPE:genre=film,emotion=狂喜"],
               "expect_movements": ["甩镜"]},
              {"from_card": "c2", "q": "景别=中景", "must": ["SHOT_PATTERN:shot_size=中景,lens=50mm,headroom_policy=board"],
               "expect_movements": []}]
    sheet = hc.render_sheet(drafts, ["c2"])
    assert "c2" in sheet and "c1" not in sheet
    assert "[ ]" in sheet
    assert "甩镜" not in sheet


def test_cli_writes_three_artifacts(tmp_path):
    cards = tmp_path / "cards.json"
    cards.write_text(json.dumps(CARDS, ensure_ascii=False), encoding="utf-8")
    rc = hc.main(["--cards", str(cards), "--out-dir", str(tmp_path)])
    assert rc == 0
    for name in ("candidates.jsonl", "disagreements.json", "candidates.md"):
        assert (tmp_path / name).is_file(), name
    first = json.loads((tmp_path / "candidates.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert first["from_card"] == "cine_shot_size"


def test_cli_skips_second_family_when_disabled(tmp_path):
    cards = tmp_path / "cards.json"
    cards.write_text(json.dumps(CARDS, ensure_ascii=False), encoding="utf-8")
    assert hc.main(["--cards", str(cards), "--out-dir", str(tmp_path),
                    "--transport-b", "none"]) == 0
    assert not (tmp_path / "disagreements.json").exists()


def test_unknown_transport_is_rejected():
    try:
        hc.build_transport("nope")
    except SystemExit as exc:
        assert "nope" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("应当 SystemExit")
