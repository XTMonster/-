"""sidecar 其余端点的请求/响应契约（执行文档 v1.2 §2.5）。

与 :mod:`messages` / :mod:`knowledge` / :mod:`health` 一起构成完整的线协议模型，
并与 ``specs/openapi.yaml`` 的 components.schemas 一一对应（§16.5）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .knowledge import Card, Case, HyperEdge
from .messages import new_request_id


@dataclass
class EmbedRequest:
    texts: List[str]
    request_id: str = field(default_factory=new_request_id)

    def to_dict(self) -> Dict[str, Any]:
        return {"request_id": self.request_id, "texts": list(self.texts)}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EmbedRequest":
        return cls(texts=list(data.get("texts", [])),
                   request_id=data.get("request_id", new_request_id()))


@dataclass
class EmbedResponse:
    vectors: List[List[float]] = field(default_factory=list)
    dim: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {"vectors": [list(map(float, v)) for v in self.vectors], "dim": self.dim}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EmbedResponse":
        vectors = [list(map(float, vec)) for vec in data.get("vectors", [])]
        dim = int(data.get("dim") or (len(vectors[0]) if vectors else 0))
        return cls(vectors=vectors, dim=dim)


@dataclass
class RetrieveRequest:
    query: str
    domain: Optional[str] = None
    top_k: int = 5
    #: v1.4 §2.3b：L3 参考案例单独一条通道，条数由它控制（默认 3，取 2–5）。
    cases_top_k: int = 3
    #: v1.4 §2.3b 的**两通道路由**：`query` 是 `constraint_query`（`键=值` 的契约串，
    #: 恒走 L1/L2 超图）；`analogy_query` 是 `analogy_query`（散文，走 L3 案例层）。
    #: 留空 = 不查 L3（**不是**"拿契约串去查 L3"——实测那样案例栏全是噪声，
    #: 双模型面板给 1–2 分，E1 = 0/24）。
    analogy_query: str = ""
    request_id: str = field(default_factory=new_request_id)

    def to_dict(self) -> Dict[str, Any]:
        return {"request_id": self.request_id, "query": self.query,
                "domain": self.domain, "top_k": self.top_k,
                "cases_top_k": self.cases_top_k,
                "analogy_query": self.analogy_query}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RetrieveRequest":
        return cls(query=data.get("query", ""),
                   domain=data.get("domain"),
                   top_k=int(data.get("top_k", 5)),
                   cases_top_k=int(data.get("cases_top_k", 3)),
                   analogy_query=data.get("analogy_query", ""),
                   request_id=data.get("request_id", new_request_id()))


@dataclass
class RetrieveResponse:
    """``POST /v1/retrieve`` 的响应（v1.4 §2.3 / §2.3b）。

    三条通道一次返回：``cards[]``（卡片正文）＋ ``edges[]``（L1/L2 超边，
    **整条**，含全部 ``forbid``）＋ ``cases[]``（L3 参考案例，永不携带约束）。
    ``edges`` / ``cases`` 都带默认值，旧客户端只读 ``cards`` 时行为不变
    （向后兼容）。
    """

    cards: List[Card] = field(default_factory=list)
    edges: List[HyperEdge] = field(default_factory=list)
    cases: List[Case] = field(default_factory=list)
    #: v1.4 §2.3：``knowledge_trace.json`` 的数据源。种子/扩展/打分只有 sidecar
    #: 算得出来，插件拿不到就算不出可重放的 trace，所以它随响应一起回来。
    trace: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cards": [c.to_dict() for c in self.cards],
            "edges": [e.to_dict() for e in self.edges],
            "cases": [c.to_dict() for c in self.cases],
            "trace": dict(self.trace),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RetrieveResponse":
        return cls(
            cards=[Card.from_dict(c) for c in data.get("cards", [])],
            edges=[HyperEdge.from_dict(e) for e in data.get("edges", [])],
            cases=[Case.from_dict(c) for c in data.get("cases", [])],
            trace=dict(data.get("trace", {})),
        )


@dataclass
class CancelRequest:
    request_id: str

    def to_dict(self) -> Dict[str, Any]:
        return {"request_id": self.request_id}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CancelRequest":
        return cls(request_id=data["request_id"])


@dataclass
class CancelResponse:
    cancelled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {"cancelled": self.cancelled}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CancelResponse":
        return cls(cancelled=bool(data.get("cancelled", True)))
