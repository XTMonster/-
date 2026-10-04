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
from ..contracts.tools import CONTROL_TOOL_NAMES, SHOT_DRAFT_TOOL
from .dialogue_budget import shot_dialogue_budget

#: **时间轴类**规则：它们读的是计划里的动作表 / 台词表，能改这两张表的只有
#: `emit_shot_draft`（`merge_draft` 整份替换 actions/dialogues）。场景工具
#: （`character_action`、`move_character`…）只往 Blender 场景里**叠**动画，
#: 一个字都不写回计划 —— 实测就是 R003 一直红的原因（见
#: `tests/test_repair_prompt_picks_the_right_tool.py` 的文件头）。
TIMELINE_RULES = frozenset({"R003", "R011", "R015"})

#: 修复尝试里的**延续轮**提示。它存在的理由是可测量的：真跑（2026-10-04，
#: `long17`）的 104 个修复回合里 **72 个**恰好是 `search_knowledge` ＋
#: `get_scene_state` 两次只读调用——模型把唯一一轮花在"查资料 + 看场景"上，
#: 然后这一轮就结束了。给了下一轮还不够：那些观测此前也**没有被发回**。
REPAIR_FOLLOWUP_NUDGE = """\
上一轮你只做了查询（场景/知识/复核），**没有改动任何东西**，所以问题依旧存在。
现在请**直接调用改动类工具**动手修正，并把要改的部分一次改到位：

- 时间轴类（R003 / R011 / R015）：用 `emit_shot_draft` 重提这一镜的草案；
- 空间/构图类（R001 / R002 / R005 / 构图分低）：用 `place_character`、
  `move_character`、`face_character`、`setup_camera`、`reframe`、
  `move_camera` 之一真的把场景挪到位；

不要再只是查询。如果确实已经无需修改，请明确说明是哪一条审计已经不再成立。
"""


def timeline_only(audit: AuditResult) -> bool:
    """这条审计的 error 是否**全部**属于时间轴类。

    只有全中时才收窄工具集：混合审计（例：R003 ＋ 构图低分）还要用场景工具
    修构图那一半，把工具拿掉反而少修一条。
    """
    rules = {str(item.rule) for item in getattr(audit, "errors", [])}
    return bool(rules) and rules <= TIMELINE_RULES


def _offers_the_draft_tool(registry) -> bool:
    """注册表里有没有 `emit_shot_draft`（假注册表没有 ``__contains__`` 时不炸）。"""
    try:
        return SHOT_DRAFT_TOOL in registry
    except TypeError:                      # 鸭子类型的最小替身：不可迭代也不算
        return False


REPAIR_SYSTEM_PROMPT = """\
你是白模预演的执行导演。当前镜头**未通过校验**，请只修复下列问题，
其余内容保持不变。

{focus}

{audit}

当前场景：
{scene_state}

{dialogue_budget}
**动作参数只能用它自己那一行的键**（下表就是唯一真源，由引擎的参数表生成）。
写别的键、或用同义词，**整条草案会被退回**，这一镜就只剩计划里的内容了——
实测（2026-10-04 的 64 镜真跑 `long19`）：修复回合为了错开 R003 重提草案，
因为表不在手上而给 `body_tilt`/`turn_head` 写了表外的键名，整条被退回、
R003 一直红到收尾。
{action_params}

**运镜 `amount` 的单位**（下表同样唯一真源；写错会让机位跑出画面）：
{movement_units}

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
                         shot_id: str = "",
                         request_id: Optional[str] = None) -> ChatPayload:
    """构造一次修复请求。``registry`` 提供可调用的工具 schema。

    ``shot`` 给了就附上这一镜的**对白帧预算**（§4.4）。没有它时，修复
    提示只会说"重新提交这一镜的草案、把起止帧错开"——而模型手上既没有
    每句要几帧、也没有那 12 帧余量是多少，只能再猜一遍（实测：
    2026-10-03 的 64 镜真跑里 26 个镜头的 S6 一直红到收尾）。

    ``shot_id`` 是**本次要修的镜头**。提示词里必须写死它：场景摘要里的
    "当前镜头"是 `SceneContext.current_shot_id`（构建时落在第一镜），
    实测（`long10`）7 次 `emit_shot_draft` 里有 2 次把 `shot_id` 写成了
    `shot_001`——正是那条过期的摘要值，于是真正要修的 `shot_043` 一直没被改。

    纯时间轴审计还会把工具集**收窄到** `emit_shot_draft` ＋ 控制类工具：
    提示词早就写着"用场景工具修不动时间轴"，可实测修复回合仍然是
    86 次 `get_scene_state` / 65 次 `check_composition` / 40 次
    `check_visibility` 对 7 次 `emit_shot_draft`——叫不动就换工具集。
    """
    budget_text = ""
    if shot is not None:
        budget = shot_dialogue_budget(shot)
        if budget.lines:
            budget_text = budget.render() + "\n"
    focus = ""
    if shot_id:
        focus = (f"**本次要修的镜头：`{shot_id}`**。"
                 f"用 `{SHOT_DRAFT_TOOL}` 时 `shot_id` 必须写成它"
                 f"（场景摘要里的\"当前镜头\"是场景默认值，不是本次的目标）。")
    #: 注册表里没有 `emit_shot_draft`（例：纯单测的最小注册表）时不收窄——
    #: 收窄到空工具集会让 `tool_choice=required` 的请求直接无法满足。
    narrow = timeline_only(audit) and _offers_the_draft_tool(registry)
    if narrow:
        focus += ("\n\n这条审计**全部是时间轴类**问题 ⇒ 本次请求的工具集**只有**"
                  f" `{SHOT_DRAFT_TOOL}` 与控制类工具：请直接重新提交这一镜的草案，"
                  "把错开的起止帧写进去。")
    #: 参数表与运镜单位表**必须和编辑器用的是同一份**（`editor.render_action_params`
    #: / `render_movement_units`）：修复回合最常见的动作就是"重提这一镜的草案"，
    #: 表不在手上时模型会自己发明键名，整条草案被退回、原来的问题一直红到收尾
    #: （实测 2026-10-04：`body_tilt(lean_deg)`、`turn_head(direction_deg)`）。
    from .editor import render_action_params, render_movement_units

    system_text = REPAIR_SYSTEM_PROMPT.format(
        focus=focus,
        audit=audit.format_for_llm(),
        scene_state=scene_state or "（尚未采集）",
        dialogue_budget=budget_text,
        action_params=render_action_params(),
        movement_units=render_movement_units())
    tools = (registry.schemas_only(SHOT_DRAFT_TOOL, *CONTROL_TOOL_NAMES)
             if narrow else registry.schemas_except("emit_plan"))
    return ChatPayload(
        messages=[
            Message(role=MessageRole.SYSTEM, content=system_text),
            Message(role=MessageRole.USER,
                    content="请调用工具修复上面的问题。"),
        ],
        # 修复阶段不给 emit_plan：计划的唯一入口是阶段 A（§7.1）
        tools=tools,
        tool_choice=ToolChoice.REQUIRED,
        temperature=temperature,
        purpose=Purpose.REPAIR,
        request_id=request_id or new_request_id(),
    )
