"""§7.1 阶段 B3/B4：校验 → 定向修复闭环的驱动器测试。"""

from __future__ import annotations

import json

import pytest

from block_director.contracts.audit import AuditError, AuditResult
from block_director.contracts.enums import Purpose, Severity
from block_director.contracts.messages import ChatReply, FunctionCall, ToolCall
from block_director.layer5_orchestrator.auditor import NullAuditor, ShotAuditor
from block_director.layer5_orchestrator.driver import DriverLimits, PrevisDriver
from block_director.layer5_orchestrator.offline import (
    OfflineTransport,
    demo_draft_dict,
    demo_plan_dict,
)
from block_director.layer5_orchestrator.planner import EMIT_PLAN_TOOL_PARAMETERS
from block_director.layer5_orchestrator.states import DriverState
from block_director.layer5_orchestrator.tool_registry import ToolRegistry
from block_director.layer6_audit.audit_logger import AuditLogger

from test_driver import InlineThread

SCRIPT = "INT. 咖啡馆 - 日\n\n小明坐下。\n"


def axis_finding() -> AuditError:
    return AuditError(rule="R001", code="E_AXIS_001", severity=Severity.ERROR,
                      target="shot_001",
                      message="相机位置违反 180° 轴线规则，可能导致角色左右方向混乱。",
                      suggestion="将相机移到轴线另一侧，或插入中性镜头过渡。")


class FakeAuditor:
    def __init__(self, results, shots=("shot_001",)):
        self._results = list(results)
        self._shots = list(shots)
        self.calls = []

    def shot_ids(self):
        return list(self._shots)

    def audit(self, shot_id):
        self.calls.append(shot_id)
        if self._results:
            return self._results.pop(0)
        return AuditResult(passed=True, target=shot_id)


class RepairingTransport:
    """按阶段回放：计划 → 单镜草案（B1）→ 修复工具调用。"""

    def __init__(self, tool_name="fix_camera"):
        self.tool_name = tool_name
        self.payloads = []
        self.chat_calls = 0
        self._editor_index = 0

    def chat(self, payload, timeout=120.0):
        self.chat_calls += 1
        self.payloads.append(payload)
        if payload.purpose is Purpose.PLAN:
            call = ToolCall(id=f"plan_{self.chat_calls}",
                            function=FunctionCall(
                                name="emit_plan",
                                arguments=json.dumps(demo_plan_dict(SCRIPT))))
            return ChatReply(tool_calls=[call])
        if payload.purpose is Purpose.EDITOR:
            draft = demo_draft_dict(self._editor_index)
            self._editor_index += 1
            call = ToolCall(id=f"draft_{self.chat_calls}",
                            function=FunctionCall(
                                name="emit_shot_draft",
                                arguments=json.dumps(draft, ensure_ascii=False)))
            return ChatReply(tool_calls=[call])
        call = ToolCall(id=f"fix_{self.chat_calls}",
                        function=FunctionCall(name=self.tool_name,
                                              arguments="{}"))
        return ChatReply(tool_calls=[call], content=None)

    def cancel(self, request_id):
        return None


class TrivialBuilder:
    """审核是针对**已建成**的场景做的，所以测试必须给一个构建器。"""

    def __init__(self):
        self.built = []

    def build(self, plan):
        self.built.append(plan)
        return {"shots": len(plan.shots), "characters": 2, "cameras": 2,
                "motions": 0, "keyframes": 0,
                "total_frames": plan.total_frames, "warnings": [],
                "results": []}


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.add(
        name="emit_plan", description="plan",
        parameters=EMIT_PLAN_TOOL_PARAMETERS,
        handler=lambda **kwargs: "计划已接收")
    registry.add(name="fix_camera", description="fix",
                 parameters={"type": "object", "additionalProperties": False,
                             "properties": {}},
                 handler=lambda: "相机已重设")
    return registry


def _driver(transport, auditor, **kwargs):
    builder = kwargs.pop("builder", None) or TrivialBuilder()
    return PrevisDriver(transport=transport, audit=AuditLogger(), script=SCRIPT,
                        registry=_registry(), auditor=auditor, builder=builder,
                        thread_factory=InlineThread, **kwargs)


def test_null_auditor_satisfies_protocol_and_skips_checking():
    assert isinstance(NullAuditor(), ShotAuditor)
    transport = OfflineTransport()
    driver = _driver(transport, NullAuditor())
    assert driver.run_to_completion() is DriverState.DONE
    assert driver.audit_results == []


def test_clean_audit_finishes_without_any_repair():
    transport = RepairingTransport()
    driver = _driver(transport, FakeAuditor([AuditResult(passed=True,
                                                         target="shot_001")]))
    assert driver.run_to_completion() is DriverState.DONE
    # 计划 + 每镜一次单镜草案（B1），没有修复调用
    assert transport.chat_calls == 1 + len(demo_plan_dict(SCRIPT)["shots"])
    assert Purpose.REPAIR not in [p.purpose for p in transport.payloads]
    assert len(driver.audit_results) == 1


def test_failure_triggers_repair_then_passes():
    transport = RepairingTransport()
    auditor = FakeAuditor([
        AuditResult.from_findings([axis_finding()], target="shot_001"),
        AuditResult(passed=True, target="shot_001"),
    ])
    driver = _driver(transport, auditor)
    assert driver.run_to_completion() is DriverState.DONE

    purposes = [p.purpose for p in transport.payloads]
    # 计划 → 两镜草案 → 修复（§7.1 的 A → B1 → B4）
    assert purposes == [Purpose.PLAN, Purpose.EDITOR, Purpose.EDITOR,
                        Purpose.REPAIR]
    assert len(auditor.calls) == 2
    assert driver.audit_results[0].passed is False
    assert driver.audit_results[-1].passed is True


def test_repair_payload_carries_structured_findings():
    transport = RepairingTransport()
    auditor = FakeAuditor([
        AuditResult.from_findings([axis_finding()], score=61.9, target="shot_001"),
        AuditResult(passed=True, target="shot_001"),
    ])
    _driver(transport, auditor).run_to_completion()

    repair_payload = [p for p in transport.payloads
                      if p.purpose is Purpose.REPAIR][0]
    system_text = repair_payload.messages[0].content
    assert "[R001]" in system_text
    assert "target=shot_001" in system_text
    assert "建议：将相机移到轴线另一侧" in system_text
    assert "评分 61.9" in system_text
    assert repair_payload.tool_choice.value == "required"
    assert {t["function"]["name"] for t in repair_payload.tools} >= {"fix_camera"}


def test_repair_uses_the_repair_temperature():
    from block_director.contracts.config import AppConfig

    config = AppConfig()
    config.llm.temperature_repair = 0.05
    config.llm.temperature_plan = 0.9
    transport = RepairingTransport()
    auditor = FakeAuditor([
        AuditResult.from_findings([axis_finding()], target="shot_001"),
        AuditResult(passed=True, target="shot_001")])
    _driver(transport, auditor, config=config).run_to_completion()
    temperatures = {p.purpose: p.temperature for p in transport.payloads}
    assert temperatures[Purpose.PLAN] == 0.9
    assert temperatures[Purpose.REPAIR] == 0.05


def test_repeated_failure_degrades_instead_of_erroring():
    transport = RepairingTransport()
    failing = AuditResult.from_findings([axis_finding()], target="shot_001")
    auditor = FakeAuditor([failing] * 6)
    driver = _driver(transport, auditor,
                     limits=DriverLimits(max_repairs_per_shot=2))
    assert driver.run_to_completion() is DriverState.DONE
    repairs = [p for p in transport.payloads if p.purpose is Purpose.REPAIR]
    assert len(repairs) == 2                  # 上限就是 2 次
    kinds = [e.kind for e in driver.audit.recent()]
    assert "shot_degraded" in kinds


def test_repair_tool_calls_are_executed():
    """修复不是"说说而已"：工具必须真的被调用。"""
    transport = RepairingTransport(tool_name="fix_camera")
    auditor = FakeAuditor([
        AuditResult.from_findings([axis_finding()], target="shot_001"),
        AuditResult(passed=True, target="shot_001")])
    driver = _driver(transport, auditor)
    driver.run_to_completion()
    tools_used = [e.data.get("tool") for e in driver.audit.recent()
                  if e.kind == "tool_call"]
    assert "fix_camera" in tools_used
    assert driver.snapshot()["repairs"] == 1


def test_auditor_exception_degrades_that_shot():
    class BrokenAuditor:
        def shot_ids(self):
            return ["shot_001"]

        def audit(self, shot_id):
            raise RuntimeError("审核器炸了")

    driver = _driver(RepairingTransport(), BrokenAuditor())
    assert driver.run_to_completion() is DriverState.DONE
    kinds = [e.kind for e in driver.audit.recent()]
    assert "audit_failed" in kinds


def test_multiple_shots_are_audited_in_order():
    transport = RepairingTransport()
    auditor = FakeAuditor([], shots=("shot_001", "shot_002"))
    driver = _driver(transport, auditor)
    assert driver.run_to_completion() is DriverState.DONE
    assert auditor.calls == ["shot_001", "shot_002"]
    assert driver.snapshot()["shots_remaining"] == 0
