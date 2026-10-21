"""R2：粗排门失败后的计划级回溯重规划（U10 三态）。

真跑 20261020-market-real-final3：模型计划声明拍对象 prop/gold_coin，
但参考 JSON 里没有对应体块 -> 4 镜全 unresolved -> 粗排门 blocked ->
驱动直接 ``_fail`` 终止，白模视频不产出。本测试钉死修复：blocked 后
必须**回溯重规划**（带回粗排反馈回 PLANNING），高分保留、低分回溯、
门过采用；回溯预算耗尽才如实失败。

纯层测试 + 驱动级两条：
1. ``coarse_plan_backtrack`` 三态裁定；
2. bad 计划 -> blocked -> 重规划 -> good 计划 -> 门过 -> 采用放行；
3. 恒 blocked + 预算 1 次回溯 -> 2 次评估后如实 ERROR，留痕。
"""

from __future__ import annotations

import json
import pathlib

from block_director.contracts.audit import AuditResult
from block_director.contracts.backtrack import coarse_plan_backtrack
from block_director.contracts.enums import Purpose
from block_director.contracts.messages import ChatReply, FunctionCall, ToolCall
from block_director.contracts.plan import Plan
from block_director.layer5_orchestrator.driver import (
    DriverLimits, PrevisDriver)
from block_director.layer5_orchestrator.offline import demo_draft_dict
from block_director.layer5_orchestrator.states import DriverState
from block_director.layer6_audit.audit_logger import AuditLogger

from test_checkpoint_resume import _registry, FOUR_SHOT_PLAN, SCRIPT
from stage_helpers import is_understand, understand_reply


GOOD_TWO_SHOT_PLAN = {
    "scene_heading": "INT. 市场 - 日",
    "continuity_notes": ["回溯重规划对照计划"],
    "shots": [
        {"shot_id": "shot_001", "order": 1, "intent": "建立",
         "intent_type": "铺垫", "shot_type": "MS", "duration_frames": 48,
         "characters": ["char_001"], "dialogue_ids": [],
         "axis_note": "", "continuity_in": "", "prompt": ""},
        {"shot_id": "shot_002", "order": 2, "intent": "收束",
         "intent_type": "收束", "shot_type": "MCU", "duration_frames": 48,
         "characters": ["char_002"], "dialogue_ids": [],
         "axis_note": "", "continuity_in": "", "prompt": ""},
    ],
}


class _NoopAuditor:
    def shot_ids(self):
        return []

    def audit(self, shot_id):
        return AuditResult(passed=True, target=shot_id)


class _NoopBuilder:
    def build(self, plan, brief=None):
        return {"shots": len(plan.shots), "characters": 2, "cameras": 2,
                "motions": 0, "keyframes": 0,
                "total_frames": plan.total_frames, "warnings": [],
                "results": [
                    {"shot_id": shot.shot_id,
                     "start_frame": i * 24 + 1, "end_frame": (i + 1) * 24,
                     "camera": f"BD_Cam_{shot.shot_id}", "lens": 35}
                    for i, shot in enumerate(plan.shots)]}


class _BadThenGoodTransport:
    """先回 bad 计划（4 镜），再回 good 计划（2 镜）；后续不再调用。"""

    def __init__(self):
        self.chat_calls = 0
        self.plan_calls = 0
        self._editor_index = 0
        self.payloads = []

    def chat(self, payload, timeout=120.0):
        if is_understand(payload):
            return understand_reply(payload.request_id)
        if payload.purpose is Purpose.EDITOR:
            draft = demo_draft_dict(self._editor_index)
            self._editor_index += 1
            call = ToolCall(
                id=f"draft_{self._editor_index}",
                function=FunctionCall(
                    name="emit_shot_draft",
                    arguments=json.dumps(draft, ensure_ascii=False)))
            return ChatReply(
                tool_calls=[call], request_id=payload.request_id)
        self.chat_calls += 1
        self.payloads.append(payload)
        self.plan_calls += 1
        plan = (FOUR_SHOT_PLAN if self.plan_calls == 1
                else GOOD_TWO_SHOT_PLAN)
        call = ToolCall(
            id=f"plan_{self.plan_calls}",
            function=FunctionCall(name="emit_plan",
                                  arguments=json.dumps(plan)))
        return ChatReply(tool_calls=[call], request_id=payload.request_id)

    def cancel(self, request_id):
        return None


def _driver(transport, coarse_gate, limits=None, coarse_restore=None):
    return PrevisDriver(
        transport=transport, audit=AuditLogger(), script=SCRIPT,
        registry=_registry(), auditor=_NoopAuditor(),
        builder=_NoopBuilder(), limits=limits or DriverLimits(),
        coarse_gate=coarse_gate, coarse_restore=coarse_restore)


def _pump(driver, max_steps=400):
    for _ in range(max_steps):
        if driver.finished:
            break
        driver.step()


def test_coarse_plan_backtrack_three_state_pure():
    """纯层三态：门过即 adopt；分数新高 new_high；低分 revert；打平 tie。"""
    adopted = coarse_plan_backtrack(-2.0, best_score=-4.0, gate_ready=True)
    assert adopted.disposition == "adopt" and adopted.adopted is True
    assert adopted.best_score == -2.0 and adopted.no_gain == 0

    high = coarse_plan_backtrack(-2.0, best_score=-4.0, gate_ready=False)
    assert high.disposition == "new_high" and high.best_score == -2.0

    low = coarse_plan_backtrack(-6.0, best_score=-4.0, no_gain=1,
                                gate_ready=False)
    assert low.disposition == "revert" and low.should_revert is True
    assert low.best_score == -4.0 and low.no_gain == 2

    tie = coarse_plan_backtrack(-4.0, best_score=-4.0, no_gain=1,
                                gate_ready=False)
    assert tie.disposition == "tie" and tie.no_gain == 2
    assert tie.should_revert is False


def test_coarse_blocked_backtracks_and_adopts_passing_plan():
    """bad 计划 blocked -> 回溯重规划 -> good 计划门过 -> 采用放行。"""
    calls = []
    tmp_report = pathlib.Path(__file__).resolve().parent / (
        "_tmp_coarse_report_for_feedback.json")
    tmp_report.write_text(json.dumps({
        "findings": [
            {"check_id": "E_BLOCKOUT_FRAMING_TARGET_UNRESOLVED",
             "shot_id": "shot_001", "severity": "error",
             "message": "声明拍对象 prop/gold_coin 但场景无体块"},
        ],
    }), encoding="utf-8")

    def gate(plan, brief=None):
        calls.append(len(plan.shots))
        if len(plan.shots) == 4:
            return {
                "ready": False,
                "reason": "镜 4 镜声明拍对象 prop/gold_coin 但场景无体块"
                          "（E_BLOCKOUT_FRAMING_TARGET_UNRESOLVED）",
                "payload": {"rounds": [{"findings": 4}],
                             "artifacts": {"blockout_report": str(tmp_report)}},
                "gates": {"coarse": "blocked", "baseline": "missing"},
            }
        return {
            "ready": True,
            "payload": {"rounds": [{"findings": 0}],
                        "artifacts": {"blockout_report": str(tmp_report)}},
            "gates": {"coarse": "pass", "baseline": "frozen"},
        }

    transport = _BadThenGoodTransport()
    driver = _driver(transport, gate)
    try:
        _pump(driver)
        events = [e.kind for e in driver.audit.recent()]
        assert calls == [4, 2], f"粗排 gate 应按 4 镜/2 镜各评估一次，实际 {calls}"
        assert "coarse_gate_blocked" in events, events
        assert "coarse_backtrack" in events, events
        assert "coarse_adopted" in events, events
        assert "coarse_gate_passed" in events, events
        assert driver.state not in (DriverState.CANCELLED, DriverState.ERROR)
        assert driver._coarse_attempts == 0, "采用后回溯态应清零"
        assert driver._coarse_feedback == [], "采用后反馈应清零"
        #: 重规划提示必须带回粗排反馈（含 finding 明细，模型能看见为什么被拦）
        assert len(transport.payloads) >= 2, (
            f"应至少两次 plan 调用，实际 {len(transport.payloads)}")
        plan_payloads = [
            payload for payload in transport.payloads
            if payload.purpose is Purpose.PLAN
        ]
        assert len(plan_payloads) >= 2, (
            f"应至少两次 plan 调用，实际 {len(plan_payloads)}")
        second_text = " ".join(
            str(getattr(message, "content", "") or "")
            for message in plan_payloads[1].messages)
        assert "gold_coin" in second_text, (
            f"重规划提示应带回粗排反馈，实际 {second_text!r}")
        assert "E_BLOCKOUT_FRAMING_TARGET_UNRESOLVED" in second_text, (
            "重规划提示应带 finding 明细（镜号/规则/消息）")
    finally:
        tmp_report.unlink(missing_ok=True)


def test_coarse_backtrack_reopens_the_plan_attempt_budget():
    """A semantic gate failure is a new planning problem, not a plan syntax
    failure.  Without resetting the exhausted attempt counter, the driver
    re-fed the same deterministic fallback into the gate forever (real r2).
    """
    def gate(plan, brief=None):
        return {
            "ready": False,
            "reason": "构图未过线",
            "payload": {"rounds": [{"findings": 1}]},
            "gates": {"coarse": "blocked", "baseline": "missing"},
        }

    transport = _BadThenGoodTransport()
    driver = _driver(transport, gate)
    driver.plan = Plan.from_dict(GOOD_TWO_SHOT_PLAN)
    driver._plan_failures = driver.limits.plan_attempts
    driver.state = DriverState.PLANNING

    assert driver._run_coarse_gate(DriverState.EDITING) is False
    assert driver._coarse_backtracking is True
    assert driver._plan_failures == 0
    assert driver.state is DriverState.PLANNING


def test_coarse_blocked_exhausts_backtrack_budget_then_fails():
    """恒 blocked + 预算 1 次回溯：2 次评估后如实 ERROR（不降级通过）。"""
    calls = []

    def gate(plan, brief=None):
        calls.append(len(plan.shots))
        return {
            "ready": False,
            "reason": "拍对象 unresolved",
            "payload": {"rounds": [{"findings": 4}]},
            "gates": {"coarse": "blocked", "baseline": "missing"},
        }

    transport = _BadThenGoodTransport()
    driver = _driver(
        transport, gate, limits=DriverLimits(coarse_replan_attempts=1))
    _pump(driver)
    assert driver.state in (DriverState.CANCELLED, DriverState.ERROR)
    assert len(calls) == 2, f"1 次回溯预算应共评估 2 次，实际 {len(calls)}"
    events = [e.kind for e in driver.audit.recent()]
    assert events.count("coarse_backtrack") == 1, events
    assert "coarse_gate_blocked" in events
    assert "coarse_adopted" not in events
    assert driver._coarse_attempts == 2
    assert driver._coarse_dispositions == ["new_high", "tie"]
    assert driver.error and "回溯预算耗尽" in driver.error


def test_coarse_exhaustion_restores_best_plan_and_physical_callback():
    """Budget exhaustion must leave the best plan + scene, not the last loser.

    Real node123 r2 finished with plan score 76.9091 in the summary while the
    on-disk coarse report represented the final 69.5 candidate.  The plan-level
    best was saved in ``_coarse_best_plan`` but never restored.
    """
    sequence = []
    for heading, errors in (
        ("LOSER-1", 40),
        ("BEST", 30),
        ("LOSER-2", 35),
    ):
        item = json.loads(json.dumps(GOOD_TWO_SHOT_PLAN))
        item["scene_heading"] = heading
        sequence.append((item, errors))

    class SequenceTransport(_BadThenGoodTransport):
        def __init__(self):
            super().__init__()
            self._sequence = sequence

        def chat(self, payload, timeout=120.0):
            if is_understand(payload):
                return understand_reply(payload.request_id)
            if payload.purpose is Purpose.EDITOR:
                draft = demo_draft_dict(self._editor_index)
                self._editor_index += 1
                call = ToolCall(
                    id=f"draft_{self._editor_index}",
                    function=FunctionCall(
                        name="emit_shot_draft",
                        arguments=json.dumps(draft, ensure_ascii=False)))
                return ChatReply(
                    tool_calls=[call], request_id=payload.request_id)
            self.chat_calls += 1
            self.payloads.append(payload)
            plan, _errors = self._sequence[self.plan_calls]
            self.plan_calls += 1
            return ChatReply(tool_calls=[ToolCall(
                id=f"plan_restore_{self.plan_calls}",
                function=FunctionCall(
                    name="emit_plan", arguments=json.dumps(plan)),
            )], request_id=payload.request_id)

    evaluated = []

    def gate(plan, brief=None):
        index = len(evaluated)
        errors = sequence[index][1]
        evaluated.append((plan.scene_heading, errors))
        return {
            "ready": False,
            "reason": f"candidate {plan.scene_heading} blocked",
            "payload": {
                "rounds": [{"findings": errors}],
                "best_score": 50.0,
                "report": {"checks": [{
                    "check_id": "composition",
                    "shot_id": "shot_001",
                    "actual": 50.0,
                    "threshold": 80.0,
                }]},
            },
            "gates": {"coarse": "blocked", "baseline": "missing"},
        }

    restored = []

    def restore(*, plan, decision):
        restored.append((plan.scene_heading, decision["payload"]))
        return {
            "restored": True,
            "plan_fingerprint": "best-plan",
            "scene_fingerprint": "best-scene",
        }

    driver = _driver(
        SequenceTransport(), gate,
        limits=DriverLimits(coarse_replan_attempts=2),
        coarse_restore=restore,
    )
    _pump(driver)

    assert evaluated == [
        ("LOSER-1", 40), ("BEST", 30), ("LOSER-2", 35)]
    assert driver.plan is not None
    assert driver.plan.scene_heading == "BEST"
    assert len(restored) == 1
    assert restored[0][0] == "BEST"
    assert restored[0][1]["rounds"][0]["findings"] == 30
    events = [event for event in driver.audit.recent()
              if event.kind == "coarse_best_restored"]
    assert len(events) == 1
    assert events[0].data["plan_score"] == -30.0
    assert events[0].data["physical_restore"] is True
    summary = driver.snapshot()
    assert summary["coarse_best_plan"] == "BEST"
    assert summary["coarse_best_plan_score"] == -30.0
    assert summary["coarse_best_scene_score"] == 50.0


def test_coarse_restore_requires_explicit_physical_confirmation():
    """A blocked report is not proof that Blender was rebuilt.

    The restore seam previously treated ``coarse_status == "blocked"`` as a
    physical success.  That would mark the retained scene as restored even
    when the callback merely returned the candidate's pipeline report.
    """
    def gate(plan, brief=None):
        return {
            "ready": False,
            "reason": "blocked",
            "payload": {"rounds": [{"findings": 2}]},
            "gates": {"coarse": "blocked", "baseline": "missing"},
        }

    def restore(*, plan, decision):
        return {
            "schema_version": "coarse-pipeline-report/v1",
            "coarse_status": "blocked",
            "gates": {"coarse": "blocked", "baseline": "missing"},
        }

    driver = _driver(
        _BadThenGoodTransport(), gate, coarse_restore=restore)
    driver.plan = Plan.from_dict(GOOD_TWO_SHOT_PLAN)
    driver._coarse_best_plan = driver.plan.to_dict()
    driver._coarse_best_plan_heading = driver.plan.scene_heading
    driver._coarse_best_decision = gate(driver.plan)
    driver._coarse_best_score = -2.0

    note = driver._restore_coarse_best()

    assert "物理场景未恢复" in note
    assert driver._coarse_restore_result["physical_restore"] is False
    assert driver._coarse_restore_result["status"] == "plan_only"


def test_coarse_replan_disabled_preserves_old_behavior():
    """``coarse_replan_attempts=0``：blocked 立即 ERROR（旧行为，可显式关闭）。"""

    def gate(plan, brief=None):
        return {"ready": False, "reason": "blocked",
                "payload": {"rounds": [{"findings": 1}]},
                "gates": {"coarse": "blocked", "baseline": "missing"}}

    transport = _BadThenGoodTransport()
    driver = _driver(
        transport, gate, limits=DriverLimits(coarse_replan_attempts=0))
    _pump(driver)
    assert driver.state in (DriverState.CANCELLED, DriverState.ERROR)
    events = [e.kind for e in driver.audit.recent()]
    assert "coarse_backtrack" not in events, events
    assert driver._coarse_attempts == 1
