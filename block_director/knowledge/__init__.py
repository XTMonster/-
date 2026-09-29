"""Light RAG 知识库（执行文档 v1.2 §6）。纯 Python，不依赖 bpy。"""

from __future__ import annotations

from .bm25 import BM25, K1, B, make_bm25, ranked, tokenize
from .client import KnowledgeClient, retrieval_call_bound
from .corpus import (
    CARDS,
    DOMAIN_DIGESTS,
    DOMAIN_LABELS,
    DOMAINS,
    cards_by_domain,
    digest_cards,
)
from .retriever import (
    RRF_K,
    TOKEN_LIMIT_PLAN,
    TOKEN_LIMIT_TOOL,
    KnowledgeRetriever,
    RetrievalHit,
    cards_in_domain_order,
    default_retriever,
    estimate_tokens,
    reset_default_retriever,
    rrf_merge,
    truncate_to_tokens,
)
from .tool import (
    SEARCH_KNOWLEDGE,
    SEARCH_KNOWLEDGE_PARAMETERS,
    register_knowledge_tools,
)

__all__ = [
    "BM25", "K1", "B", "make_bm25", "ranked", "tokenize",
    "KnowledgeClient", "retrieval_call_bound",
    "CARDS", "DOMAINS", "DOMAIN_LABELS", "DOMAIN_DIGESTS",
    "cards_by_domain", "digest_cards", "cards_in_domain_order",
    "KnowledgeRetriever", "RetrievalHit", "default_retriever",
    "reset_default_retriever", "estimate_tokens", "truncate_to_tokens",
    "rrf_merge", "RRF_K", "TOKEN_LIMIT_TOOL", "TOKEN_LIMIT_PLAN",
    "SEARCH_KNOWLEDGE", "SEARCH_KNOWLEDGE_PARAMETERS",
    "register_knowledge_tools",
]
