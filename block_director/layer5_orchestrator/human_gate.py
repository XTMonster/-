"""人工审批门（执行文档 v1.2 §11.1 Level 3）。

红线（§11.1 实现注意）：审批**不得**在 timer 回调里直接弹对话框——上下文
不完整容易失败。因此协议设计成**非阻塞**：

1. 驱动器在主线程调用 ``request()``，实现方立即返回
   ``APPROVED`` / ``REJECTED`` / ``SKIPPED`` 之一，或 ``PENDING`` 表示
   "已经弹了，等用户点"；
2. 若返回 ``PENDING``，驱动器切到 ``AWAIT_HUMAN`` 状态，每个 tick 调
   ``poll()``；期间不阻塞事件循环，UI 保持可响应。

headless 没有界面，用 :class:`AutoGate`：默认按策略自动通过或拒绝，并把
每一次决策记进 history，事后可审计。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from ..contracts.enums import StrEnum


class GateDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    PENDING = "pending"      # 已请求，等待用户
    SKIPPED = "skipped"      # 没有可用的人工门，直接放行


#: 需要人工确认的场景（§11.1）
GATE_KINDS = ("plan", "axis_violation", "regeneration", "deletion", "export")


@dataclass
class GateRequest:
    kind: str
    title: str
    detail: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    request_id: str = ""

    def __post_init__(self) -> None:
        if not self.request_id:
            self.request_id = f"gate_{uuid.uuid4().hex[:12]}"
        if self.kind not in GATE_KINDS:
            raise ValueError(f"未知审批类型 {self.kind}，合法值：{GATE_KINDS}")


@runtime_checkable
class HumanGate(Protocol):
    def request(self, request: GateRequest) -> GateDecision:
        ...

    def poll(self, request_id: str) -> Optional[GateDecision]:
        ...


class AutoGate:
    """headless / 无人值守时的审批门。

    ``policy`` 按 ``kind`` 指定默认决策；未指定的走 ``default``。
    每一次决策都写进 ``history``，被拒的请求在报告里一眼可见。
    """

    def __init__(self, policy: Optional[Dict[str, GateDecision]] = None,
                 default: GateDecision = GateDecision.SKIPPED) -> None:
        self.policy = dict(policy or {})
        self.default = default
        self.history: List[Dict[str, Any]] = []
        self.requests: List[GateRequest] = []

    def request(self, request: GateRequest) -> GateDecision:
        decision = self.policy.get(request.kind, self.default)
        self.requests.append(request)
        self.history.append({"kind": request.kind, "title": request.title,
                             "decision": str(decision),
                             "at": round(time.time(), 3)})
        return decision

    def poll(self, request_id: str) -> Optional[GateDecision]:
        return None      # 自动门从不停留在 PENDING

    @property
    def rejected(self) -> List[Dict[str, Any]]:
        return [item for item in self.history if item["decision"] == "rejected"]
