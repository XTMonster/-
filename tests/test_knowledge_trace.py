"""v1.4 §2.3 / §3.3：`knowledge_trace.json` 每次运行必写，且降级必须留痕。

`degraded` / `degraded_reason` 在 v1.3 里是**死字段**：没有人写、也没有人读。
本用例把生产者钉住——① 检索器自己产出 trace（含后端、种子、命中边、打分、
注入集合）；② 一次 headless 运行会在运行目录里落 `knowledge_trace.json`；
③ 请求超图但没有 sidecar 时必须降级为 bm25 **并写明原因**。
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from block_director.contracts.enums import RagBackend
from block_director.knowledge.retriever import (
    KnowledgeRetriever,
    cards_in_domain_order,
)


def _retriever(**kwargs) -> KnowledgeRetriever:
    return KnowledgeRetriever(cards=cards_in_domain_order(), **kwargs)


def test_trace_payload_has_the_documented_shape():
    retriever = _retriever(backend=RagBackend.BM25, top_k=5)
    retriever.block_for_plan("越轴 构图 运镜")
    payload = retriever.trace_payload()
    for key in ("backend", "requested_backend", "degraded", "degraded_reason",
                "cards", "top_k", "token_limits", "warnings",
                "shot_scope", "plan_scope"):
        assert key in payload, key
    assert payload["token_limits"] == {"shot": 800, "plan": 2000}
    assert payload["degraded"] is False


def test_hypergraph_without_a_sidecar_degrades_and_says_why():
    """负例：请求超图但没有能力/索引 → 降级为 bm25，且必须写明原因。"""
    retriever = _retriever(backend=RagBackend.HYPERGRAPH)
    assert retriever.backend is RagBackend.BM25
    assert retriever.requested_backend is RagBackend.HYPERGRAPH
    assert retriever.degraded is True
    assert retriever.degraded_reason == "hypergraph_unavailable"
    assert any("超图" in warning for warning in retriever.warnings)
    payload = retriever.trace_payload()
    assert payload["degraded"] is True
    assert payload["requested_backend"] == "hypergraph"
    assert payload["backend"] == "bm25"


def test_unknown_backend_is_not_a_silent_fallback():
    retriever = _retriever(backend="definitely-not-a-backend")
    assert retriever.backend is RagBackend.BM25
    assert retriever.degraded is True
    assert retriever.degraded_reason.startswith("unknown_backend")


def test_plan_and_shot_use_their_own_token_limits():
    retriever = _retriever(backend=RagBackend.BM25, token_limit=800,
                           plan_token_limit=2000)
    shot_block = retriever.block_for_shot("CU", "特写里的眼睛")
    plan_block = retriever.block_for_plan("越轴 构图 运镜")
    assert shot_block and plan_block
    assert retriever.token_limit == 800
    assert retriever.plan_token_limit == 2000
    # 整场预取可以比单镜检索长——这正是"两个键分列"的意义。
    assert len(plan_block) >= len(shot_block) or len(plan_block) > 0


def test_a_headless_run_writes_the_trace_file():
    from block_director.layer5_orchestrator.headless_runner import run_headless

    with tempfile.TemporaryDirectory(prefix="bd_trace_") as tmp:
        summary = run_headless("INT. 房间 - 日\n\n两人说话。\n", offline=True,
                               project_dir=Path(tmp))
        trace_path = Path(summary["knowledge_trace"])
        assert trace_path.exists(), summary
        payload = json.loads(trace_path.read_text(encoding="utf-8"))
        assert payload["backend"] and "degraded" in payload
        assert payload["written_at"]
