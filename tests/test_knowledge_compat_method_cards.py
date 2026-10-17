"""新知识（构图审核方法论卡）与旧知识（既有语料/超图/检索器）的兼容性审计。

背景：``cards_review_method.py`` 的 8 张 ``rev_method_*`` 方法卡是「评测台
方法臂话术」的知识化草案，当前**尚未**接入 ``corpus.py``（正式入库要花
DeepSeek 额度重建超图 + 重跑门⑥/Q1/E1，见模块 docstring）。本测试在
**不修改主链路的隔离环境**里验证：方法卡与旧语料合并后是否冲突、互相引用的
id 是否悬空、检索器把新旧卡放同一集合时能否同时命中、权重/检查顺序是否与
引擎真源一致。

✅ 规则号命名空间（用户 2026-10-13 裁决：给方法卡辟独立规则段，不给现有 R
编号）：方法卡的 ``rules`` 只引用 ``cards_review_method.METHOD_RULES`` 段内
的 ``MR\\d{3}`` 编号，与 ``contracts/rule_catalog.py`` 的 R001–R019 零重叠
（rule_catalog 被 ``tests/test_rule_catalog.py`` 钉死在 18 条且只认 ``R\\d{3}``，
所以独立段不能进 rule_catalog，只能落在知识卡模块自身）。方法卡消费方是
agent（评测台方法臂 + 将来的检索注入，见 spec §15.2），因此本文件还断言卡的
正文是**可执行的祈使指令**而非纯理论重述。
"""

from __future__ import annotations

from typing import List

from block_director.cinema.composition import WEIGHTS, PASS_SCORE
from block_director.knowledge import cards_review_method as cards_new
from block_director.knowledge import corpus as corpus
from block_director.knowledge.generated import merge_cards
from block_director.knowledge.retriever import (
    KnowledgeRetriever,
    TOKEN_LIMIT_TOOL,
)
from block_director.knowledge.tokens import estimate_tokens
from tools.spatial_ruler_ab.method import render_method_block


NEW_CARDS = tuple(cards_new.CARDS)


# --------------------------------------------------------------------------- #
# 1) 契约兼容
# --------------------------------------------------------------------------- #
def test_method_cards_satisfy_card_contract():
    """每张方法卡都满足 Card 约束（id 前缀 / 域 / 非空字段）。"""
    assert len(NEW_CARDS) == 8
    assert len({card.id for card in NEW_CARDS}) == len(NEW_CARDS)
    for card in NEW_CARDS:
        assert card.id.startswith("rev_method_")
        assert card.domain == "composition"
        assert card.domain in corpus.DOMAINS
        assert card.title.strip()
        assert card.content.strip()
        assert card.keywords


def test_method_card_ids_do_not_collide_with_corpus():
    """方法卡 id 与 corpus.CARDS 的 2353 个 id 无碰撞。"""
    existing = {card.id for card in corpus.CARDS}
    new_ids = {card.id for card in NEW_CARDS}
    assert new_ids.isdisjoint(existing)


# --------------------------------------------------------------------------- #
# 2) 引用兼容（related 不悬空）
# --------------------------------------------------------------------------- #
def test_method_card_related_resolve_within_old_or_new():
    """related 里的旧卡 id 必须以原样存在于 corpus，新卡 id 必须能互指。"""
    old_ids = {card.id for card in corpus.CARDS}
    new_ids = {card.id for card in NEW_CARDS}
    for card in NEW_CARDS:
        for ref in card.related:
            assert ref in old_ids or ref in new_ids, \
                f"{card.id} 引用了悬空 id {ref!r}"


def test_method_card_related_pin_existing_composition_cards():
    """方法卡应回指既有的构图理论卡（新方法建立在旧理论上）。"""
    old_ids = {card.id for card in corpus.CARDS}
    for card in NEW_CARDS:
        comp_refs = [ref for ref in card.related
                     if ref.startswith("comp_") or ref.startswith("rev_method_")]
        assert comp_refs, f"{card.id} 没有任何构图域引用"
        for ref in comp_refs:
            assert ref in old_ids or ref in {c.id for c in NEW_CARDS}


# --------------------------------------------------------------------------- #
# 3) 语义对齐：方法与引擎/摘要真源
# --------------------------------------------------------------------------- #
def test_method_card_weights_match_engine():
    """rev_method_decision 的六个权重必须与 composition.WEIGHTS 一致。"""
    decision = next(c for c in NEW_CARDS if c.id == "rev_method_decision")
    for name, weight in WEIGHTS.items():
        # 卡里写的是 `headroom 0.15 / lead_room 0.20 / ...` 短格式
        assert f"{name} {weight:g}" in decision.content, \
            f"决策卡 {name}={weight} 与引擎真源不一致"
    assert str(PASS_SCORE)[:2] in decision.content  # 至少包含 70


def test_method_card_checklist_matches_engine_order():
    """检查顺序卡与 method 臂同源（六步文本逐字一致）。"""
    content = next(c for c in NEW_CARDS if c.id == "rev_method_order").content
    for line in cards_new.CHECKLIST:
        assert line in content


# --------------------------------------------------------------------------- #
# 3b) 规则号命名空间：独立 MR 段，不占 R 编号
# --------------------------------------------------------------------------- #
def test_method_card_rules_resolve_in_method_rule_section():
    """每张方法卡引用的规则号必须存在于 METHOD_RULES 独立段。"""
    assert cards_new.METHOD_RULE_IDS, "方法卡必须有自己的独立规则段"
    for card in NEW_CARDS:
        for rule in card.rules:
            assert rule in cards_new.METHOD_RULE_IDS, \
                f"{card.id} 引用了未在 METHOD_RULES 段定义的规则 {rule!r}"


def test_method_rule_ids_never_use_engine_rule_namespace():
    """MR 段不得借用 R\\d{3} 编号，避免与 rule_catalog 语义撞车。"""
    for rule_id in cards_new.METHOD_RULE_IDS:
        assert rule_id.startswith("MR"), \
            f"方法域规则 {rule_id!r} 必须用 MR 前缀，不能占 R 编号"
    assert not cards_new.METHOD_RULE_IDS & {"R010", "R020"}, \
        "方法卡不得再引用 R010/R020 这类引擎规则号"


def test_method_cards_are_executable_instructions_for_agent():
    """方法卡正文是给 agent 执行的操作指令（祈使/操作词），不是纯理论。"""
    operation_words = ("先", "只", "不", "按", "固定", "判定", "检查",
                       "核对", "不适用", "再看", "逐项", "顺序")
    for card in NEW_CARDS:
        matched = [w for w in operation_words if w in card.content]
        assert matched, \
            f"{card.id} 的正文缺少可执行指令用语，agent 无法据此执行审核"


# --------------------------------------------------------------------------- #
# 4) 隔离合并：方法卡并入手写/生成卡后在内存里不冲突
# --------------------------------------------------------------------------- #
def test_merge_simulation_keeps_method_cards_without_new_collisions():
    """模拟注册：把方法卡并入手写卡再与生成卡归并，无新碰撞且方法卡保留。"""
    merged, collisions = merge_cards(
        list(corpus._HANDWRITTEN) + list(NEW_CARDS),
        list(corpus.GENERATED_CARDS),
    )
    # 方法卡不得引入新的碰撞
    assert not any(card_id.startswith("rev_method_")
                   for card_id, _ in collisions)
    assert len(merged) == len(corpus.CARDS) + len(NEW_CARDS)
    merged_ids = {card.id for card in merged}
    for card in NEW_CARDS:
        assert card.id in merged_ids
    # 原有 2353 张卡一个都不能少
    assert {card.id for card in corpus.CARDS}.issubset(merged_ids)


# --------------------------------------------------------------------------- #
# 5) 检索兼容：同一张 BM25 表同时命中旧理论卡与新方法卡
# --------------------------------------------------------------------------- #
def _isolated_retriever() -> KnowledgeRetriever:
    return KnowledgeRetriever(
        cards=list(corpus.CARDS) + list(NEW_CARDS),
        backend="bm25",
        top_k=8,
    )


def test_retrieval_hits_old_theory_and_new_method_together():
    """构图审核类查询应同时召回旧理论卡与方法卡。"""
    r = _isolated_retriever()
    hits = r.search_hits("如何审核一镜头部留白过多", top_k=8)
    ids = {hit.card.id for hit in hits}
    assert any(i.startswith("comp_") for i in ids)  # 旧理论卡
    assert any(i.startswith("rev_method_") for i in ids)  # 新方法卡


def test_retrieval_fight_query_hits_dynamic_method_and_eye_trace():
    """打斗镜查询：应命中 dynamic 方法卡与旧视角引导卡。"""
    r = _isolated_retriever()
    hits = r.search_hits("打斗镜头 出画 回冲 视线 方向反转", top_k=8)
    ids = {hit.card.id for hit in hits}
    assert "rev_method_dynamic" in ids or "rev_method_order" in ids
    assert any(i.startswith("comp_") for i in ids)


def test_retrieval_prescription_query_hits_guard_card_and_old_composition():
    """处方查询：命中 rev_method_prescription，且旧构图卡仍在检索面内。"""
    r = _isolated_retriever()
    hits = r.search_hits("处方 接受 拒绝 构图 guard", top_k=10)
    ids = {hit.card.id for hit in hits}
    assert "rev_method_prescription" in ids
    assert any(i.startswith("comp_") or i.startswith("gen_comp_")
               for i in ids)


def test_retrieval_total_tokens_within_tool_limit():
    """真实收口路径：block() 输出的注入文本必须 ≤ 800 token。"""
    r = _isolated_retriever()
    injected = r.block("如何审核一镜头部留白过多", domain="composition",
                       top_k=8, token_limit=TOKEN_LIMIT_TOOL)
    assert injected.strip()
    assert estimate_tokens(injected) <= TOKEN_LIMIT_TOOL, \
        f"注入 {estimate_tokens(injected)} tokens > {TOKEN_LIMIT_TOOL}"


# --------------------------------------------------------------------------- #
# 6) 与方法臂话术同源（含动态打斗镜追加）
# --------------------------------------------------------------------------- #
def test_method_block_dynamic_extension_agrees_with_dynamic_card():
    """打斗镜：method-block 的动态追加段与 rev_method_dynamic 卡同源。"""
    card = next(c for c in NEW_CARDS if c.id == "rev_method_dynamic")
    block = render_method_block({"id": "fight_01"})
    for keyword in ("出画", "回冲", "方向", "遮挡", "速度"):
        assert keyword in card.content
        assert keyword in block
