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

#: 各阶段的工具**名单**。v1.5 从 `layer3_engine/tool_bindings.py` 搬来这里，
#: 因为它要同时被两侧消费：bpy 侧注册工具、驱动器（**不许 import bpy**）判断
#: "这一轮到底动没动手"。
QUERY_TOOLS: Tuple[str, ...] = (
    "get_scene_state", "check_visibility", "check_composition",
    "check_axis", "estimate_shot_duration",
)
ACTION_TOOLS: Tuple[str, ...] = (
    "place_character", "move_character", "character_action",
    "look_at", "face_character", "interact_with", "setup_camera",
    "move_camera", "reframe",
)
REVERT_SHOT = "revert_shot"
KNOWLEDGE_TOOL_NAMES: Tuple[str, ...] = ("search_knowledge",)

#: **只读**：调了它们什么都不会变，因此**不算"已实施修复"**。
#:
#: 实测代价（2026-10-03 的 64 镜真跑）：模型在修复回合只调 `get_scene_state` 与
#: `check_composition`，而 `repair_applied` 照写"shot_001 已实施定向修复
#: （COMPOSITION/R003）"——一份**假记录**。根因是驱动器把"任何成功的工具调用"
#: 都算成动手了（`_repair_tools_ok += 1` 只排除了 `emit_plan`）。
READ_ONLY_TOOLS: frozenset = frozenset(
    {*QUERY_TOOLS, *KNOWLEDGE_TOOL_NAMES})

#: **会改动场景或计划**：只有它们能让"修复"名实相符。
MUTATING_TOOLS: frozenset = frozenset(
    {*ACTION_TOOLS, SHOT_DRAFT_TOOL, REVERT_SHOT})
