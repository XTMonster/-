"""知识条目契约（执行文档 v1.2 §6.3 / v1.3 诉求 5）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


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
