"""Canonical RAG retrieval and prompt-injection provenance."""

from __future__ import annotations

import hashlib

from block_director.contracts.knowledge import (
    Card,
    Case,
    HyperEdge as HyperEdgeDTO,
)
from block_director.contracts.enums import RagBackend
from block_director.contracts.errors import ErrorCode, TransportError
from block_director.contracts.messages import ChatReply, FunctionCall, ToolCall
from block_director.contracts.operations import RetrieveResponse
from block_director.contracts.plan import Plan
from block_director.knowledge.cases import CaseIndex
from block_director.knowledge.client import KnowledgeClient
from block_director.knowledge.hypergraph import HyperEdge, Hypergraph, Node
from block_director.knowledge.retriever import KnowledgeRetriever
from block_director.knowledge.tokens import estimate_tokens
from block_director.knowledge.tool import register_knowledge_tools
from block_director.layer5_orchestrator.driver import PrevisDriver
from block_director.layer5_orchestrator.editor import build_editor_payload
from block_director.layer5_orchestrator.planner import build_plan_payload
from block_director.layer5_orchestrator.tool_registry import ToolRegistry
from block_director.layer6_audit.audit_logger import AuditLogger


def _retriever(*, audit=None) -> KnowledgeRetriever:
    return KnowledgeRetriever(
        cards=[
            Card(id="axis_card", domain="axis_theory", title="轴线",
                 content="越过轴线会改变观众对空间方向的判断。"),
            Card(id="composition_card", domain="composition", title="构图",
                 content="三分法用于安排画面重心。"),
            Card(id="lighting_card", domain="lighting", title="照明",
                 content="侧光可以分离主体与背景。"),
        ],
        backend="bm25",
        top_k=1,
        audit=audit,
    )


class _PromptCapturingRetriever(KnowledgeRetriever):
    """Keep the exact retriever return value for prompt-content assertions."""

    def block_for_plan(self, *args, **kwargs):
        self.plan_prompt_block = super().block_for_plan(*args, **kwargs)
        return self.plan_prompt_block

    def block_for_shot(self, *args, **kwargs):
        self.shot_prompt_block = super().block_for_shot(*args, **kwargs)
        return self.shot_prompt_block


def test_plan_and_editor_prompts_reverse_resolve_to_canonical_events():
    audit_events = []
    retriever = _PromptCapturingRetriever(
        cards=[
            Card(
                id="axis_card",
                domain="axis_theory",
                title="轴线",
                content="越过轴线会改变观众对空间方向的判断。",
            ),
            Card(
                id="composition_card",
                domain="composition",
                title="构图",
                content="三分法用于安排画面重心。",
            ),
            Card(
                id="lighting_card",
                domain="lighting",
                title="照明",
                content="侧光可以分离主体与背景。",
            ),
        ],
        backend="bm25",
        top_k=1,
        audit=audit_events.append,
    )
    plan_payload = build_plan_payload(
        "INT. 房间 - 日\n两人围绕轴线与构图争执。",
        retriever=retriever,
    )
    plan_prompt = plan_payload.messages[0].content
    plan_event = retriever.trace_payload()["retrieval_events"][-1]

    assert retriever.plan_prompt_block
    assert retriever.plan_prompt_block in plan_prompt
    assert plan_event["stage"] == "plan"
    assert plan_event["injected_sha256"] == hashlib.sha256(
        retriever.plan_prompt_block.encode("utf-8")).hexdigest()

    plan = Plan.from_dict({
        "scene_heading": "INT. 房间 - 日",
        "shots": [{
            "shot_id": "shot_001",
            "order": 1,
            "intent": "角色越过轴线后重新构图",
            "shot_type": "CU",
            "duration_frames": 48,
            "characters": ["甲"],
        }],
    })
    editor_payload = build_editor_payload(
        plan.shots[0],
        plan,
        retriever=retriever,
    )
    editor_prompt = editor_payload.messages[0].content
    editor_event = retriever.trace_payload()["retrieval_events"][-1]

    assert retriever.shot_prompt_block
    assert retriever.shot_prompt_block in editor_prompt
    assert editor_event["stage"] == "editor"
    assert editor_event["scope"] == "shot"
    assert editor_event["shot_id"] == "shot_001"
    assert editor_event["injected_sha256"] == hashlib.sha256(
        retriever.shot_prompt_block.encode("utf-8")).hexdigest()

    trace_events = retriever.trace_payload()["retrieval_events"]
    assert [event["retrieval_event_id"] for event in audit_events] == [
        event["retrieval_event_id"] for event in trace_events
    ]
    assert sum(
        int(event["actual_injected_tokens"]) for event in audit_events
    ) == sum(
        int(event["actual_injected_tokens"]) for event in trace_events
    )


def test_bm25_plan_injection_emits_one_canonical_event_shared_by_trace_and_audit():
    audit_events = []
    retriever = _retriever(audit=audit_events.append)

    block = retriever.block_for_plan("轴线", limit=200, stage="plan")

    event = retriever.trace_payload()["retrieval_events"][-1]
    assert event["stage"] == "plan"
    assert event["scope"] == "plan"
    assert event["shot_id"] == ""
    assert event["query"] == "轴线"
    assert event["actual_backend"] == "bm25"
    assert event["network_call"] is False
    assert event["hit_card_ids"] == ["axis_card"]
    assert event["injected_card_ids"] == ["axis_card"]
    assert event["injected"] is True
    assert event["actual_injected_tokens"] == estimate_tokens(block)
    assert event["injected_sha256"] == hashlib.sha256(
        block.encode("utf-8")).hexdigest()

    assert len(audit_events) == 1
    audit_event = audit_events[0]
    assert audit_event["event"] == "retrieval_call"
    assert audit_event["retrieval_event_id"] == event["retrieval_event_id"]
    assert audit_event["injected_card_ids"] == event["injected_card_ids"]
    assert audit_event["actual_injected_tokens"] == estimate_tokens(block)


def test_bm25_editor_injection_keeps_stage_scope_shot_and_prompt_digest():
    audit_events = []
    retriever = _retriever(audit=audit_events.append)

    block = retriever.block_for_shot(
        "CU", "角色越过轴线后回头", limit=200, shot_id="shot_002",
        analogy="她试图掩饰迟到的慌乱", stage="editor")

    event = retriever.trace_payload()["retrieval_events"][-1]
    assert event["stage"] == "editor"
    assert event["scope"] == "shot"
    assert event["shot_id"] == "shot_002"
    assert event["query"] == "CU 角色越过轴线后回头"
    assert event["analogy_query"] == "她试图掩饰迟到的慌乱"
    assert event["injected_card_ids"] == ["axis_card"]
    assert event["injected_sha256"] == hashlib.sha256(
        block.encode("utf-8")).hexdigest()
    assert len(audit_events) == 1
    assert audit_events[0]["retrieval_event_id"] == event["retrieval_event_id"]


def test_hypergraph_prompt_injection_is_one_event_with_only_final_prompt_ids():
    nodes = [
        Node("emotion:荒诞", "emotion", "荒诞", ("absurd",)),
        Node("movement:static", "movement", "固定机位", ("固定", "static")),
    ]
    edge = HyperEdge.from_dict({
        "type": "EMOTION_PACK",
        "members": [
            ["allow", "emotion", "emotion:荒诞"],
            ["allow", "movement", "movement:static"],
        ],
        "source_kind": "theory",
        "hardness": "hard",
    })
    audit_events = []
    retriever = KnowledgeRetriever(
        cards=[
            Card(id="axis_card", domain="axis_theory", title="轴线",
                 content="越过轴线会改变观众对空间方向的判断。"),
        ],
        backend=RagBackend.HYPERGRAPH,
        capabilities=("hypergraph",),
        hypergraph=Hypergraph(nodes, [edge]),
        top_k=5,
        audit=audit_events.append,
    )

    block = retriever.block_for_shot(
        "情绪=荒诞；运镜=固定", limit=800, shot_id="shot_004",
        analogy="荒诞的停顿后突然转身", stage="coarse")

    events = retriever.trace_payload()["retrieval_events"]
    assert len(events) == 1
    event = events[0]
    assert event["stage"] == "coarse"
    assert event["scope"] == "shot"
    assert event["shot_id"] == "shot_004"
    assert event["actual_backend"] == "hypergraph"
    assert event["injected_edge_ids"] == [edge.edge_id]
    assert "[EMOTION_PACK]" in block
    assert event["injected_sha256"] == hashlib.sha256(
        block.encode("utf-8")).hexdigest()
    assert len(audit_events) == 1
    assert audit_events[0]["retrieval_event_id"] == event["retrieval_event_id"]


def test_empty_bm25_result_still_records_the_retrieval_decision():
    retriever = KnowledgeRetriever(cards=[], backend="bm25", top_k=3)

    block = retriever.block_for_shot(
        "CU", "没有知识命中", stage="detail", shot_id="shot_009")

    assert block == ""
    event = retriever.trace_payload()["retrieval_events"][-1]
    assert event["stage"] == "detail"
    assert event["scope"] == "shot"
    assert event["shot_id"] == "shot_009"
    assert event["hit_ids"] == []
    assert event["drops"] == []
    assert event["injected"] is False
    assert event["actual_injected_tokens"] == 0
    assert event["injected_sha256"] == ""


def test_card_tool_search_reports_bm25_when_hypergraph_is_configured():
    retriever = KnowledgeRetriever(
        cards=[
            Card(id="axis_card", domain="axis_theory", title="轴线",
                 content="越过轴线会改变观众的空间方向感。"),
            Card(id="lighting_card", domain="lighting", title="照明",
                 content="侧光可以分离主体与背景。"),
            Card(id="sound_card", domain="sound", title="环境声",
                 content="环境声维持空间连续性。"),
        ],
        backend=RagBackend.HYPERGRAPH,
        capabilities=("hypergraph",),
        hypergraph=Hypergraph([], []),
        top_k=1,
    )

    block = retriever.block(
        "轴线", stage="react", scope="shot", shot_id="shot_020")

    event = retriever.trace_payload()["retrieval_events"][-1]
    assert "[axis_card]" in block
    assert event["capability"] == "cards"
    assert event["requested_backend"] == "hypergraph"
    assert event["actual_backend"] == "bm25"
    assert event["network_call"] is False


def test_all_dropped_hypergraph_content_is_recorded_as_a_zero_injection():
    nodes = [
        Node("emotion:荒诞", "emotion", "荒诞", ("absurd",)),
        Node("movement:static", "movement", "固定机位", ("固定", "static")),
    ]
    edge = HyperEdge.from_dict({
        "type": "EMOTION_PACK",
        "members": [
            ["allow", "emotion", "emotion:荒诞"],
            ["allow", "movement", "movement:static"],
        ],
        "source_kind": "theory",
        "hardness": "hard",
    })
    retriever = KnowledgeRetriever(
        cards=[],
        backend=RagBackend.HYPERGRAPH,
        capabilities=("hypergraph",),
        hypergraph=Hypergraph(nodes, [edge]),
        token_limit=1,
    )

    block = retriever.block_for_shot(
        "情绪=荒诞；运镜=固定", limit=1, shot_id="shot_006",
        stage="coarse")

    assert block == ""
    event = retriever.trace_payload()["retrieval_events"][-1]
    assert event["hit_edge_ids"] == [edge.edge_id]
    assert event["injected_edge_ids"] == []
    assert event["injected"] is False
    assert event["drops"] == [{
        "id": edge.edge_id,
        "kind": "edge",
        "reason": "token_budget",
    }]


def test_partial_hypergraph_injection_never_claims_dropped_edges_as_provenance():
    nodes = [
        Node("emotion:荒诞", "emotion", "荒诞", ("absurd",)),
        Node("lighting:key", "lighting", "key", ("key",)),
    ]
    kept = HyperEdge.from_dict({
        "type": "EMOTION_PACK",
        "members": [["allow", "emotion", "emotion:荒诞"]],
        "source_kind": "theory",
        "hardness": "hard",
    })
    long_members = [["allow", "lighting", "lighting:key"]]
    for index in range(12):
        node_id = f"prop:p{index}"
        nodes.append(Node(node_id, "prop", f"p{index}"))
        long_members.append(["allow", "prop", node_id])
    dropped = HyperEdge.from_dict({
        "type": "LIGHTING_PACK",
        "members": long_members,
        "source_kind": "theory",
        "hardness": "hard",
    })
    retriever = KnowledgeRetriever(
        cards=[],
        backend=RagBackend.HYPERGRAPH,
        capabilities=("hypergraph",),
        hypergraph=Hypergraph(nodes, [kept, dropped]),
        token_limit=30,
    )

    block = retriever.block_for_shot(
        "情绪=荒诞；光线=key", limit=30, shot_id="shot_003", stage="detail")

    event = retriever.trace_payload()["retrieval_events"][-1]
    assert set(event["hit_edge_ids"]) == {kept.edge_id, dropped.edge_id}
    assert event["injected_edge_ids"] == [kept.edge_id]
    assert event["drops"] == [{
        "id": dropped.edge_id,
        "kind": "edge",
        "reason": "token_budget",
    }]
    assert event["injected"] is True
    assert event["injected_sha256"] == hashlib.sha256(
        block.encode("utf-8")).hexdigest()


def test_digest_plan_injection_records_its_own_backend_and_hit_ids():
    retriever = KnowledgeRetriever(
        cards=[], backend=RagBackend.DIGEST, plan_token_limit=500)

    block = retriever.block_for_plan("剧本摘要", stage="plan")

    event = retriever.trace_payload()["retrieval_events"][-1]
    assert event["stage"] == "plan"
    assert event["scope"] == "plan"
    assert event["actual_backend"] == "digest"
    assert event["network_call"] is False
    assert event["hit_card_ids"]
    assert set(event["injected_card_ids"]) < set(event["hit_card_ids"])
    assert {
        item["id"] for item in event["drops"]
    } == set(event["hit_card_ids"]) - set(event["injected_card_ids"])
    assert {item["reason"] for item in event["drops"]} == {"token_budget"}
    assert event["injected_sha256"] == hashlib.sha256(
        block.encode("utf-8")).hexdigest()


def test_digest_shot_injection_preserves_stage_scope_and_shot_identity():
    retriever = KnowledgeRetriever(
        cards=[], backend=RagBackend.DIGEST, token_limit=500)

    block = retriever.block_for_shot(
        "CU", "荒诞的停顿", limit=500, shot_id="shot_012",
        analogy="她把沉默当作回答", stage="detail")

    event = retriever.trace_payload()["retrieval_events"][-1]
    assert block
    assert event["stage"] == "detail"
    assert event["scope"] == "shot"
    assert event["shot_id"] == "shot_012"
    assert event["analogy_query"] == "她把沉默当作回答"
    assert event["actual_backend"] == "digest"
    assert event["injected_sha256"] == hashlib.sha256(
        block.encode("utf-8")).hexdigest()


def test_process_local_case_injection_records_case_ids_and_prompt_digest():
    case = Case(
        case_id="case_pause",
        title="停顿后的转身",
        excerpt="A held beat makes the turn feel deliberate.",
        source_ref={
            "title": "Directing Actors",
            "author": "Example",
            "license": "PublicDomain",
        },
    )
    other = Case(
        case_id="case_other",
        title="无关案例",
        excerpt="A completely different scene.",
        source_ref={
            "title": "Other",
            "author": "Example",
            "license": "PublicDomain",
        },
    )
    noise = Case(
        case_id="case_noise",
        title="第三个案例",
        excerpt="An unrelated establishing view of the harbour.",
        source_ref={
            "title": "Third",
            "author": "Example",
            "license": "PublicDomain",
        },
    )
    retriever = KnowledgeRetriever(
        cards=[],
        backend=RagBackend.BM25,
        cases_backend="hybrid",
        cases_top_k=1,
        cases_index=CaseIndex(
            [case, other, noise], backend="hybrid",
            search_zh={
                "case_pause": "荒诞 停顿 转身",
                "case_other": "街道 汽车",
                "case_noise": "港口 远景",
            }),
    )

    block = retriever.case_block(
        "荒诞的停顿之后转身", top_k=1, token_limit=200,
        stage="detail", scope="shot", shot_id="shot_008")

    event = retriever.trace_payload()["retrieval_events"][-1]
    assert event["stage"] == "detail"
    assert event["scope"] == "shot"
    assert event["shot_id"] == "shot_008"
    assert event["capability"] == "cases"
    assert event["hit_case_ids"] == ["case_pause"]
    assert event["injected_case_ids"] == ["case_pause"]
    assert event["injected_sha256"] == hashlib.sha256(
        block.encode("utf-8")).hexdigest()


def test_sidecar_prompt_injection_emits_only_the_retriever_event():
    class Transport:
        def retrieve_response(
            self, query, domain=None, top_k=5, timeout=30.0,
            cases_top_k=3, analogy_query="",
        ):
            return RetrieveResponse(
                edges=[HyperEdgeDTO(
                    edge_id="hg:775a79be5bee",
                    type="EMOTION_PACK",
                    members=[["allow", "emotion", "emotion:荒诞"]],
                )],
                trace={"backend": "hypergraph", "lanes": 1},
            )

    audit_events = []
    client = KnowledgeClient(Transport(), audit=audit_events.append)
    retriever = KnowledgeRetriever(
        cards=[],
        backend=RagBackend.HYPERGRAPH,
        client=client,
        audit=audit_events.append,
    )

    block = retriever.block_for_shot(
        "情绪=荒诞", limit=200, shot_id="shot_011", stage="detail")

    event = retriever.trace_payload()["retrieval_events"][-1]
    calls = [
        item for item in audit_events if item["event"] == "retrieval_call"
    ]
    assert "[EMOTION_PACK]" in block
    assert len(calls) == 1
    assert calls[0]["retrieval_event_id"] == event["retrieval_event_id"]
    assert event["actual_backend"] == "hypergraph"
    assert event["network_call"] is True
    assert event["injected_edge_ids"] == ["hg:775a79be5bee"]


def test_sidecar_failure_records_one_bm25_fallback_event_without_edge_claims():
    class FailingTransport:
        def retrieve_response(
            self, query, domain=None, top_k=5, timeout=30.0,
            cases_top_k=3, analogy_query="",
        ):
            raise TransportError(ErrorCode.LLM_001, "上游 503", http_status=503)

    audit_events = []
    client = KnowledgeClient(FailingTransport(), audit=audit_events.append)
    retriever = KnowledgeRetriever(
        cards=_retriever().cards,
        backend=RagBackend.HYPERGRAPH,
        client=client,
        audit=audit_events.append,
    )

    block = retriever.block_for_shot(
        "轴线", limit=200, shot_id="shot_005", stage="repair")

    event = retriever.trace_payload()["retrieval_events"][-1]
    assert "轴线" in block
    assert len(audit_events) == 1
    assert audit_events[0]["event"] == "retrieval_call"
    assert audit_events[0]["retrieval_event_id"] == event["retrieval_event_id"]
    assert event["stage"] == "repair"
    assert event["requested_backend"] == "hypergraph"
    assert event["actual_backend"] == "bm25"
    assert event["network_call"] is True
    assert event["degraded"] is True
    assert event["degradation_reason"].startswith("sidecar_unavailable:")
    assert event["hit_edge_ids"] == []
    assert event["injected_edge_ids"] == []
    assert event["injected_card_ids"] == ["axis_card"]


def test_sidecar_failure_does_not_reuse_cases_from_a_previous_query():
    case = Case(
        case_id="case_pause",
        title="停顿后的转身",
        excerpt="A held beat makes the turn feel deliberate.",
        source_ref={"title": "Directing Actors"},
    )

    class FlakyTransport:
        def __init__(self):
            self.calls = 0

        def retrieve_response(
            self, query, domain=None, top_k=5, timeout=30.0,
            cases_top_k=3, analogy_query="",
        ):
            self.calls += 1
            if self.calls > 1:
                raise TransportError(
                    ErrorCode.LLM_001, "上游 503", http_status=503)
            return RetrieveResponse(
                edges=[HyperEdgeDTO(
                    edge_id="hg:775a79be5bee",
                    type="EMOTION_PACK",
                    members=[["allow", "emotion", "emotion:荒诞"]],
                )],
                cases=[case],
                trace={"backend": "hypergraph", "lanes": 2},
            )

    audit_events = []
    retriever = KnowledgeRetriever(
        cards=[],
        backend=RagBackend.HYPERGRAPH,
        client=KnowledgeClient(FlakyTransport(), audit=audit_events.append),
        audit=audit_events.append,
    )

    first = retriever.block_for_shot(
        "情绪=荒诞", limit=200, shot_id="shot_005",
        analogy="荒诞的停顿后转身", stage="detail")
    second = retriever.block_for_shot(
        "情绪=荒诞", limit=200, shot_id="shot_006",
        analogy="荒诞的停顿后转身", stage="repair")

    first_event, second_event = (
        retriever.trace_payload()["retrieval_events"])
    assert "[case_pause]" in first
    assert first_event["injected_case_ids"] == ["case_pause"]
    assert "[case_pause]" not in second
    assert "[EMOTION_PACK]" not in second
    assert second_event["actual_backend"] == "bm25"
    assert second_event["degraded"] is True
    assert second_event["hit_edge_ids"] == []
    assert second_event["hit_case_ids"] == []
    assert second_event["injected_edge_ids"] == []
    assert second_event["injected_case_ids"] == []
    assert len([
        item for item in audit_events if item["event"] == "retrieval_call"
    ]) == 2


def test_sidecar_recovery_restores_hypergraph_event_provenance():
    class FlakyTransport:
        def __init__(self):
            self.calls = 0

        def retrieve_response(
            self, query, domain=None, top_k=5, timeout=30.0,
            cases_top_k=3, analogy_query="",
        ):
            self.calls += 1
            if self.calls == 1:
                raise TransportError(
                    ErrorCode.LLM_001, "上游 503", http_status=503)
            return RetrieveResponse(
                edges=[HyperEdgeDTO(
                    edge_id="hg:775a79be5bee",
                    type="EMOTION_PACK",
                    members=[["allow", "emotion", "emotion:荒诞"]],
                )],
                trace={"backend": "hypergraph", "lanes": 1},
            )

    audit_events = []
    client = KnowledgeClient(FlakyTransport(), audit=audit_events.append)
    retriever = KnowledgeRetriever(
        cards=[],
        backend=RagBackend.HYPERGRAPH,
        client=client,
        audit=audit_events.append,
    )

    retriever.block_for_shot(
        "情绪=荒诞", limit=200, shot_id="shot_005", stage="detail")
    recovered = retriever.block_for_shot(
        "情绪=荒诞", limit=200, shot_id="shot_006", stage="repair")

    failed_event, recovered_event = (
        retriever.trace_payload()["retrieval_events"])
    assert failed_event["actual_backend"] == "bm25"
    assert failed_event["degraded"] is True
    assert "[EMOTION_PACK]" in recovered
    assert recovered_event["actual_backend"] == "hypergraph"
    assert recovered_event["degraded"] is False
    assert recovered_event["degradation_reason"] == ""
    assert recovered_event["injected_edge_ids"] == ["hg:775a79be5bee"]
    assert retriever.degraded is False
    assert client.degraded is False


def test_sidecar_bm25_response_never_claims_hypergraph_provenance():
    class Bm25Sidecar:
        def retrieve_response(
            self, query, domain=None, top_k=5, timeout=30.0,
            cases_top_k=3, analogy_query="",
        ):
            return RetrieveResponse(
                edges=[HyperEdgeDTO(
                    edge_id="hg:untrusted-bm25-edge",
                    type="EMOTION_PACK",
                    members=[["allow", "emotion", "emotion:荒诞"]],
                )],
                trace={"backend": "bm25", "lanes": 1},
            )

    audit_events = []
    retriever = KnowledgeRetriever(
        cards=_retriever().cards,
        backend=RagBackend.HYPERGRAPH,
        client=KnowledgeClient(Bm25Sidecar(), audit=audit_events.append),
        audit=audit_events.append,
    )

    block = retriever.block_for_shot(
        "轴线", limit=200, shot_id="shot_006", stage="repair")

    event = retriever.trace_payload()["retrieval_events"][-1]
    assert "[axis_card]" in block
    assert event["requested_backend"] == "hypergraph"
    assert event["actual_backend"] == "bm25"
    assert event["degraded"] is True
    assert event["degradation_reason"].startswith("backend_degraded:")
    assert "[EMOTION_PACK]" not in block
    assert event["hit_edge_ids"] == []
    assert event["injected_edge_ids"] == []
    assert event["drops"] == [{
        "id": "hg:untrusted-bm25-edge",
        "kind": "edge",
        "reason": "backend_degraded",
    }]


def test_sidecar_without_backend_proof_drops_edges_and_reports_bm25():
    class MissingBackendSidecar:
        def retrieve_response(
            self, query, domain=None, top_k=5, timeout=30.0,
            cases_top_k=3, analogy_query="",
        ):
            return RetrieveResponse(
                edges=[HyperEdgeDTO(
                    edge_id="hg:missing-backend-edge",
                    type="EMOTION_PACK",
                    members=[["allow", "emotion", "emotion:荒诞"]],
                )],
                trace={"lanes": 1},
            )

    retriever = KnowledgeRetriever(
        cards=_retriever().cards,
        backend=RagBackend.HYPERGRAPH,
        client=KnowledgeClient(MissingBackendSidecar()),
    )

    block = retriever.block_for_shot(
        "轴线", limit=200, shot_id="shot_007", stage="repair")

    event = retriever.trace_payload()["retrieval_events"][-1]
    assert "[axis_card]" in block
    assert "[EMOTION_PACK]" not in block
    assert event["actual_backend"] == "bm25"
    assert event["degraded"] is True
    assert event["degradation_reason"] == "backend_degraded:unknown"
    assert event["hit_edge_ids"] == []
    assert event["injected_edge_ids"] == []
    assert event["drops"] == [{
        "id": "hg:missing-backend-edge",
        "kind": "edge",
        "reason": "backend_degraded",
    }]


def test_driver_tool_dispatch_preserves_repair_stage_and_shot_identity():
    engine = _retriever()
    registry = ToolRegistry()
    register_knowledge_tools(registry, engine)
    driver = PrevisDriver(
        transport=object(),
        audit=AuditLogger(),
        knowledge=engine,
        registry=registry,
    )
    driver._call_purpose = "repair"
    driver._current_shot_id = "shot_007"

    reply = ChatReply(tool_calls=[ToolCall(
        id="knowledge-repair",
        function=FunctionCall(
            name="search_knowledge",
            arguments='{"query": "轴线"}',
        ),
    )])
    problem = driver._dispatch_tool_calls(reply, messages=[])

    assert problem == ""
    event = engine.trace_payload()["retrieval_events"][-1]
    assert event["stage"] == "repair"
    assert event["scope"] == "shot"
    assert event["shot_id"] == "shot_007"


def test_process_local_case_miss_records_a_zero_hit_decision():
    cases = [
        Case(
            case_id="case_pause",
            title="停顿后的转身",
            excerpt="A held beat makes the turn feel deliberate.",
            source_ref={"title": "Directing Actors"},
        ),
        Case(
            case_id="case_cut",
            title="街道硬切",
            excerpt="A hard cut between two moving street views.",
            source_ref={"title": "Editing"},
        ),
        Case(
            case_id="case_noise",
            title="港口远景",
            excerpt="An unrelated establishing view of the harbour.",
            source_ref={"title": "Other"},
        ),
    ]
    retriever = KnowledgeRetriever(
        cards=[],
        backend=RagBackend.BM25,
        cases_backend="hybrid",
        cases_top_k=2,
        cases_index=CaseIndex(
            cases,
            backend="hybrid",
            search_zh={
                "case_pause": "荒诞 停顿 转身",
                "case_cut": "街道 硬切",
                "case_noise": "港口 远景",
            },
        ),
    )

    block = retriever.case_block(
        "zzqx_no_match_token", top_k=2, token_limit=200,
        stage="detail", scope="shot", shot_id="shot_013")

    event = retriever.trace_payload()["retrieval_events"][-1]
    assert block == ""
    assert event["hit_case_ids"] == []
    assert event["injected_case_ids"] == []
    assert event["drops"] == []
    assert event["injected"] is False
    assert event["actual_injected_tokens"] == 0
    assert event["network_call"] is False


def test_process_local_cases_dropped_by_budget_are_not_claimed_as_injected():
    cases = [
        Case(
            case_id="case_alpha",
            title="Alpha",
            excerpt="alpha",
            source_ref={"title": "First"},
        ),
        Case(
            case_id="case_beta",
            title="Beta",
            excerpt="beta",
            source_ref={"title": "Second"},
        ),
        Case(
            case_id="case_noise",
            title="Noise",
            excerpt="unrelated",
            source_ref={"title": "Third"},
        ),
        Case(
            case_id="case_other",
            title="Other",
            excerpt="different",
            source_ref={"title": "Fourth"},
        ),
    ]
    retriever = KnowledgeRetriever(
        cards=[],
        backend=RagBackend.BM25,
        cases_backend="hybrid",
        cases_top_k=2,
        cases_index=CaseIndex(cases, backend="hybrid"),
    )

    block = retriever.case_block(
        "alpha beta", top_k=2, token_limit=1,
        stage="coarse", scope="shot", shot_id="shot_014")

    event = retriever.trace_payload()["retrieval_events"][-1]
    assert block == ""
    assert event["actual_backend"] == "hybrid"
    assert event["hit_case_ids"] == ["case_alpha", "case_beta"]
    assert event["injected_case_ids"] == []
    assert event["drops"] == [
        {"id": "case_alpha", "kind": "case", "reason": "token_budget"},
        {"id": "case_beta", "kind": "case", "reason": "token_budget"},
    ]
    assert event["injected"] is False
    assert event["actual_injected_tokens"] == 0
    assert event["network_call"] is False


def test_process_local_case_provenance_separates_injected_from_dropped_hits():
    cases = [
        Case(
            case_id="case_alpha",
            title="Alpha",
            excerpt="alpha",
            source_ref={"title": "First"},
        ),
        Case(
            case_id="case_beta",
            title="Beta",
            excerpt="beta " + ("scene " * 30),
            source_ref={"title": "Second"},
        ),
        Case(
            case_id="case_noise",
            title="Noise",
            excerpt="unrelated",
            source_ref={"title": "Third"},
        ),
        Case(
            case_id="case_other",
            title="Other",
            excerpt="different",
            source_ref={"title": "Fourth"},
        ),
    ]
    retriever = KnowledgeRetriever(
        cards=[],
        backend=RagBackend.BM25,
        cases_backend="hybrid",
        cases_top_k=2,
        cases_index=CaseIndex(cases, backend="hybrid"),
    )

    block = retriever.case_block(
        "alpha beta", top_k=2, token_limit=30,
        stage="repair", scope="shot", shot_id="shot_015")

    event = retriever.trace_payload()["retrieval_events"][-1]
    assert "[case_alpha]" in block
    assert "[case_beta]" not in block
    assert event["hit_case_ids"] == ["case_alpha", "case_beta"]
    assert event["injected_case_ids"] == ["case_alpha"]
    assert event["drops"] == [{
        "id": "case_beta",
        "kind": "case",
        "reason": "token_budget",
    }]
    assert event["injected"] is True
    assert event["actual_injected_tokens"] > 0
    assert event["injected_sha256"] == hashlib.sha256(
        block.encode("utf-8")).hexdigest()
