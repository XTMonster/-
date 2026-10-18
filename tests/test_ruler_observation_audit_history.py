"""跨轮审核历史合并的回归测试（2026-10-18 贵妇跑导出中止）。

背景：``driver._ruler_observation_payload`` 按镜只保留**最后一轮**
``AuditResult``，而 ``_ruler_applied_prescriptions`` 跨轮累积——已执行
处方引用的测量（如 ``m_shot_001_thirds_deviation``）只存在于早轮，
最终轮不存在，结构校验把导出中止（``files=0``）。本文件钉住：

* ``merge_audit_history``：verdict 语义取最后一轮，guard 告警与测量取
  全轮并集（去重）；
* 合并后的 ``build_observation`` + ``validate_observation`` 恒过——处方
  引用闭合；
* ``shot_audits_from_log`` 对 ``ruler_measurements`` 同样取全轮并集。
"""

from __future__ import annotations

from block_director.contracts.plan import Plan, Responsibility, ShotPlan
from block_director.layer5_orchestrator.ruler_observation import (
    build_observation,
    merge_audit_history,
    shot_audits_from_log,
    validate_observation,
)

FPS = 24


def _plan() -> Plan:
    plan = Plan(scene_heading="码头市场")
    plan.shots = [
        ShotPlan("shot_001", "收束", "MS", 84, order=1,
                 characters=["贵妇", "伊恩", "偷盗者"],
                 responsibility=Responsibility(
                     white_model=["贵妇", "伊恩", "偷盗者"])),
    ]
    return plan


def _warning(shot_id: str, kind: str, evidence: dict) -> dict:
    return {
        "shot_id": shot_id, "frame_range": [541, 624], "type": kind,
        "subject": "贵妇", "evidence": evidence, "severity": "warning",
        "confidence": "high", "declared_intent": "",
        "suggestion_hint": "结构化修复提示",
    }


def _round1() -> dict:
    """早轮：有 thirds_deviation 告警 + 对应测量，构图未过。"""
    return {
        "target": "shot_001", "passed": False, "score": 64.7,
        "errors": [], "warnings": [],
        "guard_warnings": [_warning(
            "shot_001", "thirds_deviation",
            {"thirds_deviation": 0.21, "threshold": 0.10})],
        "ruler_measurements": [{
            "measurement_id": "m_shot_001_thirds_deviation",
            "shot_id": "shot_001", "transition_id": None,
            "subject_id": "贵妇", "frame": None, "metric": "thirds_deviation",
            "value": 0.21, "expected": 0.10, "unit": "ndc",
            "source": "blender_geometry", "provenance": "blender_geometry",
        }],
    }


def _round2() -> dict:
    """末轮：只剩 framing_too_loose，构图已过。"""
    return {
        "target": "shot_001", "passed": True, "score": 90.8,
        "errors": [], "warnings": [],
        "guard_warnings": [_warning(
            "shot_001", "framing_too_loose",
            {"body_height_ratio": 0.68,
             "expected_range": [0.7, 0.88]})],
        "ruler_measurements": [{
            "measurement_id": "m_shot_001_composition_score",
            "shot_id": "shot_001", "transition_id": None,
            "subject_id": None, "frame": None, "metric": "composition_score",
            "value": 90.8, "expected": 80.0, "unit": "score_0_100",
            "source": "blender_geometry", "provenance": "blender_geometry",
        }],
    }


def _applied_thirds_prescription() -> dict:
    return {
        "prescription_id": "p_shot_001_thirds_deviation",
        "shot_id": "shot_001", "operation": "reframe",
        "parameters": {"reason": "thirds_deviation",
                       "lens_before": 50.0, "lens_after": 36.0},
        "precondition_measurement_ids": ["m_shot_001_thirds_deviation"],
        "postcondition_measurement_ids": ["m_shot_001_composition_score"],
        "postcondition": "全镜 visible_ratio > 0 且 composition_score > 80",
        "applied": True, "applied_at": "runtime",
        "waived": False, "waive_reason": "",
    }


def test_merge_audit_history_keeps_final_verdict_and_unions_evidence():
    merged = merge_audit_history([_round1(), _round2()])
    entry = merged["shot_001"]
    # verdict 语义字段取最后一轮
    assert entry["passed"] is True
    assert entry["score"] == 90.8
    # guard 告警与测量取全轮并集
    kinds = {w["type"] for w in entry["guard_warnings"]}
    assert kinds == {"thirds_deviation", "framing_too_loose"}
    mids = {m["measurement_id"] for m in entry["ruler_measurements"]}
    assert {"m_shot_001_thirds_deviation",
            "m_shot_001_composition_score"} <= mids


def test_applied_prescription_refs_close_after_history_merge():
    """导出中止的回归：早轮处方引用的测量在合并后必须存在且校验闭合。"""
    merged = merge_audit_history([_round1(), _round2()])
    doc = build_observation(
        plan=_plan(), parsed=None, brief=None,
        shot_audits=merged,
        build_results={"shot_001": {"lens": 36.0}},
        fps=FPS, run_context={"source_run": "fixture", "status": "failed",
                              "shots": 1},
        observation_id="obs-audit-history",
        plan_findings=[],
        applied_prescriptions=[_applied_thirds_prescription()],
    )
    assert validate_observation(doc) == []


def test_shot_audits_from_log_unions_ruler_measurements():
    records = [
        {"kind": "shot_audit", "data": {
            "shot": "shot_001", "passed": False,
            "composition_score": 64.7, "findings": [],
            "ruler_measurements": _round1()["ruler_measurements"]}},
        {"kind": "shot_audit", "data": {
            "shot": "shot_001", "passed": True,
            "composition_score": 90.8, "findings": [],
            "ruler_measurements": _round2()["ruler_measurements"]}},
    ]
    audits = shot_audits_from_log(records)
    mids = {m["measurement_id"]
            for m in audits["shot_001"]["ruler_measurements"]}
    assert {"m_shot_001_thirds_deviation",
            "m_shot_001_composition_score"} <= mids
