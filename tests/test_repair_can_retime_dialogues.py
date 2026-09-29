"""修复阶段能改对白时序（真实模型暴露的能力缺口）。"""

from __future__ import annotations

import json

from block_director.contracts.audit import AuditError, AuditResult
from block_director.contracts.enums import Purpose
from block_director.contracts.messages import ChatReply, FunctionCall, ToolCall
from block_director.layer5_orchestrator.driver import (
    DriverLimits,
    PrevisDriver,
    default_registry,
)
from block_director.layer5_orchestrator.editor import EDITOR_TOOL_NAME
from block_director.layer5_orchestrator.planner import PLAN_TOOL_NAME
from block_director.layer5_orchestrator.states import DriverState
from block_director.layer6_audit.audit_logger import AuditLogger

from test_driver import InlineThread

SCRIPT = "INT. 咖啡馆 - 日\n"

PLAN = {"scene_heading": "INT. 咖啡馆 - 日", "shots": [
    {"shot_id": "shot_001", "order": 1, "intent": "对白", "shot_type": "MS",
     "duration_frames": 48, "characters": ["char_001"], "dialogue_ids": [],
     "prompt": "两人对坐"}]}

#: 第一次草案把对白排到镜头外（48 帧装不下 40+12）；修复后挪回镜头内。
TOO_LATE = {"shot_id": "shot_001",
            "dialogues": [{"character_id": "char_001", "text": "你好",
                           "start_frame": 40, "end_frame": 70}]}
RETIMED = {"shot_id": "shot_001",
           "dialogues": [{"character_id": "char_001", "text": "你好",
                          "start_frame": 5, "end_frame": 30}]}


class Transport:
    def __init__(self):
        self.payloads = []
        self._editor_calls = 0

    def chat(self, payload, timeout=120.0):
        self.payloads.append(payload)
        if payload.purpose is Purpose.PLAN:
            return self._call(PLAN_TOOL_NAME, PLAN)
        if payload.purpose is Purpose.EDITOR:
            self._editor_calls += 1
            return self._call(EDITOR_TOOL_NAME, TOO_LATE)
        if payload.purpose is Purpose.REPAIR:
            return self._call(EDITOR_TOOL_NAME, RETIMED)     # 重提草案并排回镜头内
        return ChatReply(content="ok", tool_calls=[])

    @staticmethod
    def _call(name, args):
        return ChatReply(tool_calls=[ToolCall(
            id="c", function=FunctionCall(name=name,
                                          arguments=json.dumps(args)))])

    def cancel(self, request_id):
        return None


class Auditor:
    """按草案里的对白是否越界判成败（模拟 R011/S6）。"""

    def __init__(self):
        self.payloads = []

    def shot_ids(self):
        return ["shot_001"]

    def audit(self, shot_id):
        # 从最近一次被构建的计划里读对白（由 StubBuilder 记录）
        dialogues = self.payloads[-1] if self.payloads else []
        late = any(int(item.get("end_frame", 0)) + 12 > 48
                   for item in dialogues)
        if late:
            return AuditResult(passed=False, target=shot_id, errors=[
                AuditError(rule="R011", code="E_SDL_001",
                           message="镜头装不下对白", target=shot_id,
                           suggestion="把对白前移")])
        return AuditResult(passed=True, target=shot_id)


class Builder:
    def __init__(self, auditor):
        self.auditor = auditor
        self.plans = []

    def build(self, plan, brief=None):
        self.auditor.payloads.append(plan.shots[0].dialogues)
        self.plans.append(plan.to_dict())
        return {"shots": len(plan.shots), "total_frames": plan.total_frames}


# --------------------------------------------------------------------------- #
def test_repair_can_resubmit_a_draft_and_retime():
    auditor = Auditor()
    transport = Transport()
    builder = Builder(auditor)
    driver = PrevisDriver(transport=transport, audit=AuditLogger(),
                          script=SCRIPT, builder=builder, auditor=auditor,
                          limits=DriverLimits(max_repairs_per_shot=2),
                          thread_factory=InlineThread)
    state = driver.run_to_completion()

    assert state is DriverState.DONE
    dialogues = driver.plan.shots[0].dialogues
    assert dialogues and dialogues[0]["end_frame"] == 30      # 已排回镜头内
    kinds = [event.kind for event in driver.audit.recent(200)]
    assert kinds.count("draft_received") == 2                  # B1 一次 + 修复重提一次


def test_emit_shot_draft_is_offered_to_the_repair_stage():
    from block_director.layer5_orchestrator.repair import build_repair_payload

    registry = default_registry()
    names = [item["function"]["name"]
             for item in build_repair_payload(
                 AuditResult(passed=False, target="shot_001"), registry).tools]
    assert EDITOR_TOOL_NAME in names
    assert PLAN_TOOL_NAME not in names      # 计划仍不许改


def test_plan_stage_refuses_a_shot_draft():
    transport = Transport()
    driver = PrevisDriver(transport=transport, audit=AuditLogger(),
                          script=SCRIPT, thread_factory=InlineThread,
                          limits=DriverLimits(plan_attempts=1))
    problem = driver._dispatch_tool_calls(ChatReply(tool_calls=[ToolCall(
        id="c", function=FunctionCall(name=EDITOR_TOOL_NAME,
                                      arguments=json.dumps(TOO_LATE)))]))
    assert "只在单镜阶段" in problem
