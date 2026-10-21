"""R2 空计划漏洞：driver 级预检 -> blocked -> 回溯 -> 含角色计划放行。

final5 真跑：剧本【角色锚】米迦尔/伊恩/偷盗者，模型第一次 plan 带角色被
粗排视觉门拦下后，第二次直接清空 characters 用空计划绕过粗排门。本测试
钉住修复：**计划完整性预检先于粗排视觉门**，空计划/丢角色必须被拦并回溯，
不允许"空镜豁免"把脱轨计划放过去。
"""

from __future__ import annotations

import json

from block_director.contracts.audit import AuditResult
from block_director.contracts.messages import ChatReply, FunctionCall, ToolCall
from block_director.layer1_input import parse_text
from block_director.layer5_orchestrator.driver import DriverLimits, PrevisDriver
from block_director.layer5_orchestrator.states import DriverState
from block_director.layer6_audit.audit_logger import AuditLogger

from test_checkpoint_resume import _registry
from stage_helpers import is_understand, understand_reply


SCRIPT_CN = """节点1（约16s）

【角色锚】
米迦尔：兽人，四根手指兽爪。
伊恩：年轻男性，衣着朴素。
偷盗者：瘦削成年男性，穿旧外套。

【场景锚】第十四街区码头市场，白天晴天。

镜头 1（约4s）：
- 景别视角：近景，平视米迦尔。
- 主体动作：米迦尔看到金子，表情僵住。

镜头 2（约4s）：
- 景别视角：特写，平视米迦尔面部。
- 主体动作：米迦尔气得跺脚。
"""


EMPTY_CN_PLAN = {
    "scene_heading": "码头市场",
    "continuity_notes": ["空计划不应通过预检"],
    "shots": [
        {"shot_id": "shot_001", "order": 1, "intent": "x",
         "intent_type": "铺垫", "shot_type": "MCU",
         "duration_frames": 96, "characters": [],
         "dialogue_ids": [], "axis_note": "", "continuity_in": "",
         "prompt": ""},
        {"shot_id": "shot_002", "order": 2, "intent": "x",
         "intent_type": "推进", "shot_type": "CU",
         "duration_frames": 96, "characters": [],
         "dialogue_ids": [], "axis_note": "", "continuity_in": "",
         "prompt": ""},
    ],
}


GOOD_CN_PLAN = {
    "scene_heading": "码头市场",
    "continuity_notes": ["含角色锚同名角色，预检应放行"],
    "shots": [
        {"shot_id": "shot_001", "order": 1, "intent": "x",
         "intent_type": "铺垫", "shot_type": "MCU",
         "duration_frames": 96, "characters": ["米迦尔"],
         "dialogue_ids": [], "axis_note": "", "continuity_in": "",
         "prompt": ""},
        {"shot_id": "shot_002", "order": 2, "intent": "x",
         "intent_type": "推进", "shot_type": "CU",
         "duration_frames": 96, "characters": ["伊恩"],
         "dialogue_ids": [], "axis_note": "", "continuity_in": "",
         "prompt": ""},
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


class _EmptyThenGoodTransport:
    """先回空计划，再回含角色计划；后续调用返回 empty（不触发编辑）。"""

    def __init__(self):
        self.chat_calls = 0
        self.plan_calls = 0
        self.payloads = []

    def chat(self, payload, timeout=120.0):
        if is_understand(payload):
            return understand_reply(payload.request_id)
        self.chat_calls += 1
        self.payloads.append(payload)
        self.plan_calls += 1
        plan = (EMPTY_CN_PLAN if self.plan_calls == 1
                else GOOD_CN_PLAN)
        call = ToolCall(
            id=f"plan_{self.plan_calls}",
            function=FunctionCall(name="emit_plan",
                                  arguments=json.dumps(plan)))
        return ChatReply(tool_calls=[call], request_id=payload.request_id)

    def cancel(self, request_id):
        return None


def _pump(driver, max_steps=400):
    for _ in range(max_steps):
        if driver.finished:
            break
        driver.step()


def test_empty_plan_blocked_then_good_plan_adopted():
    """空计划被预检拦 -> 回溯 -> 含角色计划通过粗排门并进入细排。"""
    transport = _EmptyThenGoodTransport()
    parsed = parse_text(SCRIPT_CN, title="market")
    driver = PrevisDriver(
        transport=transport, audit=AuditLogger(), script=SCRIPT_CN,
        parsed_script=parsed, registry=_registry(), auditor=_NoopAuditor(),
        builder=_NoopBuilder(), limits=DriverLimits(),
        coarse_gate=lambda plan, brief=None: {
            "ready": True, "gates": {"coarse": "pass"},
            "artifacts": {}, "payload": {}})
    _pump(driver)

    kinds = [event.kind
             for event in driver.audit.recent()
             if event.kind in
             ("coarse_gate_blocked", "coarse_backtrack", "coarse_gate_passed")]
    assert "coarse_gate_blocked" in kinds, kinds
    assert "coarse_backtrack" in kinds, kinds
    assert "coarse_gate_passed" in kinds, kinds
    assert driver.plan is not None
    assert ["米迦尔", "伊恩"] == [
        name for shot in driver.plan.shots
        for name in (shot.characters or [])]
    plan_payloads = [
        payload for payload in transport.payloads
        if getattr(getattr(payload, "purpose", None), "value", None) == "plan"]
    assert len(plan_payloads) == 2, (
        f"应恰好两次 emit_plan（空计划+含角色计划），实际 "
        f"{len(plan_payloads)}")
    assert driver.state == DriverState.DONE


def test_integrity_finding_line_in_coarse_feedback():
    """预检 finding 必须折成反馈行（模型重规划时看得到失败原因）。"""
    from block_director.layer5_orchestrator.driver import _coarse_finding_lines

    payload = {"findings": [{
        "check_id": "E_PLAN_NO_SUBJECT", "severity": "error",
        "shot_id": "plan", "message": "剧本角色锚声明 3 个角色，计划全空",
    }]}
    lines = _coarse_finding_lines(payload)
    assert lines == [
        "- [error] plan E_PLAN_NO_SUBJECT: "
        "剧本角色锚声明 3 个角色，计划全空"]
