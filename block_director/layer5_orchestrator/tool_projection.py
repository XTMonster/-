"""决策树 → 工具调用投影适配层（纯层，无 bpy）。

设计文档 ``work/per_shot_decision_tree_design.md`` §7.3：
``emit_shot_draft`` 的提议形状是 ``camera/movements/actions``，
而工具调用的参数是**顶层键**。这里把"改场景"类工具的参数
投影到该镜决策树的合法空间，并产出与 ``project()`` 同构的审计记录。

红线：本模块不得 import ``bpy``；工具参数形状以
``layer3_engine/tool_bindings.py`` 的 schema 为准（那里才注册工具）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ..contracts.plan import Plan, ShotPlan
from .decision_tree import (
    ProjectionRecord,
    ShotDecisionTree,
    Verdict,
    project,
)


class ToolProjectionError(ValueError):
    """工具名不在决策树判域内（不应在驱动里发生：驱动只对白名单调本层）。"""


@dataclass
class ToolProjection:
    """一次工具调用的投影结果。"""

    tool: str
    args: Dict[str, Any]
    verdict: Verdict
    records: List[ProjectionRecord] = field(default_factory=list)
    rejected: bool = False


#: 工具 → 决策树判域映射。
#: ``setup_camera``/``reframe``/``move_camera``/``character_action`` 的
#: 参数与树节点一一对应；``look_at``/``face_character`` 的 ``target`` 走
#: 剧本硬约束（角色 ∪ 锚点）；``move_character``/``place_character``/
#: ``interact_with`` 是坐标/交互域，树不管。
TOOL_TREE_MAP: Dict[str, str] = {
    "setup_camera": "camera",
    "reframe": "camera.lens",
    "move_camera": "movement",
    "character_action": "action",
    "look_at": "target",
    "face_character": "target",
}

#: 不进树的工具：坐标/速度/交互类型由工具 schema 自己管。
TOOL_PASSTHROUGH: Tuple[str, ...] = (
    "move_character", "place_character", "interact_with",
)


def _clamp_lens(value: Any) -> Tuple[float, Verdict]:
    """工具 schema 的 lens 范围（8–300mm）与树同源，clamp 后执行。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value, Verdict.REJECTED   # type: ignore[return-value]
    low, high = 8.0, 300.0
    clamped = min(high, max(low, number))
    if abs(clamped - number) < 1e-9:
        return number, Verdict.ACCEPT
    return clamped, Verdict.PROJECTED


def _project_camera(tree: ShotDecisionTree, args: Dict[str, Any],
                    *, stage: str) -> ToolProjection:
    """setup_camera：side → camera.side；lens → camera.lens。

    ``side`` 原样进树（不在这里预归一）：决策树自己处理连字符/自由文本，
    审计记录里的 ``original`` 必须是模型原始输入（设计 §7.3「投影留痕」）。
    """
    side = args.get("side")
    lens = args.get("lens")
    proposal = {"camera": {}}
    if side is not None:
        proposal["camera"]["side"] = side
    if lens is not None:
        proposal["camera"]["lens"] = lens
    projected, records = project(tree, proposal, stage=stage)
    new_args = dict(args)
    camera = projected.get("camera") or {}
    if "side" in new_args and "side" in camera:
        new_args["side"] = camera["side"]
    if "lens" in new_args and "lens" in camera:
        new_args["lens"] = camera["lens"]
    return ToolProjection(tool="setup_camera", args=new_args,
                          verdict=_verdict(records), records=records)


def _project_reframe(tree: ShotDecisionTree, args: Dict[str, Any],
                     *, stage: str) -> ToolProjection:
    """reframe：lens → camera.lens（工具没有 side 参数）。"""
    lens = args.get("lens")
    if lens is None:
        return ToolProjection(tool="reframe", args=dict(args),
                              verdict=Verdict.ACCEPT)
    lens_value, lens_verdict = _clamp_lens(lens)
    new_args = dict(args)
    records: List[ProjectionRecord] = []
    if lens_verdict == Verdict.PROJECTED:
        new_args["lens"] = lens_value
        records.append(ProjectionRecord(
            shot_id=tree.shot_id, stage=stage, node_key="camera.lens",
            original=lens, projected=lens_value, verdict=verdict_str(lens_verdict),
            reason="焦段必须在引擎支持范围 8–300mm"))
    elif lens_verdict == Verdict.REJECTED:
        records.append(ProjectionRecord(
            shot_id=tree.shot_id, stage=stage, node_key="camera.lens",
            original=lens, projected=None, verdict=verdict_str(lens_verdict),
            reason="焦段必须是数值（8–300mm）"))
    return ToolProjection(tool="reframe", args=new_args,
                          verdict=lens_verdict, records=records)


def _project_movement(tree: ShotDecisionTree, args: Dict[str, Any],
                      *, stage: str) -> ToolProjection:
    """move_camera：movement_type → camera.movements[].type；amount 钳制。

    ``movement_type`` 原样进树（不预归一）：树按 P2 词形归一 + 无歧义门槛
    投影或拒绝，审计 original 保留模型原始文本。
    """
    movement_type = args.get("movement_type")
    amount = args.get("amount")
    proposal: Dict[str, Any] = {"camera": {"movements": []}}
    if movement_type is not None:
        proposal["camera"]["movements"].append(
            {"type": movement_type})
    if amount is not None:
        #: amount 的数值域是运镜专属区间；先把 amount 放进动作项，
        #: 由树按 type 投影后的节点 clamp。
        if proposal["camera"]["movements"]:
            proposal["camera"]["movements"][0]["amount"] = amount
    projected, records = project(tree, proposal, stage=stage)
    new_args = dict(args)
    movement = (projected.get("camera") or {}).get("movements") or []
    if movement and "type" in movement[0]:
        new_args["movement_type"] = movement[0]["type"]
    if movement and "amount" in movement[0]:
        new_args["amount"] = movement[0]["amount"]
    return ToolProjection(tool="move_camera", args=new_args,
                          verdict=_verdict(records), records=records)


def _project_action(tree: ShotDecisionTree, args: Dict[str, Any],
                    *, stage: str) -> ToolProjection:
    """character_action：action_type → action_type；params 键集过滤。"""
    action_type = args.get("action_type")
    params = args.get("params") or {}
    proposal: Dict[str, Any] = {
        "actions": [{"action_type": str(action_type or "").strip(),
                     "params": dict(params)}],
    }
    projected, records = project(tree, proposal, stage=stage)
    new_args = dict(args)
    actions = projected.get("actions") or []
    if actions:
        new_args["action_type"] = actions[0].get("action_type")
        new_args["params"] = actions[0].get("params", {})
    return ToolProjection(tool="character_action", args=new_args,
                          verdict=_verdict(records), records=records)


def _project_target(tree: ShotDecisionTree, args: Dict[str, Any],
                    *, stage: str, tool: str) -> ToolProjection:
    """look_at/face_character：target → action.look_at.target 硬约束。

    ``target_position`` 是坐标，不在角色/锚点闭集内；工具 handler 自己
    管坐标合法性。target 缺失或越界 → REJECTED（剧本硬约束最高优先级）。
    """
    target = args.get("target")
    if target is None:
        return ToolProjection(tool=tool, args=dict(args),
                              verdict=Verdict.ACCEPT)
    proposal = {
        "actions": [{"action_type": "look_at",
                     "params": {"target": str(target)}}],
    }
    projected, records = project(tree, proposal, stage=stage)
    new_args = dict(args)
    actions = projected.get("actions") or []
    if actions:
        params = actions[0].get("params") or {}
        new_args["target"] = params.get("target", target)
    return ToolProjection(tool=tool, args=new_args,
                          verdict=_verdict(records), records=records)


def _verdict(records: List[ProjectionRecord]) -> Verdict:
    """任一 REJECTED 即整体 REJECTED；否则有 PROJECTED 即 PROJECTED。"""
    if any(r.verdict == Verdict.REJECTED for r in records):
        return Verdict.REJECTED
    if records:
        return Verdict.PROJECTED
    return Verdict.ACCEPT


def verdict_str(verdict: Verdict) -> str:
    return str(verdict)


def project_tool_call(tree: ShotDecisionTree, tool: str,
                      args: Dict[str, Any], *, stage: str) -> ToolProjection:
    """把一次工具调用的参数投影到该镜决策树合法空间。

    :raises ToolProjectionError: 工具不在树的判域内。
    """
    if tool in TOOL_PASSTHROUGH:
        return ToolProjection(tool=tool, args=dict(args),
                              verdict=Verdict.ACCEPT)
    if tool == "setup_camera":
        return _project_camera(tree, args, stage=stage)
    if tool == "reframe":
        return _project_reframe(tree, args, stage=stage)
    if tool == "move_camera":
        return _project_movement(tree, args, stage=stage)
    if tool == "character_action":
        return _project_action(tree, args, stage=stage)
    if tool in ("look_at", "face_character"):
        return _project_target(tree, args, stage=stage, tool=tool)
    raise ToolProjectionError(
        f"工具 {tool} 不在决策树判域内；只读/控制/越域工具不投影")
