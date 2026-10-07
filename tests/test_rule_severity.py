"""v1.4 X12 / S10：规则严重度档位表与预算降级分支。

§3.4 的档位表只约束**新增**判定：R016（新编台词）在 strict 下升 ERROR；
既有的"数量不符/时长不符"本来就是 ERROR，不得借此下调。
"""

from __future__ import annotations

from pathlib import Path

from block_director.contracts.enums import AuditLevel, Severity
from block_director.layer1_input import parse_script
from block_director.layer5_orchestrator.compliance import check_compliance

ROOT = Path(__file__).resolve().parents[1]
MARKET = ROOT / "fixtures" / "shotlist_market.md"


def _plan_with_extra_dialogue():
    script = parse_script(MARKET)
    shots = []
    for index, item in enumerate(script.declared_shots, start=1):
        dialogues = [{"character_id": item.characters[0] if item.characters else "",
                      "text": dialogue.text, "start_frame": 0, "end_frame": 0}
                     for dialogue in item.dialogues]
        shots.append({"shot_id": f"shot_{index:03d}", "order": index,
                      "intent": "推进", "shot_type": item.shot_type or "MS",
                      "duration_frames": int(round((item.declared_seconds or 4)
                                                   * 24)),
                      "characters": list(item.characters),
                      "dialogues": dialogues})
    # 第 3 镜里塞一句剧本没有的台词。
    shots[2]["dialogues"].append({"character_id": "x", "text": "这句是编的。",
                                  "start_frame": 0, "end_frame": 0})
    from block_director.contracts.plan import Plan

    return script, Plan.from_dict({"shots": shots})


def _r016(findings):
    return [item for item in findings if item.rule == "R016"
            and "剧本没有的台词" in item.message]


def test_new_dialogue_is_a_warning_by_default():
    script, plan = _plan_with_extra_dialogue()
    findings = check_compliance(plan, script, audit_level=AuditLevel.STANDARD)
    assert [item.severity for item in _r016(findings)] == [Severity.WARNING]


def test_new_dialogue_is_an_error_in_strict_mode():
    script, plan = _plan_with_extra_dialogue()
    findings = check_compliance(plan, script, audit_level=AuditLevel.STRICT)
    assert [item.severity for item in _r016(findings)] == [Severity.ERROR]


def test_shot_type_mismatch_is_an_error_without_justification():
    """v1.6 A3：无破例辩护时，声明景别被改写按 ERROR 处理（与 strict 无关）。"""
    from block_director.contracts.plan import Plan

    script = parse_script(MARKET)
    shots = []
    for index, item in enumerate(script.declared_shots, start=1):
        shots.append({"shot_id": f"shot_{index:03d}", "order": index,
                      "intent": "推进",
                      "shot_type": "ELS" if item.shot_type else "MS",
                      "duration_frames": int(round((item.declared_seconds or 4)
                                                   * 24)),
                      "characters": list(item.characters)})
    findings = check_compliance(Plan.from_dict({"shots": shots}), script,
                                audit_level=AuditLevel.STRICT)
    shot_type = [item for item in findings if "拍摄距离" in item.message]
    assert shot_type and all(item.severity is Severity.ERROR
                             for item in shot_type)


def test_shot_type_mismatch_stays_a_warning_with_break_justification():
    """v1.6 A3：有显式破例辩护时，景别改写保持 WARNING。"""
    from block_director.contracts.plan import Plan

    script = parse_script(MARKET)
    shots = []
    for index, item in enumerate(script.declared_shots, start=1):
        shots.append({"shot_id": f"shot_{index:03d}", "order": index,
                      "intent": "推进",
                      "shot_type": "ELS" if item.shot_type else "MS",
                      "duration_frames": int(round((item.declared_seconds or 4)
                                                   * 24)),
                      "characters": list(item.characters),
                      "rule_justifications": [
                          {"rule": "R015", "action": "break",
                           "reason": "需要交代环境", "precedet": ""}]})
    findings = check_compliance(Plan.from_dict({"shots": shots}), script,
                                audit_level=AuditLevel.STRICT)
    shot_type = [item for item in findings if "拍摄距离" in item.message]
    assert shot_type and all(item.severity is Severity.WARNING
                             for item in shot_type)


def test_budget_degrade_branch_is_documented_not_a_success():
    """S10：``_degrade_to_finish`` 的终态是 DONE 但带 degraded_reason。"""
    from test_driver import InlineThread
    from test_driver_builder import RecordingBuilder, SCRIPT
    from test_driver_repair import RepairingTransport, _registry

    from block_director.contracts.config import AppConfig
    from block_director.layer5_orchestrator.budget import Budget, BudgetLimits
    from block_director.layer5_orchestrator.driver import PrevisDriver
    from block_director.layer6_audit.audit_logger import AuditLogger

    driver = PrevisDriver(
        transport=RepairingTransport(), audit=AuditLogger(), script=SCRIPT,
        registry=_registry(), builder=RecordingBuilder(),
        thread_factory=InlineThread, config=AppConfig(),
        budget=Budget(BudgetLimits(max_llm_calls=1, max_tokens=0,
                                   max_cost_usd=0, max_wall_seconds=0)))
    driver.run_to_completion()
    assert driver.degraded_reason
    kinds = [event.kind for event in driver.audit.recent()]
    assert "budget_exhausted" in kinds
    # 降级收尾**不是**成功：快照里必须带着原因。
    assert driver.snapshot()["degraded_reason"] == driver.degraded_reason
