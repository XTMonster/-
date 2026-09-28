"""阶段 B5：受限 ReAct（执行文档 v1.2 §7.1 / §7.8）。

绝大多数镜头用"B1 结构化生成 + B4 定向修复"就能过，不值得付多轮试错的代价。
只有**真正需要边看边调**的镜头才进 ReAct：

1. 构图分低于阈值且 B4 没能改善；
2. 镜头里有 3 个以上角色（调度复杂）；
3. 用户显式要求精修。

因此本模块的第一件事是 :func:`should_react`——**触发条件比循环本身更重要**。
循环上限来自 ``orchestration.react_max_steps``（默认 6，0 表示关闭 B5），
纯计算，可单测。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from ..contracts.audit import AuditResult
from ..contracts.enums import Purpose, ToolChoice
from ..contracts.messages import ChatPayload, Message, MessageRole, new_request_id
from ..contracts.plan import Plan, ShotPlan

REACT_SYSTEM_PROMPT = """\
你是白模预演的执行导演，正在**精修**一个反复修不好的镜头。

当前问题：
{audit}

当前场景：
{scene_state}

要求：
- 只能通过调用工具**实际改变场景**，不要只在回复里描述计划；
- 每次改完用 check_composition / check_axis 复核一次，再决定下一步；
- 最多 {max_steps} 步；觉得已经足够好就停止调用工具；
- 不要重做整场戏，只调这个镜头。
"""


def should_react(shot: Optional[ShotPlan], result: Optional[AuditResult], *,
                 repairs_exhausted: bool = True,
                 composition_threshold: float = 70.0,
                 max_steps: int = 6,
                 user_requested: bool = False) -> bool:
    """是否进入 B5（§7.1 的三个触发条件）。"""
    if max_steps <= 0 or shot is None:
        return False
    if user_requested:
        return True
    if not repairs_exhausted:
        return False
    if len(getattr(shot, "characters", []) or []) >= 3:
        return True
    if result is None:
        return False
    if getattr(result, "score", None) is not None \
            and float(result.score) < float(composition_threshold):
        return True
    # 构图门失败但没给分数（例如只报了 E_CAM_001）时也值得一试
    return any(str(getattr(error, "rule", "")) == "COMPOSITION"
               for error in getattr(result, "errors", []) or [])


def build_react_payload(shot: ShotPlan, audit: AuditResult, *,
                        scene_state: str = "", registry=None,
                        max_steps: int = 6, temperature: float = 0.3,
                        request_id: Optional[str] = None) -> ChatPayload:
    """构造一次 ReAct 请求：工具全开、由模型自己决定何时停。"""
    system_text = REACT_SYSTEM_PROMPT.format(
        audit=audit.format_for_llm() if audit is not None else "（未知）",
        scene_state=scene_state or "（尚未采集）",
        max_steps=int(max_steps))
    tools = registry.openai_schemas() if registry is not None else []
    return ChatPayload(
        messages=[
            Message(role=MessageRole.SYSTEM, content=system_text),
            Message(role=MessageRole.USER,
                    content=f"请精修镜头 {shot.shot_id}"
                            f"（意图：{shot.intent or '未说明'}）。"),
        ],
        tools=tools,
        tool_choice=ToolChoice.AUTO,      # 允许它停下来，这是 ReAct 与 B4 的区别
        temperature=temperature,
        purpose=Purpose.REACT,
        request_id=request_id or new_request_id(),
    )


def shot_memory(plan: Optional[Plan], *, done: Sequence[str] = (),
                limit: int = 12) -> List[Dict[str, Any]]:
    """跨镜头记忆（§3.5）：只给已完成镜头的压缩摘要，绝不注入历史原文。"""
    if plan is None:
        return []
    finished = list(done)
    rows: List[Dict[str, Any]] = []
    for shot in plan.shots:
        if shot.shot_id not in finished:
            continue
        rows.append({"shot_id": shot.shot_id,
                     "intent": (shot.intent or "")[:40],
                     "shot_type": str(shot.shot_type),
                     "duration_frames": shot.duration_frames,
                     "characters": list(shot.characters)})
    return rows[-limit:]


def render_shot_memory(rows: Sequence[Dict[str, Any]]) -> str:
    """把跨镜头记忆渲染成提示里的一小段文本。"""
    if not rows:
        return ""
    lines = ["已完成镜头（摘要，用于保持连续性）："]
    for row in rows:
        lines.append(f"- {row['shot_id']}｜{row['shot_type']}｜"
                     f"{row['duration_frames']} 帧｜{row['intent']}｜"
                     f"{'、'.join(row['characters'])}")
    return "\n".join(lines)
