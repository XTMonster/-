"""sidecar 知识客户端（v1.4 §2.3 / §2.3b / §2.4）。纯 Python，**不 import bpy**。

为什么不让调用方直接用 ``Transport.retrieve()``：

1. 检索面已经有**三条通道**（``cards[] / edges[] / cases[]``）＋ ``trace{}``，
   而 ``LLMTransport.retrieve()`` 只回卡片；
2. §2.4 的预算账本要求 ``retrieval_calls`` 与 ``llm_calls`` **分列统计**——
   "谁真的发起了检索"只有这一层知道；
3. ``knowledge_trace.json``（每次运行必写）的数据源就在这里。

降级纪律：sidecar 不可达时**不静默返回空**——记 ``degraded`` ＋ 具名原因，
并让调用方拿到 ``None`` 自行决定退回 BM25。捕获的是具体的
``TransportError``，不是 ``Exception``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from ..contracts.errors import TransportError
from ..contracts.knowledge import HyperEdge as HyperEdgeDTO
from ..contracts.operations import RetrieveResponse
from .hypergraph import HyperEdge as InternalEdge, Member, Node, render_edges

#: 审计回调的载荷形状（由 audit logger 落进 run 的 JSONL）。
AuditFn = Callable[[Dict[str, Any]], None]


def retrieval_call_bound(shots: int, lanes: int = 1) -> int:
    """§2.3 的检索预算口径：``(2 + N) × lanes``（N = 镜数）。

    整场预取 1 次 ＋ 每镜 1 次 = ``2 + N``；L3 开启时 ``lanes = 2``。
    """
    return (2 + int(shots)) * int(lanes)


def to_internal_edges(edges: Iterable[HyperEdgeDTO]) -> List[InternalEdge]:
    """线协议 DTO → 超图内部对象。

    ``/v1/retrieve`` 回的是契约 DTO，而渲染与去重用的是 ``hypergraph`` 的对象；
    这一层转换是**唯一**的落点，避免两处以各自的写法拼 ``Member``。
    """
    out: List[InternalEdge] = []
    for edge in edges:
        members = tuple(Member(role=str(m[0]), kind=str(m[1]), node_id=str(m[2]))
                        for m in edge.members)
        out.append(InternalEdge(
            type=edge.type,
            members=members,
            source_kind=edge.source_kind,
            hardness=edge.hardness,
            weight=float(edge.weight),
            confidence=float(edge.confidence),
            occurrences=int(edge.occurrences),
            source_span=dict(edge.source_span),
        ))
    return out


def render_edge_block(edges: Sequence[HyperEdgeDTO], *, limit: int,
                      nodes: Optional[Dict[str, Node]] = None,
                      title: str = "硬约束（禁/许）"
                      ) -> Tuple[str, List[str], bool]:
    """把响应里的超边渲染成注入块（§2.3 的**原子注入**）。

    超边以整条为单位加入，装不下就整条不注入并记 ``dropped``——**绝不截断**，
    否则 ``forbid`` 成员会被切掉，模型照样做禁忌动作。``nodes`` 缺省时用
    ``node_id``（本身就是 ``kind:值``，可读）。返回
    ``(文本, dropped_edge_ids, quality_fail)``；文本为空表示一条都没装下。
    """
    text, dropped, quality_fail = render_edges(
        to_internal_edges(edges), dict(nodes or {}), int(limit))
    if not text:
        return "", dropped, quality_fail
    return f"【{title}】\n{text}", dropped, quality_fail


@dataclass
class KnowledgeClient:
    """把一次 ``/v1/retrieve`` 的**整条**响应变成可记账、可留痕的对象。"""

    transport: Any
    audit: Optional[AuditFn] = None
    timeout: float = 30.0
    retrieval_calls: int = 0
    degraded: bool = False
    degraded_reason: str = ""
    last_response: Optional[RetrieveResponse] = None
    history: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not hasattr(self.transport, "retrieve_response"):
            raise TypeError(
                "KnowledgeClient 需要 sidecar 传输层（必须提供 retrieve_response()）；"
                f"拿到的是 {type(self.transport).__name__}")

    def _emit(self, payload: Dict[str, Any]) -> None:
        self.history.append(payload)
        if self.audit is not None:
            self.audit(payload)

    def retrieve(self, query: str, *, domain: Optional[str] = None,
                 top_k: int = 5, cases_top_k: int = 3) -> RetrieveResponse:
        """发起一次检索；三条通道 ＋ trace 一次拿回。"""
        response = self.transport.retrieve_response(
            query, domain, top_k, self.timeout, cases_top_k)
        self.retrieval_calls += 1
        self.last_response = response
        trace = dict(response.trace or {})
        self._emit({
            "event": "retrieval_call",
            "query": query,
            "domain": domain,
            "top_k": int(top_k),
            "cards": len(response.cards),
            "edges": len(response.edges),
            "cases": len(response.cases),
            "forbid_members": sum(len(edge.forbid) for edge in response.edges),
            "lanes": int(trace.get("lanes", 1) or 1),
            "backend": str(trace.get("backend", "")),
            "cases_degraded": bool(trace.get("cases_degraded", False)),
            "retrieval_calls": self.retrieval_calls,
        })
        return response

    def retrieve_or_none(self, query: str, *, domain: Optional[str] = None,
                         top_k: int = 5, cases_top_k: int = 3
                         ) -> Optional[RetrieveResponse]:
        """sidecar 不可达时返回 ``None`` 并**留痕**（调用方退回 BM25）。

        只捕获 ``TransportError``——这不是"吞异常"：它把"哪一次、为什么"
        写成 ``degraded_reason`` 与一条审计事件，且把决定权交给调用方。
        """
        try:
            return self.retrieve(query, domain=domain, top_k=top_k,
                                 cases_top_k=cases_top_k)
        except TransportError as exc:
            self.degraded = True
            self.degraded_reason = f"sidecar_unavailable:{exc.code}"
            self._emit({
                "event": "retrieval_failed",
                "query": query,
                "domain": domain,
                "reason": self.degraded_reason,
                "detail": str(exc)[:300],
                "retrieval_calls": self.retrieval_calls,
            })
            return None

    def trace_payload(self) -> Dict[str, Any]:
        """``knowledge_trace.json`` 的收尾片段（§2.3：每次运行必写）。"""
        payload: Dict[str, Any] = dict(self.last_response.trace) if self.last_response else {}
        payload.setdefault("backend", "")
        payload.setdefault("lanes", 1)
        payload["retrieval_calls"] = self.retrieval_calls
        payload["client_degraded"] = bool(self.degraded)
        payload["client_degraded_reason"] = self.degraded_reason
        return payload
