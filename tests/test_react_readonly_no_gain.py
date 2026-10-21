"""R2 ticket 05（F2）：ReAct 只读轮计入 no_gain。

R2 ticket 10 修复后（2026-10-19）：只读连续计数与回溯"连续无新高"解耦。
``_record_react_tool_progress`` 只维护 ``_react_readonly_rounds``（诊断），
终态计数由 ``_record_react_score`` 的审核裁定负责（tie/revert +1，
adopt/new_high 归零）——只读轮以"场景未变"收场，审核必然打平，自然计入
"无新高"，同镜空转仍然会在 3 轮后触发 ``react_terminal_fail``。
"""

from __future__ import annotations

from block_director.contracts.messages import FunctionCall, ToolCall
from block_director.layer5_orchestrator.driver import PrevisDriver
from block_director.layer6_audit.audit_logger import AuditLogger


def _driver():
    return PrevisDriver(transport=None, audit=AuditLogger(), script="")


def _call(name):
    return ToolCall(id="t", function=FunctionCall(name=name, arguments="{}"))


def test_read_only_round_increments_readonly_streak_and_audits():
    driver = _driver()
    driver._react_shot = "shot_001"
    driver._record_react_tool_progress([_call("get_scene_state")])
    assert driver._react_readonly_rounds["shot_001"] == 1
    assert any(e.kind == "repair_no_progress"
               for e in driver.audit.recent())


def test_mixed_round_resets_readonly_streak_but_not_score_counter():
    driver = _driver()
    driver._react_shot = "shot_001"
    driver._react_readonly_rounds["shot_001"] = 2
    driver._react_no_gain["shot_001"] = 2
    driver._record_react_tool_progress([
        _call("get_scene_state"), _call("setup_camera")])
    assert driver._react_readonly_rounds["shot_001"] == 0
    #: 修改类工具轮只打断只读连续，不得抹掉审核侧累计的"无新高"计数。
    assert driver._react_no_gain["shot_001"] == 2
    assert not any(e.kind == "repair_no_progress"
                   for e in driver.audit.recent())


def test_three_read_only_steps_tracked_as_streak():
    driver = _driver()
    driver._react_shot = "shot_001"
    for _ in range(3):
        driver._record_react_tool_progress([_call("get_scene_state")])
    assert driver._react_readonly_rounds["shot_001"] == 3
    assert len([e for e in driver.audit.recent()
                if e.kind == "repair_no_progress"]) == 3
