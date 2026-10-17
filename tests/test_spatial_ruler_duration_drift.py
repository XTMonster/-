"""Ticket 03：空间尺计划级逐镜时长漂移判据。

spec（``.scratch/spatial-ruler-json/spec.md``）SR002 的逐镜对拍：声明的
第 n 个镜号 ↔ 计划的第 n 个镜头，``declared_seconds`` 与
``duration_frames / fps`` 偏差超过 0.2s 记为 ERROR（hard finding），
与 R015 的逐镜对拍同容差、同顺序口径，但走空间尺的处方语义
（retime_shot，直接进 plugin audit）。
"""

from __future__ import annotations

from block_director.contracts.plan import Plan, ShotPlan
from block_director.layer5_orchestrator.spatial_ruler import (
    apply_plan_prescriptions,
    audit_and_prepare_plan,
)


class DeclaredShot:
    """ParsedShotDeclaration 的最小替身（只带空间尺消费的字段）。"""

    def __init__(self, shot_number: int, declared_seconds):
        self.shot_number = shot_number
        self.declared_seconds = declared_seconds


def _plan(planned_seconds) -> Plan:
    plan = Plan(scene_heading="码头")
    plan.shots = [
        ShotPlan(f"shot_{index + 1:03d}", "建立", "ELS", int(seconds * 24),
                 responsibility=None)
        for index, seconds in enumerate(planned_seconds)
    ]
    return plan


def test_per_shot_duration_drift_is_hard_finding() -> None:
    """声明 3.5s 的镜头被拉到 7s → SR002 ERROR（Ticket 03 验收第一项）。"""
    plan = _plan([5.0, 4.0, 7.0, 3.5])
    declared = [DeclaredShot(1, 5.0), DeclaredShot(2, 4.0),
                DeclaredShot(3, 3.5), DeclaredShot(4, 3.5)]
    _, findings = audit_and_prepare_plan(
        plan, declared_shots=declared, declared_total_seconds=16.0)
    drift = [item for item in findings
             if item.rule == "SR002" and "shot_003" in item.target]
    assert drift, "3.5s→7s 的逐镜漂移必须产生 SR002 finding"
    assert all(item.severity.value == "error" for item in drift)
    assert any("7" in item.message and "3.5" in item.message
               for item in drift)


def test_per_shot_duration_within_tolerance_is_silent() -> None:
    plan = _plan([5.0, 4.0, 3.5, 3.5])
    declared = [DeclaredShot(1, 5.0), DeclaredShot(2, 4.0),
                DeclaredShot(3, 3.5), DeclaredShot(4, 3.5)]
    _, findings = audit_and_prepare_plan(
        plan, declared_shots=declared, declared_total_seconds=16.0)
    assert not any("逐镜" in item.message for item in findings)


def test_no_declared_shots_keeps_old_behaviour() -> None:
    """不传 declared_shots 时逐镜判据恒空，既有调用（总时长/节奏）不受影响。"""
    plan = _plan([5.0, 7.0])
    _, findings = audit_and_prepare_plan(
        plan, declared_total_seconds=8.0)
    assert not any("逐镜" in item.message for item in findings)


def test_repairable_drift_gets_retimed_without_residual_finding() -> None:
    """可修复的逐镜漂移：retime_shot 处方落地，不留残余硬发现（03/05 协同）。"""
    plan = _plan([7.0, 4.0])
    plan, findings, prescriptions, measurements = apply_plan_prescriptions(
        plan, declared_total_seconds=None,
        declared_seconds_by_shot={"shot_001": 3.5, "shot_002": 4.0}, fps=24)
    assert plan.shots[0].duration_frames == 84          # 3.5s * 24
    retimes = [p for p in prescriptions
               if p["operation"] == "retime_shot"]
    assert len(retimes) == 1 and retimes[0]["applied"] is True
    assert not any("逐镜" in item.message for item in findings)


def test_unrepairable_drift_leaves_hard_finding() -> None:
    """对白装不下声明时长 → retime 未落地，残留 SR002 ERROR 硬发现（阻断输入）。"""
    plan = _plan([7.0, 4.0])
    plan.shots[0].dialogues = [
        {"speaker": "甲", "text": "很长的台词，声明时长根本放不下。",
         "start_frame": 1, "end_frame": 150},
    ]
    plan, findings, prescriptions, measurements = apply_plan_prescriptions(
        plan, declared_total_seconds=None,
        declared_seconds_by_shot={"shot_001": 3.5, "shot_002": 4.0}, fps=24)
    retimes = [p for p in prescriptions
               if p["operation"] == "retime_shot"]
    assert retimes and retimes[0]["applied"] is False
    assert plan.shots[0].duration_frames == 168         # 不改帧、不硬缩
    hard = [item for item in findings
            if item.rule == "SR002" and item.severity.value == "error"
            and "shot_001" in item.target]
    assert hard, "无法自动修复的逐镜漂移必须保留 SR002 ERROR 硬发现"
    assert "3.5" in hard[0].message and "7" in hard[0].message
