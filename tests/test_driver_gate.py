"""§11.1 Level 3：人工审批门在驱动器里的行为测试。"""

from __future__ import annotations

from block_director.contracts.audit import AuditError, AuditResult
from block_director.contracts.config import AppConfig
from block_director.contracts.enums import Severity
from block_director.layer5_orchestrator.driver import DriverLimits, PrevisDriver
from block_director.layer5_orchestrator.human_gate import AutoGate, GateDecision
from block_director.layer5_orchestrator.states import DriverState
from block_director.layer6_audit.audit_logger import AuditLogger

from test_driver import InlineThread
from test_driver_builder import RecordingBuilder, SCRIPT
from test_driver_guards import _registry, _purposes
from test_driver_repair import FakeAuditor, RepairingTransport, axis_finding


class ScriptedGate:
    """先返回 PENDING，之后由 poll 给出结果——模拟"弹窗等用户点"。"""

    def __init__(self, request_decision: GateDecision, polls: list) -> None:
        self.request_decision = request_decision
        self._polls = list(polls)
        self.requests = []
        self.poll_count = 0

    def request(self, request):
        self.requests.append(request)
        return self.request_decision

    def poll(self, request_id):
        self.poll_count += 1
        return self._polls.pop(0) if self._polls else None


def _config(**audit_overrides) -> AppConfig:
    config = AppConfig()
    for key, value in audit_overrides.items():
        setattr(config.audit, key, value)
    return config


def _driver(transport, gate, *, config=None, auditor=None, **kwargs):
    return PrevisDriver(transport=transport, audit=AuditLogger(), script=SCRIPT,
                        registry=_registry(), builder=RecordingBuilder(),
                        thread_factory=InlineThread, config=config or _config(),
                        human_gate=gate,
                        auditor=auditor or FakeAuditor([AuditResult(passed=True,
                                                                    target="shot_001")]),
                        **kwargs)


# --------------------------------------------------------------------------- #
# 计划审批
# --------------------------------------------------------------------------- #
def test_without_a_gate_nothing_is_asked():
    """没有接人工门（headless 默认）时，任何审批都不该发生。"""
    driver = PrevisDriver(transport=RepairingTransport(), audit=AuditLogger(),
                          script=SCRIPT, registry=_registry(),
                          builder=RecordingBuilder(), auditor=None,
                          thread_factory=InlineThread)
    assert driver.run_to_completion() is DriverState.DONE
    assert driver.gate_history == []


def test_plan_gate_approval_lets_the_run_continue():
    gate = AutoGate(default=GateDecision.APPROVED)
    driver = _driver(RepairingTransport(), gate,
                     config=_config(human_gate_on_plan=True))
    assert driver.run_to_completion() is DriverState.DONE
    assert gate.history and gate.history[0]["kind"] == "plan"
    assert driver.gate_history[0]["decision"] == "approved"
    kinds = [e.kind for e in driver.audit.recent()]
    assert "gate_requested" in kinds and "gate_decided" in kinds


def test_plan_gate_rejection_cancels_the_run():
    gate = AutoGate(default=GateDecision.REJECTED)
    driver = _driver(RepairingTransport(), gate,
                     config=_config(human_gate_on_plan=True))
    assert driver.run_to_completion() is DriverState.CANCELLED
    assert "人工审批未通过" in driver.degraded_reason
    assert driver.snapshot()["built"] is False        # 被拒后没有建场景


def test_pending_gate_waits_without_blocking():
    gate = ScriptedGate(GateDecision.PENDING, [GateDecision.APPROVED])
    driver = _driver(RepairingTransport(), gate,
                     config=_config(human_gate_on_plan=True))

    assert driver.run_to_completion() is DriverState.DONE
    assert gate.poll_count >= 1
    assert driver.gate_history[0]["decision"] == "approved"
    assert driver.snapshot()["built"] is True


def test_gate_payload_describes_the_plan():
    gate = AutoGate(default=GateDecision.APPROVED)
    driver = _driver(RepairingTransport(), gate,
                     config=_config(human_gate_on_plan=True))
    driver.run_to_completion()
    request = gate.requests[0]
    assert "shot_001" in request.detail and "镜头" in request.detail
    assert request.payload["shots"] == 2


# --------------------------------------------------------------------------- #
# 越轴审批
# --------------------------------------------------------------------------- #
def test_axis_gate_fires_after_repairs_are_exhausted():
    failing = AuditResult.from_findings([axis_finding()], target="shot_001")
    gate = AutoGate(default=GateDecision.APPROVED)
    driver = _driver(RepairingTransport(), gate,
                     config=_config(human_gate_on_plan=False,
                                    human_gate_on_axis_violation=True),
                     auditor=FakeAuditor([failing] * 10),
                     limits=DriverLimits(max_repairs_per_shot=1))
    assert driver.run_to_completion() is DriverState.DONE
    kinds = [item["kind"] for item in driver.gate_history]
    assert "axis_violation" in kinds
    # 放行后该镜头被收下并前进，队列清空
    assert driver.snapshot()["shots_remaining"] == 0


def test_axis_gate_rejection_stops_the_run():
    failing = AuditResult.from_findings([axis_finding()], target="shot_001")
    gate = AutoGate(default=GateDecision.REJECTED)
    driver = _driver(RepairingTransport(), gate,
                     config=_config(human_gate_on_plan=False,
                                    human_gate_on_axis_violation=True),
                     auditor=FakeAuditor([failing] * 10),
                     limits=DriverLimits(max_repairs_per_shot=1))
    assert driver.run_to_completion() is DriverState.CANCELLED
    assert "越轴" in driver.degraded_reason


def test_non_axis_failure_does_not_ask_for_approval():
    """只有越轴才走人工门；普通构图问题按降级自动继续。"""
    loser = AuditResult.from_findings([
        AuditError(rule="COMPOSITION", message="构图评分 40 低于阈值",
                   severity=Severity.ERROR, target="shot_001")],
        target="shot_001")
    gate = AutoGate(default=GateDecision.APPROVED)
    driver = _driver(RepairingTransport(), gate,
                     config=_config(human_gate_on_plan=False,
                                    human_gate_on_axis_violation=True),
                     auditor=FakeAuditor([loser] * 10),
                     limits=DriverLimits(max_repairs_per_shot=1))
    assert driver.run_to_completion() is DriverState.DONE
    assert all(item["kind"] != "axis_violation" for item in driver.gate_history)
