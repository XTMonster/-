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
from .dialogue_budget import shot_dialogue_budget

REPAIR_SYSTEM_PROMPT = """\
你是白模预演的执行导演。当前镜头**未通过校验**，请只修复下列问题，
其余内容保持不变。

{audit}

当前场景：
{scene_state}

{dialogue_budget}
要求：
- **先看清每一条问题该由谁来修**（用错工具 = 修不动，白烧一次修复回合）：
  · **时间轴类**（`R003` 同角色动作重叠、`R011` 台词装不下、`R015` 时长不符）：
    必须**重新提交这一镜的草案**（`emit_shot_draft`，把错开的起止帧写进去）。
    计划里的动作表只有这条路径能改——用场景工具（`character_action` 等）只会
    **再叠加一段动画**，原动作表原封不动，问题会一直红下去。实测（2026-10-03 的
    64 镜真跑）：383 次 `R003` 与 126 次修复调用、101 次降级，绝大多数就是这么烧掉的。
  · **空间/构图类**（`R002` 穿模、`R005` 出画、`R001` 轴线、构图分低）：
    用场景工具挪机位、挪人、调焦距、加道具，然后用复核工具确认。
- 必须**调用工具**实际修改，不要只在回复里描述计划；
- 只改与问题相关的部分，不要顺手重做整个镜头；
- 修改后用 check_composition / check_axis 复核一次；
- 问题已解决就直接停止调用工具。
"""


def build_repair_payload(audit: AuditResult, registry, *,
                         scene_state: str = "", temperature: float = 0.2,
                         shot=None,
                         request_id: Optional[str] = None) -> ChatPayload:
    """构造一次修复请求。``registry`` 提供可调用的工具 schema。

    ``shot`` 给了就附上这一镜的**对白帧预算**（§4.4）。没有它时，修复
    提示只会说"重新提交这一镜的草案、把起止帧错开"——而模型手上既没有
    每句要几帧、也没有那 12 帧余量是多少，只能再猜一遍（实测：
    2026-10-03 的 64 镜真跑里 26 个镜头的 S6 一直红到收尾）。
    """
    budget_text = ""
    if shot is not None:
        budget = shot_dialogue_budget(shot)
        if budget.lines:
            budget_text = budget.render() + "\n"
    system_text = REPAIR_SYSTEM_PROMPT.format(
        audit=audit.format_for_llm(),
        scene_state=scene_state or "（尚未采集）",
        dialogue_budget=budget_text)
    return ChatPayload(
        messages=[
            Message(role=MessageRole.SYSTEM, content=system_text),
            Message(role=MessageRole.USER,
                    content="请调用工具修复上面的问题。"),
        ],
        # 修复阶段不给 emit_plan：计划的唯一入口是阶段 A（§7.1）
        tools=registry.schemas_except("emit_plan"),
        tool_choice=ToolChoice.REQUIRED,
        temperature=temperature,
        purpose=Purpose.REPAIR,
        request_id=request_id or new_request_id(),
    )
