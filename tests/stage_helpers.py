"""阶段 S（剧本理解）在测试里的最小替身。

每个测试替身只关心自己那一两个阶段的回复（计划 / 单镜草案 / 修复）。
阶段 S 是 v1.3 新加的：替身如果对它"答非所问"，驱动器会按设计**重试一次
再降级**，于是调用计数与脚本顺序都会被搅乱，测试失败的原因看起来却在
别处。所以这里给出一份统一的、结构合法但**不含任何推断**的回复。
"""

from __future__ import annotations

import json

from block_director.contracts.enums import Purpose
from block_director.contracts.messages import ChatReply, FunctionCall, ToolCall
from block_director.layer5_orchestrator.understand import BRIEF_TOOL_NAME

#: 空理解：没有节拍、没有注视关系，只有一条说明
DEMO_BRIEF_ARGS = {"notes": ["测试替身：不推断任何关系"]}

__all__ = ["DEMO_BRIEF_ARGS", "is_understand", "understand_reply"]


def is_understand(payload) -> bool:
    return getattr(payload, "purpose", None) is Purpose.UNDERSTAND


def understand_reply(request_id: str = "") -> ChatReply:
    call = ToolCall(id="brief_test",
                    function=FunctionCall(
                        name=BRIEF_TOOL_NAME,
                        arguments=json.dumps(DEMO_BRIEF_ARGS,
                                             ensure_ascii=False)))
    return ChatReply(content=None, tool_calls=[call], request_id=request_id,
                     model="stub", finish_reason="tool_calls")

