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
    code = "\n".join(line for line in source.splitlines()
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
    """给了词表就**按 kind 列出允许取值**。

    实测依据（2026-10-05）：提示词只给 kind 闭集时，模型自由造值
    （`pacing:rapid`、`lens:长镜头`、`genre:music video`），接上取值词表关之后
    **4/4 全被拒**。所以要把"每个 kind 允许写什么"写进提示词。
    """
    vocab = {"shot_size": ["MS", "MCU"], "pacing": ["short", "long"]}
    menu = ex.edge_type_menu(vocab)
    assert "shot_size：MS/MCU" in menu
    assert "pacing：short/long" in menu
    #: 有词表的 kind 与没有词表的 kind 都要能分辨——没有的写"（自由文本）"。
    assert "lens：（自由文本，取本段逐字出现的那个）" in menu


def test_without_a_vocabulary_the_menu_falls_back_to_the_frozen_enums():
    """没给词表时退回 `hg.VALUE_DOMAINS` 的冻结枚举（不许写成"随便写"）。"""
    menu = ex.edge_type_menu()
    assert "headroom_policy：board/cinematic" in menu
    assert "avg_shot_len：" in menu


def test_the_driver_passes_the_vocabulary_into_the_prompt():
    seen = {}

    def fake_llm(prompt: str) -> str:
        seen["prompt"] = prompt
        return json.dumps({"drafts": []})

    ex.extract([{"source_ref": {"url": "u", "sha256": "e" * 64},
                 "text": "景别用中景，机位偏离轴线 30 度到 45 度才是干净的单人。" * 3}],
               llm=fake_llm, max_chars=400, min_chars=0,
               vocab={"shot_size": ["MS", "MCU"]})
    assert "shot_size：MS/MCU" in seen["prompt"]


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
