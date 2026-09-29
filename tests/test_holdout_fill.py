"""`tools/holdout_fill.py` 的断点续跑与覆盖缺口（离线，不碰网络）。"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import holdout_fill  # noqa: E402


def _entry(card: str, q: str, must: list) -> dict:
    return {"from_card": card, "q": q, "must": list(must),
            "top1": list(must), "never": []}


_ANNOTATOR = {"model_id": "test-model", "family": "qwen",
              "model_version": "test-model", "prompt_sha256": "deadbeef"}


def _with_annotator(monkeypatch):
    """`absorb()` 现在跑校验器的逐条判据，而 `annotator` 的
    `model_id/family/model_version` 是换族证据链的必填项——真实调用里由
    `set_annotator()` 填好，测试里要显式给。"""
    monkeypatch.setattr(holdout_fill, "_ANNOTATOR", dict(_ANNOTATOR))


def test_partial_checkpoint_round_trips(tmp_path):
    progress = tmp_path / "progress.json"
    partial = tmp_path / "partial.jsonl"
    entry = {"id": "hq_0001", **_entry("c1", "情绪=荒诞",
                                       ["EMOTION_PACK:emotion=荒诞,intensity=high"]),
             "annotator": {"model_id": "m", "family": "f", "model_version": "v"},
             "independence": "strong", "pilot": False}
    holdout_fill.save_partial([entry], [{"reason": "x"}], {"card:1:c1"},
                              "fp-1", progress, partial)

    entries, rejects, done = holdout_fill.load_partial("fp-1", progress, partial)
    assert [e["id"] for e in entries] == ["hq_0001"]
    assert rejects == [{"reason": "x"}]
    assert done == {"card:1:c1"}

    # 指纹变了（换了模型/卡片）→ 已完成的批作废，重新抽
    entries2, _rejects, done2 = holdout_fill.load_partial("fp-2", progress, partial)
    assert entries2 == [] and done2 == set()


def test_absent_checkpoint_is_empty_not_an_error(tmp_path):
    entries, rejects, done = holdout_fill.load_partial(
        "fp", tmp_path / "nope.json", tmp_path / "nope.jsonl")
    assert (entries, rejects, done) == ([], [], set())


def test_absorb_uses_the_same_per_entry_rules_as_the_gate(monkeypatch):
    """产出侧不许比校验器松：门② 判红的条目在 `absorb()` 里也必须被拒。

    实测过一次真实长跑：partial 里 284 条有 **94 条**带门② 问题（`q` 里同一个键写了
    两个取值、`q` 与 `must` 同 kind 取值不一致），而生成器把它们全当成功收下了——
    收尾时整批翻红，白跑一轮。根因是 `absorb()` 只做了 `holdout_gen.validate_entry`
    的结构校验，没有跑校验器的逐条判据。
    """
    _with_annotator(monkeypatch)
    duplicate_key = _entry("c1", "情绪=荒诞；情绪=压抑",
                           ["EMOTION_PACK:emotion=荒诞,intensity=high"])
    good = _entry("c1", "情绪=荒诞", ["EMOTION_PACK:emotion=荒诞,intensity=high"])

    entries, rejects = [], []
    counter = holdout_fill.absorb(entries, rejects, {"entries": [duplicate_key, good]},
                                 {"c1"}, 0)

    assert counter == 1, "只有合规的那条该被收下"
    assert len(entries) == 1 and entries[0]["from_card"] == "c1"
    assert rejects and rejects[0]["reason"].startswith("gate2:")


def test_absorb_never_crashes_on_a_self_contradictory_spec(monkeypatch):
    """同一个成员既要又要（`allow` 与 `forbid` 撞车）必须变成一条 reject，不许炸整轮。

    实测过：`_dedupe_key()` 里的 `spec_key()` 会对这种槽位抛 `EntryError`，而它原先在
    `try` 之外——于是 60 分钟的批处理跑到第 2 批就整个进程退出，前功尽弃。
    """
    _with_annotator(monkeypatch)
    contradictory = _entry("c1", "情绪=荒诞；运镜=固定",
                           ["EMOTION_PACK:emotion=荒诞,forbid_movement=固定,movement=固定"])
    good = _entry("c1", "情绪=荒诞", ["EMOTION_PACK:emotion=荒诞,intensity=high"])

    entries, rejects = [], []
    counter = holdout_fill.absorb(entries, rejects,
                                 {"entries": [contradictory, good]}, {"c1"}, 0)
    assert counter == 1
    assert [e["q"] for e in entries] == ["情绪=荒诞"]
    assert len(rejects) == 1, "自相矛盾的那条必须变成一条 reject（而不是让整轮崩掉）"
    assert "固定" in json.dumps(rejects, ensure_ascii=False)


def test_corrupt_checkpoint_is_ignored(tmp_path):
    progress = tmp_path / "progress.json"
    partial = tmp_path / "partial.jsonl"
    progress.write_text("{not json", encoding="utf-8")
    partial.write_text("", encoding="utf-8")
    assert holdout_fill.load_partial("fp", progress, partial) == ([], [], set())


def test_absorb_dedupes_and_counts_rejects(monkeypatch):
    _with_annotator(monkeypatch)
    entries = []
    rejects = []
    good = _entry("c1", "情绪=荒诞", ["EMOTION_PACK:emotion=荒诞,intensity=high"])
    bad = _entry("c1", "情绪=荒诞", ["NOT_A_TYPE:emotion=荒诞"])
    counter = holdout_fill.absorb(entries, rejects, {"entries": [good, good, bad]},
                                  {"c1"}, 0)
    assert counter == 1
    assert len(entries) == 1 and entries[0]["id"] == "hq_0001"
    assert entries[0]["annotator"] == {} or isinstance(entries[0]["annotator"], dict)
    assert len(rejects) == 1

    # 第二轮再给同一条 → 不重复计入
    counter = holdout_fill.absorb(entries, rejects, {"entries": [good]}, {"c1"}, counter)
    assert counter == 1 and len(entries) == 1

    holdout_fill.absorb(entries, rejects, {"nope": []}, {"c1"}, counter)
    assert rejects[-1]["reason"] == "reply_not_a_list"


def test_coverage_gaps_reports_every_missing_gate(tmp_path):
    """空集不得到判"过"——每一道门都要以真实缺口的形式报出来。"""
    vocab = {"emotion": ["荒诞", "平静"], "movement": ["推镜"]}
    gaps = holdout_fill.coverage_gaps([], vocab)
    assert gaps["entries"] == 0
    assert gaps["deficit"] == holdout_fill.MIN_ENTRIES
    assert gaps["format_ok"] is False
    assert gaps["q7_deficit"] == holdout_fill.MIN_FORBID
    assert gaps["forbid_under_covered"] == {}
    assert holdout_fill.gaps_closed(gaps) is False


def test_total_shortfall_keeps_the_coverage_rounds_running():
    """门①（总量 ≥1200）必须进"缺口是否闭合"的判定。

    实测过一次：覆盖轮只看 ②③④⑤⑥，总量还差几百条时 `gaps_closed()` 就返回 True，
    循环直接收工，交出来的文件过不了门①——补跑机制等于自己把自己关掉了。
    """
    open_gaps = {"format_ok": True, "deficit": 300, "missing_values": {},
                 "unknown_values": {}, "thin_values": {}, "short_pairs": {},
                 "thin_cards": {}, "q7_deficit": 0, "forbid_under_covered": {}}
    assert holdout_fill.gaps_closed(open_gaps) is False

    closed = dict(open_gaps, deficit=0)
    assert holdout_fill.gaps_closed(closed) is True

    prompt = holdout_fill.build_gap_prompt(open_gaps, [], {}, [])
    assert "300" in prompt and "1200" in prompt


def test_gap_prompt_names_the_shortfall_and_the_cards():
    gaps = {"missing_values": {"emotion": ["荒诞"]}, "thin_values": {},
            "short_pairs": {"EMOTION_PACK": 2}, "thin_cards": {},
            "q7_deficit": 58, "forbid_under_covered": {"movement=固定": 0}}
    cards = [{"id": "c1", "domain": "anime", "title": "t", "content": "x" * 20}]
    prompt = holdout_fill.build_gap_prompt(gaps, cards, {"emotion": ["荒诞"]}, ["c1"])
    assert "荒诞" in prompt and "c1" in prompt
    assert "还差 58 条" in prompt
    assert "EMOTION_PACK" in prompt


def test_run_fingerprint_changes_with_the_model():
    class _Client:
        model_id = "qwen3-vl:30b"

    cards = [{"id": "c1", "content": "x"}]
    first = holdout_fill.run_fingerprint(cards, _Client(), "v1")

    class _Other:
        model_id = "qwen3-vl:8b"

    assert holdout_fill.run_fingerprint(cards, _Other(), "v1") != first
    assert holdout_fill.run_fingerprint(cards, _Client(), "v2") != first
    assert holdout_fill.run_fingerprint(cards, _Client(), "v1") == first


def test_run_fingerprint_covers_the_prompt_text_and_the_decode_prefill(monkeypatch):
    """**改 prompt 正文必须让续跑指纹变**——只哈希版本号会把两套 prompt 混进一个文件。

    原先的指纹只拼 `cards + model_id + PROMPT_VERSION`：编辑 `SYSTEM_PROMPT` 却忘了改
    版本号时，`load_partial()` 会认为"还是同一次运行"，把旧的半成品与新 prompt 的
    条目拼在同一个 `knowledge_holdout.jsonl` 里（每条 `prompt_sha256` 不同，文件看不出来）。
    """
    class _Client:
        model_id = "qwen3-vl:30b"
        model_version = "bd-annotator:8k"
        prefill = ""

    cards = [{"id": "c1", "content": "x"}]
    baseline = holdout_fill.run_fingerprint(cards, _Client(), "v1")

    # 1) 版本号不变，只改 prompt 正文 → 指纹必须变
    monkeypatch.setattr(holdout_fill.holdout_gen, "SYSTEM_PROMPT",
                        holdout_fill.holdout_gen.SYSTEM_PROMPT + "\n新增一行约束")
    assert holdout_fill.run_fingerprint(cards, _Client(), "v1") != baseline

    # 2) 打开 assistant 预填（改变解码条件）→ 指纹也必须变
    class _Prefilled(_Client):
        prefill = '{"entries": ['

    assert holdout_fill.run_fingerprint(cards, _Prefilled(), "v1") != baseline

    # 3) 模型版本变了（同一个 model_id 下换了变体）→ 指纹也要变
    class _OtherVersion(_Client):
        model_version = "qwen3-vl:30b"

    assert holdout_fill.run_fingerprint(cards, _OtherVersion(), "v1") != baseline


def test_fill_writes_the_input_card_set_and_reports_the_missing_ones(tmp_path, monkeypatch):
    """`.cards.json` 必须是**输入卡片全集**，否则门⑥ 会退化成同义反复。

    原先这里写的是"covered 集合"，于是门⑥（每张入库卡至少派生 1 条）永远成立：
    工具自己定义输入、再断言输入被覆盖。现在 `.cards.json` 写全量（门⑥ 的输入），
    另存 `.covered.json` 与 `report["cards_missing"]` 作为诊断——缺口要能翻红，
    而不是被抹平。
    """
    out = tmp_path / "holdout.jsonl"
    vocab_path = tmp_path / "vocab.json"
    vocab_path.write_text(json.dumps({"holdout_vocab": {"emotion": ["荒诞"]}}),
                          encoding="utf-8")
    cards = [{"id": "c1", "domain": "anime", "title": "t", "content": "x"},
             {"id": "c2", "domain": "anime", "title": "t", "content": "y"}]
    scripted = tmp_path / "scripted.json"
    scripted.write_text(json.dumps({"responses": {"c1": {"entries": [
        _entry("c1", "情绪=荒诞", ["EMOTION_PACK:emotion=荒诞,intensity=high"])]}}}),
        encoding="utf-8")
    cards_path = tmp_path / "cards.jsonl"
    cards_path.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in cards),
                          encoding="utf-8")
    code = holdout_fill.main([
        "--provider", "scripted", "--model", "fake", "--scripted", str(scripted),
        "--cards", str(cards_path), "--batch", "2", "--rounds", "0",
        "--vocab", str(vocab_path),
        "--out", str(out),
        "--progress", str(tmp_path / "progress.json"),
        "--partial", str(tmp_path / "partial.jsonl"),
        "--report", str(tmp_path / "report.json"),
    ])
    assert code == 1, "远不到 1200 条时必须以非零退出，不得假装完成"
    declared = json.loads(out.with_suffix(".cards.json").read_text(encoding="utf-8"))
    assert declared == ["c1", "c2"], "门⑥ 的输入是全量卡片，不是产出过条目的子集"
    assert json.loads(out.with_suffix(".cards.covered.json").read_text(
        encoding="utf-8")) == ["c1"]
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["entries"] == 1 and report["cards_covered"] == 1
    assert report["cards_missing"] == ["c2"], "没派生条目的卡必须被点名（这才是门⑥ 的牙齿）"
    assert report["gaps"]["entries"] == 1
