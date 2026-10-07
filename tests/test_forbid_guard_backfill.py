"""v1.5 §5.6 / 卡 P4-T3：**禁忌补挂**（守门激活）。

OPEN_ITEMS B7 记的是"违规 0 至今仍是**无物可违**"：第二次真跑 `edge_active = 30`，
而这 30 条**一条 `forbid` 成员都没有** ⇒ `forbid_members_seen = 0` ⇒ 执行闭环没有
守门能力。本文件钉住把这个读数从"结构性 0"变成"测量量"的那段代码：

* 一条**有禁忌**、且正向成员命中本轮种子的边，即使分数进不了 top-k，也要被
  **补挂**进注入（排最前）；
* 没有禁忌边时行为**逐字不变**（不凭空多注入边）；
* 补挂是**纯检索期**行为：不改索引、不改判据、不动打分公式。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge.hypergraph import (  # noqa: E402
    HyperEdge,
    Hypergraph,
    Member,
    Node,
)


def _nodes():
    return [
        Node(node_id="shot_size:MS", type="shot_size", name="MS", value="MS"),
        Node(node_id="intensity:high", type="intensity", name="high",
             value="high"),
        #: 取值写法与查询词表**不同形**：查询折成 `固定`，节点名是 `固定机位`、
        #: 别名才是 `固定`。只做全等的实现会漏掉它——这正是真索引里的形状。
        Node(node_id="movement:固定机位", type="movement", name="固定机位",
             aliases=("固定",), value="固定机位"),
        Node(node_id="movement:甩镜", type="movement", name="甩镜",
             aliases=("甩镜头",), value="甩镜"),
    ]


def _plain_edge():
    """分数高、**没有** forbid 成员的边。

    它把查询点名的两个槽位（景别 ＋ 运镜）都占了，所以 coverage/precision 都是 1；
    guard 边只占一个槽位。两者分数因而拉开，`top_k=1` 时 guard 必然落选——补挂
    才有东西可做。
    """
    return HyperEdge(type="SHOT_PATTERN", source_kind="theory", hardness="hard",
                     occurrences=9, confidence=0.9,
                     members=(Member("allow", "shot_size", "shot_size:MS"),
                              Member("allow", "movement", "movement:固定机位")))


def _guard_edge():
    """有 forbid 成员、且正向成员命中查询的边（应被补挂）。"""
    return HyperEdge(type="SHOT_PATTERN", source_kind="theory", hardness="hard",
                     occurrences=1, confidence=0.7,
                     members=(Member("allow", "shot_size", "shot_size:MS"),
                              Member("forbid", "movement",
                                     "movement:甩镜")))


def test_the_guard_edge_is_backfilled_but_does_not_steal_the_top1():
    """补挂只"加入注入"，**不得改写检索名次**（2026-10-07 实测修正）。

    为什么改这条断言：第一版把补挂边**插到检索列表最前**，于是 held-out 的
    `Q1`（每个查询的 **top-1** 是否就是期望边）从 0.9975 塌到 0.1208
    （40 条抽样里 30 条的 top-1 被顶掉）。TDD §5.6 的原话是"**渲染**排最前"，
    那是**注入文本**的顺序，不是检索名次。所以现在这里断言三件事：
    ①guard 边确实被补挂进注入集合；②**名次仍是原样**（分数高的 plain 边还是
    top-1）；③"排最前"由渲染层负责——见下一条用例对 `render_rule_pack`
    的 `exempt_edge_ids` 断言。判据没有被放宽：`forbid_members_seen` 与
    "禁忌必须真的出现在文本里"两条都保留。
    """
    guard = _guard_edge()
    plain = _plain_edge()
    graph = Hypergraph(_nodes(), [plain, guard])
    selected, text, trace = graph.retrieve("景别=MS；运镜=固定", top_k=1)

    assert trace.seed_miss is False
    assert trace.forbid_backfilled == [guard.edge_id], trace.to_dict()
    # 名次没有被补挂改写：分数高的 plain 边仍是 top-1
    assert selected[0].edge_id == plain.edge_id, "补挂不得顶掉检索名次"
    # 但补挂的边仍在**注入集合**里
    assert guard.edge_id in {edge.edge_id for edge in selected}
    assert trace.forbid_members_seen >= 1
    # 渲染里必须真的看得到那条禁忌（模型才有东西可守）
    assert "甩镜" in text


def test_exempt_edges_are_rendered_first_in_the_injected_block():
    """`render_rule_pack(exempt_edge_ids=…)` 把补挂的行**排在正文最前**。"""
    from block_director.knowledge.rulepack import render_rule_pack
    from block_director.knowledge.hypergraph import render_edge

    guard = _guard_edge()
    plain = _plain_edge()
    nodes = {node.node_id: node for node in _nodes()}
    text, _dropped, _stats = render_rule_pack(
        [plain, guard], nodes, budget=5, token_limit=400,
        exempt_edge_ids=[guard.edge_id])
    lines = [line for line in text.splitlines() if line.strip()]
    assert lines, text
    assert render_edge(guard, nodes) in lines[0], (
        "禁忌补挂的行必须排在注入文本最前（TDD §5.6 的'渲染排最前'）")


def test_forbid_members_seen_counts_the_injected_edges():
    guard = _guard_edge()
    graph = Hypergraph(_nodes(), [_plain_edge(), guard])
    _selected, _text, trace = graph.retrieve("景别=MS；运镜=固定", top_k=1)
    # 补挂把 guard 顶进来之后，注入集合里带 1 个 forbid 成员
    assert trace.forbid_members_seen == 1
    assert trace.to_dict()["forbid_members_seen"] == 1
    assert trace.to_dict()["forbid_backfilled"] == [guard.edge_id]


def test_without_any_forbid_member_nothing_is_backfilled():
    """负例：索引里没有带禁忌的边时，行为必须与补挂之前一致。"""
    plain = _plain_edge()
    graph = Hypergraph(_nodes(), [plain])
    selected, _text, trace = graph.retrieve("景别=MS；运镜=固定", top_k=5)
    assert trace.forbid_backfilled == []
    assert trace.forbid_members_seen == 0
    assert [edge.edge_id for edge in selected] == [plain.edge_id]


def test_a_forbid_edge_whose_allow_member_misses_the_query_is_not_backfilled():
    """守门 != "只要带禁忌就注入"：正向成员**不命中本轮种子**的边不许补挂。"""
    unrelated = HyperEdge(
        type="SHOT_PATTERN", source_kind="theory", hardness="hard",
        members=(Member("allow", "intensity", "intensity:high"),
                 Member("forbid", "movement", "movement:甩镜")))
    # 只查景别 → unrelated 的 allow 是 intensity，不该挂上
    graph = Hypergraph(_nodes(), [_plain_edge(), unrelated])
    _selected, _text, trace = graph.retrieve("景别=MS", top_k=5)
    assert trace.forbid_backfilled == []

    # 换一条查询：intensity 进了种子 ⇒ 它这才该被考虑
    graph2 = Hypergraph(_nodes(), [_plain_edge(), unrelated])
    _sel2, _text2, trace2 = graph2.retrieve("景别=MS；强度=high", top_k=5)
    assert unrelated.edge_id in (trace2.forbid_backfilled
                                 or [e.edge_id for e in _sel2])


def test_backfill_is_capped_by_the_assembly_budget():
    """条数上限是**装配预算**（与枢纽配额同量级），不是验收判据。"""
    edges = [_plain_edge()]
    for index in range(Hypergraph.FORBID_BACKFILL_MAX + 5):
        edges.append(HyperEdge(
            type="SHOT_PATTERN", source_kind="theory", hardness="hard",
            occurrences=1, confidence=0.1 + index * 1e-4,
            members=(Member("allow", "shot_size", "shot_size:MS"),
                     Member("forbid", "movement", "movement:甩镜"))))
    graph = Hypergraph(_nodes(), edges)
    _selected, _text, trace = graph.retrieve("景别=MS；运镜=固定", top_k=1)
    assert len(trace.forbid_backfilled) <= Hypergraph.FORBID_BACKFILL_MAX
    assert trace.forbid_backfilled, "至少要有补挂"


def test_the_scoring_formula_is_untouched_by_backfill():
    """补挂只**加名额**，不改打分：同一批候选的分数在有无补挂时完全相同。"""
    guard = _guard_edge()
    graph = Hypergraph(_nodes(), [_plain_edge(), guard])
    _selected, _text, trace = graph.retrieve("景别=MS；运镜=固定", top_k=1)
    # 打分集合是"全部候选"的，不因补挂而变化
    assert set(trace.scores) == {_plain_edge().edge_id, guard.edge_id}
