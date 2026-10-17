"""驱动器状态（执行文档 v1.2 §3.3）。"""

from __future__ import annotations

from ..contracts.enums import StrEnum


class DriverState(StrEnum):
    IDLE = "IDLE"
    UNDERSTANDING = "UNDERSTANDING"  # 阶段 S：剧本理解（v1.3 §3.2）
    #: v1.7 §9（卡 E1）：剧本优化。默认关，仅 script_polish.enabled 且
    #: 有 builder 时才进入（见 driver._polish_gate）。
    POLISHING = "POLISHING"
    PLANNING = "PLANNING"            # 阶段 A：剧本 → 分镜计划
    CALLING_LLM = "CALLING_LLM"      # 等待后台线程的 LLM 结果
    EXECUTING_TOOL = "EXECUTING_TOOL"  # 执行 LLM 请求的工具调用
    BUILDING = "BUILDING"            # 把分镜计划落成场景（§7.1 阶段 B2）
    EDITING = "EDITING"              # 阶段 B1：逐镜结构化生成（§7.1）
    PREPARE_SCENE = "PREPARE_SCENE"  # 方案 B：只建场景与元素（§3.6.3）
    PER_SHOT = "PER_SHOT"            # 方案 B：逐镜预演循环（§3.6.3）
    AWAIT_HUMAN = "AWAIT_HUMAN"      # 等待人工审批（§11.1 Level 3，非阻塞）
    REVIEWING = "REVIEWING"          # Level 2 自我审核（§11.1，独立回合）
    CHECKING = "CHECKING"            # 规则/构图校验（Phase 5）
    REPAIRING = "REPAIRING"          # 定向修复（Phase 4）
    FINISHING = "FINISHING"          # 收尾写盘
    DONE = "DONE"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"


TERMINAL_STATES = frozenset({DriverState.DONE, DriverState.ERROR,
                             DriverState.CANCELLED})
