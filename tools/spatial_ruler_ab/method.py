"""方法臂话术（spec §15.2 方法臂）——与知识卡草案同源。

方法臂 = 基线臂 + 「构图视觉审核方法论」：给模型一套可操作的检查顺序与判定
规则，但**不给任何具体读数数值**（读数增量由 ruler / ruler_method 臂单独测）。
知识化草案在 ``block_director/knowledge/cards_review_method.py``；本模块直接
引用它的检查清单，避免各写一套。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from block_director.knowledge.cards_review_method import (
    CHECKLIST,
    render_method_checklist,
)


def render_method_block(scene: Optional[Dict[str, Any]] = None) -> str:
    """渲染方法块（不引用具体读数数值）。scene 仅用于动态镜追加动态检查项。"""
    lines = [
        "构图审核方法论（检查顺序 step 1→6 与判定规则，不引用具体读数数值）：",
        render_method_checklist(),
        "",
        "判定规则：先排除致命项（出画/整体遮挡），再谈微调项（三分/重心）。"
        "每个失败分量先读当前值与目标区间再判过/不过（构图过门判定：总分 ≥ 70 "
        "且逐项对照目标区间），最后汇成 verdict；没有读数值时只做定性判断，"
        "不编数字。",
    ]
    is_dynamic = isinstance(scene, dict) and scene.get("id") == "fight_01"
    if not is_dynamic:
        is_dynamic = hasattr(scene, "shot_id") and scene.shot_id == "fight_01"
    if is_dynamic:
        lines += [
            "",
            "动态打斗镜追加（第六步）：先按静态六项逐帧核对，再追：谁出画/哪帧、"
            "出画后是否从另一侧回冲、方向反转几次/哪帧、关键帧遮挡归因、速度档。"
            "只报可复算事实，不裁决动作观赏性。",
        ]
    return "\n".join(lines)


#: 模块级默认方法块（通用静态镜）。评测台用它构造通用方法臂话术。
METHOD_PROMPT = render_method_block()
