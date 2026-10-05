"""A 路：抽取前先把**散文片段**变成**短知识陈述**（卡片形状）。

为什么需要这一层（实测 2026-10-05 的证据链）：

* 现役 v18 抽取器是在**卡片**上工作的——卡片是已蒸馏过的短知识单元；
* v4 现在把 700–1,040 字的**学术散文段**直接喂进去；
* 同一批输入上，提示词每加一层 schema 细节，产量就掉一截：21 → 4 → 0 → 0 → 0。
  ⇒ 问题很可能不在提示词，而在**输入的形状**：模型要一边读散文、一边把它塞进
  一套它不认识的抽象槽位，于是选择空手。

所以本层只干一件事：把一段散文压成若干条**短陈述**（每条必须是这段里说过的，
不许评论、不许总结、不许发明）。之后的抽取就回到"在短知识单元上抽边"的形态，
也就是 v18 那套**已被验证过**的形态。

四条纪律：

1. **陈述必须可回溯**：每条带 `source`（url／sha256／该段的 span）；P5 的
   `to_edge` 靠它把成员依据回查到原文；
2. **解析失败具名**（`parse_fault:*`），不许静默跳过；
3. **账目闭合**：`statements_kept + rejected == statements_seen`；
4. **不许把散文原样当陈述**：太长的"陈述"（> `max_statement_chars`）判
   `too_long`——那说明模型在偷懒复述，不是蒸馏。
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.kb_fetch import distill_segments as ds  # noqa: E402

TEXT = (
    "正反打是两人对话的主力覆盖，但它最容易越轴：机位偏离轴线 30 度到 45 度才是"
    "干净的单人镜头。\n\n"
    "另外，连续两个中性镜头会让观众失去左右关系，所以中性镜头只能当跨轴桥梁。\n"
)


def _record(url: str = "https://example.org/a") -> dict:
    return {"source_ref": {"url": url, "sha256": "a" * 64}, "text": TEXT}


def _fake_llm(statements):
    def _llm(prompt: str) -> str:
        return json.dumps({"statements": statements}, ensure_ascii=False)
    return _llm


def test_a_segment_becomes_short_statements_with_provenance():
    #: 单段夹具：`segment_text` 会按空行切段，所以这里用没有空行的正文。
    single = {"source_ref": {"url": "https://example.org/a", "sha256": "a" * 64},
              "text": "正反打最容易越轴，机位偏离轴线 30 度到 45 度才是干净的单人镜头。"}
    statements, rejects, stats = ds.distill(
        [single], llm=_fake_llm(["正反打最容易越轴，机位要偏离轴线 30 到 45 度。"]),
        max_chars=400, min_chars=0)
    assert rejects == []
    assert stats["statements_seen"] == 1 and stats["kept"] == 1
    item = statements[0]
    assert item["text"].startswith("正反打最容易越轴")
    assert item["source"]["url"] == "https://example.org/a"
    assert item["source"]["span"][1] > item["source"]["span"][0]


def test_each_statement_carries_the_span_of_its_own_segment():
    """两条陈述分属两个片段 ⇒ 它们的 span 必须**不同**（否则 P5 回查会串段）。"""
    def _llm(prompt: str) -> str:
        if "正反打" in prompt:
            return json.dumps({"statements": ["正反打最容易越轴。"], }, ensure_ascii=False)
        return json.dumps({"statements": ["中性镜头只能当跨轴桥梁。"]}, ensure_ascii=False)

    statements, _rejects, _stats = ds.distill([_record()], llm=_llm,
                                              max_chars=120, min_chars=0)
    spans = {tuple(item["source"]["span"]) for item in statements}
    assert len(spans) == len(statements), "不同片段的 span 不许相同"


def test_a_restated_paragraph_is_rejected_as_too_long():
    """模型把整段复述回来 ⇒ 那不是蒸馏，判 `too_long`。"""
    statements, rejects, _stats = ds.distill(
        [_record()], llm=_fake_llm([TEXT]), max_chars=400, min_chars=0,
        max_statement_chars=40)
    assert statements == []
    assert rejects[0]["reason"].startswith("too_long:")


def test_a_parse_fault_is_named_not_silently_skipped():
    statements, rejects, stats = ds.distill([_record()], llm=lambda _p: "not json",
                                            max_chars=400, min_chars=0)
    assert statements == []
    assert rejects[0]["reason"].startswith("parse_fault")
    assert stats["statements_seen"] + stats["segments_failed"] == stats["segments"]


def test_the_distill_prompt_forbids_inventing_and_asks_for_short_units():
    prompt = ds.distill_prompt("某段正文")
    assert "不要评论" in prompt and "不许发明" in prompt
    assert "某段正文" in prompt
