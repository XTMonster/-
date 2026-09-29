"""检索器 ↔ sidecar 的接线（v1.4 §2.3 / §2.4）。

这一层以前是断的：`_make_knowledge(config)` 既不传 `capabilities` 也不传
`hypergraph`/`client`，于是**即使 sidecar 在跑**，`resolve_backend()` 也永远
把超图降级成 BM25，`edges[]/cases[]` 进不了提示词、`retrieval_calls` 恒为 0。
这里把接线钉住，并覆盖 sidecar 中途不可达时的降级留痕。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from block_director.contracts.config import AppConfig
from block_director.contracts.enums import RagBackend
from block_director.contracts.errors import ErrorCode, TransportError
from block_director.contracts.knowledge import Card, HyperEdge
from block_director.contracts.operations import RetrieveResponse
from block_director.layer5_orchestrator.headless_runner import _make_knowledge

FORBID = [["forbid", "movement", "movement:固定机位"]]


class _Sidecar:
    """最小 sidecar 替身：只实现 `retrieve_response`（客户端的硬要求）。"""

    def __init__(self, *, edges=None, error: Optional[Exception] = None):
        self.edges = edges if edges is not None else [
            HyperEdge(edge_id="hg:wired", type="EMOTION_PACK",
                      members=[["allow", "emotion", "emotion:荒诞"],
                               ["qualifier", "intensity", "intensity:high"],
                               ["forbid", "movement", "movement:固定机位"]],
                      forbid=FORBID)]
        self.error = error
        self.calls = 0

    def retrieve_response(self, query, domain=None, top_k=5, timeout=30.0,
                          cases_top_k=3) -> RetrieveResponse:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return RetrieveResponse(
            cards=[Card(id="c1", domain="d", title="t", content="x")],
            edges=list(self.edges),
            trace={"backend": "hypergraph", "lanes": 2, "query": query,
                   "seeds": ["emotion:荒诞"]})


class _Audit:
    def __init__(self):
        self.events: List[Dict[str, Any]] = []

    def log(self, kind, message, /, level="info", **extra):
        self.events.append({"kind": kind, "message": message, **extra})


def _config() -> AppConfig:
    config = AppConfig()
    config.rag.backend = RagBackend.HYPERGRAPH
    return config


def test_a_live_sidecar_makes_the_hypergraph_backend_reachable():
    transport = _Sidecar()
    retriever = _make_knowledge(_config(), transport)
    assert retriever.backend is RagBackend.HYPERGRAPH
    assert retriever.degraded is False
    block = retriever.block_for_shot("CU", "荒诞的瞬间")
    assert "禁={" in block and "固定机位" in block
    assert retriever.retrieval_calls == 1


def test_the_plan_prefetch_goes_through_the_sidecar_too():
    transport = _Sidecar()
    retriever = _make_knowledge(_config(), transport)
    block = retriever.block_for_plan("情绪=荒诞；运镜=固定")
    assert "禁={" in block
    assert transport.calls == 1
    assert retriever.retrieval_calls == 1


def test_retrieval_calls_are_audited_separately_from_llm_calls():
    audit = _Audit()
    retriever = _make_knowledge(_config(), _Sidecar(), audit)
    retriever.block_for_shot("CU", "荒诞")
    kinds = [event["kind"] for event in audit.events]
    assert kinds == ["retrieval_call"]
    assert audit.events[0]["forbid_members"] == 1
    assert audit.events[0]["retrieval_calls"] == 1
    assert "retrieval_calls" in retriever.trace_payload()
    assert retriever.trace_payload()["retrieval_calls"] == 1


def test_sidecar_failure_mid_run_degrades_loudly_instead_of_crashing():
    error = TransportError(ErrorCode.LLM_001, "上游 500", http_status=500)
    retriever = _make_knowledge(_config(), _Sidecar(error=error))
    block = retriever.block_for_shot("CU", "荒诞")   # 不许抛
    assert retriever.degraded is True
    assert retriever.degraded_reason.startswith("sidecar_unavailable")
    assert any("sidecar" in warning for warning in retriever.warnings)
    assert retriever.retrieval_calls == 0
    # 退回卡片检索：仍然给出非空注入块（不是空转）。
    assert block
    payload = retriever.trace_payload()
    assert payload["degraded"] is True
    assert payload["degraded_reason"].startswith("sidecar_unavailable")


def test_without_a_sidecar_transport_the_old_degrade_path_is_unchanged():
    retriever = _make_knowledge(_config(), object())
    assert retriever.backend is RagBackend.BM25
    assert retriever.degraded is True
    assert retriever.degraded_reason == "hypergraph_unavailable"


def test_digest_backend_is_not_rerouted_to_the_sidecar():
    config = _config()
    config.rag.enabled = False
    transport = _Sidecar()
    retriever = _make_knowledge(config, transport)
    assert retriever.backend is RagBackend.DIGEST
    assert transport.calls == 0
