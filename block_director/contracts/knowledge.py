"""知识条目契约（执行文档 v1.2 §6.3 / v1.3 诉求 5 / v1.4 §2.3、§2.3b）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


RETRIEVAL_EVENT_SCHEMA_VERSION = "knowledge-retrieval-event/v1"


@dataclass
class Card:
    """一条 Light RAG 知识卡。字段与 §6.3 的 JSON 结构一一对应。"""

    id: str
    domain: str
    title: str
    content: str
    keywords: List[str] = field(default_factory=list)
    rules: List[str] = field(default_factory=list)
    parameters: Dict[str, Any] = field(default_factory=dict)
    examples: List[str] = field(default_factory=list)
    related: List[str] = field(default_factory=list)
    #: v1.3：这条知识**引擎能不能真的做到**——
    #: ``implemented`` / ``approximated`` / ``unsupported``。
    #: 不标清楚，模型会要求引擎做它做不到的事（比如"手持跟拍 + 变焦"）。
    engine_support: str = ""
    #: v1.3：情感语义（运镜与表演类卡片必填），供"情绪 → 手法"的检索用。
    emotion: str = ""
    #: v1.3：检索辅助标签（"推镜""压迫""特写"这类可检索词）。
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "domain": self.domain,
            "title": self.title,
            "content": self.content,
            "keywords": list(self.keywords),
            "rules": list(self.rules),
            "parameters": dict(self.parameters),
            "examples": list(self.examples),
            "related": list(self.related),
            "engine_support": self.engine_support,
            "emotion": self.emotion,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Card":
        return cls(
            id=data["id"],
            domain=data["domain"],
            title=data["title"],
            content=data["content"],
            keywords=list(data.get("keywords", [])),
            rules=list(data.get("rules", [])),
            parameters=dict(data.get("parameters", {})),
            examples=list(data.get("examples", [])),
            related=list(data.get("related", [])),
            engine_support=str(data.get("engine_support", "")),
            emotion=str(data.get("emotion", "")),
            tags=list(data.get("tags", [])),
        )


# --------------------------------------------------------------------------- #
# v1.4 §2.3：``/v1/retrieve`` 的响应形状加了两种元素——超边与案例。
#
# 设计约束：
# * 超边以**整条**为单位传输，绝不截断（"半条边"会让模型照样做禁忌动作）；
# * L3 案例**结构上不可能**携带约束（没有 ``forbid`` 字段），这是 E3
#   「经验越权率 = 0」在类型层的机制保证，而不是靠调用方自觉。
# --------------------------------------------------------------------------- #


def _triples(raw: Any) -> List[List[str]]:
    """把 ``[[role, kind, node_id], ...]`` 归一成纯字符串三元组。"""
    out: List[List[str]] = []
    for item in raw or ():
        parts = list(item)
        if len(parts) != 3:
            raise ValueError(f"超边成员必须是 (role, kind, node_id) 三元组：{item!r}")
        out.append([str(parts[0]), str(parts[1]), str(parts[2])])
    return out


@dataclass
class HyperEdge:
    """一条超边（§2.3 的线协议元素）。

    ``members`` 是 ``[role, kind, node_id]`` 三元组列表
    （``role ∈ {allow, forbid, qualifier}``）。``forbid`` 是其中 ``role=forbid``
    的那一部分，**单独再列一次**：消费方即便只读 ``forbid`` 也不会漏掉禁忌
    （Q6b 完整率 / Q7 拦截率的机制保证）。
    """

    edge_id: str
    type: str
    members: List[List[str]] = field(default_factory=list)
    forbid: List[List[str]] = field(default_factory=list)
    weight: float = 1.0
    source_span: Dict[str, Any] = field(default_factory=dict)
    source_kind: str = "theory"
    hardness: str = "hard"
    occurrences: int = 1
    confidence: float = 0.7

    def to_dict(self) -> Dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "type": self.type,
            "members": [list(m) for m in self.members],
            "forbid": [list(m) for m in self.forbid],
            "weight": float(self.weight),
            "source_span": dict(self.source_span),
            "source_kind": self.source_kind,
            "hardness": self.hardness,
            "occurrences": int(self.occurrences),
            "confidence": float(self.confidence),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HyperEdge":
        members = _triples(data.get("members", []))
        if "forbid" in data:
            forbid = _triples(data.get("forbid"))
        else:
            forbid = [m for m in members if m[0] == "forbid"]
        return cls(
            edge_id=str(data["edge_id"]),
            type=str(data["type"]),
            members=members,
            forbid=forbid,
            weight=float(data.get("weight", 1.0)),
            source_span=dict(data.get("source_span", {})),
            source_kind=str(data.get("source_kind", "theory")),
            hardness=str(data.get("hardness", "hard")),
            occurrences=int(data.get("occurrences", 1)),
            confidence=float(data.get("confidence", 0.7)),
        )


@dataclass
class Case:
    """一条 L3 参考案例（§2.3b）。

    L3 **永不产出约束**——见类文档上方说明，这里刻意没有 ``forbid`` 字段。
    ``case_type ∈ {narrative, sequence_pattern, lesson}``；``sequence_pattern``
    携带 ``beat_sequence``（如 ``["establish", "coverage", "reaction"]``）。
    """

    case_id: str
    case_type: str = "narrative"
    title: str = ""
    excerpt: str = ""
    beat_sequence: List[str] = field(default_factory=list)
    source_ref: Dict[str, Any] = field(default_factory=dict)
    score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "case_type": self.case_type,
            "title": self.title,
            "excerpt": self.excerpt,
            "beat_sequence": list(self.beat_sequence),
            "source_ref": dict(self.source_ref),
            "score": float(self.score),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Case":
        return cls(
            case_id=str(data["case_id"]),
            case_type=str(data.get("case_type", "narrative")),
            title=str(data.get("title", "")),
            excerpt=str(data.get("excerpt", "")),
            beat_sequence=[str(item) for item in data.get("beat_sequence", [])],
            source_ref=dict(data.get("source_ref", {})),
            score=float(data.get("score", 0.0)),
        )


@dataclass(frozen=True)
class RetrievalEvent:
    """One logical retrieval decision that produced an injected prompt block.

    ``retrieval_calls`` remains the compatibility count for network requests.
    A process-local BM25/hypergraph/case lookup therefore has an event with
    ``network_call=False`` and does not consume that budget.
    """

    retrieval_event_id: str
    stage: str
    scope: str
    shot_id: str
    query: str
    analogy_query: str
    top_k: int
    token_budget: int
    requested_backend: str
    actual_backend: str
    capability: str
    degraded: bool
    degradation_reason: str
    network_call: bool
    hit_card_ids: List[str] = field(default_factory=list)
    hit_edge_ids: List[str] = field(default_factory=list)
    hit_case_ids: List[str] = field(default_factory=list)
    injected_card_ids: List[str] = field(default_factory=list)
    injected_edge_ids: List[str] = field(default_factory=list)
    injected_case_ids: List[str] = field(default_factory=list)
    drops: List[Dict[str, str]] = field(default_factory=list)
    actual_injected_tokens: int = 0
    injected: bool = False
    injected_sha256: str = ""
    schema_version: str = RETRIEVAL_EVENT_SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        hit_ids = [
            *self.hit_card_ids,
            *self.hit_edge_ids,
            *self.hit_case_ids,
        ]
        injected_ids = [
            *self.injected_card_ids,
            *self.injected_edge_ids,
            *self.injected_case_ids,
        ]
        return {
            "schema_version": self.schema_version,
            "retrieval_event_id": self.retrieval_event_id,
            "stage": self.stage,
            "scope": self.scope,
            "shot_id": self.shot_id,
            "query": self.query,
            "analogy_query": self.analogy_query,
            "top_k": int(self.top_k),
            "token_budget": int(self.token_budget),
            "requested_backend": self.requested_backend,
            "actual_backend": self.actual_backend,
            "capability": self.capability,
            "degraded": bool(self.degraded),
            "degradation_reason": self.degradation_reason,
            "network_call": bool(self.network_call),
            "cards": len(self.hit_card_ids),
            "edges": len(self.hit_edge_ids),
            "cases": len(self.hit_case_ids),
            "hit_ids": hit_ids,
            "hit_card_ids": list(self.hit_card_ids),
            "hit_edge_ids": list(self.hit_edge_ids),
            "hit_case_ids": list(self.hit_case_ids),
            "injected_ids": injected_ids,
            "injected_card_ids": list(self.injected_card_ids),
            "injected_edge_ids": list(self.injected_edge_ids),
            "injected_case_ids": list(self.injected_case_ids),
            "dropped_ids": [str(item.get("id") or "") for item in self.drops],
            "drops": [dict(item) for item in self.drops],
            "actual_injected_tokens": int(self.actual_injected_tokens),
            "injected": bool(self.injected),
            "injected_sha256": self.injected_sha256,
        }
