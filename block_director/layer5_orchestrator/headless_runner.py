"""headless 同步驱动（执行文档 v1.2 §2.4 形态 C）。

Modal Operator 在 ``--background`` 下不可用（无 window），因此批处理路径
直接同步驱动同一个 :class:`PrevisDriver`。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from ..layer6_audit.audit_logger import AuditLogger
from ..settings import get_config
from ..utils.logger import get_logger
from ..utils.paths import default_project_root, ensure_dir
from .driver import DriverLimits, PrevisDriver
from .states import DriverState
from .transport_factory import make_transport

log = get_logger("headless")


def run_headless(
    script: str = "",
    *,
    offline: bool = True,
    project_dir: Optional[Path] = None,
    config=None,
    poll_interval: float = 0.02,
    max_wall_s: float = 180.0,
    limits: Optional[DriverLimits] = None,
    audit: Optional[AuditLogger] = None,
    builder=None,
    registry=None,
    auditor=None,
    scene_state_provider=None,
    human_gate=None,
) -> Dict[str, Any]:
    """把状态机跑到终止，返回结果摘要（含审计日志路径）。"""
    config = config or get_config()
    transport, mode = make_transport(config, offline=offline)

    if audit is None:
        root = Path(project_dir) if project_dir else default_project_root()
        audit = AuditLogger(directory=ensure_dir(root / "runs"))
    driver = PrevisDriver(transport=transport, audit=audit, script=script,
                          config=config, limits=limits, builder=builder,
                          registry=registry, auditor=auditor,
                          scene_state_provider=scene_state_provider,
                          human_gate=human_gate)

    log.info("headless 运行开始（模式=%s，run_id=%s）", mode, audit.run_id)
    state = driver.run_to_completion(poll_interval=poll_interval,
                                     max_wall_s=max_wall_s)
    summary = driver.snapshot()
    summary["mode"] = mode
    summary["success"] = state is DriverState.DONE
    summary["audit_log"] = str(audit.audit_path) if audit.audit_path else None
    summary["llm_trace"] = str(audit.trace_path) if audit.trace_path else None
    # 分镜计划是值得持久化的产物，直接带回完整结构（交付层要用）
    summary["plan"] = driver.plan.to_dict() if driver.plan else None
    log.info("headless 运行结束：%s（镜头 %s 个）", state.value, summary["shots"])
    return summary
