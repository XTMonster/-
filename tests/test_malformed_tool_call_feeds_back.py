"""参数 JSON 解析失败的工具调用必须**回灌反馈**且**补齐协议闭环**。

现场（G2 终验收，DeepSeek V4 Pro 官方通道）：`invalid 工具调用`是四个红项之一。
旧实现里 `_dispatch_tool_calls` 对 `parsed_arguments()` 抛 `ValueError` 的调用只是
`errors.append(...); continue`——assistant 消息已经带着这条 tool_call 进了对话，
却没有对应的 `role="tool"` 回应，下一轮请求成为"有调用、无回应"的畸形对话
（DeepSeek 官方端点对此容忍度差），且模型永远收不到"你刚才的 JSON 是坏的"。

本文件钉：解析失败时，对话里必须出现一条同 `tool_call_id` 的 tool 消息，
内容把解析错误和"请重新调用"回灌给模型；`validate_conversation` 不得再报结构问题。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.contracts.messages import (  # noqa: E402
    ChatReply, FunctionCall, MessageRole, ToolCall, validate_conversation,
)
from block_director.layer5_orchestrator.driver import (  # noqa: E402
    DriverLimits, PrevisDriver, default_registry,
)
from block_director.layer5_orchestrator.offline import OfflineTransport  # noqa: E402
from block_director.layer6_audit.audit_logger import AuditLogger  # noqa: E402

SCRIPT = "INT. 咖啡馆 - 日\n\n小明坐下。\n"


class InlineThread:
    def __init__(self, target, name=""):
        self._target = target

    def start(self):
        self._target()


def _driver() -> PrevisDriver:
    return PrevisDriver(transport=OfflineTransport(), audit=AuditLogger(),
                        script=SCRIPT, thread_factory=InlineThread,
                        registry=default_registry(), limits=DriverLimits())


def test_a_malformed_call_gets_a_tool_response_with_feedback():
    driver = _driver()
    call = ToolCall(id="bad_1", function=FunctionCall(
        name="get_scene_state", arguments='{"character_id: "小明"}'))
    problem = driver._dispatch_tool_calls(ChatReply(tool_calls=[call]))

    assert problem                        # 本轮必须被判失败
    tool_msgs = [m for m in driver.messages
                 if m.role is MessageRole.TOOL and m.tool_call_id == "bad_1"]
    assert len(tool_msgs) == 1, "解析失败的调用也必须补一条 tool 回应（协议闭环）"
    assert "不是合法 JSON" in (tool_msgs[0].content or "")
    assert "重新调用" in (tool_msgs[0].content or "")


def test_the_conversation_stays_well_formed_after_a_malformed_call():
    """畸形调用之后，对话必须仍通过 §3.4 结构校验（不留下"有调用、无回应"）。"""
    driver = _driver()
    good = ToolCall(id="ok_1", function=FunctionCall(
        name="get_scene_state", arguments="{}"))
    bad = ToolCall(id="bad_1", function=FunctionCall(
        name="check_composition", arguments='{"shot_id": '))
    driver._dispatch_tool_calls(ChatReply(tool_calls=[good, bad]))
    assert validate_conversation(driver.messages) == []
