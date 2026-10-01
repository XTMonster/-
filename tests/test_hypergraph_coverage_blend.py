"""覆盖率分母：**种子集**与**查询取值**的混合（Q4/Q6b 硬尾巴的收官修正）。

`seeds_for` 是词面匹配，一个查询取值常常命中一二十个节点（`运镜=上下场` 把 8 个
拉成种子），于是 `_edge_coverage` 的分母 `len(seed_set)` 被稀释——"本边"只覆盖到
3/8 就被判成部分匹配，与竞争边只差 0.002–0.01 分。实测 4928 条 `must` 里
**3544 条（71.9%）**属于这种情况。

两个极端都试过：只留精确命中会掉召回；纯按查询取值算会让独立标定工具
（`tools/knowledge/ranking_quality.py`）的 Q1 从 0.70 掉到 0.66。所以取混合，
系数由一次多目标扫参定（`COVERAGE_VALUE_BLEND`，实测 0.1–0.3 是一个平台）。
"""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge import hypergraph as hg  # noqa: E402


def _node(node_id: str) -> hg.Node:
    kind, value = node_id.split(":", 1)
    return hg.Node(node_id=node_id, type=kind, name=value, value=value)


def _edge(members) -> hg.HyperEdge:
    return hg.HyperEdge(
        type="INTENT_PACK", members=tuple(members), source_kind="theory",
        hardness="hard", occurrences=1, confidence=0.7, confidence_max=0.7,
        sources=("card_1",), source_span={"chunk_id": "c1", "start": 0, "end": 4},
        extractor={"prompt_version": "test"}, provenance_kind="生成卡片")


def test_blend_is_a_convex_combination_of_the_two_denominators():
    """混合系数在 [0,1] 内；0 = 旧口径，1 = 纯按查询取值。"""
    assert 0.0 <= hg.COVERAGE_VALUE_BLEND <= 1.0
    assert hg.COVERAGE_VALUE_BLEND > 0.0, (
        "默认值必须已经打开混合——否则 Q4/Q6b 的硬尾巴会原样回来")


def test_a_diluted_seed_set_no_longer_buries_the_edge_that_covers_the_value():
    """查询值命中 3 个节点、边只落在其中 1 个上时：

    * 旧口径（blend 0）覆盖率 = 1/3，被稀释；
    * 新口径（blend 1）覆盖率 = 1/1 = 1.0 —— "这个取值被解释了"。
    """
    # 三个节点都会被 `轴线=运动轴` 的别名匹配到，但边只含其中一个
    nodes = [_node("axis_topic:运动轴"), _node("axis_topic:关系轴"),
             _node("axis_topic:视线轴")]
    edge = _edge([hg.Member("qualifier", "axis_topic", "axis_topic:运动轴")])
    graph = hg.Hypergraph(nodes, [edge])
    query = {"axis_topic": ["运动轴"]}
    per_value = {("axis_topic", "运动轴"): {"axis_topic:运动轴", "axis_topic:关系轴",
                                          "axis_topic:视线轴"}}
    seed_set = set(per_value[("axis_topic", "运动轴")])

    original = hg.COVERAGE_VALUE_BLEND
    try:
        hg.COVERAGE_VALUE_BLEND = 0.0
        legacy = graph._edge_coverage(edge, seed_set, per_value, query)
        hg.COVERAGE_VALUE_BLEND = 1.0
        by_value = graph._edge_coverage(edge, seed_set, per_value, query)
    finally:
        hg.COVERAGE_VALUE_BLEND = original
    assert legacy == pytest.approx(1 / 3)
    assert by_value == pytest.approx(1.0)

    # 混合值必须落在两者之间（这就是"不抛弃召回、也不再被稀释"）。
    mixed = graph._edge_coverage(edge, seed_set, per_value, query)
    assert legacy < mixed < by_value


def test_without_per_value_the_blend_is_a_no_op():
    """反面：没有按取值展开的信息时，覆盖率必须**逐位等于**旧口径。"""
    nodes = [_node("axis_topic:运动轴")]
    edge = _edge([hg.Member("qualifier", "axis_topic", "axis_topic:运动轴")])
    graph = hg.Hypergraph(nodes, [edge])
    assert graph._edge_coverage(edge, {"axis_topic:运动轴"}) == 1.0
    assert graph._edge_coverage(edge, set()) == 0.0
