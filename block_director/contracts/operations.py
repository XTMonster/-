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
    request_id: str = field(default_factory=new_request_id)

    def to_dict(self) -> Dict[str, Any]:
        return {"request_id": self.request_id, "query": self.query,
                "domain": self.domain, "top_k": self.top_k}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RetrieveRequest":
        return cls(query=data.get("query", ""),
                   domain=data.get("domain"),
                   top_k=int(data.get("top_k", 5)),
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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cards": [c.to_dict() for c in self.cards],
            "edges": [e.to_dict() for e in self.edges],
            "cases": [c.to_dict() for c in self.cases],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RetrieveResponse":
        return cls(
            cards=[Card.from_dict(c) for c in data.get("cards", [])],
            edges=[HyperEdge.from_dict(e) for e in data.get("edges", [])],
            cases=[Case.from_dict(c) for c in data.get("cases", [])],
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
