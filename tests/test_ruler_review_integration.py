"""空间尺转正接线测试：AuditResult / driver 硬门阻断 / 观测折档 / 重放。

钉住转正的四条接缝：
* ``AuditResult.ruler_review`` 零形状差（缺省不出键，设置后原样携带）；
* CHECKING 阶段旧 passed 之后查 H1–H6 硬门，命中即进修复回路；
* ``shot_audit`` 事件的 ``ruler_review`` 可被重放折档读回；
* 观测文档新增 ``ruler_reviews`` 段且过 committed schema 与纯层校验。
"""

from __future__ import annotations

from block_director.contracts.audit import AuditResult
from block_director.contracts.enums import Purpose
from block_director.layer5_orchestrator.states import DriverState

from test_driver_repair import FakeAuditor, RepairingTransport, _driver


def _review_dict(hard_gates=(), overview=50.0) -> dict:
    layers = {"geometry": 60.0, "attention": 70.0, "action": 40.0,
              "continuity": 0.0, "cinema": 55.0, "robustness": 65.0}
    return {
        "shot_id": "shot_001",
        "layer_scores": layers,
        "overview": overview,
        "hard_gates": list(hard_gates),
        "findings": [],
        "measurements": [],
        "prescriptions": [],
    }


# --------------------------------------------------------------------------- #
# 契约：AuditResult.ruler_review 零形状差
# --------------------------------------------------------------------------- #
def test_audit_result_ruler_review_default_absent():
    payload = AuditResult(passed=True, target="shot_001").to_dict()
    assert "ruler_review" not in payload


def test_audit_result_ruler_review_carried_when_set():
    review = _review_dict(hard_gates=("H2",))
    payload = AuditResult(passed=True, target="shot_001",
                          ruler_review=review).to_dict()
    assert payload["ruler_review"] == review
    assert payload["passed"] is True            # 硬门不参与 passed


# --------------------------------------------------------------------------- #
# driver：CHECKING 硬门阻断
# --------------------------------------------------------------------------- #
def test_hard_gate_blocks_passed_shot_into_repair():
    transport = RepairingTransport()
    auditor = FakeAuditor([
        AuditResult(passed=True, target="shot_001",
                    ruler_review=_review_dict(hard_gates=("H2",))),
        AuditResult(passed=True, target="shot_001"),
    ])
    driver = _driver(transport, auditor)
    assert driver.run_to_completion() is DriverState.DONE

    kinds = [e.kind for e in driver.audit.recent()]
    assert "ruler_gate_blocked" in kinds
    blocked = [e for e in driver.audit.recent()
               if e.kind == "ruler_gate_blocked"][0]
    assert blocked.data["hard_gates"] == ["H2"]
    assert Purpose.REPAIR in [p.purpose for p in transport.payloads]
    assert len(auditor.calls) == 2          # 一次阻断 → 修复 → 复测


def test_no_hard_gate_passed_shot_finishes_without_repair():
    transport = RepairingTransport()
    auditor = FakeAuditor([
        AuditResult(passed=True, target="shot_001",
                    ruler_review=_review_dict()),
    ])
    driver = _driver(transport, auditor)
    assert driver.run_to_completion() is DriverState.DONE
    kinds = [e.kind for e in driver.audit.recent()]
    assert "ruler_gate_blocked" not in kinds
    assert Purpose.REPAIR not in [p.purpose for p in transport.payloads]


# --------------------------------------------------------------------------- #
# 重放与观测折档
# --------------------------------------------------------------------------- #
def test_shot_audits_from_log_carries_ruler_review():
    from block_director.layer5_orchestrator.ruler_observation import (
        shot_audits_from_log)
    review = _review_dict(hard_gates=("H4",))
    records = [{
        "kind": "shot_audit",
        "data": {"shot": "shot_001", "passed": True,
                 "composition_score": 80.0, "ruler_review": review},
    }]
    audits = shot_audits_from_log(records)
    assert audits["shot_001"]["ruler_review"] == review


def test_observation_folds_ruler_reviews_and_validates():
    from block_director.layer5_orchestrator.ruler_observation import (
        build_observation, validate_observation)
    from tests.test_ruler_observation_build import (
        _audits, _build_results, _findings, _parsed, _plan)
    audits = _audits()
    audits["shot_001"]["ruler_review"] = _review_dict(
        hard_gates=("H1",))
    doc = build_observation(
        plan=_plan(), parsed=_parsed(), shot_audits=audits,
        build_results=_build_results(), fps=24,
        plan_findings=_findings())
    assert doc["ruler_reviews"]["shot_001"]["hard_gates"] == ["H1"]
    assert doc["ruler_reviews"]["shot_001"]["layer_scores"].keys() == {
        "geometry", "attention", "action", "continuity",
        "cinema", "robustness"}
    assert validate_observation(doc) == []


def test_observation_ruler_reviews_default_empty_when_none():
    from block_director.layer5_orchestrator.ruler_observation import (
        build_observation, validate_observation)
    from tests.test_ruler_observation_build import (
        _audits, _build_results, _findings, _parsed, _plan)
    doc = build_observation(
        plan=_plan(), parsed=_parsed(), shot_audits=_audits(),
        build_results=_build_results(), fps=24,
        plan_findings=_findings())
    assert doc["ruler_reviews"] == {}
    assert validate_observation(doc) == []


def test_attach_sequence_review_without_blender_keeps_doc_unchanged():
    """重放/无 bpy 路径：序列采样不可得时如实标缺，不重算、不伪造。"""
    from block_director.layer5_orchestrator.ruler_observation import (
        attach_sequence_review, build_observation)
    from tests.test_ruler_observation_build import (
        _audits, _build_results, _findings, _parsed, _plan)
    doc = build_observation(
        plan=_plan(), parsed=_parsed(), shot_audits=_audits(),
        build_results=_build_results(), fps=24,
        plan_findings=_findings())
    before = dict(doc["ruler_reviews"])
    out = attach_sequence_review(doc, plan=_plan(), fps=24)
    assert out["ruler_reviews"] == before      # scene 级不走伪造
