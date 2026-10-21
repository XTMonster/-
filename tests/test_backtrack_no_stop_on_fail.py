"""缺陷 B/D / U6（T6）：拦截错误后回溯而不停止；3 轮无新高才转 fail 继续。

驱动级闭环（纯层，无 bpy）：单镜分数序列 ``[55, 62, 55, 55, 55]``（第一版
55 为 best 基线，62 刷新 best，之后连续 3 版无新高）——状态机进入回溯循环，
不 CANCELLED、不停生成；第 3 次无新高后该镜记 ``failed``、推进下一镜。
"""

from __future__ import annotations

import json

from block_director.contracts.audit import AuditError, AuditResult
from block_director.contracts.config import AppConfig
from block_director.contracts.enums import Severity
from block_director.contracts.messages import (
    ChatReply,
    FunctionCall,
    ToolCall,
)
from block_director.layer5_orchestrator.driver import DriverLimits, PrevisDriver
from block_director.layer5_orchestrator.editor import (
    EMIT_SHOT_DRAFT_PARAMETERS,
)
from block_director.layer5_orchestrator.control_tools import (
    register_control_tools,
)
from block_director.layer5_orchestrator.planner import PLAN_TOOL_NAME
from block_director.layer5_orchestrator.states import DriverState
from block_director.layer6_audit.audit_logger import AuditLogger
from block_director.layer5_orchestrator.tool_registry import ToolRegistry

from stage_helpers import is_understand, understand_reply

SCRIPT = "INT. 咖啡馆 - 日\n\n小明坐下。\n"


class InlineThread:
    def __init__(self, target, name=""):
        self._target = target

    def start(self):
        self._target()


class ScriptedTransport:
    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = 0
        self.payloads = []
        self._editor_index = 0
        self._script_index = 0

    def chat(self, payload, timeout=120.0):
        if is_understand(payload):
            return understand_reply(payload.request_id)
        self.calls += 1
        self.payloads.append(payload)
        if str(payload.purpose) == "editor":
            from block_director.layer5_orchestrator.offline import demo_draft_dict

            draft = demo_draft_dict(self._editor_index)
            self._editor_index += 1
            call = ToolCall(id=f"draft_{self.calls}",
                            function=FunctionCall(
                                name="emit_shot_draft",
                                arguments=json.dumps(draft, ensure_ascii=False)))
            return ChatReply(tool_calls=[call], request_id=payload.request_id)
        item = self._replies[min(self._script_index, len(self._replies) - 1)]
        self._script_index += 1
        if item is None:
            return ChatReply(content="已经足够好", tool_calls=[],
                             request_id=payload.request_id)
        name, args = item
        call = ToolCall(id=f"c{self.calls}",
                        function=FunctionCall(name=name,
                                              arguments=json.dumps(args)))
        return ChatReply(tool_calls=[call], request_id=payload.request_id)

    def cancel(self, request_id):
        return None


class LadderAuditor:
    """shot_001 按分数阶梯出结果；shot_002 直接通过。"""

    def __init__(self, ladder):
        self.ladder = list(ladder)
        self.audited = []

    def shot_ids(self):
        return ["shot_001", "shot_002"]

    def audit(self, shot_id):
        if shot_id == "shot_001":
            index = min(len(self.ladder) - 1, len(self.audited))
            score = self.ladder[index]
            self.audited.append(shot_id)
            return AuditResult(passed=score > 80.0, target=shot_id, score=score,
                               errors=[] if score > 80.0 else [
                                   AuditError(rule="COMPOSITION",
                                              code="E_CAM_001",
                                              message=f"构图评分 {score:.0f} "
                                                      "低于阈值",
                                              severity=Severity.ERROR,
                                              target=shot_id,
                                              suggestion="回溯到最高分版本")])
        self.audited.append(shot_id)
        return AuditResult(passed=True, target=shot_id, score=88.0)


class StubBuilder:
    def build(self, plan, brief=None):
        return {"shots": len(plan.shots)}


PLAN_REPLY = (PLAN_TOOL_NAME, {"shots": [
    {"shot_id": "shot_001", "order": 1, "intent": "x", "shot_type": "MS",
     "duration_frames": 24},
    {"shot_id": "shot_002", "order": 2, "intent": "y", "shot_type": "CU",
     "duration_frames": 24}]})


def make_driver(transport, auditor, **kwargs):
    config = AppConfig()
    config.orchestration.react_max_steps = kwargs.pop("react_max_steps", 6)
    config.orchestration.react_max_rounds = kwargs.pop(
        "react_max_rounds", 4)
    config.orchestration.context_window_tokens = kwargs.pop("window", 32000)
    registry = kwargs.pop("registry", None)
    return PrevisDriver(transport=transport, audit=AuditLogger(), script=SCRIPT,
                        config=config, builder=StubBuilder(), auditor=auditor,
                        registry=registry,
                        limits=DriverLimits(max_repairs_per_shot=1),
                        thread_factory=InlineThread, **kwargs)


def _react_registry() -> ToolRegistry:
    """纯层工具表：计划/草案 + 只读 check_composition + 修改 setup_camera。"""
    registry = ToolRegistry()
    register_control_tools(registry)
    registry.add(
        name=PLAN_TOOL_NAME, description="plan",
        parameters={"type": "object", "additionalProperties": True,
                    "properties": {"shots": {"type": "array"}}},
        handler=lambda **kwargs: "计划已接收")
    registry.add(
        name="emit_shot_draft", description="draft",
        parameters=EMIT_SHOT_DRAFT_PARAMETERS,
        handler=lambda **kwargs: "草案已接收")
    registry.add(
        name="check_composition", description="检查构图",
        parameters={"type": "object", "additionalProperties": False,
                    "properties": {"shot_id": {"type": "string"}}},
        handler=lambda **kwargs: "构图 55 分")
    registry.add(
        name="setup_camera", description="重设相机",
        parameters={"type": "object", "additionalProperties": False,
                    "properties": {"shot_id": {"type": "string"},
                                   "shot_type": {"type": "string"}}},
        handler=lambda **kwargs: "相机已重设")
    return registry


def _run_backtrack(react_max_steps=2):
    """分数序列：首审 55（best 基线）→ 62（新高）→ 55/55/55（三次无新高）。"""
    auditor = LadderAuditor([55.0, 55.0, 62.0, 55.0, 55.0, 55.0, 55.0])
    transport = ScriptedTransport([
        PLAN_REPLY,
        ("setup_camera", {"shot_id": "shot_001", "shot_type": "MCU"}),  # B4
        None,                                                          # ReAct
    ])
    driver = make_driver(transport, auditor, react_max_steps=react_max_steps)
    state = driver.run_to_completion()
    return driver, state


def test_no_high_for_three_rounds_marks_fail_and_continues():
    driver, state = _run_backtrack()
    assert state is DriverState.DONE, f"不应整体 CANCELLED：{state}"
    terminal = driver.snapshot()["terminal_shots"]
    assert terminal.get("shot_001") == "failed", terminal
    assert terminal.get("shot_002") in ("passed", "finished"), terminal
    # 第二个镜头照常审核，没有被第一镜拖死
    assert "shot_002" in driver.auditor.audited
    # 回溯三态留痕：基线 new_high → 新高 new_high → 三次 revert
    trail = driver._react_scores.get("shot_001", [])
    dispositions = [item["disposition"] for item in trail]
    assert dispositions[:5] == ["new_high", "new_high",
                                "revert", "revert", "revert"], dispositions


def test_backtrack_never_stops_generation_on_interception():
    """拦截错误（构图 fail）后状态机进入回溯循环而不是停止。"""
    driver, state = _run_backtrack(react_max_steps=3)
    kinds = [event.kind for event in driver.audit.recent(200)]
    assert state is DriverState.DONE
    assert "react_started" in kinds and "react_finished" in kinds
    # 每次无新高都自动回滚（driver 应记录 revert 决策），不需要人停
    trail = driver._react_scores.get("shot_001", [])
    assert any(item["disposition"] == "revert" for item in trail)
    assert driver.snapshot()["terminal_shots"].get("shot_001") == "failed"


class LowScoreAuditor:
    """shot_001 永远给低分；shot_002 直接通过。

    与 LadderAuditor 的区别：分数**恒定**在 55，所以每次审核都是 tie——
    只有 R2-F11 的"总回合上限"或"连续只读轮"能终止 shot_001。
    """

    def __init__(self):
        self.audited = []

    def shot_ids(self):
        return ["shot_001", "shot_002"]

    def audit(self, shot_id):
        if shot_id == "shot_001":
            self.audited.append(shot_id)
            return AuditResult(passed=False, target=shot_id, score=55.0,
                               errors=[AuditError(
                                   rule="COMPOSITION", code="E_CAM_001",
                                   message="构图评分 55 低于阈值",
                                   severity=Severity.ERROR,
                                   target=shot_id,
                                   suggestion="回溯到最高分版本")])
        self.audited.append(shot_id)
        return AuditResult(passed=True, target=shot_id, score=88.0)


class ReadonlyReactTransport(ScriptedTransport):
    """ReAct 阶段按脚本返回工具调用；``mutate`` 决定是否先修改再收尾。"""

    def __init__(self, replies, *, mutate=False):
        super().__init__(replies)
        self.mutate = mutate
        self._react_step = 0

    def chat(self, payload, timeout=120.0):
        if is_understand(payload):
            return understand_reply(payload.request_id)
        if str(payload.purpose) == "editor":
            return super().chat(payload, timeout)
        if str(payload.purpose) == "react":
            self.calls += 1
            self.payloads.append(payload)
            step = self._react_step
            self._react_step += 1
            if self.mutate and step % 2 == 0:
                call = ToolCall(
                    id=f"mut_{self.calls}",
                    function=FunctionCall(
                        name="setup_camera",
                        arguments=json.dumps(
                            {"shot_id": "shot_001", "shot_type": "MCU"})))
                return ChatReply(tool_calls=[call],
                                 request_id=payload.request_id)
            if self.mutate and step % 2 == 1:
                call = ToolCall(
                    id=f"fin_{self.calls}",
                    function=FunctionCall(
                        name="finish_shot",
                        arguments=json.dumps({"shot_id": "shot_001"})))
                return ChatReply(tool_calls=[call],
                                 request_id=payload.request_id)
            call = ToolCall(
                id=f"ro_{self.calls}",
                function=FunctionCall(
                    name="check_composition",
                    arguments=json.dumps({"shot_id": "shot_001"})))
            return ChatReply(tool_calls=[call], request_id=payload.request_id)
        return super().chat(payload, timeout)

    def cancel(self, request_id):
        return None


def _run_round_exhausted(react_max_rounds=2):
    """shot_001 恒 55 分；ReAct 轮持续只读 → 回合上限耗尽即单镜失败。"""
    auditor = LowScoreAuditor()
    transport = ReadonlyReactTransport([
        PLAN_REPLY,
        ("setup_camera", {"shot_id": "shot_001", "shot_type": "MCU"}),  # B4
    ], mutate=True)
    driver = make_driver(transport, auditor,
                         react_max_rounds=react_max_rounds,
                         registry=_react_registry())
    state = driver.run_to_completion()
    return driver, state


def test_react_round_cap_marks_fail_and_continues():
    """R2-F11：每镜 ReAct 总回合上限耗尽仍未过 80 → 失败继续下一镜。"""
    driver, state = _run_round_exhausted(react_max_rounds=2)
    assert state is DriverState.DONE, f"不应整体停止：{state}"
    terminal = driver.snapshot()["terminal_shots"]
    assert terminal.get("shot_001") == "failed", terminal
    assert terminal.get("shot_002") in ("passed", "finished"), terminal
    assert "shot_002" in driver.auditor.audited
    kinds = [event.kind for event in driver.audit.recent(300)]
    assert "react_round_exhausted" in kinds, kinds
    assert driver._react_round_counts.get("shot_001", 0) >= 2


def test_readonly_rounds_trigger_terminal_fail():
    """R2-F11：连续一整回合（≥ react_max_steps 步）纯只读 = 无实质进展，
    触发单镜失败继续（不改 score 侧 no_gain，避免与审核 tie 双重计数）。"""
    auditor = LowScoreAuditor()
    transport = ReadonlyReactTransport([
        PLAN_REPLY,
        ("setup_camera", {"shot_id": "shot_001", "shot_type": "MCU"}),
    ])
    driver = make_driver(transport, auditor, react_max_rounds=0,
                         registry=_react_registry())
    state = driver.run_to_completion()
    assert state is DriverState.DONE, f"不应整体停止：{state}"
    terminal = driver.snapshot()["terminal_shots"]
    assert terminal.get("shot_001") == "failed", terminal
    assert terminal.get("shot_002") in ("passed", "finished"), terminal
    assert (driver._react_readonly_rounds.get("shot_001", 0)
            >= driver._react_max_steps())
    kinds = [event.kind for event in driver.audit.recent(300)]
    assert "react_terminal_fail" in kinds, kinds
