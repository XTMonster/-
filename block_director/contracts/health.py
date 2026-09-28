"""sidecar 健康检查与能力协商契约（执行文档 v1.2 §2.5）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from .enums import Capability


@dataclass
class HealthStatus:
    """``GET /health`` 的响应体。

    ``capabilities`` 是**能力协商**的依据：插件据此决定 RAG 后端与是否启用
    向量检索，避免"配置了但没装"的静默失败（§2.5 / §6.1）。
    """

    status: str = "ok"
    version: str = ""
    capabilities: List[Capability] = field(default_factory=list)
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def has(self, capability: Capability) -> bool:
        return capability in self.capabilities

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "status": self.status,
            "version": self.version,
            "capabilities": [str(c) for c in self.capabilities],
        }
        if self.detail:
            out["detail"] = self.detail
        return out

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HealthStatus":
        raw = data.get("capabilities", []) or []
        caps: List[Capability] = []
        for item in raw:
            try:
                caps.append(Capability(item))
            except ValueError:
                continue   # 未知能力忽略（向前兼容）
        return cls(
            status=data.get("status", "ok"),
            version=data.get("version", ""),
            capabilities=caps,
            detail=data.get("detail", ""),
        )
