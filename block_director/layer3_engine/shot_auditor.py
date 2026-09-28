"""镜头审核器（执行文档 v1.2 §7.1 阶段 B3）。

把 :mod:`rule_checker` 包成驱动器需要的 ``ShotAuditor`` 协议。
"""

from __future__ import annotations

from typing import List

from ..contracts.audit import AuditResult
from ..utils.logger import get_logger
from ..utils.threading_guard import main_thread_only
from .rule_checker import check_shot
from .scene_context import get_context

log = get_logger("shot-auditor")


class BpyShotAuditor:
    """按当前场景上下文逐镜头审核。"""

    def __init__(self, composition_threshold: float = 70.0) -> None:
        self.composition_threshold = composition_threshold

    def shot_ids(self) -> List[str]:
        context = get_context()
        if context is None:
            return []
        if context.plan is not None:
            return [shot.shot_id for shot in context.plan.shots
                    if shot.shot_id in context.cameras]
        return sorted(context.cameras)

    @main_thread_only("BpyShotAuditor.audit")
    def audit(self, shot_id: str) -> AuditResult:
        return check_shot(shot_id, composition_threshold=self.composition_threshold)
