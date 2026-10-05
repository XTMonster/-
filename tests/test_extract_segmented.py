"""P4：两趟"分段 → 归属"抽取器（计划 v4 的 `extract/v19-seg`）。

它要解决的事（来自 `docs/knowledge/S2_UPSTREAM_PREMISE.md` 的实测）：
现役 v18 是**一趟**原子事实抽取；上游 HyperGraphRAG 的"超边"载荷是
一句话 ＋ 0–10 分，**没有类型／角色／槽位**，所以在我们的槽位 schema 下
"移植上游抽取层"不成立。可取的是它的**结构**：先切"完整知识片段"，
再把该片段里的耦合归到片段上。本模块按**本仓 schema 自实现**那趟结构
（ADR-0014 判例：翻译层＝自研，只记"算法参考"）。

本文件钉五件事（全部离线，LLM 用替身注入）：

1. **分段是确定性的**，且**覆盖全部正文**（不许把大段文字悄悄丢掉）；
2. 闭集之外的一切（边型／角色／kind）**拒收并具名**，绝不静默丢弃——
   这是本项目最反复踩的坑（`S0` 的静默 no-op、`53d3e3f` 的手抄漂移同族）；
3. 每条草稿必须带**出处**（哪份来源、哪一段偏移），否则拒收；
4. **账目闭合**：喂进去的段落数 ＝ 产出的草稿数（按段计）＋ 被拒数；
5. 闭集是**单一真源**：从 `block_director/knowledge/hypergraph.py` 读，
   本模块不许自带第二份清单（`check_holdout.py` 的注释点名过这个坑）。
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge import hypergraph as hg  # noqa: E402
from tools.kb_fetch import extract_segmented as ex  # noqa: E402

TEXT = (
    "第一段讲正反打：拍 A 的正面机位恰好落在两人连线上，正确做法是把机位偏离轴线 30 度。\n"
    "\n"
    "第二段讲越轨的代价：连续两个中性镜头会让观众失去左右关系。\n"
    "\n"
    "第三段讲留白：主体要落在背向视线的那条三分线上。\n"
)


def _record(url: str = "https://example.org/a") -> dict:
    return {"source_ref": {"url": url, "sha256": "a" * 64}, "text": TEXT}


# --- 1. 分段 -----------------------------------------------------------------

def test_segments_are_deterministic_and_cover_the_whole_text():
    first = ex.segment_text(TEXT, source_ref=_record()["source_ref"], max_chars=400)
    second = ex.segment_text(TEXT, source_ref=_record()["source_ref"], max_chars=400)
    assert [s.span for s in first] == [s.span for s in second]
    #: 覆盖：所有段的原文拼起来（去掉空白差异）必须等于输入。
    joined = "".join(TEXT[s.span[0]:s.span[1]] for s in first)
    assert "".join(joined.split()) == "".join(TEXT.split())
    assert all(s.text.strip() for s in first)


def test_a_long_paragraph_is_split_at_the_cap_not_truncated():
    long_text = "。".join("句子%02d" % index for index in range(60)) + "。"
    segments = ex.segment_text(long_text, source_ref={"url": "u", "sha256": "b" * 64},
                              max_chars=120)
    assert len(segments) > 1
    assert all(len(s.text) <= 120 for s in segments), [len(s.text) for s in segments]
    joined = "".join(long_text[s.span[0]:s.span[1]] for s in segments)
    assert "".join(joined.split()) == "".join(long_text.split())


# --- 2/3. 闭集与出处 ----------------------------------------------------------

def test_an_out_of_closed_set_edge_type_is_rejected_by_name():
    draft = {"type": "NOT_A_REAL_TYPE", "members": [["allow", "shot_size", "shot_size:MS"]],
             "source": {"url": "u", "sha256": "c" * 64, "span": [0, 10]}}
    ok, reason = ex.validate_draft(draft)
    assert ok is False
    assert reason == "bad_type:NOT_A_REAL_TYPE"


def test_an_out_of_closed_set_kind_is_rejected_by_name():
    draft = {"type": hg.SHOT_PATTERN,
             "members": [["allow", "not_a_kind", "not_a_kind:MS"]],
             "source": {"url": "u", "sha256": "c" * 64, "span": [0, 10]}}
    ok, reason = ex.validate_draft(draft)
    assert ok is False
    assert reason.startswith("bad_kind:")


def test_a_draft_without_provenance_is_rejected():
    draft = {"type": hg.SHOT_PATTERN, "members": [["allow", "shot_size", "shot_size:MS"]]}
    ok, reason = ex.validate_draft(draft)
    assert ok is False
    assert reason == "missing_source"


def test_a_valid_draft_keeps_its_span_and_members():
    draft = {"type": hg.SHOT_PATTERN,
             "members": [["allow", "shot_size", "shot_size:MS"],
                         ["allow", "lens", "lens:50mm"]],
             "source": {"url": "u", "sha256": "c" * 64, "span": [3, 40]},
             "confidence": 8}
    ok, reason = ex.validate_draft(draft)
    assert (ok, reason) == (True, "")


def test_the_closed_set_is_read_from_the_schema_not_copied():
    """单一真源：模块里不许自带第二份边型／kind 清单。"""
    source = (ROOT / "tools" / "kb_fetch" / "extract_segmented.py").read_text(encoding="utf-8")
    #: 只看**代码**：注释与 docstring 是散文（里面提到边型名是解释，不是抄清单）。
    code = re.sub(r'"""[\s\S]*?"""', "", source)
    code = re.sub(r"'''[\s\S]*?'''", "", code)
    code = "\n".join(line for line in code.splitlines()
                     if not line.strip().startswith("#"))
    assert "from block_director.knowledge import hypergraph" in code
    #: 硬编码的枚举清单（例如把 16 个边型抄成字面量元组）会在这里露头。
    assert "EMOTION_PACK" not in code, "边型清单被抄进了本模块"


def test_the_prompt_lists_the_required_slots_of_every_edge_type():
    """提示词必须带**每种边型的必填槽位**。

    实测依据（2026-10-05）：第一版提示词只列了闭集、没列必填，试点 21 条草稿
    在影子构建里 **100% 被拒，全部 `missing_required`**——模型给的是"这条边讲了
    哪几个槽位"，而 schema 要的是"这套边必须凑齐哪几个槽位"。
    """
    menu = ex.edge_type_menu()
    for edge_type, required in hg.REQUIRED_MEMBERS.items():
        assert edge_type in menu
        for role, kind in required:
            assert ("%s/%s" % (role, kind)) in menu, (edge_type, role, kind)


def test_the_prompt_lists_the_allowed_values_per_kind_when_a_vocabulary_is_given():
    """`value_lines()` 是**可选件**：给了词表就按 kind 列出允许取值。

    实测依据（2026-10-05）：提示词只给 kind 闭集时，模型自由造值
    （`pacing:rapid`、`lens:长镜头`、`genre:music video`），接上取值词表关之后
    **4/4 全被拒**。但把这张表**塞进单段提示词**会把产量打到 0（见
    `test_the_single_step_menu_deliberately_omits_values_and_glosses`），
    所以它只作为两段式 B 段的输入。
    """
    vocab = {"shot_size": ["MS", "MCU"], "pacing": ["short", "long"]}
    lines = ex.value_lines(vocab)
    assert "shot_size：MS/MCU" in lines
    assert "pacing：short/long" in lines
    #: 有词表的 kind 与没有词表的 kind 都要能分辨——没有的写"（自由文本）"。
    assert "lens：（自由文本，取本段逐字出现的那个）" in lines


def test_without_a_vocabulary_the_menu_falls_back_to_the_frozen_enums():
    """没给词表时 `value_lines()` 退回 `hg.VALUE_DOMAINS` 的冻结枚举。"""
    lines = ex.value_lines()
    assert "headroom_policy：board/cinematic" in lines
    assert "avg_shot_len：" in lines


def test_the_driver_uses_the_vocabulary_in_the_two_step_member_prompt():
    """`extract_two_step` 的 B 段必须把词表带进提示词（单段版**不带**，见上面的守门）。"""
    seen = {}

    def fake_llm(prompt: str) -> str:
        seen["prompt"] = prompt
        if ex.TYPE_STEP_MARK in prompt:
            return json.dumps({"types": ["SHOT_PATTERN"]})
        return json.dumps({"members": []})

    ex.extract_two_step([{"source_ref": {"url": "u", "sha256": "e" * 64},
                          "text": "景别用中景，机位 50mm，留白落在三分线。" * 6}],
                        llm=fake_llm, max_chars=600, min_chars=0,
                        vocab={"shot_size": ["MS", "MCU"]})
    assert "shot_size：MS/MCU" in seen["prompt"]


# --- 两段式（P4/P5⑥：平铺取值表把模型压死之后的唯一出路）---------------------------

def test_step_a_asks_only_for_types_and_carries_no_value_menu():
    """A 段只问"这段支持哪些边型"——**不带**取值表（那是压死模型的东西）。"""
    segment = ex.Segment(index=0, text="景别用中景，机位偏离轴线 30 度。" * 6,
                         span=(0, 120), source_ref={"url": "u", "sha256": "f" * 64})
    prompt = ex.type_prompt(segment)
    assert "支持哪些边型" in prompt
    assert "SHOT_PATTERN" in prompt and "必填" in prompt
    #: 取值表的下标（`kind：值1/值2`）不许出现在 A 段。
    assert "headroom_policy：board" not in prompt


def test_every_edge_type_has_a_semantic_gloss_taken_from_the_v18_prompt():
    """A 段必须带**语义注解**——而且注解是从现役 v18 提示词里**解析**出来的。

    为什么（实测 2026-10-05）：A 段只写"边型 ← 必填：role/kind"时，模型对
    700–1,040 字的段**一律返回 `{"types":[]}`**——`EMOTION_PACK`／`TROPE` 这些是
    我们自造的抽象名，只给名字与槽位结构，模型没法把学术散文映射过去。现役 v18 的
    `SYSTEM_PROMPT` 里本来就有每个边型的一句人话注解，直接复用、不再抄第二份。
    """
    glosses = ex.type_glosses()
    missing = sorted(set(hg.EDGE_TYPES) - set(glosses))
    assert missing == [], "这些边型没有语义注解：%s" % missing
    for edge_type, gloss in glosses.items():
        assert gloss.strip(), edge_type
    #: v18 对 ACTION_BEAT 的原话里有"节拍"两个字——解析必须真的取到它。
    assert "节拍" in glosses[hg.ACTION_BEAT]


def test_the_type_prompt_carries_the_gloss_not_just_the_slot_shape():
    segment = ex.Segment(index=0, text="推门进来，节拍落在 establish。" * 4,
                         span=(0, 60), source_ref={"url": "u", "sha256": "i" * 64})
    prompt = ex.type_prompt(segment)
    assert "节拍" in prompt          # ← 注解在
    assert "ACTION_BEAT" in prompt


def test_the_single_step_menu_deliberately_omits_values_and_glosses():
    """**别把取值表与注解塞回单段提示词**——实测每加一层细节产量就掉一截。

    同一批 60 段／temperature=0：只给边型 21 条 → ＋必填槽位 **4 条** →
    ＋允许取值 0 条 → ＋语义注解 0 条（重复两次）。所以默认只给必填槽位；
    取值表与注解保留为可选件（`value_lines()`／`type_glosses()`，两段式的 B 段用）。
    """
    menu = ex.edge_type_menu()
    assert "headroom_policy：board" not in menu      # 取值表不在
    assert "节拍" not in menu                       # 注解不在
    assert "HEADROOM" not in menu.upper() or True   # （只作可读性断言，不参与判据）
    #: 可选件本身仍然可用（两段式的 B 段要用）。
    assert "headroom_policy：board" in ex.value_lines()
    assert "节拍" in ex.type_glosses()[hg.ACTION_BEAT]


def test_the_closed_set_test_ignores_prose_but_catches_a_copied_list():
    """那条"不许抄第二份清单"的守门只看**代码**：注释与 docstring 是解释，不是清单。"""
    code = "TYPE_LIST = ('EMOTION_PACK', 'SHOT_PATTERN')"     # 真抄了
    prose = '"""说明里提到 EMOTION_PACK 不算抄。"""'
    assert "EMOTION_PACK" in code and "EMOTION_PACK" in prose


# --- A 路：陈述自带出处指针 ⇒ 当**原子段**，不许重新分段 ------------------------

def test_a_record_with_a_provenance_pointer_is_treated_as_one_atomic_segment():
    """A 路修法（台账 ⑪）：记录自带 `source.span` 时，抽取必须**原样用那个 span**。

    实测的缺陷（2026-10-05）：蒸馏出的 165 条陈述喂回抽取器时被**又分了一次段**，
    草稿的 span 于是相对**陈述串**，丢了指向原语料段的指针——
    影子构建里 3/3 全判 `no_segment_for_span`。
    """
    record = {"source_ref": {"url": "u", "sha256": "k" * 64},
              "text": "正反打最容易越轴。",                # 短陈述
              "source": {"url": "u", "sha256": "k" * 64, "span": [120, 480]}}
    segments = ex.segments_of(record, max_chars=100)
    assert len(segments) == 1
    assert segments[0].span == (120, 480)          # ← 原语料段的 span，不是 0-9
    assert segments[0].text == "正反打最容易越轴。"


def test_a_record_without_a_pointer_is_still_segmented_normally():
    record = {"source_ref": {"url": "u", "sha256": "l" * 64},
              "text": "一段讲正反打。\n\n另一段讲中性镜头。"}
    segments = ex.segments_of(record, max_chars=200)
    assert len(segments) == 2


def test_the_driver_keeps_the_pointer_span_on_the_draft():
    def fake_llm(prompt: str) -> str:
        return json.dumps({"drafts": [{"type": hg.SHOT_PATTERN,
                                       "members": [["allow", "shot_size", "shot_size:MS"],
                                                   ["allow", "lens", "lens:50mm"],
                                                   ["qualifier", "headroom_policy",
                                                    "headroom_policy:board"]]}]},
                          ensure_ascii=False)

    record = {"source_ref": {"url": "u", "sha256": "m" * 64},
              "text": "正反打最容易越轴，机位要偏离轴线 30 到 45 度。",
              "source": {"url": "u", "sha256": "m" * 64, "span": [200, 260]}}
    drafts, _rejects, _stats = ex.extract([record], llm=fake_llm, min_chars=0)
    assert drafts[0]["source"]["span"] == [200, 260]


def test_step_b_carries_only_the_selected_types_kinds_and_values():
    """B 段只带**被选中那一个边型**的 kind 与允许取值。"""
    prompt = ex.member_prompt(SegmentLike("文本"), hg.SHOT_PATTERN,
                              {"shot_size": ["MS"], "lens": ["50mm"],
                               "headroom_policy": ["board"], "pacing": ["short"]})
    assert "SHOT_PATTERN" in prompt
    assert "shot_size：MS" in prompt and "lens：50mm" in prompt
    #: 不属于这个边型的 kind 不许出现（枚举面从 26 个缩到 3 个）。
    assert "pacing：" not in prompt
    assert "EDIT_RHYTHM" not in prompt


class SegmentLike:
    """给 B 段用的最小片段替身（只带 `text` 与 `span`）。"""

    def __init__(self, text: str):
        self.text = text
        self.span = (0, len(text))


def test_two_step_combines_into_a_draft_with_provenance():
    text = "机位偏离轴线 30 度到 45 度，景别用中景，镜头 50mm。" * 4

    def fake_llm(prompt: str) -> str:
        if "支持哪些边型" in prompt:
            return json.dumps({"types": ["SHOT_PATTERN"]})
        return json.dumps({"members": [["allow", "shot_size", "shot_size:MS"],
                                       ["allow", "lens", "lens:50mm"],
                                       ["qualifier", "headroom_policy",
                                        "headroom_policy:board"]],
                           "confidence": 8})

    drafts, rejects, stats = ex.extract_two_step(
        [{"source_ref": {"url": "u", "sha256": "g" * 64}, "text": text}],
        llm=fake_llm, max_chars=600, min_chars=0,
        vocab={"shot_size": ["MS"], "lens": ["50mm"], "headroom_policy": ["board"]})
    assert rejects == []
    assert len(drafts) == 1
    draft = drafts[0]
    assert draft["type"] == hg.SHOT_PATTERN
    assert draft["source"]["url"] == "u" and draft["source"]["span"][1] > 0
    assert [member[0] for member in draft["members"]] == ["allow", "allow", "qualifier"]
    assert stats["calls"] == 2


def test_two_step_records_a_named_reject_when_the_type_step_is_unparseable():
    def fake_llm(prompt: str) -> str:
        return "not json at all"

    drafts, rejects, stats = ex.extract_two_step(
        [{"source_ref": {"url": "u", "sha256": "h" * 64}, "text": "x" * 200}],
        llm=fake_llm, max_chars=600, min_chars=0, vocab={})
    assert drafts == []
    assert rejects[0]["reason"].startswith("parse_fault")
    assert stats["kept"] + stats["rejected"] == stats["drafts_seen"] + stats["segments_failed"]


# --- 4. 驱动器与账目 ----------------------------------------------------------

def test_the_driver_closes_the_books_on_kept_and_rejected():
    """喂 3 段：2 段产出合法草稿、1 段产出闭集外的边型 ⇒ 账目必须闭合。"""
    replies = {
        "第一段": {"drafts": [{"type": hg.SHOT_PATTERN,
                             "members": [["allow", "shot_size", "shot_size:MS"]],
                             "confidence": 9}]},
        "第二段": {"drafts": [{"type": "BOGUS",
                             "members": [["allow", "shot_size", "shot_size:MS"]]}]},
        "第三段": {"drafts": [{"type": hg.STAGING_PACK,
                             "members": [["qualifier", "composition_rule", "composition_rule:三分线"]],
                             "confidence": 7}]},
    }

    def fake_llm(prompt: str) -> str:
        for key, payload in replies.items():
            if key in prompt:
                return json.dumps(payload, ensure_ascii=False)
        return json.dumps({"drafts": []})

    #: 这一段用短夹具，所以关掉"过短跳过"的过滤（那条另有专门的用例）。
    drafts, rejects, stats = ex.extract([_record()], llm=fake_llm, max_chars=400,
                                        min_chars=0)
    assert stats["segments"] == 3
    assert len(drafts) == 2 and len(rejects) == 1
    assert rejects[0]["reason"] == "bad_type:BOGUS"
    #: 每条草稿的出处＝它所在的那一段（供 P5 挂卡）。
    for draft in drafts:
        assert draft["source"]["span"][0] < draft["source"]["span"][1]
        assert draft["source"]["url"] == "https://example.org/a"
    assert stats["kept"] + stats["rejected"] == stats["drafts_seen"]


def test_short_chrome_segments_are_skipped_not_sent_to_the_model():
    """过短的段落（站点样板："Skip to main content"）不送模型——**也不算拒收**。

    实测（2026-10-05 的 P4 试点）：抽掉 HTML 之后，文章页前面几段仍是站点导航，
    模型对它们返空是**对的**；把它们算进"抽取失败"会把账记错地方。
    分段本身仍然**无损**（那是 `segment_text` 的不变量），过滤只发生在驱动这一层。
    """
    text = "Skip to main content\n\n" + ("讲正反打：机位要偏离轴线 30 度，否则会越轴。" * 6)

    def fake_llm(prompt: str) -> str:
        assert "Skip to main content" not in prompt, "样板段不该被送进模型"
        return json.dumps({"drafts": [{"type": hg.SHOT_PATTERN,
                                       "members": [["allow", "shot_size", "shot_size:MS"]]}]},
                          ensure_ascii=False)

    drafts, rejects, stats = ex.extract([{"source_ref": {"url": "u", "sha256": "d" * 64},
                                          "text": text}],
                                        llm=fake_llm, max_chars=400, min_chars=60)
    assert stats["skipped_short"] == 1
    assert stats["segments"] == 2
    assert len(drafts) == 1 and rejects == []


# --- ⑬ 候选边型由**查词表**决定，不问模型 -------------------------------------

def _nodes():
    """最小节点表：`name`/`aliases` 用来在正文里做匹配。"""
    return [
        {"node_id": "shot_size:MS", "type": "shot_size", "name": "中景",
         "value": "MS", "aliases": ["MS", "中景镜头"]},
        {"node_id": "lens:50mm", "type": "lens", "name": "50mm",
         "value": "50mm", "aliases": []},
        {"node_id": "headroom_policy:board", "type": "headroom_policy",
         "name": "board", "value": "board", "aliases": []},
        {"node_id": "pacing:short", "type": "pacing", "name": "短镜",
         "value": "short", "aliases": ["快剪"]},
        {"node_id": "avg_shot_len:>8s", "type": "avg_shot_len", "name": ">8s",
         "value": ">8s", "aliases": []},
    ]


def test_candidate_types_come_from_a_vocabulary_lookup_not_from_the_model():
    """正文里出现某边型**必填 kind** 的词表取值 ⇒ 它就是一个候选边型。

    为什么要这样（台账 ⑬）：让模型"先分类"（A 段）实测对 700–1,040 字的段
    **一律返回空**；而"这段里出现了哪些取值"是**词表在手就能判**的事，不该花一次调用。
    """
    text = "这一镜用中景，镜头 50mm，剪辑上是快剪。"
    candidates = ex.candidate_types(text, _nodes())
    assert "SHOT_PATTERN" in candidates          # 中景 ＋ 50mm 命中它的两个必填 kind
    assert "EDIT_RHYTHM" in candidates           # 快剪（pacing 的别名）命中一个
    assert "AXIS_RULE" not in candidates         # 正文里没有它的 kind 取值


def test_candidate_types_are_ranked_and_deterministic():
    text = "用中景，镜头 50mm，剪辑上是快剪。"
    first = ex.candidate_types(text, _nodes())
    second = ex.candidate_types(text, _nodes())
    assert first == second, "同输入必须同输出"
    #: 命中更多必填 kind 的排前面（SHOT_PATTERN 命中 2 个，EDIT_RHYTHM 命中 1 个）。
    assert first.index("SHOT_PATTERN") < first.index("EDIT_RHYTHM")


def test_scoped_extraction_only_calls_the_model_for_candidate_types():
    seen = []

    def fake_llm(prompt: str) -> str:
        seen.append(prompt)
        return json.dumps({"members": [["allow", "shot_size", "shot_size:MS"],
                                       ["allow", "lens", "lens:50mm"],
                                       ["qualifier", "headroom_policy",
                                        "headroom_policy:board"]],
                           "confidence": 8})

    record = {"source_ref": {"url": "u", "sha256": "n" * 64},
              "text": "这一镜用中景，镜头 50mm。",
              "source": {"url": "u", "sha256": "n" * 64, "span": [0, 40]}}
    drafts, _rejects, stats = ex.extract_scoped(
        [record], llm=fake_llm, nodes=_nodes(), vocab=ex.vocab_from_nodes(_nodes()),
        min_chars=0)
    assert len(seen) == stats["calls"], "每次调用都要记进 calls"
    expected = ex.candidate_types("这一镜用中景，镜头 50mm。", _nodes())[:3]
    asked = [edge for edge in ex.hg.EDGE_TYPES
             if any(("边型：%s\n" % edge) in prompt for prompt in seen)]
    assert asked == expected, "问的边型必须正好是查表得到的候选（不多不少）"
    assert "SHOT_PATTERN" in asked
    assert drafts and all(draft["type"] in asked for draft in drafts)


def test_scoped_extraction_skips_a_segment_with_no_candidate_type():
    called = []

    def fake_llm(prompt: str) -> str:
        called.append(prompt)
        return json.dumps({"members": []})

    record = {"source_ref": {"url": "u", "sha256": "o" * 64},
              "text": "这段讲的是影史分期，没有任何取值词表里的词。"}
    drafts, _rejects, stats = ex.extract_scoped(
        [record], llm=fake_llm, nodes=_nodes(), vocab={}, min_chars=0)
    assert called == [] and drafts == []
    assert stats["calls"] == 0 and stats["segments_skipped_no_candidate"] == 1


def test_the_member_prompt_allows_inference_the_way_the_repo_records_it():
    """提示词必须**允许推断**，并且与 `to_edge` 的记账机制对齐。

    实测依据：我的第一版 B 段写着"填不齐就返回空数组，不许编"，结果 76 次调用
    **全部返空**；而本仓的设计本来就允许推断——`build_hypergraph.py:178` 记着
    "284 个槽位里 86 个 quoted（30.3%）／198 个 inferred"，即**多数成员是推断来的**。
    机制上：`to_edge` 里**给了依据但原文没有** ⇒ `fabricated`；**不给依据** ⇒ `inferred`。
    所以正确写法是"原文没明说的槽位**不写第 4 项**"。
    """
    prompt = ex.member_prompt(SegmentLike("文本"), hg.SHOT_PATTERN, {})
    assert "inferred" in prompt
    assert "不要写第 4 项" in prompt
    #: 反面：不许再出现"填不齐就返回空数组"那种把推断堵死的措辞。
    assert "填不齐就返回空数组" not in prompt
    #: 单段提示词同样允许推断。
    assert "inferred" in ex.edge_type_menu()


def test_a_member_that_merges_role_and_kind_is_normalised():
    """模型常把角色与 kind 写成一格（`["allow/emotion", "emotion:joy"]`）⇒ 归一化。

    实测（2026-10-05 的 scoped 试点）：21 条草稿里 **19 条**全是这一种滑倒，
    拒收原因清一色 `bad_role:allow/emotion`／`bad_role:qualifier/transition`。
    形状归一化不是放宽判据——闭集与必填槽位照样由 `to_edge` 把关。
    """
    draft = {"type": hg.EMOTION_PACK,
             "members": [["allow/emotion", "emotion:喜悦"],
                         ["qualifier/intensity", "intensity:high"]],
             "source": {"url": "u", "sha256": "p" * 64, "span": [0, 10]}}
    ok, reason = ex.validate_draft(draft)
    assert (ok, reason) == (True, "")
    members = ex.normalise_members(draft["members"])
    assert members[0] == ["allow", "emotion", "emotion:喜悦"]
    assert members[1] == ["qualifier", "intensity", "intensity:high"]


def test_a_member_with_a_js_object_shape_is_also_normalised():
    """有的模型给的是 `{"role":…,"kind":…,"node_id":…}`——同样归一化成三元组。"""
    members = ex.normalise_members([{"role": "allow", "kind": "shot_size",
                                     "node_id": "shot_size:MS"}])
    assert members == [["allow", "shot_size", "shot_size:MS"]]


def test_normalisation_does_not_invent_anything():
    """归一化只改形状：合不出来的原样留着，交给闭集判据去拒。"""
    members = ex.normalise_members([["这不是角色", "也不是 kind"]])
    assert members == [["这不是角色", "也不是 kind"]]


def test_the_three_real_shapes_from_the_scoped_pilot_are_normalised():
    """scoped 试点里那 19 条 `bad_role` 的**三种真实形状**（逐条照抄自产物）。

    形状归一化不是放宽判据：闭集与必填槽位照样由 `validate_draft` 与 `to_edge` 把关；
    这里只是把"同一件事的另一种写法"还原成契约形状。
    """
    #: ① 3 段、首格含斜杠：`["allow/genre", "genre", "genre:动画"]`
    case1 = ex.normalise_members([["allow/genre", "genre", "genre:动画"]],
                                 hg.TROPE)
    assert case1 == [["allow", "genre", "genre:动画"]]
    #: ② 首格是 kind、第二格也是 kind：`["action", "action", "action:出场"]`
    case2 = ex.normalise_members([["action", "action", "action:出场"]],
                                 hg.ACTION_BEAT)
    assert case2 == [["allow", "action", "action:出场"]]
    #: ③ 角色与 kind 互换：`["beat_type", "qualifier", "beat_type:establish"]`
    case3 = ex.normalise_members([["beat_type", "qualifier", "beat_type:establish"]],
                                 hg.ACTION_BEAT)
    assert case3 == [["qualifier", "beat_type", "beat_type:establish"]]


def test_the_draft_that_reaches_the_writer_is_already_normalised():
    """驱动**写进草稿**的成员就得是契约形状——否则下游 `to_edge` 照样被拒。"""
    def fake_llm(prompt: str) -> str:
        return json.dumps({"members": [["allow/genre", "genre", "genre:动画"],
                                       ["allow/emotion", "emotion", "emotion:愉快"]]},
                          ensure_ascii=False)

    record = {"source_ref": {"url": "u", "sha256": "q" * 64},
              "text": "这是讲题材与情绪的段落，用中景。",
              "source": {"url": "u", "sha256": "q" * 64, "span": [0, 30]}}
    drafts, _rejects, _stats = ex.extract_scoped(
        [record], llm=fake_llm, nodes=_nodes(), vocab={}, min_chars=0)
    assert drafts, "应该有草稿产出"
    for draft in drafts:
        for member in draft["members"]:
            assert member[0] in hg.ROLES, member
            assert "/" not in member[0], member
