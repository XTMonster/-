"""工具名与"控制类工具"名单的单一真源（v1.3 P0-13）。

v1.2 把这份名单拆成两处各自维护：

- ``layer5_orchestrator/control_tools.py`` 的 ``CONTROL_TOOL_NAMES``
  （本模块**注册**的三个控制工具）；
- ``layer9_persistence/replay.py`` 的 ``CONTROL_TOOLS``
  （重放时**跳过**的工具，另外还包括 ``emit_plan``）。

两者含义不同（"注册了哪些" vs "重放时跳过哪些"），但必须口径一致：
新增一个控制类工具时只改一处，另一处就会把它当成普通场景工具去重放。
放在 contracts 是因为工具名本身属于 §7.4 / §16 的线协议约定。
"""

from __future__ import annotations

from typing import Tuple

#: 各阶段的工具名（与 §7.2 / §7.1 的 schema 一一对应）
PLAN_TOOL = "emit_plan"
SHOT_DRAFT_TOOL = "emit_shot_draft"
REVIEW_TOOL = "submit_review"

#: §7.4 的控制类工具：它们不改场景，只操纵这次运行
REQUEST_SELF_REVIEW = "request_self_review"
FINISH_SHOT = "finish_shot"
ABORT = "abort"

#: ``control_tools`` 模块负责注册的那三个
CONTROL_TOOL_NAMES: Tuple[str, ...] = (
    REQUEST_SELF_REVIEW, FINISH_SHOT, ABORT)

#: 重放时应当跳过的工具：控制类 + 计划提交（计划由 plan_received 事件还原）
REPLAY_SKIPPED_TOOLS = frozenset({PLAN_TOOL, *CONTROL_TOOL_NAMES})
