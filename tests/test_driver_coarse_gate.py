"""R2 ticket 04（F1）driver 级：plan 落定后、进细排前跑粗排 gate。

headless 执行链必须经过粗排 gate；blocked 时驱动器转失败阻止进细排，
pass 时放行；未注入回调时行为与既有完全一致（零差异）。
"""

from __future__ import annotations

import json

from block_director.contracts.audit import AuditResult
from block_director.contracts.enums import Purpose
from block_director.contracts.messages import ChatReply, FunctionCall, ToolCall
from block_director.layer5_orchestrator.driver import (
    DriverLimits, PrevisDriver, ResumeState, plan_for_shots)
from block_director.layer5_orchestrator.human_gate import AutoGate, GateDecision
from block_director.layer5_orchestrator.offline import demo_draft_dict
from block_director.layer5_orchestrator.states import DriverState
from block_director.layer6_audit.audit_logger import AuditLogger

from test_checkpoint_resume import _registry, FOUR_SHOT_PLAN, SCRIPT
from stage_helpers import is_understand, understand_reply


def _edited_four_shot_plan():
    plan = json.loads(json.dumps(FOUR_SHOT_PLAN))
    actions = {
        "shot_001": {
            "character_id": "char_001",
            "action_type": "nod",
            "start_frame": 1,
            "end_frame": 24,
            "params": {"cycles": 2},
        },
        "shot_002": {
            "character_id": "char_002",
            "action_type": "sit",
            "start_frame": 1,
            "end_frame": 24,
            "params": {"drop": 0.2},
        },
    }
    for shot in plan["shots"]:
        action = actions.get(shot["shot_id"])
        if action is not None:
            shot["actions"] = [action]
    return plan


def _complete_draft_ledger(plan):
    return {
        shot["shot_id"]: {"shot_id": shot["shot_id"]}
        for shot in plan["shots"]
    }


class _PlanTransport:
    """阶段替身：understand + 一次 emit_plan，之后不再有调用。"""

    def __init__(self):
        self.chat_calls = 0

    def chat(self, payload, timeout=120.0):
        if is_understand(payload):
            return understand_reply(payload.request_id)
        self.chat_calls += 1
        call = ToolCall(
            id=f"plan_{self.chat_calls}",
            function=FunctionCall(name="emit_plan",
                                  arguments=json.dumps(FOUR_SHOT_PLAN)))
        return ChatReply(tool_calls=[call], request_id=payload.request_id)

    def cancel(self, request_id):
        return None


class _ResumeDraftTransport(_PlanTransport):
    """只回答 resume 后尚未完成的 B1 草案。"""

    def __init__(self):
        super().__init__()
        self.editor_calls = 0

    def chat(self, payload, timeout=120.0):
        if payload.purpose is not Purpose.EDITOR:
            return super().chat(payload, timeout)
        draft = demo_draft_dict(self.editor_calls)
        self.editor_calls += 1
        call = ToolCall(
            id=f"draft_{self.editor_calls}",
            function=FunctionCall(
                name="emit_shot_draft",
                arguments=json.dumps(draft, ensure_ascii=False)))
        return ChatReply(tool_calls=[call], request_id=payload.request_id)


class _NoopAuditor:
    def shot_ids(self):
        return []

    def audit(self, shot_id):
        return AuditResult(passed=True, target=shot_id)


class _NoopBuilder:
    """有 builder 才走细排路径（EDITING→BUILDING/PREPARE_SCENE）。"""

    def build(self, plan, brief=None):
        return {"shots": len(plan.shots), "characters": 2, "cameras": 2,
                "motions": 0, "keyframes": 0, "total_frames": plan.total_frames,
                "warnings": [], "results": [
                    {"shot_id": shot.shot_id, "start_frame": i * 24 + 1,
                     "end_frame": (i + 1) * 24,
                     "camera": f"BD_Cam_{shot.shot_id}", "lens": 35}
                    for i, shot in enumerate(plan.shots)]}


def _driver(coarse_gate=None):
    return PrevisDriver(
        transport=_PlanTransport(), audit=AuditLogger(), script=SCRIPT,
        registry=_registry(), auditor=_NoopAuditor(),
        builder=_NoopBuilder(), limits=DriverLimits(),
        coarse_gate=coarse_gate)


def _pump(driver, max_steps=200):
    for _ in range(max_steps):
        if driver.finished:
            break
        driver.step()


def test_coarse_gate_blocked_stops_before_fine():
    gate = lambda plan, brief=None: {  # noqa: E731
        "ready": False, "reason": "分镜顺序被改错（E_BLOCKOUT_SHOT_SEQUENCE_MISMATCH）",
        "gates": {"coarse": "blocked", "baseline": "missing"},
    }
    driver = _driver(coarse_gate=gate)
    _pump(driver)
    assert driver.state in (DriverState.CANCELLED, DriverState.ERROR)
    events = [e.kind for e in driver.audit.recent()]
    assert "coarse_gate_blocked" in events
    assert driver._coarse_decision["ready"] is False


def test_coarse_gate_pass_allows_fine():
    gate = lambda plan, brief=None: {  # noqa: E731
        "ready": True, "gates": {"coarse": "pass", "baseline": "frozen"},
    }
    driver = _driver(coarse_gate=gate)
    _pump(driver)
    events = [e.kind for e in driver.audit.recent()]
    assert "coarse_gate_passed" in events
    assert driver.state not in (DriverState.CANCELLED, DriverState.ERROR)


def test_coarse_gate_receives_the_drivers_shared_budget_ledger():
    """Coarse Agent calls must debit the one run-level budget, not a copy."""
    seen = {}

    def gate(plan, brief=None):
        seen["budget"] = getattr(gate, "bound_budget", None)
        return {"ready": True, "gates": {"coarse": "pass",
                                         "baseline": "frozen"}}

    def bind_budget(budget):
        gate.bound_budget = budget

    gate.bind_budget = bind_budget
    driver = _driver(coarse_gate=gate)
    _pump(driver)

    assert seen["budget"] is driver.budget


def test_no_coarse_gate_changes_nothing():
    """未注入回调：行为与既有完全一致（零差异）。"""
    driver = _driver(coarse_gate=None)
    _pump(driver)
    events = [e.kind for e in driver.audit.recent()]
    assert "coarse_gate_blocked" not in events
    assert "coarse_gate_passed" not in events


def test_coarse_gate_runs_before_human_gate_autogate():
    """R2-F1 回归：即使 ``human_gate_on_plan=True``（headless AutoGate 立即
    放行），粗排 gate 也必须在 plan 落定、进细排前被调用一次——不能被
    ``_apply_gate`` 的立即跳转绕过（真跑 20261019-r2-market-coin-full 的
    audit 无任何 coarse 事件，根因即 AutoGate 跳过粗排检查）。"""
    from block_director.contracts.config import AppConfig
    from block_director.layer5_orchestrator.human_gate import (
        AutoGate, GateDecision,
    )

    calls = []

    def gate(plan, brief=None):
        calls.append((plan, brief))
        return {"ready": True, "gates": {"coarse": "pass", "baseline": "frozen"}}

    cfg = AppConfig()
    cfg.audit.human_gate_on_plan = True
    driver = PrevisDriver(
        transport=_PlanTransport(), audit=AuditLogger(), script=SCRIPT,
        registry=_registry(), auditor=_NoopAuditor(),
        builder=_NoopBuilder(), limits=DriverLimits(), config=cfg,
        human_gate=AutoGate(policy={"plan": GateDecision.SKIPPED}),
        coarse_gate=gate)
    _pump(driver)
    events = [e.kind for e in driver.audit.recent()]
    assert len(calls) == 1, f"粗排 gate 应恰好调用 1 次，实际 {len(calls)}"
    #: A：headless 粗排需要真实 brief（Stage S 产物），driver 必须透传
    assert calls[0][0] is not None
    assert calls[0][1] is not None, "粗排 gate 应收到 Stage S 的真实 brief"
    assert getattr(calls[0][1], "to_dict", None) is not None
    assert "coarse_gate_passed" in events, events
    assert "gate_requested" in events, events


def test_coarse_gate_blocked_wins_over_human_gate_autogate():
    """粗排 blocked 时**不**落入人工门放行：先失败，不允许进细排。"""
    from block_director.contracts.config import AppConfig
    from block_director.layer5_orchestrator.human_gate import (
        AutoGate, GateDecision,
    )

    def gate(plan, brief=None):
        return {"ready": False, "reason": "E_BLOCKOUT_ANCHOR_UNRESOLVED",
                "gates": {"coarse": "blocked", "baseline": "missing"}}

    cfg = AppConfig()
    cfg.audit.human_gate_on_plan = True
    driver = PrevisDriver(
        transport=_PlanTransport(), audit=AuditLogger(), script=SCRIPT,
        registry=_registry(), auditor=_NoopAuditor(),
        builder=_NoopBuilder(), limits=DriverLimits(), config=cfg,
        human_gate=AutoGate(policy={"plan": GateDecision.SKIPPED}),
        coarse_gate=gate)
    _pump(driver)
    events = [e.kind for e in driver.audit.recent()]
    assert "coarse_gate_blocked" in events, events
    assert driver.state in (DriverState.CANCELLED, DriverState.ERROR)


def test_coarse_execution_error_fails_without_replanning():
    """A programming failure is not a semantic reason to regenerate the plan.

    Real r2 exposed this distinction: the first complete 11-shot plan reached
    the coarse gate, an implementation exception was converted into
    ``ready=False``, and the driver spent another full model call producing the
    same plan.  Execution failures must stop with their traceback intact.
    """
    calls = []

    def gate(plan, brief=None):
        calls.append(plan)
        return {
            "ready": False,
            "execution_error": True,
            "reason": "粗排执行失败：UnboundLocalError: local_distance",
            "gates": {"coarse": "blocked", "baseline": "missing"},
        }

    driver = _driver(coarse_gate=gate)
    _pump(driver)

    events = [e.kind for e in driver.audit.recent()]
    assert len(calls) == 1, "execution failure must not trigger replanning"
    assert "coarse_backtrack" not in events, events
    assert "coarse_execution_error" in events, events
    assert driver.state in (DriverState.CANCELLED, DriverState.ERROR)
    assert driver._plan_failures == 0


def test_coarse_gate_runs_on_resume_with_plan():
    """R2-F1 回归：断点续跑恢复 plan 后**同样**要过粗排 gate，不能因为
    ``_apply_resume_state`` 直接跳进 EDITING/PREPARE_SCENE 而绕过
    （旧断点由首跑 AutoGate 短路产生，resume 若不查会整体漏掉粗排验证）。"""
    calls = []

    def gate(plan, brief=None):
        calls.append((plan, brief))
        return {"ready": True, "gates": {"coarse": "pass", "baseline": "frozen"}}

    edited_plan = _edited_four_shot_plan()
    resume = ResumeState(
        run_id="r1",
        plan=edited_plan,
        drafts=_complete_draft_ledger(edited_plan),
        brief={"notes": ["resume 断点：粗排需恢复真实 brief"]})
    driver = PrevisDriver(
        transport=_PlanTransport(), audit=AuditLogger(), script=SCRIPT,
        registry=_registry(), auditor=_NoopAuditor(),
        builder=_NoopBuilder(), limits=DriverLimits(),
        resume_state=resume, resume_state_path=None,
        coarse_gate=gate)
    events = [e.kind for e in driver.audit.recent()]
    assert len(calls) == 1, f"resume 后粗排 gate 应恰好调用 1 次，实际 {len(calls)}"
    #: resume 恢复 brief 后同样透传给粗排 gate
    assert calls[0][1] is not None, "resume 后粗排 gate 应收到恢复的 brief"
    assert calls[0][0].shots[0].actions[0]["action_type"] == "nod"
    assert calls[0][0].shots[1].actions[0]["action_type"] == "sit"
    assert "coarse_gate_passed" in events, events
    assert "run_resumed" in events, events


def test_resume_during_b1_preserves_coarse_then_human_plan_gate_order():
    """A checkpoint taken mid-B1 must finish B1 before either plan gate.

    The resume branch deliberately constructs no placeholder plan gate.  It
    must carry the same "plan details pending" bit as a fresh run, otherwise
    the remaining draft is merged, coarse runs, and the configured human plan
    gate silently disappears.
    """
    from block_director.contracts.config import AppConfig

    calls = []

    def coarse_gate(plan, brief=None):
        calls.append(("coarse", plan))
        return {"ready": True, "gates": {"coarse": "pass",
                                         "baseline": "frozen"}}

    edited_plan = _edited_four_shot_plan()
    drafts = _complete_draft_ledger(edited_plan)
    drafts.pop("shot_004")
    resume = ResumeState(run_id="r-mid-b1", plan=edited_plan, drafts=drafts)
    transport = _ResumeDraftTransport()
    human_gate = AutoGate(default=GateDecision.APPROVED)
    config = AppConfig()
    config.audit.human_gate_on_plan = True
    driver = PrevisDriver(
        transport=transport, audit=AuditLogger(), script=SCRIPT,
        registry=_registry(), auditor=_NoopAuditor(),
        builder=_NoopBuilder(), limits=DriverLimits(),
        config=config, human_gate=human_gate,
        resume_state=resume, resume_state_path=None,
        coarse_gate=coarse_gate)

    _pump(driver)

    assert transport.editor_calls == 1
    assert len(calls) == 1
    assert calls[0][1].shots[0].actions[0]["action_type"] == "nod"
    assert len(human_gate.requests) == 1
    assert human_gate.requests[0].kind == "plan"
    events = [event.kind for event in driver.audit.recent()]
    assert events.index("coarse_gate_passed") < events.index("gate_requested")


def test_resume_after_last_b1_draft_still_requests_human_plan_gate():
    """The final draft checkpoint precedes the plan-level gates.

    A hard exit after merging the last B1 draft therefore leaves all drafts
    complete but both gates unfinished.  Resume must not infer "all drafts are
    present" as "the plan was already approved".
    """
    from block_director.contracts.config import AppConfig

    edited_plan = _edited_four_shot_plan()
    resume = ResumeState(
        run_id="r-after-b1",
        plan=edited_plan,
        drafts=_complete_draft_ledger(edited_plan))
    resume.plan_details_pending = True
    human_gate = AutoGate(default=GateDecision.APPROVED)
    config = AppConfig()
    config.audit.human_gate_on_plan = True
    driver = PrevisDriver(
        transport=_ResumeDraftTransport(), audit=AuditLogger(), script=SCRIPT,
        registry=_registry(), auditor=_NoopAuditor(),
        builder=_NoopBuilder(), limits=DriverLimits(),
        config=config, human_gate=human_gate,
        resume_state=resume, resume_state_path=None,
        coarse_gate=lambda plan, brief=None: {
            "ready": True,
            "gates": {"coarse": "pass", "baseline": "frozen"},
        })

    _pump(driver)

    assert len(human_gate.requests) == 1
    assert human_gate.requests[0].kind == "plan"
    events = [event.kind for event in driver.audit.recent()]
    assert events.index("coarse_gate_passed") < events.index("gate_requested")


def test_plan_details_pending_survives_checkpoint_round_trip():
    edited_plan = _edited_four_shot_plan()
    state = ResumeState(
        run_id="r-round-trip",
        plan=edited_plan,
        drafts=_complete_draft_ledger(edited_plan),
        plan_details_pending=True)

    payload = state.to_dict()
    restored = ResumeState.from_dict(payload)

    assert payload["plan_details_pending"] is True
    assert restored.plan_details_pending is True
    #: Legacy v1 files predate the field.  Without a versioned coarse decision
    #: they cannot prove the plan gates ran, so resume must treat them as open.
    legacy = dict(payload)
    legacy.pop("plan_details_pending")
    legacy["coarse_decision"] = None
    assert ResumeState.from_dict(legacy).plan_details_pending is True


def test_coarse_gate_blocked_on_resume_stops():
    """resume 恢复 plan 后粗排 blocked：同样转失败，不允许进入细排。"""

    def gate(plan, brief=None):
        return {"ready": False, "reason": "E_BLOCKOUT_ANCHOR_UNRESOLVED",
                "gates": {"coarse": "blocked", "baseline": "missing"}}

    edited_plan = _edited_four_shot_plan()
    resume = ResumeState(
        run_id="r1",
        plan=edited_plan,
        drafts=_complete_draft_ledger(edited_plan),
    )
    driver = PrevisDriver(
        transport=_PlanTransport(), audit=AuditLogger(), script=SCRIPT,
        registry=_registry(), auditor=_NoopAuditor(),
        builder=_NoopBuilder(), limits=DriverLimits(),
        resume_state=resume, resume_state_path=None,
        coarse_gate=gate)
    events = [e.kind for e in driver.audit.recent()]
    assert "coarse_gate_blocked" in events, events


def test_coarse_gate_receives_real_brief():
    """R2-F5/F7：粗排 gate 必须拿到 driver 产出的真实 brief。

    emit_plan 的 payload 往往不带 environment（锚点/道具在阶段 S 的 brief
    里产出）；若 gate 只收 plan 而 brief 传 None，粗排参考 JSON 的
    anchors/props 为空 -> 银币摊/海面等明确主体丢失 -> 空墙。
    """
    seen = {}

    def gate(plan, brief=None):
        seen["brief"] = brief
        return {"ready": True, "gates": {"coarse": "pass",
                                         "baseline": "frozen"}}

    driver = _driver(coarse_gate=gate)
    _pump(driver)
    events = [e.kind for e in driver.audit.recent()]
    assert "coarse_gate_passed" in events, events
    #: driver 在 UNDERSTANDING 阶段的真实 brief（含 environment/notes）要
    #: 被传进 gate；不是 None。
    assert seen.get("brief") is not None
