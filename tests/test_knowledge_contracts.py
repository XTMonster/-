"""超边 / 案例 DTO 与 ``/v1/retrieve`` 响应形状（v1.4 §2.3、§2.3b）。

这些用例钉死三件事：

1. **往返无损**：``to_dict`` → ``from_dict`` 不丢字段、不改类型；
2. **向后兼容**：``RetrieveResponse`` 只用 ``cards=`` 构造时仍可用，
   且 ``edges`` / ``cases`` 缺省为空列表（旧 sidecar 的载荷照样解析）；
3. **E3 的机制保证**：``Case`` 在类型层**没有** ``forbid`` 字段——
   "经验越权率 = 0" 不是靠调用方自觉。
"""

from __future__ import annotations

from dataclasses import fields

import pytest

from block_director.contracts.knowledge import Card, Case, HyperEdge
from block_director.contracts.operations import RetrieveResponse


def _edge() -> HyperEdge:
    return HyperEdge(
        edge_id="hg:abcdef012345",
        type="EMOTION_PACK",
        members=[
            ["allow", "emotion", "荒诞"],
            ["qualifier", "intensity", "high"],
            ["allow", "movement", "甩镜"],
            ["forbid", "movement", "固定机位"],
        ],
        forbid=[["forbid", "movement", "固定机位"]],
        weight=2.0,
        source_span={"chunk_id": "c9", "start": 3, "end": 88,
                     "provenance_kind": "生成卡片"},
        source_kind="lesson",
        hardness="soft",
        occurrences=4,
        confidence=0.66,
    )


def test_hyperedge_round_trips_without_loss():
    edge = _edge()
    again = HyperEdge.from_dict(edge.to_dict())
    assert again.to_dict() == edge.to_dict()
    assert again.members == [["allow", "emotion", "荒诞"],
                            ["qualifier", "intensity", "high"],
                            ["allow", "movement", "甩镜"],
                            ["forbid", "movement", "固定机位"]]
    assert again.forbid == [["forbid", "movement", "固定机位"]]


def test_hyperedge_derives_forbid_when_absent():
    """宽松解析：载荷没带 ``forbid`` 时从 members 里推出来，不静默丢禁忌。"""
    payload = _edge().to_dict()
    payload.pop("forbid")
    edge = HyperEdge.from_dict(payload)
    assert edge.forbid == [["forbid", "movement", "固定机位"]]


def test_hyperedge_rejects_malformed_member():
    """成员必须是三元组：两元组（丢 kind）不许静默通过。"""
    with pytest.raises(ValueError):
        HyperEdge.from_dict({"edge_id": "hg:x", "type": "TROPE",
                             "members": [["allow", "emotion"]]})


def test_case_has_no_forbid_field():
    """E3 的机制保证：案例 DTO 结构上不可能携带约束。"""
    names = {f.name for f in fields(Case)}
    assert "forbid" not in names
    assert names == {"case_id", "case_type", "title", "excerpt",
                     "beat_sequence", "source_ref", "score"}


def test_case_round_trips_sequence_pattern():
    case = Case(case_id="case_7", case_type="sequence_pattern",
                title="建立→覆盖→反应", excerpt="…",
                beat_sequence=["establish", "coverage", "reaction"],
                source_ref={"url": "u", "license": "OwnWork"}, score=0.5)
    assert Case.from_dict(case.to_dict()).to_dict() == case.to_dict()


def test_retrieve_response_defaults_are_empty():
    """只用 ``cards=`` 构造（既有调用点的写法）必须照旧可用。"""
    resp = RetrieveResponse(cards=[Card(id="c1", domain="d", title="t",
                                        content="x")])
    assert resp.edges == [] and resp.cases == []
    assert resp.trace == {}
    assert set(resp.to_dict()) == {"cards", "edges", "cases", "trace"}


def test_retrieve_response_parses_legacy_payload():
    """旧 sidecar 只回 ``{"cards": [...]}`` 时必须解析成功、两条通道为空。"""
    resp = RetrieveResponse.from_dict(
        {"cards": [Card(id="c1", domain="d", title="t", content="x").to_dict()]})
    assert len(resp.cards) == 1 and resp.edges == [] and resp.cases == []


def test_retrieve_response_round_trips_all_three_lanes():
    resp = RetrieveResponse(
        cards=[Card(id="c1", domain="d", title="t", content="x")],
        edges=[_edge()],
        cases=[Case(case_id="case_1", case_type="lesson")])
    again = RetrieveResponse.from_dict(resp.to_dict())
    assert again.to_dict() == resp.to_dict()
    assert again.edges[0].forbid == [["forbid", "movement", "固定机位"]]
