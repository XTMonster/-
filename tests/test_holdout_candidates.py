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
    prompt = hc.prompt_for(CARDS[0])
    a = hc.offline_transport(prompt)
    b = hc.offline_transport(prompt)
    assert a == b
    payload = json.loads(a)
    assert payload["must"], "必须给出至少一条边"


def test_prompt_carries_every_field_the_stub_needs():
    card = hc.card_from_prompt(hc.prompt_for(CARDS[1]))
    assert card["id"] == "axis_180"
    assert card["domain"] == "axis_theory"
    assert card["title"] == "一百八十度规则"


def test_prompt_mentions_the_card_and_the_rules():
    prompt = hc.prompt_for(CARDS[0])
    assert "九种景别" in prompt
    assert "top1" in prompt and "must" in prompt
    assert "JSON" in prompt


def test_prompt_teaches_the_forbid_syntax():
    """提示词不提 forbid_ 语法，门⑤ 就永远过不了（这是审查员抓到的一条）。"""
    prompt = hc.prompt_for(CARDS[0])
    assert "forbid_" in prompt
    assert "禁忌" in prompt


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
    drafts = hc.draft_all(CARDS, hc.offline_transport, family="a")
    assert [d["from_card"] for d in drafts] == ["cine_shot_size", "axis_180"]
    assert all(len(d["_prompt_sha256"]) == 64 for d in drafts)


def test_draft_all_records_transport_failure_without_raising():
    def boom(_prompt: str) -> str:
        raise RuntimeError("network down")

    try:
        hc.draft_all(CARDS[:1], boom, family="a")
    except RuntimeError:
        pass  # 传输层异常原样冒泡是允许的；解析失败才被记录


# ---------------------------------------------------------------- 并发与续跑

def test_concurrent_drafting_matches_sequential():
    seq = hc.draft_all(CARDS, hc.offline_transport, family="a", concurrency=1)
    par = hc.draft_all(CARDS, hc.offline_transport, family="a", concurrency=3)
    assert seq == par


def test_resume_skips_cards_already_in_the_checkpoint(tmp_path):
    checkpoint = tmp_path / "draft_checkpoint.jsonl"
    calls: list = []
    first = hc.draft_all(CARDS, hc.offline_transport, family="a", concurrency=1,
                         checkpoint=checkpoint, calls=calls)
    assert calls == ["cine_shot_size", "axis_180"]
    assert checkpoint.is_file()

    calls2: list = []
    second = hc.draft_all(CARDS, hc.offline_transport, family="a", concurrency=1,
                          checkpoint=checkpoint, calls=calls2)
    assert calls2 == []                      # 全部命中检查点，没有再发请求
    assert second == first


def test_resume_reprompts_when_the_prompt_changes(tmp_path, monkeypatch):
    """提示词一变，指纹就对不上，缓存必须失效（否则会静默复用旧答案）。"""
    checkpoint = tmp_path / "draft_checkpoint.jsonl"
    hc.draft_all(CARDS[:1], hc.offline_transport, family="a", checkpoint=checkpoint)
    monkeypatch.setattr(hc, "prompt_for", lambda card: "完全不同的提示词 " + str(card.get("id")))
    calls: list = []
    hc.draft_all(CARDS[:1], hc.offline_transport, family="a", checkpoint=checkpoint,
                 calls=calls)
    assert calls == ["cine_shot_size"]


def test_resume_is_per_family(tmp_path):
    """两个族各存各的检查点行，互不冒充。"""
    checkpoint = tmp_path / "draft_checkpoint.jsonl"
    calls: list = []
    hc.draft_all(CARDS[:1], hc.offline_transport, family="a", checkpoint=checkpoint)
    hc.draft_all(CARDS[:1], hc.offline_transport_b, family="b", checkpoint=checkpoint,
                 calls=calls)
    assert calls == ["cine_shot_size"]


def test_disagreements_detects_must_differences():
    a = [{"from_card": "c1", "must": ["X:emotion=a,intensity=mid"]}]
    b = [{"from_card": "c1", "must": ["Y:genre=film,emotion=a"]}]
    assert hc.disagreements(a, b) == ["c1"]


def test_disagreements_also_look_at_q_and_never():
    """q 是 Q5 的 join 键、never 是 Q3 的输入，只看 must 会漏掉它们的分歧。"""
    a = [{"from_card": "c1", "must": ["M"], "q": "情绪=荒诞", "top1": ["M"], "never": []}]
    b = [{"from_card": "c1", "must": ["M"], "q": "情绪=滑稽", "top1": ["M"], "never": []}]
    assert hc.disagreements(a, b) == ["c1"]
    c = [{"from_card": "c1", "must": ["M"], "q": "情绪=荒诞", "top1": ["M"], "never": ["N"]}]
    assert hc.disagreements(a, c) == ["c1"]


def test_two_stub_families_really_disagree():
    """两个族的 stub 必须真的产生分歧，否则分歧通道等于没测。"""
    a = hc.draft_all(CARDS, hc.offline_transport)
    b = hc.draft_all(CARDS, hc.offline_transport_b)
    assert hc.disagreements(a, b) == ["cine_shot_size", "axis_180"]


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
    rc = hc.main(["--cards", str(cards), "--out-dir", str(tmp_path),
                  "--family", "qwen", "--extractor-family", "deepseek",
                  "--model-id", "qwen3-vl:30b", "--model-version", "30b"])
    assert rc == 0
    for name in ("candidates.jsonl", "disagreements.json", "candidates.md"):
        assert (tmp_path / name).is_file(), name
    first = json.loads((tmp_path / "candidates.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert first["from_card"] == "cine_shot_size"
    assert first["id"] == "hq_0001"
    assert first["annotator"]["family"] == "qwen"
    assert first["annotator"]["model_id"] == "qwen3-vl:30b"
    assert first["annotator"]["model_version"] == "30b"
    assert first["annotator"]["prompt_sha256"]          # 证据链不得为空
    assert first["independence"] == "strong"


def test_independence_is_weak_without_a_different_extractor_family(tmp_path):
    """协议 §5.1：与抽取族同族 → weak；不给抽取族 → 只能保守记 weak。"""
    cards = tmp_path / "cards.json"
    cards.write_text(json.dumps(CARDS, ensure_ascii=False), encoding="utf-8")
    assert hc.main(["--cards", str(cards), "--out-dir", str(tmp_path)]) == 0
    first = json.loads((tmp_path / "candidates.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert first["independence"] == "weak"


def test_cli_output_is_accepted_by_check_holdout(tmp_path):
    """草稿必须能直接喂给校验器（管道闭合）。"""
    sys.path.insert(0, str(ROOT))
    from tools import check_holdout

    cards = tmp_path / "cards.json"
    cards.write_text(json.dumps(CARDS, ensure_ascii=False), encoding="utf-8")
    assert hc.main(["--cards", str(cards), "--out-dir", str(tmp_path),
                    "--model-id", "offline", "--model-version", "stub"]) == 0
    rc = check_holdout.main([str(tmp_path / "candidates.jsonl"), "--pilot", "--json"])
    # 格式门必须过；其余门在 2 条草稿上按试点门限判定
    assert rc in (0, 1, 2)
    report = json.loads(_capture(lambda: check_holdout.main(
        [str(tmp_path / "candidates.jsonl"), "--pilot", "--json"])))
    assert report["gate_2_format"]["status"] == "pass"


def _capture(fn):
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    with redirect_stdout(buf):
        fn()
    return buf.getvalue()


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


# ---------------------------------------------------------------- 人裁决的最后一公里

def test_merge_decisions_drops_rejected_and_records_review():
    entries = [{"id": "hq_0001", "from_card": "c1"}, {"id": "hq_0002", "from_card": "c2"}]
    merged = hc.merge_decisions(entries, {"hq_0001": "accepted", "hq_0002": "rejected"})
    assert [e["id"] for e in merged] == ["hq_0001"]
    assert merged[0]["review"] == {"reviewed_by": "human", "verdict": "accepted"}


def test_merge_decisions_keeps_undecided_entries_untouched():
    """两族一致的条目不用人裁，保持原样入库。"""
    entries = [{"id": "hq_0001"}, {"id": "hq_0002"}]
    merged = hc.merge_decisions(entries, {"hq_0002": "amended"})
    assert "review" not in merged[0]
    assert merged[1]["review"]["verdict"] == "amended"


def test_merge_decisions_accepts_rich_verdicts():
    entries = [{"id": "hq_0001"}]
    merged = hc.merge_decisions(entries, {"hq_0001": {"verdict": "amended",
                                                      "note": "把 intensity 改成 low"}})
    assert merged[0]["review"]["note"] == "把 intensity 改成 low"


def test_merge_decisions_rejects_unknown_ids():
    try:
        hc.merge_decisions([{"id": "hq_0001"}], {"hq_9999": "accepted"})
    except SystemExit as exc:
        assert "hq_9999" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("应当 SystemExit（裁决表与文件漂移）")


def test_cli_merge_writes_the_final_jsonl(tmp_path):
    cards = tmp_path / "cards.json"
    cards.write_text(json.dumps(CARDS, ensure_ascii=False), encoding="utf-8")
    assert hc.main(["--cards", str(cards), "--out-dir", str(tmp_path)]) == 0
    decisions = tmp_path / "decisions.json"
    decisions.write_text(json.dumps({"hq_0001": "accepted", "hq_0002": "rejected"}),
                         encoding="utf-8")
    rc = hc.main(["--merge-from", str(decisions), "--out-dir", str(tmp_path)])
    assert rc == 0
    final = (tmp_path / "knowledge_holdout.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(final) == 1
    assert json.loads(final[0])["review"]["verdict"] == "accepted"


def test_sheet_round_trips_back_into_decisions(tmp_path):
    """人打勾的 md 必须能机械读回——否则"最后一公里"还是人工转写。"""
    drafts = [{"id": "hq_0001", "from_card": "c1", "q": "情绪=狂喜",
               "must": ["TROPE:genre=film,emotion=狂喜"], "expect_movements": []},
              {"id": "hq_0002", "from_card": "c2", "q": "景别=中景",
               "must": ["SHOT_PATTERN:shot_size=中景,lens=50mm,headroom_policy=board"],
               "expect_movements": []}]
    sheet = hc.render_sheet(drafts, ["c1", "c2"])
    assert "hq_0001" in sheet
    ticked = sheet.replace("| [ ] |", "| [x] |", 1)          # 人只勾了第一条
    decisions = hc.sheet_to_decisions(ticked)
    assert decisions == {"hq_0001": "accepted"}

    path = tmp_path / "candidates.jsonl"
    path.write_text("\n".join(json.dumps(d, ensure_ascii=False) for d in
                              [dict(d, never=[], annotator={"model_id": "m", "family": "f",
                                                            "model_version": "1",
                                                            "prompt_sha256": "x"},
                                    independence="weak") for d in drafts]) + "\n",
                    encoding="utf-8")
    sheet_path = tmp_path / "candidates.md"
    sheet_path.write_text(ticked, encoding="utf-8")
    assert hc.main(["--merge-sheet", str(sheet_path), "--merge-into", str(path),
                    "--out-dir", str(tmp_path)]) == 0
    final = [json.loads(l) for l in
             (tmp_path / "knowledge_holdout.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(final) == 2                      # 没勾的保留（两族一致即可直接入库）
    assert final[0]["review"]["verdict"] == "accepted"


def test_cli_keeps_both_families_drafts_for_audit(tmp_path):
    """两族的草稿都要留痕（`drafts` 字段），否则分歧无法回溯。"""
    cards = tmp_path / "cards.json"
    cards.write_text(json.dumps(CARDS, ensure_ascii=False), encoding="utf-8")
    assert hc.main(["--cards", str(cards), "--out-dir", str(tmp_path),
                    "--family", "qwen", "--extractor-family", "deepseek"]) == 0
    first = json.loads((tmp_path / "candidates.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert set(first["drafts"]) == {"qwen", "qwen-b"}
