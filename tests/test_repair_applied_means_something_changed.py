"""`repair_applied` 只能记在**真的动过手**的回合上（v1.5）。

现场（2026-10-03 的 64 镜真跑，`docs/evidence/20261003_chunked_long4/`）：
模型在修复回合只调了 `get_scene_state` 与 `check_composition`（**只读**），
而审计照写

    shot_001 已实施定向修复（COMPOSITION/R003）

——一份**假记录**。根因在驱动器：`_repair_tools_ok += 1` 的判据是"任何成功的
工具调用（除了 emit_plan）"。"修过没修过"是 `repair_applied` / `before_score` /
`after_score` 那一整套证据的第一格，它必须与"真的改动了场景或计划"同义。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.contracts.tools import (  # noqa: E402
    ACTION_TOOLS,
    KNOWLEDGE_TOOL_NAMES,
    MUTATING_TOOLS,
    QUERY_TOOLS,
    SHOT_DRAFT_TOOL,
    READ_ONLY_TOOLS,
)


def test_the_two_classes_are_disjoint_and_cover_the_registered_names():
    assert MUTATING_TOOLS & READ_ONLY_TOOLS == frozenset()
    assert MUTATING_TOOLS >= set(ACTION_TOOLS) | {SHOT_DRAFT_TOOL}
    assert READ_ONLY_TOOLS >= set(QUERY_TOOLS) | set(KNOWLEDGE_TOOL_NAMES)
    #: 反面对照：只读工具**不许**混进"动手"那一类（这正是那次假记录的入口）。
    assert "get_scene_state" not in MUTATING_TOOLS
    assert "check_composition" not in MUTATING_TOOLS


def test_the_bpy_side_reads_the_same_lists():
    """注册用的名单必须**引用** contracts，而不是各抄一份。"""
    source = (ROOT / "block_director" / "layer3_engine"
              / "tool_bindings.py").read_text(encoding="utf-8")
    assert "from ..contracts.tools import" in source
    assert "QUERY_TOOLS" in source and "ACTION_TOOLS" in source
    #: 手抄那三行不该再出现（"get_scene_state" 之类的字面量在名单里彻底消失）。
    assert '"get_scene_state", "check_visibility"' not in source
    assert '"place_character", "move_character", "character_action"' not in source


def test_a_read_only_round_is_not_recorded_as_applied(tmp_path):
    """端到端：修复回合只调只读工具 ⇒ **不许**写 `repair_applied`。"""
    from block_director.contracts.audit import AuditError, AuditResult  # noqa: PLC0415
    from block_director.contracts.messages import (  # noqa: PLC0415
        ChatReply,
        FunctionCall,
        ToolCall,
    )
    from block_director.layer5_orchestrator.driver import (  # noqa: PLC0415
        DriverLimits,
        PrevisDriver,
        default_registry,
    )
    from block_director.layer6_audit.audit_logger import AuditLogger  # noqa: PLC0415

    class _Auditor:
        composition_threshold = 70.0

        def audit(self, shot_id):
            return AuditResult(passed=False, level="rule",
                               errors=[AuditError(rule="R003",
                                                  message="动作时间重叠")],
                               score=55.8)

    class _Transport:
        """修复回合只回一个只读工具调用（正是真跑里模型的行为）。"""

        def chat(self, payload, timeout=10.0):
            call = ToolCall(id="c1", function=FunctionCall(
                name="get_scene_state", arguments="{}"))
            return ChatReply(content=None, tool_calls=[call],
                             request_id=getattr(payload, "request_id", "stub"),
                             model="stub",
                             finish_reason="tool_calls")

        def health(self, timeout=2.0):        # pragma: no cover
            raise AssertionError

    audit = AuditLogger(directory=tmp_path)
    driver = PrevisDriver(transport=_Transport(), audit=audit, script="",
                          limits=DriverLimits(), knowledge=None,
                          registry=default_registry(), auditor=_Auditor())
    driver._call_purpose = "repair"
    reply = _Transport().chat(None)
    driver._dispatch_tool_calls(reply, driver.repair_messages)
    assert driver._repair_tools_ok == 0, (
        "只读工具不算动手——否则 repair_applied 会写出一条假记录")


def test_a_repair_round_is_not_judged_by_the_plan_contract(tmp_path):
    """修复回合**不许**被判"没有收到 emit_plan"（2026-10-04 实测，long16 六十四镜）。

    现场：`_dispatch_tool_calls` 的收尾判据是 `if not plan_seen: return
    "没有收到 emit_plan 调用"`，**与阶段无关**；而修复回合在上面本来就拒绝
    `emit_plan`（"emit_plan 只在阶段 A 被接受"），于是**每一轮修复**都必然返回这条
    问题、被记成 `repair_invalid`。long16 的 104 条 `repair_invalid` 里 **89 条**
    是这条假问题（long15 是 39/96）——真错与假错混在同一个事件名里，"这一轮到底
    错没错"就判不出来了，而它正是我排查修复回路时唯一能依赖的信号。

    反面对照：**阶段 A** 的回合仍然必须拿到 `emit_plan`（判据一个字不改）。
    """
    from block_director.contracts.messages import (  # noqa: PLC0415
        ChatReply,
        FunctionCall,
        ToolCall,
    )
    from block_director.layer5_orchestrator.driver import (  # noqa: PLC0415
        DriverLimits,
        PrevisDriver,
        default_registry,
    )
    from block_director.layer6_audit.audit_logger import AuditLogger  # noqa: PLC0415

    #: 用 `default_registry()` 里真实存在、且**不是** emit_plan 的那个工具：
    #: 这一条要问的是"没有 emit_plan 的回合算不算错"，工具本身是就绪的。
    reply = ChatReply(content=None, tool_calls=[ToolCall(
        id="c1", function=FunctionCall(
            name="request_self_review",
            arguments='{"shot_id": "shot_001"}'))],
        request_id="stub", model="stub", finish_reason="tool_calls")

    def build(purpose: str):
        driver = PrevisDriver(transport=None, audit=AuditLogger(directory=tmp_path),
                              script="", limits=DriverLimits(), knowledge=None,
                              registry=default_registry())
        driver._call_purpose = purpose
        driver._current_shot_id = "shot_001"
        return driver._dispatch_tool_calls(reply, driver.repair_messages)

    problem = build("repair")
    assert "没有收到" not in problem, f"修复回合被计划契约误判：{problem!r}"
    assert problem == "", "只读查询在修复回合是**合法**动作（只是不算动手）"
    plan_problem = build("plan")
    assert "没有收到 emit_plan" in plan_problem, (
        "阶段 A 的判据不许被放宽——它正是计划契约本身")
