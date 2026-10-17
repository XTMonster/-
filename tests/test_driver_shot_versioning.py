"""逐镜版本历史（shot versioning）接进 driver 的测试。

覆盖（SPEC_wire_shot_versioning_20261012_v2）：
- 每镜每次审核都留一版（initial/repair/rollback），restore 只读深拷贝；
- resume_state 往返后版本历史不丢，新 driver 能恢复同长历史；
- 换镜（_advance_shot）不清历史；缺失镜 restore 抛 KeyError。

全部通过公开行为断言；不触碰阈值/判据/既有测试。
"""

from __future__ import annotations

import json

from block_director.contracts.audit import AuditError, AuditResult
from block_director.contracts.enums import Purpose, Severity
from block_director.contracts.messages import ChatReply, FunctionCall, ToolCall
from block_director.layer5_orchestrator.driver import (
    RESUME_STATE_FILENAME,
    PrevisDriver,
    load_resume_state,
    save_resume_state,
)
from block_director.layer5_orchestrator.offline import (
    demo_draft_dict,
    demo_plan_dict,
)
from block_director.layer5_orchestrator.planner import EMIT_PLAN_TOOL_PARAMETERS
from block_director.layer5_orchestrator.tool_registry import ToolRegistry
from block_director.layer6_audit.audit_logger import AuditLogger

from test_driver import InlineThread
from stage_helpers import is_understand, understand_reply

SCRIPT = "INT. 咖啡馆 - 日\n\n小明坐下。\n"


def failing(rules, *, score=60.0):
    errors = [AuditError(rule=rule, code=f"E_{rule}", severity=Severity.ERROR,
                         target="shot_001", message=f"{rule} 红", suggestion="改")
              for rule in rules]
    return AuditResult(passed=False, level="rule", errors=errors, score=score)


class PerShotBuilder:
    """支持 prepare_scene + rebuild_shot 的假 builder（方案 B 主路径）。"""

    def __init__(self):
        self.prepared = 0
        self.rebuilt: list = []
        self.built = 0

    def prepare_scene(self, plan, brief=None, spec=None):
        self.prepared += 1
        return {"characters": 2, "cameras": 0, "props": 0,
                "crowd": 0, "prepared_at": "2026-10-12T00:00:00+00:00"}

    def rebuild_shot(self, shot_id, *, plan=None, brief=None):
        self.rebuilt.append({"shot_id": shot_id, "plan": plan})
        return {"shot_id": shot_id, "warnings": [], "protected": [],
                "camera": f"BD_Cam_{shot_id}", "keyframes": 1,
                "characters": list(plan.shots[0].characters)
                if plan and plan.shots else []}

    def build(self, plan, brief=None):
        self.built += 1
        return {"shots": len(plan.shots)}


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


class PerShotTransport:
    """按阶段回放：理解 → 计划 → 每镜草案（B1）。"""

    def __init__(self):
        self.chat_calls = 0
        self._editor_index = 0

    def chat(self, payload, timeout=120.0):
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
                                arguments=json.dumps(draft, ensure_ascii=False)))
            return ChatReply(tool_calls=[call])
        return ChatReply(tool_calls=[], content=None)

    def cancel(self, request_id):
        return None


class RepairingTransport(PerShotTransport):
    """在草案后追加一个修复工具调用（setup_camera）。"""

    def chat(self, payload, timeout=120.0):
        reply = super().chat(payload, timeout)
        if reply.tool_calls:
            return reply
        call = ToolCall(id=f"fix_{self.chat_calls}",
                        function=FunctionCall(name="setup_camera",
                                              arguments="{}"))
        return ChatReply(tool_calls=[call], content=None)


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.add(
        name="emit_plan", description="plan",
        parameters=EMIT_PLAN_TOOL_PARAMETERS,
        handler=lambda **kwargs: "计划已接收")
    registry.add(name="setup_camera", description="fix",
                 parameters={"type": "object", "additionalProperties": False,
                             "properties": {}},
                 handler=lambda: "相机已重设")
    return registry


def _driver(transport, auditor, builder, **kwargs):
    return PrevisDriver(transport=transport, audit=AuditLogger(), script=SCRIPT,
                        registry=_registry(), auditor=auditor, builder=builder,
                        thread_factory=InlineThread, **kwargs)


def _history(driver, shot_id):
    return driver._shot_versions[str(shot_id)]


def test_every_audit_round_records_a_version_and_restore_is_readonly():
    """先失败后通过：一镜留两版（initial/repair），restore 是只读深拷贝。"""
    builder = PerShotBuilder()
    auditor = FakeAuditor([failing(["R003"]),
                           AuditResult(passed=True, target="shot_001")])
    driver = _driver(RepairingTransport(), auditor, builder)

    assert driver.run_to_completion() is not None
    history = _history(driver, "shot_001")
    assert len(history) == 2
    assert [item.reason for item in
            (history.get(0), history.get(1))] == ["initial", "repair"]

    restored = driver.restore_shot_version("shot_001", 0)
    assert isinstance(restored, dict)
    assert restored == driver.plan.to_dict()
    #: 只读：改动返回值不得影响当前计划或历史。
    restored["shots"][0]["duration_frames"] = 1
    restored["scene_heading"] = "被篡改"
    assert driver.plan.to_dict() != restored
    assert history.get(0).plan != restored
    assert history.get(0).plan == driver.plan.to_dict()


def test_rollback_round_is_marked_as_rollback_version():
    """{R003} → {R003,R001} → pass：回滚后的那次审核标记为 rollback。"""
    builder = PerShotBuilder()
    auditor = FakeAuditor([
        failing(["R003"]),
        failing(["R003", "R001"]),
        AuditResult(passed=True, target="shot_001"),
    ])
    driver = _driver(RepairingTransport(), auditor, builder)

    assert driver.run_to_completion() is not None
    reasons = [item.reason for item in
               [driver._shot_versions["shot_001"].get(i)
                for i in range(len(driver._shot_versions["shot_001"]))]]
    assert "rollback" in reasons
    assert "repair_rolled_back" in [e.kind for e in driver.audit.recent()]


def test_version_histories_survive_resume_state_round_trip(tmp_path):
    """checkpoint 落盘 → load → 新 driver 恢复同长版本历史。"""
    path = tmp_path / "sub" / RESUME_STATE_FILENAME
    builder = PerShotBuilder()
    auditor = FakeAuditor([failing(["R003"]),
                           AuditResult(passed=True, target="shot_001")])
    driver = _driver(RepairingTransport(), auditor, builder,
                     resume_state_path=path)

    assert driver.run_to_completion() is not None
    state = load_resume_state(path)
    assert state.version_histories, "checkpoint 必须带上版本历史"
    assert len(state.version_histories["shot_001"]) == 2

    second = tmp_path / "second" / RESUME_STATE_FILENAME
    save_resume_state(second, state)
    loaded = load_resume_state(second)
    assert loaded.to_dict() == state.to_dict()

    resumed = _driver(PerShotTransport(), FakeAuditor([]), PerShotBuilder(),
                      resume_state=loaded, resume_state_path=path)
    assert len(resumed._shot_versions["shot_001"]) == 2
    assert resumed._shot_versions["shot_001"].get(0).reason == "initial"


def test_advance_shot_keeps_history_of_previous_shots():
    """换镜前进不清历史：两镜跑完后两镜的版本都还在。"""
    builder = PerShotBuilder()
    auditor = FakeAuditor(
        [AuditResult(passed=True, target="shot_001"),
         AuditResult(passed=True, target="shot_002")],
        shots=("shot_001", "shot_002"))
    driver = _driver(PerShotTransport(), auditor, builder)

    assert driver.run_to_completion() is not None
    assert "shot_001" in driver._shot_versions
    assert "shot_002" in driver._shot_versions
    assert len(driver._shot_versions["shot_001"]) == 1
    assert len(driver._shot_versions["shot_002"]) == 1


def test_restore_without_history_raises_key_error():
    """没有版本历史的镜 restore 必须抛 KeyError，不猜不吞。"""
    driver = _driver(PerShotTransport(), FakeAuditor([]), PerShotBuilder())
    try:
        driver.restore_shot_version("shot_001", 0)
    except KeyError:
        pass
    else:
        raise AssertionError("restore_shot_version 应当抛 KeyError")
