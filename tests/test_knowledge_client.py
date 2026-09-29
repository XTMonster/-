"""sidecar 知识客户端（v1.4 §2.3 / §2.3b / §2.4）。

要点：三条通道一次拿回、`retrieval_calls` 与 `llm_calls` **分列**记账、
每次调用留一条审计事件、sidecar 不可达时**留痕降级**而不是静默返回空，
以及 §2.3 的检索预算口径 `(2 + N) × lanes`。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from block_director.contracts.errors import ErrorCode, TransportError
from block_director.contracts.knowledge import Card, Case, HyperEdge
from block_director.contracts.operations import RetrieveResponse
from block_director.knowledge.client import KnowledgeClient, retrieval_call_bound


def _response(lanes: int = 2) -> RetrieveResponse:
    return RetrieveResponse(
        cards=[Card(id="c1", domain="d", title="t", content="x")],
        edges=[HyperEdge(edge_id="hg:1", type="EMOTION_PACK",
                         members=[["allow", "emotion", "emotion:荒诞"],
                                  ["forbid", "movement", "movement:固定机位"]],
                         forbid=[["forbid", "movement", "movement:固定机位"]])],
        cases=[Case(case_id="case_1", case_type="lesson")],
        trace={"backend": "hypergraph", "lanes": lanes, "seeds": ["emotion:荒诞"]},
    )


class _FakeTransport:
    def __init__(self, response=None, error: Optional[Exception] = None):
        self.response = response
        self.error = error
        self.calls: List[Dict[str, Any]] = []

    def retrieve_response(self, query, domain=None, top_k=5, timeout=30.0,
                          cases_top_k=3):
        self.calls.append({"query": query, "domain": domain, "top_k": top_k,
                           "timeout": timeout, "cases_top_k": cases_top_k})
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


def test_client_returns_all_three_lanes_and_counts_the_call():
    transport = _FakeTransport(_response())
    client = KnowledgeClient(transport)
    response = client.retrieve("情绪=荒诞；运镜=固定", top_k=4)
    assert [c.id for c in response.cards] == ["c1"]
    assert response.edges[0].forbid == [["forbid", "movement", "movement:固定机位"]]
    assert response.cases[0].case_id == "case_1"
    assert client.retrieval_calls == 1
    assert transport.calls[0]["cases_top_k"] == 3
    assert transport.calls[0]["top_k"] == 4


def test_client_emits_one_audit_event_per_retrieval():
    events: List[Dict[str, Any]] = []
    client = KnowledgeClient(_FakeTransport(_response()), audit=events.append)
    client.retrieve("q1")
    client.retrieve("q2")
    assert [event["event"] for event in events] == ["retrieval_call"] * 2
    first = events[0]
    assert first["edges"] == 1 and first["cards"] == 1 and first["cases"] == 1
    # 禁忌成员数要被单独记下来：Q7 的取证从这里来。
    assert first["forbid_members"] == 1
    assert first["lanes"] == 2 and first["backend"] == "hypergraph"
    assert [event["retrieval_calls"] for event in events] == [1, 2]


def test_client_reports_degraded_when_the_sidecar_is_unreachable():
    error = TransportError(ErrorCode.LLM_001, "连接被拒绝", http_status=503)
    events: List[Dict[str, Any]] = []
    client = KnowledgeClient(_FakeTransport(error=error), audit=events.append)
    assert client.retrieve_or_none("q") is None
    assert client.retrieval_calls == 0          # 没成功的调用不计入
    assert client.degraded is True
    assert client.degraded_reason == f"sidecar_unavailable:{ErrorCode.LLM_001}"
    assert events[0]["event"] == "retrieval_failed"
    assert events[0]["reason"] == client.degraded_reason


def test_client_refuses_a_transport_without_the_three_lane_method():
    class OnlyCards:                    # 只有旧契约的 retrieve()
        def retrieve(self, query, domain=None, top_k=5):
            return []

    with pytest.raises(TypeError):
        KnowledgeClient(OnlyCards())


def test_trace_payload_carries_the_lanes_and_the_call_count():
    client = KnowledgeClient(_FakeTransport(_response()))
    client.retrieve("q")
    payload = client.trace_payload()
    assert payload["backend"] == "hypergraph"
    assert payload["lanes"] == 2
    assert payload["seeds"] == ["emotion:荒诞"]
    assert payload["retrieval_calls"] == 1
    assert payload["client_degraded"] is False


def test_trace_payload_is_written_even_when_nothing_was_retrieved():
    """§2.3：knowledge_trace.json 每次运行必写——没检索过也要有合法形状。"""
    payload = KnowledgeClient(_FakeTransport(_response())).trace_payload()
    assert payload["backend"] == ""
    assert payload["lanes"] == 1
    assert payload["retrieval_calls"] == 0


@pytest.mark.parametrize("shots,lanes,expected", [
    (0, 1, 2), (3, 1, 5), (3, 2, 10), (61, 2, 126), (61, 1, 63),
])
def test_retrieval_budget_formula(shots, lanes, expected):
    """§2.3 写死的口径：retrieval_calls ≤ (2 + N) × lanes。"""
    assert retrieval_call_bound(shots, lanes) == expected
