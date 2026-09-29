"""§3.3 驱动器状态机测试（用离线传输替代真实 LLM，确定性可断言）。"""

from __future__ import annotations

import json

from block_director.contracts.enums import MessageRole
from block_director.contracts.messages import ChatReply, FunctionCall, ToolCall, validate_conversation
from block_director.layer5_orchestrator.driver import DriverLimits, PrevisDriver
from block_director.layer5_orchestrator.offline import OfflineTransport, demo_plan_dict
from block_director.layer5_orchestrator.planner import PLAN_TOOL_NAME
from block_director.layer5_orchestrator.states import DriverState
from block_director.layer6_audit.audit_logger import AuditLogger

from stage_helpers import is_understand, understand_reply

SCRIPT = "INT. 咖啡馆 - 日\n\n小明坐下。\n"


class InlineThread:
    """同步执行器：让 LLM 调用在 start() 时立即完成，测试无需 sleep。"""

    def __init__(self, target, name=""):
        self._target = target

    def start(self):
        self._target()


class ScriptedTransport:
    """按脚本返回预设回复（可控地制造错误路径）。"""

    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = 0
        self.cancelled = []

    def chat(self, payload, timeout=120.0):
        # 阶段 S 不消耗脚本项、也不计入 calls：这里的脚本与计数都是
        # "计划/草案/修复"这条主线的，混进一次理解调用会让所有
        # 位置对应的断言整体错位一格。
        if is_understand(payload):
            return understand_reply(payload.request_id)
        self.calls += 1
        item = self._replies[min(self.calls - 1, len(self._replies) - 1)]
        if isinstance(item, Exception):
            raise item
        if isinstance(item, dict):
            # 单镜草案走 emit_shot_draft，计划走 emit_plan：脚本项本身不关心
            # 阶段名，按请求的 purpose 决定工具名。
            name = ("emit_shot_draft" if str(payload.purpose) == "editor"
                    else PLAN_TOOL_NAME)
            call = ToolCall(id=f"c{self.calls}",
                            function=FunctionCall(name=name,
                                                  arguments=json.dumps(item)))
            return ChatReply(tool_calls=[call])
        return item

    def cancel(self, request_id):
        self.cancelled.append(request_id)


def _driver(transport, audit=None, **kwargs):
    return PrevisDriver(transport=transport,
                        audit=audit or AuditLogger(),
                        script=SCRIPT,
                        thread_factory=InlineThread,
                        **kwargs)


def test_happy_path_reaches_done():
    driver = _driver(OfflineTransport())
    state = driver.run_to_completion()
    assert state is DriverState.DONE
    assert driver.plan is not None
    assert len(driver.plan.shots) == 2
    assert driver.snapshot()["total_frames"] == 216
    assert not driver.error


def test_conversation_stays_valid():
    """§3.4：驱动器自己构造的会话必须始终合法。"""
    driver = _driver(OfflineTransport())
    driver.run_to_completion()
    assert validate_conversation(driver.messages) == []
    roles = [m.role for m in driver.messages]
    assert roles == [MessageRole.ASSISTANT, MessageRole.TOOL]
    assert driver.messages[1].tool_call_id == driver.messages[0].tool_calls[0].id


def test_state_transitions_are_audited(tmp_path):
    audit = AuditLogger(directory=tmp_path)
    driver = _driver(OfflineTransport(), audit=audit)
    driver.run_to_completion()
    kinds = [event.kind for event in audit.recent()]
    assert kinds[0] == "run_started"
    assert "llm_request" in kinds
    assert "tool_call" in kinds
    assert "plan_received" in kinds
    assert kinds[-1] == "run_finished"
    # 状态迁移记录完整
    states = [e.message for e in audit.recent() if e.kind == "state"]
    # v1.3 起 IDLE 先去阶段 S（剧本理解），再进阶段 A
    assert states[0] == "IDLE → UNDERSTANDING"
    assert states[1] == "UNDERSTANDING → CALLING_LLM"
    assert "CALLING_LLM → PLANNING" in states
    assert states[-1].endswith("→ DONE")
    assert audit.trace_path.exists()


def test_llm_failure_retries_then_errors():
    limits = DriverLimits(plan_attempts=2)
    transport = ScriptedTransport([RuntimeError("network down")])
    driver = _driver(transport, limits=limits)
    state = driver.run_to_completion()
    assert state is DriverState.ERROR
    assert "分镜计划生成失败" in driver.error
    assert transport.calls == 2          # 用尽两次尝试


def test_transient_failure_recovers_on_retry():
    transport = ScriptedTransport([RuntimeError("flaky"),
                                   demo_plan_dict(SCRIPT)])
    driver = _driver(transport, limits=DriverLimits(plan_attempts=2))
    assert driver.run_to_completion() is DriverState.DONE
    assert transport.calls == 2


def test_invalid_plan_args_are_rejected_by_tool_schema():
    bad = demo_plan_dict(SCRIPT)
    bad["shots"][0]["shot_type"] = "XXXL"        # 非九种景别
    driver = _driver(ScriptedTransport([bad]), limits=DriverLimits(plan_attempts=1))
    assert driver.run_to_completion() is DriverState.ERROR
    assert "参数校验失败" in driver.error


def test_missing_plan_tool_call_is_reported():
    driver = _driver(ScriptedTransport([ChatReply(content="我想好了")]),
                     limits=DriverLimits(plan_attempts=1))
    assert driver.run_to_completion() is DriverState.ERROR
    assert "没有工具调用" in driver.error


def test_cancel_is_collaborative():
    driver = _driver(OfflineTransport())
    assert driver.step() is True          # IDLE → PLANNING
    driver.cancel()
    assert driver.run_to_completion() is DriverState.CANCELLED


def test_max_steps_guard():
    driver = _driver(OfflineTransport(), limits=DriverLimits(max_steps=2))
    state = driver.run_to_completion()
    assert state is DriverState.ERROR
    assert "最大步数" in driver.error


def test_step_after_terminal_is_noop():
    driver = _driver(OfflineTransport())
    driver.run_to_completion()
    assert driver.step() is False


def test_observers_receive_events():
    events = []
    driver = _driver(OfflineTransport())
    driver.add_observer(events.append)
    driver.run_to_completion()
    kinds = {event.kind for event in events}
    assert {"run_started", "state", "tool_call", "run_finished"} <= kinds


def test_broken_observer_does_not_break_run():
    def boom(_event):
        raise ValueError("observer bug")

    driver = _driver(OfflineTransport())
    driver.add_observer(boom)
    assert driver.run_to_completion() is DriverState.DONE


def test_unknown_tool_does_not_raise():
    reply = ChatReply(tool_calls=[ToolCall(
        id="c1", function=FunctionCall(name="does_not_exist", arguments="{}"))])
    driver = _driver(ScriptedTransport([reply]), limits=DriverLimits(plan_attempts=1))
    assert driver.run_to_completion() is DriverState.ERROR
    assert "工具不存在" in driver.error
