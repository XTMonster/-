"""驱动器状态（执行文档 v1.2 §3.3）。"""

from __future__ import annotations

from ..contracts.enums import StrEnum


class DriverState(StrEnum):
    IDLE = "IDLE"
    PLANNING = "PLANNING"            # 阶段 A：剧本 → 分镜计划
    CALLING_LLM = "CALLING_LLM"      # 等待后台线程的 LLM 结果
    EXECUTING_TOOL = "EXECUTING_TOOL"  # 执行 LLM 请求的工具调用
    BUILDING = "BUILDING"            # 把分镜计划落成场景（§7.1 阶段 B2）
    CHECKING = "CHECKING"            # 规则/构图校验（Phase 5）
    REPAIRING = "REPAIRING"          # 定向修复（Phase 4）
    FINISHING = "FINISHING"          # 收尾写盘
    DONE = "DONE"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"


TERMINAL_STATES = frozenset({DriverState.DONE, DriverState.ERROR,
                             DriverState.CANCELLED})
