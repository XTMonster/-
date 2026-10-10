"""§7.1 B5 触发规则 / §3.5 上下文治理的纯计算测试。"""

from __future__ import annotations

from block_director.contracts.audit import AuditError, AuditResult
from block_director.contracts.enums import MessageRole, Purpose, ToolChoice
from block_director.contracts.messages import Message, ToolCall, FunctionCall
from block_director.contracts.plan import Plan, ShotPlan
from block_director.layer5_orchestrator.context_budget import (
    budget_report,
    count_tokens,
    trim_messages,
)
from block_director.layer5_orchestrator.control_tools import FINISH_SHOT
from block_director.layer5_orchestrator.react import (
    build_react_payload,
    render_shot_memory,
    should_react,
    shot_memory,
)
from block_director.layer5_orchestrator.tool_registry import ToolRegistry


def shot(characters=("char_001",)) -> ShotPlan:
    return ShotPlan.from_dict({
        "shot_id": "shot_001", "order": 1, "intent": "精修这一镜",
        "shot_type": "MS", "duration_frames": 48,
        "characters": list(characters)})


def failed(score=None, rule="R001") -> AuditResult:
    return AuditResult(passed=False, target="shot_001", score=score, errors=[
        AuditError(rule=rule, code="E_X", message="有问题",
                   target="shot_001", suggestion="改一下")])


# --------------------------------------------------------------------------- #
# B5 触发条件
# --------------------------------------------------------------------------- #
def test_react_is_off_when_the_step_budget_is_zero():
    assert should_react(shot(), failed(50.0), max_steps=0) is False


def test_react_waits_until_b4_is_exhausted():
    assert should_react(shot(), failed(50.0), repairs_exhausted=False) is False
    assert should_react(shot(), failed(50.0), repairs_exhausted=True) is True


def test_low_composition_score_triggers_react():
    assert should_react(shot(), failed(58.0), composition_threshold=70.0) is True
    assert should_react(shot(), failed(88.0), composition_threshold=70.0) is False


def test_composition_rule_error_triggers_even_without_a_score():
    assert should_react(shot(), failed(None, rule="COMPOSITION")) is True
    assert should_react(shot(), failed(None, rule="R001")) is False


def test_three_or_more_characters_always_qualify():
    crowded = shot(("char_001", "char_002", "char_003"))
    assert should_react(crowded, failed(95.0)) is True


def test_explicit_user_request_bypasses_the_other_conditions():
    assert should_react(shot(), failed(95.0), repairs_exhausted=False,
                        user_requested=True) is True


def test_missing_shot_or_result_is_handled():
    assert should_react(None, failed(50.0)) is False
    assert should_react(shot(), None) is False


# --------------------------------------------------------------------------- #
# B5 请求构造
# --------------------------------------------------------------------------- #
def test_react_payload_lets_the_model_stop():
    registry = ToolRegistry()
    registry.add(name="check_composition", description="x",
                 parameters={"type": "object"}, handler=lambda **kw: "ok")
    registry.add(name=FINISH_SHOT, description="完成当前镜头",
                 parameters={"type": "object"}, handler=lambda **kw: "ok")
    payload = build_react_payload(shot(), failed(50.0), scene_state="场景",
                                  registry=registry, max_steps=4)
    assert payload.purpose is Purpose.REACT
    assert payload.tool_choice is ToolChoice.REQUIRED  # 与 B4 相同：必须工具调用
    assert payload.tools and payload.tools[0]["function"]["name"] == "check_composition"
    system = payload.messages[0].content
    assert "最多 4 步" in system and "shot_001" in payload.messages[1].content


def test_react_payload_without_a_registry_has_no_tools():
    payload = build_react_payload(shot(), failed(50.0))
    assert payload.tools == [] and payload.tool_choice is ToolChoice.REQUIRED


# --------------------------------------------------------------------------- #
# 跨镜头记忆
# --------------------------------------------------------------------------- #
def test_shot_memory_only_includes_finished_shots():
    plan = Plan.from_dict({"shots": [
        {"shot_id": "shot_001", "order": 1, "intent": "第一镜",
         "shot_type": "MS", "duration_frames": 24},
        {"shot_id": "shot_002", "order": 2, "intent": "第二镜",
         "shot_type": "CU", "duration_frames": 24}]})
    rows = shot_memory(plan, done=["shot_001"])
    assert [row["shot_id"] for row in rows] == ["shot_001"]
    assert "shot_001" in render_shot_memory(rows)
    assert "第二镜" not in render_shot_memory(rows)      # 不注入未完成的
    assert render_shot_memory([]) == ""


# --------------------------------------------------------------------------- #
# §3.5 上下文治理
# --------------------------------------------------------------------------- #
def conversation(count: int, size: int = 200):
    messages = [Message(role=MessageRole.SYSTEM, content="你是导演")]
    for index in range(count):
        messages.append(Message(role=MessageRole.TOOL,
                                content=f"观察 {index}：" + "观" * size))
    messages.append(Message(role=MessageRole.USER, content="请回答"))
    return messages


def test_count_tokens_covers_content_and_tool_arguments():
    messages = [Message(role=MessageRole.ASSISTANT, content="",
                        tool_calls=[ToolCall(
                            id="c", function=FunctionCall(
                                name="x", arguments="参" * 50))])]
    assert count_tokens(messages) >= 50


def test_trim_keeps_everything_when_under_budget():
    messages = conversation(2)
    kept, dropped = trim_messages(messages, 100000)
    assert kept == messages and dropped == []


def test_trim_drops_the_oldest_observations_first():
    messages = conversation(8, size=300)
    kept, dropped = trim_messages(messages, 1500)
    assert dropped, "应当裁掉一些旧观察"
    # system 与最新一条永远在
    assert kept[0].role is MessageRole.SYSTEM
    assert kept[-1].content == "请回答"
    assert count_tokens(kept) <= 1500
    # 被裁掉的都是最旧的
    assert dropped[0].content.startswith("观察 0")


def test_trim_never_drops_the_question_itself():
    messages = conversation(3, size=5000)
    kept, _dropped = trim_messages(messages, 200)
    assert kept[-1].content == "请回答"
    assert kept[0].role is MessageRole.SYSTEM


def test_zero_budget_means_no_limit():
    messages = conversation(5)
    kept, dropped = trim_messages(messages, 0)
    assert kept == messages and dropped == []


def test_budget_report_summarises_the_window():
    report = budget_report(conversation(2), 1000)
    assert report["max_tokens"] == 1000
    assert report["used_tokens"] > 0
    assert report["remaining_tokens"] == max(0, 1000 - report["used_tokens"])
    assert report["messages"] == 4
