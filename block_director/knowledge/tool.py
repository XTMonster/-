"""``search_knowledge`` 工具（执行文档 v1.2 §7.4 知识工具 / §6.5）。

知识工具**不碰 bpy**：语料是纯数据、检索是纯计算，因此注册逻辑也放在本包内，
由 ``register_all_scene_tools`` 一并接进注册表。这样"知识"与"场景"两条工具线
各自独立演进，却共享同一个入口。

返回值遵守 §16.2：任何失败都转成 LLM 可读的观察文本，工具永不抛异常
（异常处理在 :class:`~block_director.layer5_orchestrator.tool_registry.ToolRegistry`
统一兜底）。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .corpus import DOMAINS
from .retriever import (
    TOKEN_LIMIT_TOOL,
    KnowledgeRetriever,
    default_retriever,
    estimate_tokens,
)

SEARCH_KNOWLEDGE = "search_knowledge"

SEARCH_KNOWLEDGE_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["query"],
    "properties": {
        "query": {"type": "string"},
        "domain": {"type": "string", "enum": list(DOMAINS)},
        "top_k": {"type": "integer", "minimum": 1, "maximum": 20},
    },
}

SEARCH_KNOWLEDGE_DESCRIPTION = (
    "检索摄影 / 轴线 / 构图 / 调度 / 表演五个知识域，返回相关条目的要点、"
    "关联规则与关键参数。不确定怎么处理某个镜头时用它，而不是凭印象编造。")


def register_knowledge_tools(registry,
                             retriever: Optional[KnowledgeRetriever] = None,
                             token_limit: int = TOKEN_LIMIT_TOOL):
    """把 ``search_knowledge`` 注册进工具注册表（重复调用是安全的）。"""
    engine = retriever or default_retriever()

    def handler(query: str, domain: Optional[str] = None,
                top_k: Optional[int] = None,
                _context: Optional[Dict[str, Any]] = None) -> str:
        context = dict(_context or {})
        shot_id = str(context.get("shot_id") or "")
        text = engine.block(
            query,
            domain,
            top_k,
            token_limit=token_limit,
            stage=str(context.get("stage") or "direct"),
            scope=str(context.get("scope") or ("shot" if shot_id else "tool")),
            shot_id=shot_id,
        )
        if not text:
            known = "、".join(DOMAINS)
            if domain:
                return (f"知识库里没有匹配「{query}」（域 {domain}）的条目。"
                        f"可换关键词，或省略 domain 在全部域里检索：{known}。")
            return (f"知识库里没有匹配「{query}」的条目。"
                    f"可用域：{known}。试试更具体的术语，如「越轴」「三分法」。")
        return f"{text}\n（共 {estimate_tokens(text)} token）"

    return registry.add(
        name=SEARCH_KNOWLEDGE,
        description=SEARCH_KNOWLEDGE_DESCRIPTION,
        parameters=SEARCH_KNOWLEDGE_PARAMETERS,
        handler=handler,
    )
