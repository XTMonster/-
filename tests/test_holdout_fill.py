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


def test_absorb_rejects_values_outside_the_frozen_vocab(monkeypatch):
    """`q`/`must` 里写了词表外的取值 → 产出侧就要拦（门③ 的 unknown 侧）。

    实测：`轴线=银幕方向` 这种写法在索引里找不到 node，一个种子都命中不了——
    38 条查询的 Q1 掉到 0.026、Q2 掉到 0.184，而根因只是查询串没落进词表。
    """
    _with_annotator(monkeypatch)
    vocab = {"emotion": ["荒诞", "平静"], "intensity": ["high", "low"],
             "shot_size": ["MS"]}
    good = _entry("c1", "情绪=荒诞", ["EMOTION_PACK:emotion=荒诞,intensity=high"])
    bad_q = _entry("c1", "情绪=暴怒", ["EMOTION_PACK:emotion=暴怒,intensity=high"])
    bad_slot = _entry("c2", "情绪=荒诞", ["EMOTION_PACK:emotion=荒诞,intensity=extreme"])

    entries, rejects = [], []
    holdout_fill.absorb(entries, rejects, {"entries": [good, bad_q, bad_slot]},
                        {"c1", "c2"}, 0, vocab=vocab)

    assert [e["id"] for e in entries] == ["hq_0001"]
    reasons = [r["reason"] for r in rejects]
    assert sum(1 for r in reasons if r.startswith("vocab:")) == 2


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


def test_coverage_rounds_rotate_through_the_cards(tmp_path, monkeypatch):
    """新鲜卡用完时必须**换一批卡**，不能在同样 12 张卡上空转。

    temperature=0 下，同一批卡 ＋ 同一个 prompt 会产出逐字相同的条目，全被
    `_dedupe_key` 丢掉——覆盖轮于是"跑了 60 轮，一条没加"，而总量门还差几百条。
    """
    cards = [{"id": f"c{i:02d}", "domain": "anime", "title": "t", "content": "x"}
             for i in range(30)]
    seen_picks = []

    class _Client:
        model_id = "m"
        model_version = "v"
        prefill = ""

        def chat_json(self, system, user, temperature, seed, num_ctx, key="", retries=2):
            # 从提示里把"用这几张卡"的段落记下来，然后什么都不产出
            import re
            seen_picks.append(tuple(sorted(re.findall(r"### (c\d+)", user))))
            return {"entries": []}

    holdout_fill.coverage_rounds(cards, {"emotion": ["荒诞"]}, _Client(), [], [], set(),
                                 "fp", rounds=3, counter=0, window=6,
                                 progress_path=tmp_path / "progress.json",
                                 partial_path=tmp_path / "partial.jsonl")

    assert len(seen_picks) == 3
    assert seen_picks[0] != seen_picks[1], "相邻覆盖轮必须换卡"
    assert seen_picks[1] != seen_picks[2]


def test_gap_round_entries_record_the_gap_prompt_sha(tmp_path, monkeypatch):
    """补跑轮用的是 `GAP_PROMPT`，条目必须记**它**的 sha，而不是基础 prompt 的。

    否则同一份文件里两种提示产出的条目会被记成同一个标注者——provenance 变成假账。
    """
    _with_annotator(monkeypatch)
    base_sha = holdout_fill._ANNOTATOR["prompt_sha256"]
    cards = [{"id": "c0", "domain": "anime", "title": "t", "content": "x" * 20}]

    class _Client:
        model_id = "m"
        model_version = "v"
        prefill = ""

        def chat_json(self, system, user, temperature, seed, num_ctx, key="", retries=2):
            # 补跑轮的**有效**系统提示 = 基础 prompt ＋ 缺口清单段（缺了前者，
            # 模型会写出 `标签=`/`关键词=` 这种不在冻结键集里的键）
            assert system == holdout_fill.holdout_gen.SYSTEM_PROMPT + "\n\n" + \
                holdout_fill.GAP_PROMPT
            return {"entries": [_entry("c0", "情绪=荒诞",
                                       ["EMOTION_PACK:emotion=荒诞,intensity=high"])]}

    entries, rejects = [], []
    holdout_fill.coverage_rounds(cards, {"emotion": ["荒诞"]}, _Client(), entries, rejects,
                                 set(), "fp", rounds=1, counter=0, window=1,
                                 progress_path=tmp_path / "progress.json",
                                 partial_path=tmp_path / "partial.jsonl")
    assert len(entries) == 1
    assert entries[0]["annotator"]["prompt_sha256"] == holdout_fill.gap_prompt_sha()
    assert entries[0]["annotator"]["prompt_sha256"] != base_sha


def test_gap_prompt_change_scopes_the_gap_keys_not_the_card_rounds(monkeypatch):
    """改补跑提示：**只**让补跑轮重跑，不该把卡片轮的结果一起作废。

    卡片轮与补跑轮是两套提示：前者用 `holdout_gen.SYSTEM_PROMPT`，后者是
    `SYSTEM_PROMPT ＋ GAP_PROMPT`。把它们塞进同一个续跑指纹，会出现"改补跑提示
    ＝丢掉整轮卡片结果"这种过度作废（实测：674 条卡片结果会因补跑提示措辞变化被扔）。
    现在补跑轮的完成键带补跑提示 sha 前缀，提示一变旧键自然失效、该轮重跑。
    """
    _with_annotator(monkeypatch)

    class _Client:
        model_id = "m"
        model_version = "v"
        prefill = ""

    cards = [{"id": "c1", "content": "x"}]
    baseline = holdout_fill.run_fingerprint(cards, _Client(), "v1")
    old_key = holdout_fill.gap_round_key(3, ["c1", "c2"])
    monkeypatch.setattr(holdout_fill, "GAP_PROMPT", holdout_fill.GAP_PROMPT + "\n新增")
    assert holdout_fill.run_fingerprint(cards, _Client(), "v1") == baseline, \
        "卡片轮的续跑指纹不该被补跑提示牵动"
    assert holdout_fill.gap_round_key(3, ["c1", "c2"]) != old_key, \
        "补跑提示变了，同一轮的完成键必须换，逼它重跑"


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
