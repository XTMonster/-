"""计划只能由阶段 A 改写（真实模型踩出来的回归）。"""

from __future__ import annotations

import json

from block_director.contracts.enums import Purpose
from block_director.contracts.messages import ChatReply, FunctionCall, ToolCall
from block_director.layer5_orchestrator.driver import DriverLimits, PrevisDriver
from block_director.layer5_orchestrator.planner import PLAN_TOOL_NAME
from block_director.layer5_orchestrator.repair import build_repair_payload
from block_director.layer5_orchestrator.react import build_react_payload
from block_director.layer5_orchestrator.states import DriverState
from block_director.layer5_orchestrator.tool_registry import ToolRegistry
from block_director.layer6_audit.audit_logger import AuditLogger
from block_director.contracts.audit import AuditResult
from block_director.contracts.plan import Plan, ShotPlan

from test_driver import InlineThread

SCRIPT = "INT. 咖啡馆 - 日\n"

THREE_SHOTS = {"scene_heading": "INT. 咖啡馆 - 日", "shots": [
    {"shot_id": "shot_001", "order": 1, "intent": "a", "shot_type": "MS",
     "duration_frames": 24, "characters": ["char_001"]},
    {"shot_id": "shot_002", "order": 2, "intent": "b", "shot_type": "MCU",
     "duration_frames": 24, "characters": ["char_001"]},
    {"shot_id": "shot_003", "order": 3, "intent": "c", "shot_type": "CU",
     "duration_frames": 24, "characters": ["char_001"]}]}

ONE_SHOT = {"scene_heading": "INT. 咖啡馆 - 日", "shots": [
    {"shot_id": "shot_001", "order": 1, "intent": "改主意了",
     "shot_type": "ECU", "duration_frames": 37, "characters": ["char_001"]}]}


class RepaintingTransport:
    """模拟真实模型的行为：修复回合里又提交了一份计划。"""

    def __init__(self, repair_tool="emit_plan"):
        self.repair_tool = repair_tool
        self.payloads = []

    def chat(self, payload, timeout=120.0):
        self.payloads.append(payload)
        if payload.purpose is Purpose.PLAN:
            return self._call(PLAN_TOOL_NAME, THREE_SHOTS)
        if payload.purpose is Purpose.EDITOR:
            return self._call("emit_shot_draft",
                              {"shot_id": self._next_editor_shot()})
        if self.repair_tool == "emit_plan":
            return self._call(PLAN_TOOL_NAME, ONE_SHOT)
        return self._call(self.repair_tool, {})

    def _next_editor_shot(self) -> str:
        index = sum(1 for item in self.payloads
                    if str(item.purpose) == "editor") - 1
        return f"shot_{min(index + 1, 3):03d}"

    @staticmethod
    def _call(name, args):
        return ChatReply(tool_calls=[ToolCall(
            id="c", function=FunctionCall(name=name,
                                          arguments=json.dumps(args)))])

    def cancel(self, request_id):
        return None


class FailOnceAuditor:
    def __init__(self):
        self.calls = 0

    def shot_ids(self):
        return ["shot_001"]

    def audit(self, shot_id):
        self.calls += 1
        if self.calls == 1:
            from block_director.contracts.audit import AuditError

            return AuditResult(passed=False, target=shot_id, score=50.0,
                               errors=[AuditError(rule="COMPOSITION",
                                                  code="E_CAM_001",
                                                  message="构图差",
                                                  target=shot_id)])
        return AuditResult(passed=True, target=shot_id)


class StubBuilder:
    def __init__(self):
        self.plans = []

    def build(self, plan, brief=None):
        self.plans.append(plan.to_dict())
        return {"shots": len(plan.shots), "total_frames": plan.total_frames}


def make_driver(transport, builder):
    return PrevisDriver(transport=transport, audit=AuditLogger(), script=SCRIPT,
                        builder=builder, auditor=FailOnceAuditor(),
                        limits=DriverLimits(max_repairs_per_shot=1),
                        thread_factory=InlineThread)


# --------------------------------------------------------------------------- #
# 驱动器侧
# --------------------------------------------------------------------------- #
def test_emit_plan_during_repair_is_ignored():
    transport = RepaintingTransport("emit_plan")
    builder = StubBuilder()
    driver = make_driver(transport, builder)
    state = driver.run_to_completion()

    assert state in (DriverState.DONE, DriverState.ERROR)
    # 计划仍是最初那三镜，没有被修复回合覆盖成一镜
    assert len(driver.plan.shots) == 3
    assert [str(shot.shot_type) for shot in driver.plan.shots][0] == "MS"
    assert len(builder.plans[0]["shots"]) == 3
    kinds = [event.kind for event in driver.audit.recent(200)]
    assert "plan_ignored" in kinds


def test_repair_and_react_payloads_do_not_offer_emit_plan():
    registry = ToolRegistry()
    registry.add(name=PLAN_TOOL_NAME, description="plan",
                 parameters={"type": "object"}, handler=lambda **kw: "ok")
    registry.add(name="setup_camera", description="fix",
                 parameters={"type": "object"}, handler=lambda **kw: "ok")
    audit = AuditResult(passed=False, target="shot_001")
    shot = ShotPlan.from_dict({"shot_id": "shot_001", "intent": "x",
                               "shot_type": "MS", "duration_frames": 24})
    repair_names = [t["function"]["name"] for t in
                    build_repair_payload(audit, registry).tools]
    react_names = [t["function"]["name"] for t in
                   build_react_payload(shot, audit, registry=registry).tools]
    assert PLAN_TOOL_NAME not in repair_names
    assert PLAN_TOOL_NAME not in react_names
    assert "setup_camera" in repair_names


def test_schemas_except_keeps_the_other_tools():
    registry = ToolRegistry()
    for name in ("emit_plan", "setup_camera", "check_axis"):
        registry.add(name=name, description=name,
                     parameters={"type": "object"}, handler=lambda **kw: "ok")
    names = [item["function"]["name"]
             for item in registry.schemas_except("emit_plan")]
    assert names == ["check_axis", "setup_camera"]
