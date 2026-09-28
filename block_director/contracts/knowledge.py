"""知识条目契约（执行文档 v1.2 §6.3）。"""

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
        )
