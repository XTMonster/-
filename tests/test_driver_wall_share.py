# F13：per-shot 墙钟前瞻均摊（driver 接线）。
# 真跑（final8/final9）实测全局墙钟是唯一时间护栏：单镜 ReAct/修复空转
# （一次 LLM 调用可达 190s+）可耗尽整场墙钟 -> CANCELLED，后续镜没有
# 生成机会。修复后：单镜超过自己的公平份额（剩余墙钟/剩余镜数）且未
# 过线时，保留 best、如实记 unfinished 并推进下一镜——不再停止生成。
# 判据/阈值一字不动（未过线照记 failed，F12 保证 failed 镜照常出 mp4）。
from __future__ import annotations

import json

from block_director.contracts.audit import AuditError, AuditResult
from block_director.contracts.enums import Purpose, Severity
from block_director.contracts.messages import ChatReply, FunctionCall, ToolCall
from block_director.layer5_orchestrator.budget import Budget, BudgetLimits
from block_director.layer5_orchestrator.driver import PrevisDriver
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
from stage_helpers import is_understand, understand_reply

SCRIPT = "INT. 咖啡馆 - 日\n\n小明坐下。\n"


class AdvancingClock:
    """可手动推进的 monotonic 时钟（driver + budget 共用）。"""

    def __init__(self):
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


class PerShotBuilder:
    def __init__(self):
        self.prepared = 0
        self.rebuilt: list = []

    def prepare_scene(self, plan, brief=None, spec=None):
        self.prepared += 1
        return {"characters": 2, "cameras": 0, "props": 0, "crowd": 0}

    def rebuild_shot(self, shot_id, *, plan=None, brief=None,
                     preserve_camera_edits=False):
        self.rebuilt.append(str(shot_id))
        return {"shot_id": shot_id, "warnings": [], "protected": [],
                "camera": f"BD_Cam_{shot_id}", "keyframes": 1,
                "characters": list(plan.shots[0].characters)
                if plan and plan.shots else []}

    def build(self, plan, brief=None):
        return {"shots": len(plan.shots)}


class FakeAuditor:
    def __init__(self, results, shots=("shot_001", "shot_002")):
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


class AdvancingTransport:
    """按阶段回放；每次 LLM 调用推进时钟（模拟慢模型）。"""

    def __init__(self, clock: AdvancingClock, dt_per_call: float = 100.0):
        self.clock = clock
        self.dt = dt_per_call
        self.chat_calls = 0
        self._editor_index = 0

    def chat(self, payload, timeout=120.0):
        self.clock.advance(self.dt)
        self.chat_calls += 1
        if is_understand(payload):
            self.chat_calls -= 1
            return understand_reply(payload.request_id)
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
                                arguments=json.dumps(draft,
                                                     ensure_ascii=False)))
            return ChatReply(tool_calls=[call])
        return ChatReply(tool_calls=[], content=None)

    def cancel(self, request_id):
        return None


class RepairingTransport(AdvancingTransport):
    def chat(self, payload, timeout=120.0):
        reply = super().chat(payload, timeout)
        if reply.tool_calls:
            return reply
        # 修复调用是"慢模型"主战场：一次推进 15000s，放大单次调用耗时，
        # 让 per-shot 份额可被触发（全局 max_wall 设 100000 保证有余量）。
        self.clock.advance(15000.0)
        call = ToolCall(id=f"fix_{self.chat_calls}",
                        function=FunctionCall(name="setup_camera",
                                              arguments="{}"))
        return ChatReply(tool_calls=[call], content=None)


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.add(name="emit_plan", description="plan",
                 parameters=EMIT_PLAN_TOOL_PARAMETERS,
                 handler=lambda **kwargs: "计划已接收")
    registry.add(name="emit_shot_draft", description="draft",
                 parameters={"type": "object", "properties": {}},
                 handler=lambda **kwargs: "草案已接收")
    registry.add(name="setup_camera", description="fix",
                 parameters={"type": "object", "additionalProperties": False,
                             "properties": {}},
                 handler=lambda: "相机已重设")
    return registry


def _driver(transport, auditor, builder, budget, **kwargs):
    return PrevisDriver(transport=transport, audit=AuditLogger(),
                        script=SCRIPT, registry=_registry(), auditor=auditor,
                        builder=builder, thread_factory=InlineThread,
                        budget=budget, **kwargs)


def _fail(rule="R001") -> AuditError:
    return AuditError(rule=rule, code="E_AXIS_001", severity=Severity.ERROR,
                      target="shot_001", message="轴线违规",
                      suggestion="移动相机")


def test_wall_share_exhausted_advances_to_next_shot():
    """单镜超公平份额且未过线 -> wall_share_exhausted -> 推进下一镜。

    max_wall=100000s、2 镜：understand/plan/editor 各 +100，每轮 repair
    +15100。第三轮 repair 后 elapsed_in_shot > 剩余墙钟/2（份额），而
    全局未撞线 -> 触发收尾推进，不把整场打成 CANCELLED；shot_001 记
    unfinished（如实），shot_002 正常完成。
    """
    clock = AdvancingClock()
    budget = Budget(limits=BudgetLimits(max_wall_seconds=100000.0),
                    clock=clock)
    auditor = FakeAuditor([
        AuditResult.from_findings([_fail()], target="shot_001"),
        AuditResult.from_findings([_fail()], target="shot_001"),
        AuditResult.from_findings([_fail()], target="shot_001"),
    ])
    builder = PerShotBuilder()
    driver = _driver(RepairingTransport(clock), auditor, builder, budget)
    assert driver.run_to_completion() is DriverState.DONE
    assert driver._shot_terminal.get("shot_001") == "unfinished"
    assert driver._shot_terminal.get("shot_002") == "passed"
    assert "shot_002" in driver._finished_shots
    assert not driver._wall_clock_exhausted
    events = [item.kind for item in driver.audit._recent]
    assert "wall_share_exhausted" in events
    advanced = next(
        event for event in driver.audit._recent
        if event.kind == "shot_advanced"
        and event.data.get("shot_id") == "shot_001")
    assert advanced.data["terminal_status"] == "unfinished"
    assert advanced.data["quality_pass"] is False
    assert "通过" not in advanced.message


def test_wall_share_disabled_preserves_old_behavior():
    """wall_share_enabled=False：即使单镜耗时可超份额，也不触发收尾，
    仍走旧路径（修复到过线 -> DONE），份额检查完全不介入。"""
    from block_director.contracts.config import AppConfig

    clock = AdvancingClock()
    budget = Budget(limits=BudgetLimits(max_wall_seconds=100000.0),
                    clock=clock)
    config = AppConfig()
    config.orchestration.wall_share_enabled = False
    auditor = FakeAuditor([
        AuditResult.from_findings([_fail()], target="shot_001"),
        AuditResult.from_findings([_fail()], target="shot_001"),
        AuditResult.from_findings([_fail()], target="shot_001"),
        AuditResult.from_findings([_fail()], target="shot_001"),
        AuditResult(passed=True, target="shot_001"),
    ])
    builder = PerShotBuilder()
    driver = _driver(RepairingTransport(clock), auditor, builder, budget,
                     config=config)
    assert driver.run_to_completion() is DriverState.DONE
    assert driver._shot_terminal.get("shot_001") == "passed"
    events = [item.kind for item in driver.audit._recent]
    assert "wall_share_exhausted" not in events


def test_wall_share_last_shot_never_triggers():
    """剩余 1 镜：整场墙钟归它，永不因份额收尾。"""
    clock = AdvancingClock()
    budget = Budget(limits=BudgetLimits(max_wall_seconds=100000.0),
                    clock=clock)
    auditor = FakeAuditor([
        AuditResult.from_findings([_fail()], target="shot_001"),
        AuditResult(passed=True, target="shot_001"),
    ], shots=("shot_001",))
    builder = PerShotBuilder()
    driver = _driver(RepairingTransport(clock), auditor, builder, budget)
    assert driver.run_to_completion() is DriverState.DONE
    assert driver._shot_terminal.get("shot_001") == "passed"
    events = [item.kind for item in driver.audit._recent]
    assert "wall_share_exhausted" not in events
