"""定向修复提示（执行文档 v1.2 §7.1 阶段 B4 / §18.3）。

要点：回灌给模型的是**结构化违规项**（rule/target/message/suggestion），
而不是"构图不好，改改"。修复靠工具调用落地，所以工具集必须包含真正能改
场景的几个动作工具。
"""

from __future__ import annotations

from typing import Optional

from ..contracts.audit import AuditResult
from ..contracts.enums import Purpose, ToolChoice
from ..contracts.messages import ChatPayload, Message, MessageRole, new_request_id

REPAIR_SYSTEM_PROMPT = """\
你是白模预演的执行导演。当前镜头**未通过校验**，请只修复下列问题，
其余内容保持不变。

{audit}

当前场景：
{scene_state}

要求：
- 必须**调用工具**实际修改场景，不要只在回复里描述计划；
- 只改与问题相关的部分，不要顺手重做整个镜头；
- 修改后用 check_composition / check_axis 复核一次；
- 问题已解决就直接停止调用工具。
"""


def build_repair_payload(audit: AuditResult, registry, *,
                         scene_state: str = "", temperature: float = 0.2,
                         request_id: Optional[str] = None) -> ChatPayload:
    """构造一次修复请求。``registry`` 提供可调用的工具 schema。"""
    system_text = REPAIR_SYSTEM_PROMPT.format(
        audit=audit.format_for_llm(),
        scene_state=scene_state or "（尚未采集）")
    return ChatPayload(
        messages=[
            Message(role=MessageRole.SYSTEM, content=system_text),
            Message(role=MessageRole.USER,
                    content="请调用工具修复上面的问题。"),
        ],
        tools=registry.openai_schemas(),
        tool_choice=ToolChoice.REQUIRED,
        temperature=temperature,
        purpose=Purpose.REPAIR,
        request_id=request_id or new_request_id(),
    )
