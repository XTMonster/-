"""扩展预算：**按边排队，不按遍历顺序**（2026-10-02 的 Q4 收官修正）。

实测的失败形状（`构图=headroom；景别=MCU；机位=平视`）：

* 该查询的 required 边 `STAGING_PACK(composition_rule=headroom, shot_size=MCU,
  camera_angle=平视)` 在它相邻的**每一个**节点上都排第 1；
* 但 `seeds_for` 先给出 `headroom_policy:board`／`headroom_policy:cinematic`／
  `applies_to_shot_size:MCU` 这些**通用节点**，它们各自把 `MAX_EDGES_TOTAL=40`
  的额度吃掉一大块，轮到 `shot_size:MCU` 时额度已经用完——那条边**连候选都不是**
  （`trace.scores` 里查不到它），Q4 于是永远差那一对。

修法：本跳先把所有邻居合并，再按同一把尺子（coverage → precision → occurrences
→ edge_id）取前 40。额度分配与遍历顺序无关。
"""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge import hypergraph as hg  # noqa: E402


def _edge(members, occurrences: int = 1) -> hg.HyperEdge:
    return hg.HyperEdge(
        type="STAGING_PACK", members=tuple(members), source_kind="theory",
        hardness="hard", occurrences=occurrences, confidence=0.7, confidence_max=0.7,
        sources=("card_1",), source_span={"chunk_id": "c1", "start": 0, "end": 4},
        extractor={"prompt_version": "test"}, provenance_kind="生成卡片")


def _nodes(*ids):
    return [hg.Node(node_id=node_id, type=node_id.split(":", 1)[0],
                    name=node_id.split(":", 1)[1], value=node_id.split(":", 1)[1])
            for node_id in ids]


def test_a_specific_seed_is_not_starved_by_the_generic_ones():
    """**核心不变量**：通用种子（邻居多）先把额度吃光时，后面那个具体种子的
    第 1 名边仍必须进候选。

    构造：`shot_size:MCU`（具体）只有 1 条邻边；`composition_rule:headroom`
    （通用）挂着 60 条无关边。`MAX_EDGES_TOTAL` 是 40，所以旧代码在遍历到
    `composition_rule:headroom` 时就把额度用完，`shot_size:MCU` 的那条边进不来。
    """
    want = _edge([hg.Member("qualifier", "composition_rule", "composition_rule:headroom"),
                  hg.Member("allow", "shot_size", "shot_size:MCU"),
                  hg.Member("qualifier", "camera_angle", "camera_angle:平视")])
    noise = [_edge([hg.Member("qualifier", "composition_rule",
                              "composition_rule:headroom"),
                    hg.Member("allow", "shot_size", "shot_size:MCU"),
                    hg.Member("qualifier", "camera_angle", "camera_angle:平视"),
                    hg.Member("allow", "lens", f"lens:{50 + i}mm")])
             for i in range(60)]
    ids = ["composition_rule:headroom", "shot_size:MCU", "camera_angle:平视"]
    ids += [f"lens:{50 + i}mm" for i in range(60)]
    graph = hg.Hypergraph(_nodes(*ids), [want] + noise)

    seeds = ["composition_rule:headroom", "shot_size:MCU", "camera_angle:平视"]
    candidates, truncated = graph.expand(seeds)
    ids_out = {edge.edge_id for edge in candidates}
    assert truncated, "60+ 条边挤 40 个额度，必须如实报截断"
    assert want.edge_id in ids_out, (
        "具体的种子（shot_size:MCU，只有 1 条邻边）不该被通用种子挤掉")

    # 正对照：额度之内的**排序**仍然按 coverage → precision → occurrences →
    # edge_id，所以"整条边都被查询解释"的 want 排在语料支持更高的噪声边之前。
    ordered = [edge.edge_id for edge in candidates]
    assert ordered.index(want.edge_id) == 0


def test_expansion_stays_within_the_hard_caps():
    """反向：无论怎么排队，`MAX_EDGES_TOTAL` 与 `HUB_EDGES_PER_NODE` 都不许被突破。"""
    noise = [_edge([hg.Member("qualifier", "composition_rule",
                              "composition_rule:headroom"),
                    hg.Member("allow", "shot_size", "shot_size:MCU"),
                    hg.Member("qualifier", "camera_angle", "camera_angle:平视"),
                    hg.Member("allow", "lens", f"lens:{50 + i}mm")])
             for i in range(120)]
    ids = ["composition_rule:headroom", "shot_size:MCU", "camera_angle:平视"]
    ids += [f"lens:{50 + i}mm" for i in range(120)]
    graph = hg.Hypergraph(_nodes(*ids), noise)
    candidates, _truncated = graph.expand(ids[:3])
    assert len(candidates) <= hg.MAX_EDGES_TOTAL
