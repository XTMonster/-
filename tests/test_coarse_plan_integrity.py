"""R2 空计划漏洞：粗排门前的计划完整性预检。

final5 实锤：剧本【角色锚】声明米迦尔/伊恩/偷盗者，模型计划 characters=[]
（或只有与角色无关的 prop 拍对象）时，粗排门因空镜豁免零修正放行，细排
构图 0.0。``plan_integrity_findings`` 用**确定性声明**（cast_declarations）
比对计划主体：声明角色非空而计划无主体 -> E_PLAN_NO_SUBJECT；有主体但
无一对应声明角色 -> E_PLAN_CAST_DROP；无声明角色 -> 不判（空镜剧本合法）。
"""

from __future__ import annotations

from block_director.contracts.plan import Plan, ShotPlan
from block_director.delivery.coarse_gate import (
    E_PLAN_CAST_DROP,
    E_PLAN_NO_SUBJECT,
    merge_integrity_decision,
    plan_integrity_findings,
)


class _Parsed:
    cast_declarations = ["米迦尔", "伊恩", "偷盗者"]


def _plan(shots):
    return Plan(shots=shots)


def _shot(shot_id="shot_001", characters=(), framing_target=None):
    return ShotPlan(
        shot_id=shot_id, intent="x", shot_type="MCU",
        duration_frames=96, characters=list(characters),
        framing_target=framing_target)


def test_empty_plan_with_declared_cast_is_no_subject():
    """声明 3 角色 + 计划全片无角色/拍对象 -> E_PLAN_NO_SUBJECT error。"""
    plan = _plan([
        _shot("shot_001"),
        _shot("shot_002"),
    ])
    findings = plan_integrity_findings(plan, _Parsed())
    assert len(findings) == 1
    assert findings[0]["check_id"] == E_PLAN_NO_SUBJECT
    assert findings[0]["severity"] == "error"
    assert "米迦尔" in findings[0]["message"]


def test_plan_with_unrelated_prop_subject_is_cast_drop():
    """计划有主体（金弹）但无一对应声明角色 -> E_PLAN_CAST_DROP error。"""
    plan = _plan([
        _shot("shot_002", framing_target={"kind": "prop", "ref": "金弹"}),
    ])
    findings = plan_integrity_findings(plan, _Parsed())
    assert len(findings) == 1
    assert findings[0]["check_id"] == E_PLAN_CAST_DROP
    assert findings[0]["severity"] == "error"
    assert "金弹" in findings[0]["message"]


def test_plan_with_declared_role_name_passes():
    """计划含角色锚同名角色 -> 无 finding。"""
    plan = _plan([
        _shot("shot_001", characters=["米迦尔"]),
        _shot("shot_002", characters=["伊恩"]),
    ])
    assert plan_integrity_findings(plan, _Parsed()) == []


def test_dict_plan_compatible():
    """计划以 dict 形状（resume/plan payload）传入同样判定。"""
    plan = {"shots": [{"shot_id": "shot_001", "characters": [],
                       "framing_target": None}]}
    findings = plan_integrity_findings(plan, _Parsed())
    assert findings and findings[0]["check_id"] == E_PLAN_NO_SUBJECT


def test_no_declared_cast_means_no_finding():
    """剧本没有角色锚声明 -> 空计划合法（空镜剧本不加戏）。"""
    class _EmptyParsed:
        cast_declarations = []

    plan = _plan([_shot("shot_001"), _shot("shot_002")])
    assert plan_integrity_findings(plan, _EmptyParsed()) == []


def test_merge_integrity_decision_forces_blocked():
    """预检 error findings 并入后 decision 必须 blocked 且带 reason/findings。"""
    findings = [{
        "check_id": E_PLAN_NO_SUBJECT, "severity": "error",
        "shot_id": "plan", "message": "剧本角色锚声明 3 个角色，计划全空",
    }]
    merged = merge_integrity_decision(
        {"ready": False, "blocked": True, "reason": "",
         "gates": {}, "artifacts": {}, "payload": {}},
        findings)
    assert merged["ready"] is False
    assert merged["blocked"] is True
    assert "计划未兑现剧本角色/主体声明" in merged["reason"]
    assert merged["payload"]["findings"] == findings
    assert merged["integrity"] == findings
