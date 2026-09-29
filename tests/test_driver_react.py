"""§7.1 阶段 B5：受限 ReAct 的闭环测试（纯驱动，不需要 Blender）。"""

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
from block_director.layer5_orchestrator.planner import PLAN_TOOL_NAME
from block_director.layer5_orchestrator.states import DriverState
from block_director.layer6_audit.audit_logger import AuditLogger

from stage_helpers import is_understand, understand_reply

SCRIPT = "INT. 咖啡馆 - 日\n\n小明坐下。\n"


class InlineThread:
    def __init__(self, target, name=""):
        self._target = target

    def start(self):
        self._target()


class ScriptedTransport:
    """按脚本回放；脚本项是 ``(tool_name, args)``，``None`` 表示"模型不再调用工具"。

    单镜草案（阶段 B1）不占用脚本：它按计划里的镜头顺序自动回放，
    这样脚本只描述"修复/精修"那几步，测试意图仍然清晰。
    """

    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = 0
        self.payloads = []
        self._editor_index = 0
        self._script_index = 0

    def chat(self, payload, timeout=120.0):
        if is_understand(payload):
            # 阶段 S 不占脚本项、也不计入 calls（见 stage_helpers）
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


class StubAuditor:
    """前 ``fail_times`` 次判失败（构图门），之后通过。"""

    def __init__(self, fail_times: int = 3):
        self.fail_times = fail_times
        self.audited = []

    def shot_ids(self):
        return ["shot_001", "shot_002"]

    def audit(self, shot_id):
        self.audited.append(shot_id)
        if shot_id == "shot_001" and self.audited.count("shot_001") <= self.fail_times:
            return AuditResult(passed=False, target=shot_id, score=55.0, errors=[
                AuditError(rule="COMPOSITION", code="E_CAM_001",
                           message="构图评分 55.0 低于阈值 70",
                           severity=Severity.ERROR, target=shot_id,
                           suggestion="重新构图")])
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
    config.orchestration.context_window_tokens = kwargs.pop("window", 32000)
    return PrevisDriver(transport=transport, audit=AuditLogger(), script=SCRIPT,
                        config=config, builder=StubBuilder(), auditor=auditor,
                        limits=DriverLimits(max_repairs_per_shot=1),
                        thread_factory=InlineThread, **kwargs)


# --------------------------------------------------------------------------- #
# 进入 B5 并靠工具修好
# --------------------------------------------------------------------------- #
def test_react_round_fixes_the_shot_and_finishes():
    auditor = StubAuditor(fail_times=3)      # 初次 + 复核 + B5 后的复核之前
    transport = ScriptedTransport([
        PLAN_REPLY,
        ("setup_camera", {"shot_id": "shot_001", "shot_type": "CU"}),  # B4
        ("setup_camera", {"shot_id": "shot_001", "shot_type": "MCU"}),  # B5 第 1 步
        None,                                                          # B5 停止
    ])
    driver = make_driver(transport, auditor)
    state = driver.run_to_completion()
    kinds = [event.kind for event in driver.audit.recent(200)]

    assert state is DriverState.DONE
    assert "react_started" in kinds and "react_finished" in kinds
    assert driver.react_history == [
        {"shot_id": "shot_001", "steps": 2, "reason": "模型停止调用工具"}]
    assert driver.snapshot()["react_rounds"] == 1
    # 两个镜头都过了
    assert auditor.audited.count("shot_001") >= 3
    assert "shot_002" in auditor.audited


def test_react_payload_is_auto_tool_choice_and_carries_the_registry():
    transport = ScriptedTransport([PLAN_REPLY,
                                   ("setup_camera", {"shot_id": "shot_001"}),
                                   ("setup_camera", {"shot_id": "shot_001"}),
                                   None])
    driver = make_driver(transport, StubAuditor(fail_times=3))
    driver.run_to_completion()
    react_payloads = [item for item in transport.payloads
                      if str(item.purpose) == "react"]
    assert react_payloads, "应当发起过 ReAct 请求"
    first = react_payloads[0]
    assert str(first.tool_choice) == "auto"
    assert any(tool["function"]["name"] == PLAN_TOOL_NAME
               or tool["function"]["name"] == "setup_camera"
               for tool in first.tools)
    assert "精修" in first.messages[0].content


# --------------------------------------------------------------------------- #
# 上限与开关
# --------------------------------------------------------------------------- #
def test_react_stops_at_the_step_limit():
    transport = ScriptedTransport([
        PLAN_REPLY,
        ("setup_camera", {"shot_id": "shot_001"}),
        ("setup_camera", {"shot_id": "shot_001"}),      # B5 第 1 步
        ("setup_camera", {"shot_id": "shot_001"}),      # B5 第 2 步（到顶）
    ])
    driver = make_driver(transport, StubAuditor(fail_times=9),
                         react_max_steps=2)
    driver.run_to_completion()
    assert driver.react_history[0]["steps"] == 2
    assert "步数上限" in driver.react_history[0]["reason"]


def test_react_is_skipped_when_disabled():
    transport = ScriptedTransport([PLAN_REPLY,
                                   ("setup_camera", {"shot_id": "shot_001"})])
    driver = make_driver(transport, StubAuditor(fail_times=9),
                         react_max_steps=0)
    driver.run_to_completion()
    kinds = [event.kind for event in driver.audit.recent(200)]
    assert driver.react_history == []
    assert "react_started" not in kinds
    assert "shot_degraded" in kinds            # 回到原有的降级路径


def test_react_runs_at_most_once_per_shot():
    """B5 之后仍然不过时，不该无限精修——每个镜头只给一次。"""
    transport = ScriptedTransport([PLAN_REPLY,
                                   ("setup_camera", {"shot_id": "shot_001"}),
                                   ("setup_camera", {"shot_id": "shot_001"}),
                                   None])
    driver = make_driver(transport, StubAuditor(fail_times=99))
    driver.run_to_completion()
    assert len(driver.react_history) == 1
    assert driver._react_done == {"shot_001"}


# --------------------------------------------------------------------------- #
# §3.5 上下文治理在真实循环里生效
# --------------------------------------------------------------------------- #
def test_react_conversation_is_trimmed_to_the_window():
    from block_director.layer5_orchestrator.driver import default_registry

    transport = ScriptedTransport([
        PLAN_REPLY,
        ("setup_camera", {"shot_id": "shot_001"}),
        ("setup_camera", {"shot_id": "shot_001"}),
        ("setup_camera", {"shot_id": "shot_001"}),
        ("setup_camera", {"shot_id": "shot_001"}),
        None])
    # 让工具每次都返回一大段观察，才逼得出裁剪（真实场景里是场景状态快照）
    registry = default_registry()
    registry.add(name="setup_camera", description="x",
                 parameters={"type": "object", "additionalProperties": True},
                 handler=lambda **kw: "机位已调整：" + "说" * 200)
    driver = make_driver(transport, StubAuditor(fail_times=9),
                         react_max_steps=4, window=600, registry=registry)
    driver.run_to_completion()
    kinds = [event.kind for event in driver.audit.recent(400)]
    from block_director.layer5_orchestrator.context_budget import count_tokens
    react_payloads = [item for item in transport.payloads
                      if str(item.purpose) == "react"]
    assert "context_trimmed" in kinds, "窗口很小，应当发生裁剪"
    assert all(count_tokens(item.messages) <= 600 for item in react_payloads)
