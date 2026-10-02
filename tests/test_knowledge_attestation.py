"""`tools/knowledge/attestation.py`：入库索引的**证据支持率**。

为什么这条要存在（2026-10-02）：`extractor.member_grounding` 那一栏看着像测量，
其实是**常量**——提示词只要求一条边级 `quote`，成员都是三元组，于是 8087/8087 个槽位
按构造全是 `inferred`。**一个只能取一个值的指标不是测量。** 本模块改成从产物本身算：
拿每条边自己的来源卡正文回查每个槽位取值的 surface。

实测（入库索引 698 条边）：可查槽位 1805 个，**只有 20.7% 能回查到依据**；
**只有 38 条边（5.4%）的每个槽位都有依据**。这与独立复核面板判掉 92% 是同一件事的
两个侧面（`work/zz_p14_attestation.py`、`work/zz_p14_template_edges.py`）。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge.hypergraph import HyperEdge, Member, Node  # noqa: E402
from tools.knowledge import attestation as AT  # noqa: E402


def _nodes():
    return {
        "composition_rule:balance": Node("composition_rule:balance", "composition_rule",
                                         "balance", aliases=("平衡", "重心")),
        "shot_size:MS": Node("shot_size:MS", "shot_size", "MS", aliases=("中景",)),
        #: 词表自己就是桶名：正文里本来不会出现它 ⇒ not-checkable。
        "intensity:mid": Node("intensity:mid", "intensity", "mid"),
    }


def _edge(members, sources=("c1",)):
    return HyperEdge(type="STAGING_PACK", members=tuple(members), sources=tuple(sources),
                     source_kind="theory", hardness="hard").to_dict()


def test_attested_and_unattested_and_not_checkable_are_separated():
    """三个桶各司其职：能回查、回查不到、以及**根本不可查**（桶名）。"""
    edges = [_edge([Member("qualifier", "composition_rule", "composition_rule:balance"),
                    Member("allow", "shot_size", "shot_size:MS"),
                    Member("qualifier", "intensity", "intensity:mid")])]
    cards = {"c1": {"id": "c1", "title": "构图", "content": "构图是否平衡时看画面。"}}
    report = AT.audit(edges, cards, _nodes())
    assert report["slots"] == {"attested": 1, "unattested": 1, "not-checkable": 1}
    assert report["checkable_slots"] == 2
    assert report["attested_share"] == 0.5
    assert report["edges_fully_attested"] == 0


def test_a_card_that_names_every_value_makes_the_edge_fully_attested():
    edges = [_edge([Member("qualifier", "composition_rule", "composition_rule:balance"),
                    Member("allow", "shot_size", "shot_size:MS")])]
    cards = {"c1": {"id": "c1", "title": "中景平衡",
                    "content": "中景里用平衡的构图。"}}
    report = AT.audit(edges, cards, _nodes())
    assert report["edges_fully_attested"] == 1
    assert report["edges_fully_attested_share"] == 1.0
    assert report["attested_share"] == 1.0


def test_the_ledger_is_about_the_edges_own_source_cards_only():
    """别的卡写了这个取值**不算**——判据是"这条边自己的来源卡"。"""
    edges = [_edge([Member("qualifier", "composition_rule", "composition_rule:balance")],
                   sources=("c1",))]
    cards = {"c1": {"id": "c1", "title": "无关", "content": "讲的是别的事。"},
             "c2": {"id": "c2", "title": "平衡", "content": "这里讲平衡。"}}
    report = AT.audit(edges, cards, _nodes())
    assert report["slots"] == {"unattested": 1}
    assert report["attested_share"] == 0.0


def test_the_audit_is_deterministic():
    """同一份输入两次必须一致（诊断也要可重放）。"""
    edges = [_edge([Member("qualifier", "composition_rule", "composition_rule:balance"),
                    Member("allow", "shot_size", "shot_size:MS")])]
    cards = {"c1": {"id": "c1", "title": "中景", "content": "中景。"}}
    first = AT.audit(edges, cards, _nodes())
    second = AT.audit(list(edges), dict(cards), _nodes())
    assert first == second


def test_the_shipped_index_reports_a_non_degenerate_number():
    """入库索引必须**报得出**这个数字，而且它**不是常量**。

    `member_grounding` 的教训：只能取一个值的指标不是测量。所以这里两向都要有——
    有能回查到的、也有回查不到的（都 ≥1%）。
    """
    edges_path = ROOT / "knowledge" / "hypergraph.edges.jsonl"
    if not edges_path.is_file():
        import pytest

        pytest.skip("索引未入库")
    nodes = {row["node_id"]: __import__(
        "block_director.knowledge.hypergraph", fromlist=["Node"]).Node.from_dict(row)
        for row in AT.load_jsonl(ROOT / "knowledge" / "hypergraph.nodes.jsonl")}
    report = AT.audit(AT.load_jsonl(edges_path),
                      AT.load_cards(ROOT / "knowledge" / "cards_generated"), nodes)
    assert report["criterion_version"] == "attest/v1"
    assert report["checkable_slots"] > 100, "可查槽位太少，这条诊断失去意义"
    share = report["attested_share"]
    assert 0.01 <= share <= 0.99, (
        f"证据支持率 {share} 落在退化区——要么判据写反了，要么它是个常量")
    assert report["unattested_examples"], "回查不到的槽位必须给出具名例子"
