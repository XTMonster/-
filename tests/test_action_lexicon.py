"""`action` 词表的对抗性用例（审计 #16：标签空间污染）。

缺陷的形状（2026-10-01 实测）：`vocabulary.build_nodes` 第 4 步把
performance／blocking 域卡片里长度 ≤6 的 tag **全部**铺成 `action:` 节点。
tag 是卡片生成模型写的**话题词**，于是 343 个 action 节点里只有 7 个是真动作，
837 条边里 258 条带一个不是动作的 `action` 取值（`动作`×41、`反应`×27、
`克制`×15、`人物塑造`×12…）。抽取提示写了"不能写概念"，但**节点表把话题词
当成了合法取值**，模型自然照抄。

三条不变量在这里钉住：候选集与旧规则同源、入库节点必须来自词表、污染词必须被拒。
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.kb_fetch import action_lexicon as AL  # noqa: E402
from tools.kb_fetch import vocabulary as V  # noqa: E402

LEXICON = ROOT / "knowledge" / "action_lexicon.json"
NODES = ROOT / "knowledge" / "hypergraph.nodes.jsonl"


@pytest.fixture(scope="module")
def cards():
    from block_director.knowledge.corpus import CARDS

    return CARDS


@pytest.fixture(scope="module")
def lexicon():
    if not LEXICON.is_file():
        pytest.skip("action 词表未入库")
    return AL.load(LEXICON)


def test_candidates_match_the_rule_that_used_to_mint_the_pollution(cards):
    """候选集必须与**旧规则**同源，否则"污染清单钉死了"这句话不成立。

    旧规则：`card.domain in (performance, blocking)` ＋ `1 <= len(tag) <= 6`
    ＋ 不与已知节点重名。新词表沿用同一份候选，逐个判过。
    """
    candidates = AL.candidates(cards)
    expected = []
    known = {canon for canon, _ in V.ACTIONS}
    for card in cards:
        if str(card.domain) not in ("performance", "blocking"):
            continue
        for tag in card.tags:
            tag = str(tag).strip()
            if tag and tag not in known and 2 <= len(tag) <= 6 and tag not in expected:
                expected.append(tag)
    assert candidates == expected
    assert len(candidates) > 100, "候选集不该是空的——否则这条测试是空过的"


def test_the_words_the_audit_named_are_rejected(lexicon):
    """审计 #16 逐字点名的污染词必须全部在 rejected 里（正对照：动作要留着）。"""
    for word in ("人物弧光", "人物塑造", "分工", "制作流程", "分镜写法", "动线",
                 "化妆", "协作", "反派表演", "在场处理", "叙事", "台词"):
        assert word in lexicon["rejected"], word
        assert word not in lexicon["accepted"], word
    # 类别词本身也必须拒绝：`动作=动作` 的查询没有任何信息量。
    # 只有真的进了候选集的那些才可能出现在文件里（`行为` 至今不是任何卡片的 tag），
    # 所以这里判"出现在已判定集合里的类别词必须全在 rejected"。
    decided = set(lexicon["accepted"]) | set(lexicon["rejected"])
    for word in AL.VACUOUS_ACTION_WORDS & decided:
        assert word in lexicon["rejected"], word
    assert "动作" in decided and "动作" in lexicon["rejected"]
    # 正对照：真动作必须留着，否则"收紧"就变成了"全砍"。
    assert "出场" in lexicon["accepted"]
    assert "走位" in lexicon["accepted"]


def test_every_shipped_action_node_comes_from_the_lexicon(lexicon, cards):
    """**核心不变量**：节点表里的每一个 `action:` 取值都必须来自受控表或词表。

    这条一断，抽取器就又会拿到话题词当合法取值，258 条污染边会原样回来。
    """
    if not NODES.is_file():
        pytest.skip("索引未入库")
    allowed = set(AL.action_values(lexicon))
    nodes = [json.loads(l) for l in
             NODES.read_text(encoding="utf-8").split("\n") if l.strip()]
    actions = [n for n in nodes if n["type"] == "action"]
    assert actions, "节点表里不该没有动作节点"
    for node in actions:
        value = str(node.get("value") or str(node["node_id"]).split(":", 1)[1])
        assert value in allowed, (value, "不在 action 词表里")


def test_lexicon_carries_its_provenance_and_has_no_overlap(lexicon):
    """词表必须是**可复核**的产物：判据、模型、提示指纹、逐词理由都要有。"""
    provenance = lexicon["_provenance"]
    for field in ("criterion", "model_id", "prompt_sha256"):
        assert str(provenance.get(field) or "").strip(), field
    assert not (set(lexicon["accepted"]) & set(lexicon["rejected"])), "accept/reject 不得重叠"
    for word in list(lexicon["accepted"]) + list(lexicon["rejected"]):
        assert str(lexicon["reason"].get(word) or "").strip(), word
    assert lexicon["controlled"] == [canon for canon, _ in V.ACTIONS]


def test_without_the_lexicon_the_action_domain_falls_back_to_the_controlled_table(
        tmp_path, monkeypatch):
    """反面：词表文件缺席时**只**回落受控表 —— 绝不回落到那条污染规则。

    回落旧规则等于把 258 条 `action=人物弧光` 重新放回索引；"少几条
    `ACTION_BEAT`"是可接受的代价（`docs/knowledge/AUDIT_TRIAGE.md` #16）。
    """
    from tools.kb_fetch import common

    monkeypatch.setattr(common, "KNOWLEDGE", tmp_path)
    values = V._action_values()
    assert values == [canon for canon, _ in V.ACTIONS]


def test_merge_never_re_decides_a_word_that_is_already_pinned(lexicon, cards):
    """增量合并**只判新词**：已入库的结论不许被下一次模型调用翻案。

    实测抖动：同一条判据重跑，第二次把 `肢体语言`／`情绪姿态` 从 rejected 翻成
    accepted。词表是索引的输入，抖动会让语料/索引无法复现。
    """
    class _NeverCalled:
        model_id = "should-not-be-called"

        def chat_json(self, *args, **kwargs):  # pragma: no cover - 被调用即失败
            raise AssertionError("已判定过全部候选时不该再发请求")

    merged = AL.merge(lexicon, cards, _NeverCalled(), AL.candidates(cards))
    assert merged["accepted"] == lexicon["accepted"]
    assert merged["rejected"] == lexicon["rejected"]
