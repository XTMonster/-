"""v1.6 B4 的驱动器接线：guard_warning 事件与 accept → guard_verdict 留痕。

卡 B4 红线两条：
* 审核失败时 ``AuditResult`` 携带 ``GuardWarning[]``（不只是分数）——
  这里验证它是一等字段、serde 往返、且缺省零形状差；
* ``accept`` 绝不静默——修复回复正文里的 ``ACCEPT <type> <reason>``
  必须逐条落成 ``guard_verdict`` 审计事件。
"""

from __future__ import annotations

import json

from block_director.contracts.audit import AuditResult
from block_director.contracts.guard import Confidence, GuardWarning, Severity
from block_director.contracts.messages import ChatReply, FunctionCall, ToolCall
from block_director.layer5_orchestrator.states import DriverState

from test_driver_repair import (
    FakeAuditor,
    RepairingTransport,
    _driver,
    axis_finding,
)


def _warning(warning_type="framing_too_tight", severity=Severity.ERROR):
    return GuardWarning(
        shot_id="shot_001", frame_range=(1, 48), type=warning_type,
        subject="char_001",
        evidence={"head_ratio": 0.82, "expected_range": [0.55, 0.75]},
        severity=severity, confidence=Confidence.HIGH,
        suggestion_hint="reframe（拉远距离或降焦段）")


# --------------------------------------------------------------------- serde


def test_audit_result_guard_fields_survive_json_round_trip():
    result = AuditResult(passed=False, target="shot_001",
                         guard_warnings=[_warning()],
                         guard_frames_sampled=25)
    payload = json.loads(json.dumps(result.to_dict(), ensure_ascii=False))
    assert payload["guard_frames_sampled"] == 25
    (warning,) = payload["guard_warnings"]
    assert warning["type"] == "framing_too_tight"
    assert warning["evidence"]["expected_range"] == [0.55, 0.75]


def test_audit_result_without_guard_run_keeps_legacy_shape():
    """缺省（guard 没跑）⇒ to_dict 与升级前逐字节一致（零形状差纪律）。"""
    payload = AuditResult(passed=True, target="shot_001").to_dict()
    assert "guard_warnings" not in payload
    assert "guard_frames_sampled" not in payload
    assert "guard_sampling_error" not in payload


def test_audit_result_sampling_error_is_serialized():
    result = AuditResult(
        passed=True, target="shot_001",
        guard_sampling_error={"code": "E_GUARD_001", "message": "没有相机"})
    payload = result.to_dict()
    assert payload["guard_sampling_error"]["code"] == "E_GUARD_001"


# ------------------------------------------------------------ guard_warning 事件


def test_audit_shot_emits_guard_warning_event_with_contract_keys():
    auditor = FakeAuditor([
        AuditResult(passed=True, target="shot_001",
                    guard_warnings=[_warning(severity=Severity.WARNING)],
                    guard_frames_sampled=25),
        AuditResult(passed=True, target="shot_002"),
    ], shots=("shot_001", "shot_002"))
    driver = _driver(RepairingTransport(), auditor)
    assert driver.run_to_completion() is DriverState.DONE

    events = [e for e in driver.audit.recent() if e.kind == "guard_warning"]
    assert len(events) == 1                     # 只在采样过的那一镜发
    data = events[0].data
    for key in ("shot_id", "warnings", "frames_sampled"):
        assert key in data, f"guard_warning 缺契约键 {key}"
    assert data["shot_id"] == "shot_001"
    assert data["frames_sampled"] == 25
    assert data["warnings"][0]["type"] == "framing_too_tight"


def test_audit_shot_without_guard_run_emits_no_guard_warning_event():
    auditor = FakeAuditor([AuditResult(passed=True, target="shot_001")])
    driver = _driver(RepairingTransport(), auditor)
    assert driver.run_to_completion() is DriverState.DONE
    assert not [e for e in driver.audit.recent() if e.kind == "guard_warning"]


# ------------------------------------------------------ accept → guard_verdict


class AcceptingTransport(RepairingTransport):
    """修复回复正文里带 accept 声明（工具调用照旧——修复仍然动手）。"""

    def __init__(self, accept_text, **kwargs):
        super().__init__(**kwargs)
        self._accept_text = accept_text

    def chat(self, payload, timeout=120.0):
        reply = super().chat(payload, timeout=timeout)
        if reply.tool_calls and reply.tool_calls[0].id.startswith("fix_"):
            reply = ChatReply(tool_calls=reply.tool_calls,
                              content=self._accept_text)
        return reply


def _run_accept(accept_text):
    auditor = FakeAuditor([
        AuditResult.from_findings([axis_finding()], target="shot_001"),
        AuditResult(passed=True, target="shot_001"),
    ])
    driver = _driver(AcceptingTransport(accept_text), auditor)
    assert driver.run_to_completion() is DriverState.DONE
    return driver


def test_accept_lines_become_guard_verdict_events():
    driver = _run_accept(
        "我检查了构图。\nACCEPT framing_too_tight 剧本刻意的情绪特写\n"
        "ACCEPT thirds_deviation 刻意偏心构图\n")
    verdicts = [e for e in driver.audit.recent() if e.kind == "guard_verdict"]
    assert len(verdicts) == 2
    first = verdicts[0].data
    for key in ("shot_id", "warning_type", "accepted", "reason", "fix_action"):
        assert key in first, f"guard_verdict 缺契约键 {key}"
    assert first["shot_id"] == "shot_001"
    assert first["warning_type"] == "framing_too_tight"
    assert first["accepted"] is True
    assert first["reason"] == "剧本刻意的情绪特写"
    assert first["fix_action"] == "accept"


def test_no_accept_lines_means_no_verdict_events():
    driver = _run_accept("我只是说明一下修复思路，没有刻意声明。")
    assert not [e for e in driver.audit.recent() if e.kind == "guard_verdict"]


def test_malformed_accept_line_is_repair_invalid_not_silent():
    driver = _run_accept("ACCEPT\n")
    kinds = [e.kind for e in driver.audit.recent()]
    assert "repair_invalid" in kinds
    assert "guard_verdict" not in kinds


def test_accepted_is_a_real_boolean_in_the_event():
    driver = _run_accept("ACCEPT headroom_off 顶格构图是设计\n")
    (event,) = [e for e in driver.audit.recent() if e.kind == "guard_verdict"]
    assert event.data["accepted"] is True
    json.dumps(event.data, ensure_ascii=False)      # 事件载荷必须可 JSON
