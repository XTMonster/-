"""v1.6 A3（D-15）：R015 声明景别无破例辩护时从 warning 升为 error。"""

from __future__ import annotations

from pathlib import Path

import pytest

from block_director.contracts.enums import Severity
from block_director.contracts.plan import Plan
from block_director.layer1_input import parse_script
from block_director.layer5_orchestrator.compliance import check_compliance

ROOT = Path(__file__).resolve().parents[1]
MARKET = ROOT / "fixtures" / "shotlist_market.md"


def _faithful_plan(script):
    """按声明造一份完全落实的计划，只在第一条改景别。"""
    shots = []
    for index, item in enumerate(script.declared_shots, start=1):
        shots.append({
            "shot_id": f"shot_{index:03d}", "order": index,
            "intent": item.field("作用") or "落实分镜表",
            "shot_type": item.shot_type or "MS",
            "duration_frames": 120,
            "characters": list(item.characters),
            "dialogues": []})
    return Plan.from_dict({"shots": shots})


def test_shot_type_without_justification_is_error():
    script = parse_script(MARKET)
    plan = _faithful_plan(script).to_dict()
    plan["shots"][0]["shot_type"] = "LS"  # 声明是 MCU
    findings = check_compliance(Plan.from_dict(plan), script)
    type_findings = [item for item in findings
                     if item.rule == "R015" and "拍摄距离" in item.message]
    assert len(type_findings) == 1
    assert type_findings[0].severity == Severity.ERROR


def test_shot_type_with_break_justification_stays_warning():
    script = parse_script(MARKET)
    plan = _faithful_plan(script).to_dict()
    plan["shots"][0]["shot_type"] = "LS"
    plan["shots"][0]["rule_justifications"] = [
        {"rule": "R015", "action": "break", "reason": "需要交代环境",
         "precedet": ""}]
    findings = check_compliance(Plan.from_dict(plan), script)
    type_findings = [item for item in findings
                     if item.rule == "R015" and "拍摄距离" in item.message]
    assert len(type_findings) == 1
    assert type_findings[0].severity == Severity.WARNING


def test_shot_type_with_reasonless_break_is_error():
    """旧数据里的无理由破例不满足合法豁免条件。"""
    script = parse_script(MARKET)
    plan = _faithful_plan(script).to_dict()
    plan["shots"][0]["shot_type"] = "LS"
    plan["shots"][0]["rule_justifications"] = [
        {"rule": "R015", "action": "break"}]
    findings = check_compliance(Plan.from_dict(plan), script)
    type_findings = [item for item in findings
                     if item.rule == "R015" and "拍摄距离" in item.message]
    assert len(type_findings) == 1
    assert type_findings[0].severity == Severity.ERROR


def test_other_rule_justifications_do_not_satisfy_r015():
    """只有 rule="R015" + action="break" 才算有效破例。"""
    script = parse_script(MARKET)
    plan = _faithful_plan(script).to_dict()
    plan["shots"][0]["shot_type"] = "LS"
    plan["shots"][0]["rule_justifications"] = [
        {"rule": "R001", "action": "break", "reason": "越轴有桥接",
         "precedet": ""}]
    findings = check_compliance(Plan.from_dict(plan), script)
    type_findings = [item for item in findings
                     if item.rule == "R015" and "拍摄距离" in item.message]
    assert len(type_findings) == 1
    assert type_findings[0].severity == Severity.ERROR
