"""规则包（执行文档 v1.5 §5.1/§5.2/§5.3；卡 P4-T1 + P4-T2）。

PRD P-3 的三条缺陷在这里各自有一条负例钉住：注入**无强度标注**、
**无规则预算**、**冲突不并陈**。三条都不是"跑通即可"——每一条都要求
"改回去就红"的形状。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge.hypergraph import (  # noqa: E402
    HyperEdge,
    Member,
    Node,
)
from block_director.knowledge.rulepack import (  # noqa: E402
    CONFLICT_TAIL,
    FREEDOM_TITLE,
    HARD_PREFIX,
    SOFT_PREFIX,
    edges_conflict,
    freedom_block,
    render_rule_pack,
    rule_line,
    strength_prefix,
)


def _nodes():
    return {
        "shot_size:MS": Node("shot_size:MS", "shot_size", "MS", value="MS"),
        "composition_rule:occlusion": Node(
            "composition_rule:occlusion", "composition_rule", "occlusion",
            value="occlusion"),
        "composition_rule:balance": Node(
            "composition_rule:balance", "composition_rule", "balance",
            value="balance"),
        "movement:固定机位": Node("movement:固定机位", "movement", "固定机位",
                                  aliases=("固定",), value="固定机位"),
        "intensity:high": Node("intensity:high", "intensity", "high",
                               value="high"),
        "intensity:low": Node("intensity:low", "intensity", "low",
                              value="low"),
    }


def _edge(composition="occlusion", *, hardness="hard", occurrences=1,
          confidence=0.8, forbid=None, edge_type="STAGING_PACK"):
    members = [Member("qualifier", "composition_rule",
                      f"composition_rule:{composition}"),
               Member("allow", "shot_size", "shot_size:MS")]
    if forbid:
        members.append(Member("forbid", "movement", f"movement:{forbid}"))
    return HyperEdge(type=edge_type, members=tuple(members),
                     source_kind="theory", hardness=hardness,
                     occurrences=occurrences, confidence=confidence)


# --------------------------------------------------------------------------- #
# §5.1 强度渲染
# --------------------------------------------------------------------------- #
def test_hard_and_soft_edges_get_different_strength_markers():
    """FR-5：`hardness` 必须真的渲染进 prompt——否则模型不知道让步空间。"""
    hard = _edge(hardness="hard")
    soft = _edge(hardness="soft")
    assert strength_prefix(hard) == HARD_PREFIX
    assert strength_prefix(soft) == SOFT_PREFIX
    assert rule_line(hard, _nodes()).startswith(HARD_PREFIX)
    assert rule_line(soft, _nodes()).startswith(SOFT_PREFIX)
    # 正文仍是 hypergraph 那一份（单一真源）：闭合输出的 `禁={…}` 不丢
    line = rule_line(_edge(forbid="固定机位"), _nodes())
    assert "禁={" in line and "固定机位" in line


def test_the_pack_carries_the_marker_into_the_text():
    text, _dropped, stats = render_rule_pack([_edge(hardness="hard")], _nodes())
    assert text.startswith(HARD_PREFIX)
    assert stats.hard == 1 and stats.soft == 0
    text2, _d2, stats2 = render_rule_pack([_edge(hardness="soft")], _nodes())
    assert text2.startswith(SOFT_PREFIX)
    assert stats2.soft == 1 and stats2.hard == 0


# --------------------------------------------------------------------------- #
# §5.2 条数预算
# --------------------------------------------------------------------------- #
def test_the_count_budget_truncates_within_a_bucket_by_confidence_times_occurrences():
    edges = [_edge(occurrences=i + 1, confidence=0.5) for i in range(6)]
    text, dropped, stats = render_rule_pack(edges, _nodes(), budget=3)
    assert stats.injected == 3
    assert len(dropped) == 3
    assert stats.count_dropped == dropped
    assert len(text.splitlines()) == 3
    # 留下来的必须是 occurrences 高的那三条（4/5/6 ⇒ occurrence 越大分越高）
    top = {edge.edge_id for edge in
           sorted(edges, key=lambda e: (-(e.confidence * e.occurrences), e.edge_id))[:3]}
    kept_lines = set(text.splitlines())
    assert all(rule_line(edge, _nodes()) in kept_lines
               for edge in edges if edge.edge_id in top)


def test_different_buckets_do_not_share_the_budget():
    """桶是 `(类型, 主键值)`：不同话题各拿一份预算，不是全场共用一个。"""
    a = _edge(composition="occlusion", edge_type="STAGING_PACK")
    b = _edge(composition="balance", edge_type="SHOT_PATTERN")
    text, dropped, stats = render_rule_pack([a, b], _nodes(), budget=1)
    assert dropped == [] and stats.injected == 2


def test_exempt_edges_are_not_truncated_by_the_count_budget():
    """FR-9：禁忌补挂进来的边不受**条数**预算截断（token 上限仍然生效）。"""
    edges = [_edge(occurrences=i + 1, confidence=0.5) for i in range(4)]
    weakest = sorted(edges, key=lambda e: (e.confidence * e.occurrences,
                                           e.edge_id))[0]
    text, dropped, stats = render_rule_pack(
        edges, _nodes(), budget=1, exempt_edge_ids=[weakest.edge_id])
    assert weakest.edge_id not in dropped
    assert rule_line(weakest, _nodes()) in text.splitlines()


# --------------------------------------------------------------------------- #
# 原子注入
# --------------------------------------------------------------------------- #
def test_atomic_injection_never_truncates_a_line():
    text, dropped, stats = render_rule_pack([_edge()], _nodes(), token_limit=1)
    assert text == ""
    assert len(dropped) == 1
    assert stats.quality_fail is True
    assert stats.token_dropped == dropped


def test_empty_edge_set_yields_nothing():
    text, dropped, stats = render_rule_pack([], _nodes())
    assert text == "" and dropped == []
    assert stats.injected == 0 and stats.conflict_pairs == 0


# --------------------------------------------------------------------------- #
# §5.2 冲突并陈
# --------------------------------------------------------------------------- #
def test_conflicting_edges_are_both_kept_and_surfaced():
    """FR-7：同桶里结论互斥的两条**都保留**，并明写"由你裁决"。"""
    a = _edge(composition="occlusion")
    b = _edge(composition="balance")
    assert edges_conflict(a, b, _nodes()) is True
    text, dropped, stats = render_rule_pack([a, b], _nodes(), budget=1)
    assert stats.conflict_pairs == 1
    assert dropped == [], "冲突对不受条数预算截断"
    assert "[冲突]" in text and CONFLICT_TAIL in text
    assert "occlusion" in text and "balance" in text


def test_allow_and_forbid_of_the_same_value_conflict():
    a = _edge(composition="occlusion", forbid="固定机位")
    b = HyperEdge(type="STAGING_PACK",
                  members=(Member("qualifier", "composition_rule",
                                  "composition_rule:occlusion"),
                           Member("allow", "movement", "movement:固定机位")),
                  source_kind="theory", hardness="hard")
    assert edges_conflict(a, b, _nodes()) is True


def test_non_conflicting_edges_are_not_labelled():
    a = _edge(composition="occlusion")
    b = _edge(composition="occlusion", occurrences=2)
    assert edges_conflict(a, b, _nodes()) is False
    text, _dropped, stats = render_rule_pack([a, b], _nodes())
    assert "[冲突]" not in text and stats.conflict_pairs == 0


def test_conflicts_are_only_searched_inside_a_bucket():
    """跨桶不算冲突：不同话题的规则各说各话，不该被当成竞争。"""
    a = _edge(composition="occlusion", edge_type="STAGING_PACK")
    b = _edge(composition="balance", edge_type="SHOT_PATTERN")
    assert edges_conflict(a, b, _nodes()) is True      # 语义上仍互斥
    _text, _dropped, stats = render_rule_pack([a, b], _nodes())
    assert stats.conflict_pairs == 0, "跨桶不该报冲突"


# --------------------------------------------------------------------------- #
# §5.3 自由度声明
# --------------------------------------------------------------------------- #
def test_freedom_block_lists_both_sides():
    text = freedom_block(["composition_rule", "shot_size"], ["movement"])
    assert text.startswith(FREEDOM_TITLE)
    assert "composition_rule" in text and "shot_size" in text
    assert "movement" in text
    assert freedom_block([], []) == ""


def test_freedom_block_sorts_and_dedupes():
    text = freedom_block(["b", "a", "a"], [])
    assert "a、b" in text


# --------------------------------------------------------------------------- #
# 确定性
# --------------------------------------------------------------------------- #
def test_the_pack_is_deterministic():
    edges = [_edge(occurrences=i) for i in range(5)]
    first = render_rule_pack(edges, _nodes(), budget=2)
    second = render_rule_pack(edges, _nodes(), budget=2)
    assert first[0] == second[0]
    assert first[1] == second[1]
    assert first[2].to_dict() == second[2].to_dict()
