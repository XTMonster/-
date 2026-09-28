"""镜头审核器协议（执行文档 v1.2 §7.1 阶段 B3 / §11.1）。

驱动器不 import bpy：它只依赖这个协议；bpy 实现在
``layer3_engine/shot_auditor.py``（跑轴线 / 构图 / 可见性）。
没有审核器时用 :class:`NullAuditor`，离线路径视为全部通过。
"""

from __future__ import annotations

from typing import List, Protocol, runtime_checkable

from ..contracts.audit import AuditResult


@runtime_checkable
class ShotAuditor(Protocol):
    """逐镜头审核。返回结构化结果供定向修复使用（§18.3）。"""

    def shot_ids(self) -> List[str]:
        ...

    def audit(self, shot_id: str) -> AuditResult:
        ...


class NullAuditor:
    """没有审核能力时的替身：不产出任何镜头，因此跳过整个校验阶段。"""

    def shot_ids(self) -> List[str]:
        return []

    def audit(self, shot_id: str) -> AuditResult:
        return AuditResult(passed=True, target=shot_id)
