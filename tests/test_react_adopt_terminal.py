"""U10「过分数采用」的驱动级闭环：score > 80 即 adopt 并立即收尾。

final9 实测缺陷：shot_002 v5=80.7 adopt 后被 Level 2 自我审核 reopen
（"未表达意图"），随后 v6=79.5 revert、3 轮无新高被记 failed——违反
"过分数采用"。本测试钉住：adopt 后直接 terminal=passed 并前进，自我
审核不得把它重新打开。
"""

from __future__ import annotations

import json

from block_director.contracts.audit import AuditError, AuditResult
from block_director.contracts.config import AppConfig
from block_director.contracts.enums import Purpose, Severity
from block_director.contracts.messages import ChatReply, FunctionCall, ToolCall
from block_director.layer5_orchestrator.driver import DriverLimits, PrevisDriver
from block_director.layer5_orchestrator.planner import PLAN_TOOL_NAME
from block_director.layer5_orchestrator.states import DriverState
from block_director.layer6_audit.audit_logger import AuditLogger

from test_backtrack_no_stop_on_fail import (
    InlineThread,
    ScriptedTransport,
    StubBuilder,
)


class AdoptAuditor:
    """shot_001：首审 55（fail）→ 修复后仍 55（fail，进入 B5 基线）→
    再审核 80.7（passed，过线 adopt）；shot_002 通过。"""

    def __init__(self):
        self.audited = []
        self._shot_001_audits = 0

    def shot_ids(self):
        return ["shot_001", "shot_002"]

    def audit(self, shot_id):
        if shot_id == "shot_001":
            self._shot_001_audits += 1
            self.audited.append(shot_id)
            if self._shot_001_audits < 3:
                return AuditResult(
                    passed=False, target=shot_id, score=55.0,
                    errors=[AuditError(
                        rule="COMPOSITION", code="E_CAM_001",
                        message="构图评分 55 低于阈值",
                        severity=Severity.ERROR, target=shot_id,
                        suggestion="回溯到最高分版本")])
            return AuditResult(passed=True, target=shot_id, score=80.7)
        self.audited.append(shot_id)
        return AuditResult(passed=True, target=shot_id, score=88.0)


PLAN_REPLY = (PLAN_TOOL_NAME, {"shots": [
    {"shot_id": "shot_001", "order": 1, "intent": "x", "shot_type": "MS",
     "duration_frames": 24},
    {"shot_id": "shot_002", "order": 2, "intent": "y", "shot_type": "CU",
     "duration_frames": 24}]})


def _make_driver():
    config = AppConfig()
    config.orchestration.react_max_steps = 6
    config.orchestration.react_max_rounds = 4
    config.orchestration.context_window_tokens = 32000
    config.orchestration.self_review = True      # 开自我审核，验证它不再 reopen
    transport = ScriptedTransport([
        PLAN_REPLY,
        ("setup_camera", {"shot_id": "shot_001", "shot_type": "MCU"}),  # B4
        None,                                                          # ReAct
    ])
    driver = PrevisDriver(
        transport=transport, audit=AuditLogger(), script="INT. 咖啡馆 - 日\n\n"
        "小明坐下。\n",
        config=config, builder=StubBuilder(), auditor=AdoptAuditor(),
        limits=DriverLimits(max_repairs_per_shot=1),
        thread_factory=InlineThread)
    return driver, transport


def test_adopt_score_marks_passed_and_does_not_reopen():
    driver, transport = _make_driver()
    state = driver.run_to_completion()
    assert state is DriverState.DONE, f"不应停止：{state}"
    snapshot = driver.snapshot()
    terminal = snapshot["terminal_shots"]
    assert terminal.get("shot_001") == "passed", terminal
    assert terminal.get("shot_002") in ("passed", "finished"), terminal
    # 过线采用立即收尾：Level 2 自我审核不再把它重新打开
    purposes = [p.purpose for p in transport.payloads
                if getattr(p, "purpose", None) is not None]
    assert Purpose.REVIEW not in purposes, purposes
    assert driver.review_history == []
    trail = driver._react_scores.get("shot_001", [])
    dispositions = [item["disposition"] for item in trail]
    # B5 进入时记 v1 基线（new_high），过线版 v2 adopt
    assert dispositions == ["new_high", "adopt"], dispositions
    kinds = [e.kind for e in driver.audit.recent()]
    assert "react_adopted_terminal" in kinds, kinds
