"""v1.6 F1（D-02）：超时重试阶梯纯状态机 + 瘦身包。"""
from __future__ import annotations

from block_director.contracts.messages import Message, MessageRole
from block_director.layer5_orchestrator.context_budget import (
    SLIM_PLACEHOLDER,
    slim_messages,
    strip_knowledge_columns,
)
from block_director.layer5_orchestrator.retry_ladder import (
    DEGRADE,
    RETRY_SAME,
    RETRY_SLIM,
    STAGE_OF,
    CallOutcome,
    RetryPolicy,
    is_timeout,
    next_step,
)

POLICY = RetryPolicy()


def test_timeout_then_slim_then_degrade_never_a_third_call():
    history = [CallOutcome(ok=False, timed_out=True)]
    assert next_step(history, POLICY) == RETRY_SLIM
    history.append(CallOutcome(ok=False, timed_out=True, slim=True))
    assert next_step(history, POLICY) == DEGRADE


def test_non_timeout_failure_retries_same_once_then_degrades():
    history = [CallOutcome(ok=False, timed_out=False)]
    assert next_step(history, POLICY) == RETRY_SAME
    history.append(CallOutcome(ok=False))
    assert next_step(history, POLICY) == DEGRADE


def test_slim_disabled_retries_same():
    policy = RetryPolicy(slim_on_timeout=False)
    assert next_step([CallOutcome(ok=False, timed_out=True)], policy) == RETRY_SAME


def test_already_slim_timeout_does_not_slim_again():
    policy = RetryPolicy(max_attempts=3)
    history = [CallOutcome(ok=False, timed_out=True, slim=True)]
    assert next_step(history, policy) == RETRY_SAME


def test_success_or_empty_history_means_normal_call():
    assert next_step([], POLICY) == RETRY_SAME
    assert next_step([CallOutcome(ok=False), CallOutcome(ok=True)], POLICY) == RETRY_SAME


def test_never_retries_forever():
    history = []
    decisions = []
    for _ in range(10):
        history.append(CallOutcome(ok=False, timed_out=True,
                                   slim=bool(decisions and decisions[-1] == RETRY_SLIM)))
        decision = next_step(history, POLICY)
        decisions.append(decision)
        if decision == DEGRADE:
            break
    assert decisions[-1] == DEGRADE
    assert len(history) == POLICY.max_attempts


def test_is_timeout_recognises_transport_wording():
    assert is_timeout("TimeoutError: The read operation timed out")
    assert is_timeout("请求超时（120s）")
    assert not is_timeout("HTTP 502 Bad Gateway")
    assert not is_timeout("")


def test_stage_names_cover_every_decision():
    assert set(STAGE_OF) == {RETRY_SAME, RETRY_SLIM, DEGRADE}


KNOWLEDGE = ("镜头声明：shot_004 CU 米迦尔\n"
             "【硬约束（禁/许）】\n- 禁 CU 于建立镜\n- 许 MLS\n"
             "【经验建议（软）】\n- 若对话则正反打\n"
             "【参考案例（仅参考）】\n- 案例 A\n\n"
             "审计发现：R003 重叠 frames 12-20")


def test_strip_removes_all_three_columns_and_keeps_shot_and_audit_text():
    slimmed, removed = strip_knowledge_columns(KNOWLEDGE)
    assert removed == 3
    assert "禁 CU" not in slimmed and "正反打" not in slimmed and "案例 A" not in slimmed
    assert "镜头声明：shot_004 CU 米迦尔" in slimmed
    assert "审计发现：R003 重叠 frames 12-20" in slimmed
    assert slimmed.count(SLIM_PLACEHOLDER) == 1


def test_text_without_columns_is_unchanged():
    text = "【其它标题】保留\n审计发现：R001"
    assert strip_knowledge_columns(text) == (text, 0)


def test_slim_messages_only_touches_knowledge_content():
    messages = [Message(role=MessageRole.SYSTEM, content="system rules"),
                Message(role=MessageRole.USER, content=KNOWLEDGE),
                Message(role=MessageRole.TOOL, content="工具结果：相机已重设",
                        tool_call_id="t1")]
    slimmed, removed = slim_messages(messages)
    assert removed == 3
    assert slimmed[0] is messages[0] and slimmed[2] is messages[2]
    assert slimmed[1].tool_call_id == messages[1].tool_call_id
    assert "审计发现" in slimmed[1].content
    assert messages[1].content == KNOWLEDGE          # 原消息不被就地改写
