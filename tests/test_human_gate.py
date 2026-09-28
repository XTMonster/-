"""§11.1 人工审批门协议测试。"""

from __future__ import annotations

import pytest

from block_director.layer5_orchestrator.human_gate import (
    AutoGate,
    GateDecision,
    GateRequest,
    HumanGate,
)


def test_request_requires_a_known_kind():
    with pytest.raises(ValueError):
        GateRequest(kind="whatever", title="x")


def test_request_gets_a_unique_id():
    first = GateRequest(kind="plan", title="a")
    second = GateRequest(kind="plan", title="b")
    assert first.request_id and first.request_id != second.request_id


def test_auto_gate_defaults_to_skipped():
    gate = AutoGate()
    assert isinstance(gate, HumanGate)
    decision = gate.request(GateRequest(kind="plan", title="计划确认"))
    assert decision is GateDecision.SKIPPED
    assert gate.history[0]["kind"] == "plan"


def test_auto_gate_policy_can_reject_selected_kinds():
    gate = AutoGate(policy={"axis_violation": GateDecision.REJECTED},
                    default=GateDecision.SKIPPED)
    assert gate.request(GateRequest(kind="axis_violation", title="越轴")) \
        is GateDecision.REJECTED
    assert gate.request(GateRequest(kind="plan", title="计划")) \
        is GateDecision.SKIPPED
    assert len(gate.rejected) == 1
    assert gate.rejected[0]["kind"] == "axis_violation"


def test_auto_gate_never_stays_pending():
    gate = AutoGate()
    gate.request(GateRequest(kind="export", title="导出确认"))
    assert gate.poll("anything") is None
