"""P5：L1/L2 的**影子构建**——把 P4 的草稿喂进现役的 `to_edge`。

为什么要一个薄壳而不是改 `build_hypergraph.py`：那个 134 KB 的模块是**判据执行
环境**（门①–⑩、九条校验、归并窗口都在它与 `block_director/knowledge/hypergraph.py`
里），它已经被 `tests/plan_v4_instruments.sha256.json` 冻结。重建要换的是**语料与
抽取实现**，不是那些门——所以本模块只做"草稿 → 现役 `to_edge` → 落影子目录"，
**一行都不改** `to_edge`。

v4 里"卡片"是什么：**知识片段**（P4 的 `Segment`）。草稿带 `source.span`，
按 span 反查出它所在的片段，把片段当卡片（`content` ＝ 片段正文）。这不是换概念，
而是让 `to_edge` 的**成员级依据**检查真的有东西可查——依据必须逐字出自那一段。

本文件钉四件事：

1. 草稿能变成 `to_edge` 认的原始边形状（`type`／`source_card`／`members`）；
2. **取值词表外的写法被拒收并具名**——这是 P4 试点暴露的口径差（`pacing:followed
   the singer` 过得了 P4 的粗闭集，过不了这一层），也是 D9 护栏的第一次真实读数；
3. 账目闭合：`kept + rejected == drafts seen`；
4. 只往**给定的影子目录**写，现役 `knowledge/` 一个字节都不动。
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge import hypergraph as hg  # noqa: E402
from tools.kb_fetch import build_shadow as bs  # noqa: E402
from tools.kb_fetch import extract_segmented as ex  # noqa: E402

TEXT = (
    "正反打是两人对话的主力覆盖，但它最容易越轴：机位偏离轴线 30 度到 45 度才是干净的单人。\n"
    "\n"
    "这条经验说的是：景别用中景、镜头用 50mm 的时候，留白要落在背向视线的那条三分线上。\n"
)


def _corpus(tmp_path: pathlib.Path) -> pathlib.Path:
    corpus = tmp_path / "corpus_v4"
    corpus.mkdir(parents=True, exist_ok=True)
    record = {"source_ref": {"url": "https://example.org/a", "sha256": "a" * 64},
              "domain": "cinematography", "text": TEXT}
    (corpus / "fetched.jsonl").write_text(json.dumps(record, ensure_ascii=False) + "\n",
                                          encoding="utf-8")
    return corpus


def _draft(tmp_path: pathlib.Path, members, edge_type=hg.SHOT_PATTERN):
    """造一条带**真实出处**的草稿：span 指向第二段。"""
    start = TEXT.index("这条经验")
    return {"type": edge_type, "members": members, "confidence": 8,
            "source": {"url": "https://example.org/a", "sha256": "a" * 64,
                       "span": [start, len(TEXT)]}}


def test_segment_cards_key_on_the_span_and_carry_the_segment_text(tmp_path):
    cards = bs.segment_cards(_corpus(tmp_path), max_chars=2400)
    assert cards, "没有造出任何片段卡"
    for card_id, card in cards.items():
        assert card_id.startswith("seg:")
        assert card["content"].strip()
        assert card["source_ref"]["url"] == "https://example.org/a"


def test_a_draft_becomes_the_raw_edge_shape_that_to_edge_accepts(tmp_path):
    cards = bs.segment_cards(_corpus(tmp_path), max_chars=2400)
    draft = _draft(tmp_path, [["allow", "shot_size", "shot_size:MS"],
                              ["allow", "lens", "lens:50mm"]])
    raw, reason = bs.draft_to_raw(draft, cards=cards)
    assert reason == ""
    assert raw["type"] == hg.SHOT_PATTERN
    assert raw["source_card"] in cards
    assert raw["members"][0][:3] == ("allow", "shot_size", "shot_size:MS")


def test_a_draft_whose_span_matches_no_segment_is_rejected_by_name(tmp_path):
    cards = bs.segment_cards(_corpus(tmp_path), max_chars=2400)
    draft = _draft(tmp_path, [["allow", "shot_size", "shot_size:MS"]])
    draft["source"]["span"] = [0, 5]  # 落在第一段的片段边界里，但不是它的起点
    raw, reason = bs.draft_to_raw(draft, cards=cards)
    assert raw is None
    assert reason.startswith("no_segment_for_span")


def test_an_incomplete_draft_is_rejected_by_name_at_the_real_gate(tmp_path):
    """缺必填槽位的草稿在这一层被**具名**拒收（`missing_required`）。

    P4 的粗闭集只看 type/role/kind，所以"形状对但槽位不齐"的草稿过得去；
    现役 `to_edge` 的必填槽位门才是拦它的人。
    """
    drafts = [
        #: 缺 `qualifier/headroom_policy`（SHOT_PATTERN 的必填项）。
        _draft(tmp_path, [["allow", "shot_size", "shot_size:MS"],
                          ["allow", "lens", "lens:50mm"]]),
        #: 齐了。
        _draft(tmp_path, [["allow", "shot_size", "shot_size:MS"],
                          ["allow", "lens", "lens:50mm"],
                          ["qualifier", "headroom_policy", "headroom_policy:board"]]),
    ]
    drafts_path = tmp_path / "drafts.jsonl"
    drafts_path.write_text("\n".join(json.dumps(item, ensure_ascii=False)
                                     for item in drafts) + "\n", encoding="utf-8")
    out = tmp_path / "knowledge_v4"
    report = bs.build_shadow(drafts_path, corpus_dir=_corpus(tmp_path), out_dir=out)
    assert report["drafts_seen"] == 2
    assert report["kept"] + report["rejected"] == report["drafts_seen"]
    assert report["kept"] == 1 and report["rejected"] == 1
    assert report["rejects"][0]["reason"].startswith("missing_required:SHOT_PATTERN")


def test_without_a_node_index_the_value_vocabulary_is_NOT_checked(tmp_path):
    """**如实钉住当前的缺口**：`to_edge(node_index=None)` 不查取值词表。

    这不是"已经覆盖了"，恰恰相反——把 `pacing:followed the singer` 这种自由文本
    放进一条必填齐备的边里，它**照样通过**。要拦它必须在 `to_edge` 里传一个
    `NodeIndex`（现役 `build_hypergraph.NodeIndex.resolve()` 负责把词表外的成员
    丢掉、必填被丢则整条边判 `missing_required`），而 v4 的 `NodeIndex` 要先用
    `tools.kb_fetch.vocabulary` 在**新语料**上建出来。

    所以 P5 的下一块是"建 v4 词表 → 传 NodeIndex 再跑一次"，在它落地之前，
    **不许**把这一层的拒绝率当成词表关的读数。
    """
    cards = bs.segment_cards(_corpus(tmp_path), max_chars=2400)
    draft = _draft(tmp_path, [["allow", "shot_size", "shot_size:MS"],
                              ["allow", "lens", "lens:50mm"],
                              ["qualifier", "headroom_policy", "headroom_policy:board"],
                              ["allow", "pacing", "pacing:followed the singer"]])
    raw, reason = bs.draft_to_raw(draft, cards=cards)
    assert reason == ""
    edge, why = bs.hg_to_edge(raw, cards)
    assert (edge is not None, why) == (True, "")   # ← 词表外的取值**没有被拦**


def test_the_v4_vocabulary_harvests_lens_values_from_the_corpus_text(tmp_path):
    """`lens` 一类的开放值只能从**正文**里汇出来（现役 `vocabulary._LENS_RE`）。

    实测：只跑受控表得 176 个节点、把片段正文喂进去得 180——差的正是 4 个镜头焦距。
    夹具的正文里写了 "50mm"，所以 v4 词表里必须出现 `lens:50mm`。
    """
    cards = bs.segment_cards(_corpus(tmp_path), max_chars=2400)
    nodes, _vocab = bs.build_vocab(cards)
    ids = {str(node["node_id"]) for node in nodes}
    assert "lens:50mm" in ids
    assert "shot_size:MS" in ids
    assert "headroom_policy:board" in ids


def test_with_the_index_an_out_of_vocabulary_required_value_is_rejected(tmp_path):
    """接上 `NodeIndex` 之后，词表外的**必填**取值被丢掉 ⇒ 整条边具名拒收。"""
    cards = bs.segment_cards(_corpus(tmp_path), max_chars=2400)
    draft = _draft(tmp_path, [["allow", "shot_size", "shot_size:MS"],
                              ["allow", "lens", "lens:not-a-lens"],
                              ["qualifier", "headroom_policy", "headroom_policy:board"]])
    raw, reason = bs.draft_to_raw(draft, cards=cards)
    assert reason == ""
    nodes, _vocab = bs.build_vocab(cards)
    edge, why = bs.hg_to_edge(raw, cards, bs.node_index(nodes))
    assert edge is None
    assert why.startswith("missing_required:SHOT_PATTERN")
    assert "dropped=" in why


def test_building_the_shadow_vocab_does_not_touch_the_shipped_artifacts(tmp_path):
    """**回归守门**：影子构建绝不许写现役知识产物。

    2026-10-05 实测踩过一次：`vocabulary.run()` 有副作用（写
    `knowledge/hypergraph.vocab.json`、`knowledge/hypergraph.nodes.jsonl`、
    `fixtures/knowledge_holdout.vocab.json`），影子构建把它调起来之后，
    现役词表被覆盖、全量 pytest 三条红。重建期间现役产物必须逐字节不动。
    """
    import hashlib

    shipped = [bs.common.KNOWLEDGE / "hypergraph.vocab.json",
               bs.common.KNOWLEDGE / "hypergraph.nodes.jsonl",
               bs.common.ROOT / "fixtures" / "knowledge_holdout.vocab.json"]
    before = {str(path): (hashlib.sha256(path.read_bytes()).hexdigest()
                          if path.is_file() else "")
              for path in shipped}
    cards = bs.segment_cards(_corpus(tmp_path), max_chars=2400)
    bs.build_vocab(cards)
    after = {str(path): (hashlib.sha256(path.read_bytes()).hexdigest()
                         if path.is_file() else "")
             for path in shipped}
    assert before == after, "影子构建动了现役产物：%s" % [
        name for name in before if before[name] != after[name]]


def test_the_required_value_domain_is_known_to_the_schema():
    """反面参考：`headroom_policy` 的闭集是 `("board","cinematic")`——词表是有的，
    只是当前这条路径没把 `NodeIndex` 传进去（见上一条）。"""
    assert hg.VALUE_DOMAINS["headroom_policy"] == ("board", "cinematic")


def test_only_the_shadow_dir_is_written(tmp_path):
    blank = tmp_path / "drafts.jsonl"
    blank.write_text("", encoding="utf-8")
    out = tmp_path / "knowledge_v4"
    bs.build_shadow(blank, corpus_dir=_corpus(tmp_path), out_dir=out)
    assert (out / "build_report.json").is_file()
    assert (out / "hypergraph.edges.jsonl").is_file()
    assert not (bs.common.KNOWLEDGE / "hypergraph.edges.jsonl.tmp").exists()


def test_the_evidence_must_come_from_the_segment_it_cites(tmp_path):
    """成员依据逐字出自片段 ⇒ `to_edge` 记 `quoted`；现编的记 `fabricated`。"""
    cards = bs.segment_cards(_corpus(tmp_path), max_chars=2400)
    quote = "留白要落在背向视线的那条三分线上"
    draft = _draft(tmp_path, [["allow", "shot_size", "shot_size:MS", quote],
                              ["allow", "lens", "lens:50mm", quote],
                              ["qualifier", "headroom_policy",
                               "headroom_policy:board", quote]])
    raw, reason = bs.draft_to_raw(draft, cards=cards)
    assert reason == ""
    edge, why = bs.hg_to_edge(raw, cards)
    assert why == ""
    assert edge is not None
    #: 逐字依据落在 `extractor.member_grounding`（`to_edge` 的落地状态面）。
    assert edge.extractor["member_grounding"]["allow/shot_size"] == "quoted"
    assert edge.extractor["member_quotes"]["allow/lens"] == quote
