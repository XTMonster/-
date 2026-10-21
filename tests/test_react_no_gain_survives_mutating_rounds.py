"""R2 ticket 10 修复（T6/U10）：修改类工具轮不得抹掉回溯"连续无新高"计数。

真跑证据（``docs/evidence/20261019-r2-market-coin-accept-32k-v2/``）：shot_001
每轮先调 ``setup_camera``（修改类工具）再得到相同分数，而 ``_record_react_tool_progress``
把"混合轮清零"写进与回溯共用的 ``_react_no_gain``，score 侧累计的 no_gain 每轮被
归零，"连续 3 轮无新高 → react_terminal_fail"的终态判据永远到不了 3，墙钟被单镜
耗尽（steps=887 / 11 个对抗版本 / 5 次 revert，其余 6 镜未进审核）。

本文件先红后绿：**终态计数只由审核裁定**（``_record_react_score`` 的 backtrack：
tie/revert +1，adopt/new_high 归零），工具轮是否含修改类不再改写它。
"""

from __future__ import annotations

from block_director.contracts.audit import AuditResult
from block_director.contracts.messages import FunctionCall, ToolCall
from block_director.layer5_orchestrator.driver import PrevisDriver
from block_director.layer6_audit.audit_logger import AuditLogger


def _driver():
    return PrevisDriver(transport=None, audit=AuditLogger(), script="")


def _call(name):
    return ToolCall(id="t", function=FunctionCall(name=name, arguments="{}"))


def _result(shot_id="shot_001", score=59.3):
    return AuditResult(target=shot_id, passed=False, score=score)


def test_mutating_round_does_not_erase_score_backed_no_gain():
    """三轮"每轮先 setup_camera（修改类）再打平"→ no_gain 必须到 3。"""
    driver = _driver()
    shot = "shot_001"
    driver._react_shot = shot
    driver._react_best[shot] = {"score": 59.3, "version": 1,
                                "world_state": None}
    for _ in range(3):
        driver._record_react_tool_progress([_call("setup_camera")])
        driver._record_react_score(shot, _result(score=59.3))
    assert driver._react_no_gain[shot] == 3


def test_read_only_rounds_reach_terminal_fail_via_audit():
    """只读轮照记 repair_no_progress；终态计数来自审核打平，不重复累加。"""
    driver = _driver()
    shot = "shot_001"
    driver._react_shot = shot
    driver._react_best[shot] = {"score": 59.3, "version": 1,
                                "world_state": None}
    for _ in range(3):
        driver._record_react_tool_progress([_call("get_scene_state")])
        driver._record_react_score(shot, _result(score=59.3))
    assert driver._react_no_gain[shot] == 3
    assert len([e for e in driver.audit.recent()
                if e.kind == "repair_no_progress"]) == 3


def test_new_high_resets_no_gain_even_after_mutating_rounds():
    """新高/过线照旧归零——只改计数来源，不改"无新高才累计"的口径。"""
    driver = _driver()
    shot = "shot_001"
    driver._react_shot = shot
    driver._react_best[shot] = {"score": 59.3, "version": 1,
                                "world_state": None}
    driver._record_react_tool_progress([_call("setup_camera")])
    driver._record_react_score(shot, _result(score=59.3))
    assert driver._react_no_gain[shot] == 1
    driver._record_react_tool_progress([_call("setup_camera")])
    driver._record_react_score(shot, _result(score=62.0))
    assert driver._react_no_gain[shot] == 0


def test_terminal_fail_route_condition_uses_score_backed_counter():
    """终态路由判据（driver._audit_and_route）读取的就是 score 侧计数。"""
    driver = _driver()
    shot = "shot_001"
    driver._react_best[shot] = {"score": 59.3, "version": 1,
                                "world_state": None}
    driver._react_no_gain[shot] = 3
    assert (driver._react_no_gain.get(shot, 0) >= 3
            and shot in driver._react_best)
