"""R2 ticket 09：sidecar 502 的有界重试。

502 是瞬时 5xx，不是超时 ⇒ 走 ``retry_same``（同一份载荷再发一次）。
同一次调用的重试有上限（``RetryPolicy.max_attempts=2``），超限必须如实
结束（不无限重试、不假装成功），且个别 502 之后的成功请求照常继续。
"""
from __future__ import annotations

import json

from block_director.contracts.audit import (
    AuditError,
    AuditResult,
    missing_event_fields,
)
from block_director.contracts.enums import Purpose, Severity
from block_director.contracts.messages import ChatReply, FunctionCall, ToolCall
from block_director.layer5_orchestrator.driver import DriverLimits, PrevisDriver
from block_director.layer5_orchestrator.offline import demo_draft_dict, demo_plan_dict
from block_director.layer5_orchestrator.planner import EMIT_PLAN_TOOL_PARAMETERS
from block_director.layer5_orchestrator.states import DriverState
from block_director.layer5_orchestrator.tool_registry import ToolRegistry
from block_director.layer6_audit.audit_logger import AuditLogger

from stage_helpers import is_understand, understand_reply
from test_driver_repair import FakeAuditor, TrivialBuilder

SCRIPT = "INT. 咖啡馆 - 日\n\n小明坐下。\n"


def _axis_finding() -> AuditError:
    return AuditError(rule="R001", code="E_AXIS_001", severity=Severity.ERROR,
                      target="shot_001",
                      message="相机位置违反 180° 轴线规则。",
                      suggestion="将相机移到轴线另一侧。")


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.add(name="emit_plan", description="plan",
                 parameters=EMIT_PLAN_TOOL_PARAMETERS,
                 handler=lambda **kwargs: "计划已接收")
    registry.add(name="setup_camera", description="fix",
                 parameters={"type": "object", "properties": {}},
                 handler=lambda: "相机已重设")
    return registry


class Sidecar502Transport:
    """understand/plan/editor 自动回放；repair 按脚本（Exception 或 None）。"""

    def __init__(self, repair_script=()):
        self.repair_script = list(repair_script)
        self._repair_i = 0
        self._editor_index = 0
        self.payloads = []   # type: list

    def chat(self, payload, timeout=120.0):
        if is_understand(payload):
            return understand_reply(payload.request_id)
        self.payloads.append(payload)
        if payload.purpose is Purpose.PLAN:
            call = ToolCall(id=f"plan_{len(self.payloads)}",
                            function=FunctionCall(
                                name="emit_plan",
                                arguments=json.dumps(demo_plan_dict(SCRIPT))))
            return ChatReply(tool_calls=[call], request_id=payload.request_id)
        if payload.purpose is Purpose.EDITOR:
            draft = demo_draft_dict(self._editor_index)
            self._editor_index += 1
            call = ToolCall(id=f"draft_{len(self.payloads)}",
                            function=FunctionCall(
                                name="emit_shot_draft",
                                arguments=json.dumps(draft, ensure_ascii=False)))
            return ChatReply(tool_calls=[call], request_id=payload.request_id)
        if payload.purpose is Purpose.REPAIR:
            item = self.repair_script[min(
                self._repair_i, len(self.repair_script) - 1)]
            self._repair_i += 1
            if isinstance(item, Exception):
                raise item
            call = ToolCall(id=f"fix_{self._repair_i}",
                            function=FunctionCall(name="setup_camera",
                                                  arguments="{}"))
            return ChatReply(tool_calls=[call], request_id=payload.request_id)
        return ChatReply(content="", request_id=payload.request_id)

    def cancel(self, request_id):
        return None


def _driver(transport, results, *, limits=None, scene_state_provider=None):
    return PrevisDriver(
        transport=transport, audit=AuditLogger(), script=SCRIPT,
        registry=_registry(), auditor=FakeAuditor(results),
        builder=TrivialBuilder(), thread_factory=InlineThread,
        limits=limits or DriverLimits(),
        scene_state_provider=scene_state_provider)


class InlineThread:
    def __init__(self, target, name=""):
        self._target = target

    def start(self):
        self._target()


def _ladder_events(driver):
    return [event for event in driver.audit.recent()
            if event.kind == "retry_ladder"]


def test_502_retries_are_bounded_and_fail_shot_then_continue():
    """连续 502（非超时）⇒ 原样重试一次 ⇒ 上限耗尽记 failed 并继续下一镜。

    用户红线：拦截错误后回溯而不停止生成——瞬时 5xx 阶梯耗尽不能把整条链
    CANCELLED 停机，而是保留最高分、记该镜 failed、继续推进（白模预演视频
    仍要生成）。重试本身仍有上限：同一调用绝无第三次。
    """
    transport = Sidecar502Transport(repair_script=[
        RuntimeError("HTTP 502 Bad Gateway"),
        RuntimeError("HTTP 502 Bad Gateway"),
    ])
    failing = AuditResult.from_findings([_axis_finding()], target="shot_001")
    driver = _driver(transport, [failing, failing],
                     scene_state_provider=lambda: "小明在桌边")

    assert driver.run_to_completion() is DriverState.DONE
    terminal = driver.snapshot()["terminal_shots"]
    assert terminal.get("shot_001") == "failed", terminal
    assert "shot_advanced" in [e.kind for e in driver.audit.recent()]

    repairs = [p for p in transport.payloads
               if p.purpose is Purpose.REPAIR]
    assert len(repairs) == 2, "同一次调用的 502 重试有上限，不能无限重试"
    events = _ladder_events(driver)
    assert [e.data["stage"] for e in events] == ["same_retry", "degrade"]
    assert all(missing_event_fields("retry_ladder", e.data) == []
               for e in events)


def test_502_then_success_continues_the_flow():
    """一次 502 后恢复 ⇒ 同一负载重发一次成功，流程照常走到 DONE。"""
    transport = Sidecar502Transport(repair_script=[
        RuntimeError("HTTP 502 Bad Gateway"), None])
    failing = AuditResult.from_findings([_axis_finding()], target="shot_001")
    driver = _driver(transport, [failing,
                                 AuditResult(passed=True, target="shot_001")],
                     scene_state_provider=lambda: "小明在桌边")

    assert driver.run_to_completion() is DriverState.DONE

    repairs = [p for p in transport.payloads
               if p.purpose is Purpose.REPAIR]
    assert len(repairs) == 2
    events = _ladder_events(driver)
    assert [e.data["stage"] for e in events] == ["same_retry"]
    kinds = [e.kind for e in driver.audit.recent()]
    assert "shot_degraded" not in kinds, "502 重试成功后不应降级"
