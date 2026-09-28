"""§11.1 Level 2 / §7.10：自我审核作为独立回合的行为测试。"""

from __future__ import annotations

import json

from block_director.contracts.audit import AuditResult
from block_director.contracts.config import AppConfig
from block_director.contracts.enums import Purpose
from block_director.contracts.messages import ChatReply, FunctionCall, ToolCall
from block_director.layer5_orchestrator.driver import DriverLimits, PrevisDriver
from block_director.layer5_orchestrator.states import DriverState
from block_director.layer6_audit.audit_logger import AuditLogger

from test_driver import InlineThread
from test_driver_builder import RecordingBuilder, SCRIPT
from test_driver_guards import _registry
from test_driver_repair import FakeAuditor, RepairingTransport


class ReviewTransport(RepairingTransport):
    """计划/修复照旧，审核回合回一个 submit_review 结论。"""

    def __init__(self, verdict: str = "ok", *, malformed: bool = False,
                 **kwargs) -> None:
        super().__init__(**kwargs)
        self.verdict = verdict
        self.malformed = malformed

    def chat(self, payload, timeout=120.0):
        if payload.purpose is not Purpose.REVIEW:
            return super().chat(payload, timeout)
        self.chat_calls += 1
        self.payloads.append(payload)
        if self.malformed:
            return ChatReply(content="我觉得还行", tool_calls=[])
        arguments = json.dumps({
            "verdict": self.verdict,
            "notes": "测试结论",
            "issues": (["机位没有表达孤立感"] if self.verdict == "needs_fix"
                       else []),
            "suggestion": "换更紧的景别，并把机位抬高",
        }, ensure_ascii=False)
        return ChatReply(tool_calls=[ToolCall(
            id=f"review_{self.chat_calls}",
            function=FunctionCall(name="submit_review", arguments=arguments))])


def _config(self_review: bool = True) -> AppConfig:
    config = AppConfig()
    config.orchestration.self_review = self_review
    config.audit.human_gate_on_plan = False       # 这里只测审核，不掺审批
    return config


def _driver(transport, auditor, config=None, **kwargs):
    return PrevisDriver(transport=transport, audit=AuditLogger(), script=SCRIPT,
                        registry=_registry(), builder=RecordingBuilder(),
                        thread_factory=InlineThread, config=config or _config(),
                        auditor=auditor, **kwargs)


def _purposes(transport):
    return [payload.purpose for payload in transport.payloads]


def test_review_passes_and_the_shot_advances():
    transport = ReviewTransport()
    driver = _driver(transport,
                     FakeAuditor([AuditResult(passed=True, target="shot_001")]))
    assert driver.run_to_completion() is DriverState.DONE
    assert Purpose.REVIEW in _purposes(transport)
    assert driver.review_history == [{"shot_id": "shot_001", "verdict": "ok",
                                      "notes": "测试结论"}]


def test_review_carries_the_shot_intent():
    transport = ReviewTransport()
    _driver(transport,
            FakeAuditor([AuditResult(passed=True, target="shot_001")])
            ).run_to_completion()
    payload = [p for p in transport.payloads if p.purpose is Purpose.REVIEW][0]
    system_text = payload.messages[0].content
    assert "建立场景与人物关系" in system_text      # 来自两镜夹具的意图
    assert "submit_review" in system_text
    assert payload.tool_choice.value == "required"


def test_review_needs_fix_goes_through_repair():
    transport = ReviewTransport(verdict="needs_fix")
    auditor = FakeAuditor([
        AuditResult(passed=True, target="shot_001"),       # 规则层先放行
        AuditResult(passed=True, target="shot_001"),       # 修复后复核仍通过
    ])
    driver = _driver(transport, auditor)
    assert driver.run_to_completion() is DriverState.DONE

    purposes = _purposes(transport)
    assert purposes.index(Purpose.REVIEW) < purposes.index(Purpose.REPAIR)
    assert driver.snapshot()["repairs"] == 1
    warnings = [e for e in driver.audit.recent() if e.kind == "self_review"
                and e.level == "warning"]
    assert warnings and "未表达意图" in warnings[0].message


def test_review_runs_once_per_shot():
    """修完之后不该再复核一遍，否则会绕圈。"""
    transport = ReviewTransport(verdict="needs_fix")
    auditor = FakeAuditor([AuditResult(passed=True, target="shot_001")] * 4)
    driver = _driver(transport, auditor)
    driver.run_to_completion()
    reviews = [p for p in transport.payloads if p.purpose is Purpose.REVIEW]
    assert len(reviews) == 1


def test_self_review_can_be_disabled():
    transport = ReviewTransport()
    driver = _driver(transport,
                     FakeAuditor([AuditResult(passed=True, target="shot_001")]),
                     config=_config(self_review=False))
    driver.run_to_completion()
    assert Purpose.REVIEW not in _purposes(transport)
    assert driver.review_history == []


def test_malformed_review_does_not_block_the_run():
    """规则层已经放行；审核回复不合规只记警告，不阻断。"""
    transport = ReviewTransport(malformed=True)
    driver = _driver(transport,
                     FakeAuditor([AuditResult(passed=True, target="shot_001")]))
    assert driver.run_to_completion() is DriverState.DONE
    kinds = [e.kind for e in driver.audit.recent()]
    assert "self_review_invalid" in kinds
