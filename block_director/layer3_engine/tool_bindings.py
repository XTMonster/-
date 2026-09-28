"""把执行引擎暴露成 LLM 可调用的工具（执行文档 v1.2 §7.4）。

工具注册表本身在 layer5（不依赖 bpy）；本模块负责把**需要 bpy 的**查询与
操作绑定进注册表。红线不变：工具永不抛异常，失败一律转成可回灌的观察文本。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import bpy
from mathutils import Vector

from ..motion.model import ACTION_TYPES
from ..contracts.enums import SHOT_TYPES
from ..observation.state import format_scene_state
from ..layer5_orchestrator.tool_registry import ToolResult
from ..utils.logger import get_logger
from ..utils.threading_guard import main_thread_only
from .character_system import MotionBlender, get_facing
from .cinema_engine import (
    check_camera_axis,
    evaluate_camera_composition,
    place_camera_for_shot,
)
from .scene_context import get_context
from .scene_state import collect_scene_state

log = get_logger("tool-bindings")

QUERY_TOOLS = ("get_scene_state", "check_visibility", "check_composition",
               "check_axis")
ACTION_TOOLS = ("place_character", "character_action", "setup_camera")


def _fail(text: str) -> ToolResult:
    """领域级失败：调用没成，交给驱动器的修复循环处理。"""
    return ToolResult(False, text, error="domain_error")


def _require_character(character_id: str):
    context = get_context()
    if context is None:
        return None, _fail("场景上下文为空：请先构建场景")
    character = context.character(character_id)
    if character is None:
        known = ", ".join(sorted(context.characters)) or "（无）"
        return None, _fail(f"找不到角色 {character_id}。现有角色: {known}")
    return character, ""


def _resolve_camera(args: Dict[str, Any]):
    """按 camera_id / 当前镜头找相机；找不到返回 ``(None, 错误文本)``。"""
    context = get_context()
    if context is None:
        return None, _fail("场景上下文为空：请先构建场景")
    camera_id = str(args.get("camera_id") or "")
    if camera_id:
        camera = context.camera_by_name(camera_id) or context.cameras.get(camera_id)
        if camera is None:
            known = ", ".join(sorted(context.cameras)) or "（无）"
            return None, _fail(f"找不到相机 {camera_id}。可用镜头: {known}")
        return camera, ""
    camera = context.camera_for()
    if camera is None:
        return None, _fail("当前镜头没有相机")
    return camera, ""


@main_thread_only("tool_get_scene_state")
def _tool_get_scene_state() -> str:
    return format_scene_state(collect_scene_state(detailed=False))


@main_thread_only("tool_check_visibility")
def _tool_check_visibility(character_id: str = "", camera_id: str = ""):
    context = get_context()
    if context is None:
        return _fail("场景上下文为空：请先构建场景")
    camera, problem = _resolve_camera({"camera_id": camera_id})
    if camera is None:
        return problem

    state = collect_scene_state(detailed=True, context=context)
    entries = state.characters
    if character_id:
        entries = [c for c in entries if c.id == character_id]
        if not entries:
            known = ", ".join(c.id for c in state.characters) or "（无）"
            return _fail(f"找不到角色 {character_id}。现有角色: {known}")

    lines = []
    for entry in entries:
        mark = "在画" if entry.in_frame else "**不在画**"
        lines.append(f"{entry.id} {mark}，屏幕 "
                     f"({entry.screen_position[0]:.2f}, "
                     f"{entry.screen_position[1]:.2f})，"
                     f"高度占比 {entry.height_fraction:.2f}")
    return "；".join(lines)


@main_thread_only("tool_check_composition")
def _tool_check_composition(camera_id: str = ""):
    context = get_context()
    if context is None:
        return _fail("场景上下文为空：请先构建场景")
    camera, problem = _resolve_camera({"camera_id": camera_id})
    if camera is None:
        return problem
    shot_id = context.current_shot_id
    shot_type = context.shot_types.get(shot_id, "MS")
    report = evaluate_camera_composition(camera, context.character_list,
                                         shot_type=shot_type)
    lines = [f"构图评分 {report.score:.1f}（{'通过' if report.passed else '需调整'}）"]
    for name, item in report.items.items():
        if item.suggestion:
            lines.append(f"- {name} {item.score:.2f}：{item.suggestion}")
    if not report.suggestions:
        lines.append("- 各项均达标")
    return "\n".join(lines)


@main_thread_only("tool_check_axis")
def _tool_check_axis(camera_id: str = ""):
    context = get_context()
    if context is None:
        return _fail("场景上下文为空：请先构建场景")
    camera, problem = _resolve_camera({"camera_id": camera_id})
    if camera is None:
        return problem
    if context.axis is None:
        return _fail("本场尚未建立轴线（需要至少两名角色的镜头）")
    message = check_camera_axis(context.axis, camera)
    if message:
        return _fail(message)
    side = "+" if context.axis.established_side > 0 else "-"
    return f"轴线合规：相机在轴线的 {side} 侧，与首镜一致"


@main_thread_only("register_scene_tools")
def register_scene_tools(registry) -> None:
    """把查询工具注册进给定的 ToolRegistry（重复调用是安全的）。"""
    registry.add(
        name="get_scene_state",
        description="查看当前场景状态（角色位置/朝向、当前镜头与相机）。"
                    "默认返回轻量摘要，不含屏幕投影。",
        parameters={"type": "object", "additionalProperties": False,
                    "properties": {}},
        handler=_tool_get_scene_state,
    )
    registry.add(
        name="check_visibility",
        description="检查角色是否在画面内，并给出屏幕坐标与高度占比。",
        parameters={"type": "object", "additionalProperties": False,
                    "properties": {"character_id": {"type": "string"},
                                   "camera_id": {"type": "string"}}},
        handler=_tool_check_visibility,
    )
    registry.add(
        name="check_composition",
        description="对当前机位做构图评分（六项加权 + 可操作建议，含遮挡检测）。",
        parameters={"type": "object", "additionalProperties": False,
                    "properties": {"camera_id": {"type": "string"}}},
        handler=_tool_check_composition,
    )
    registry.add(
        name="check_axis",
        description="检查机位是否违反 180° 轴线（与首镜建立的方向基准对比）。",
        parameters={"type": "object", "additionalProperties": False,
                    "properties": {"camera_id": {"type": "string"}}},
        handler=_tool_check_axis,
    )
    log.info("已注册场景查询工具：%s", ", ".join(QUERY_TOOLS))


# --------------------------------------------------------------------------- #
# 动作工具：LLM 的"手"——真的能改场景
# --------------------------------------------------------------------------- #
@main_thread_only("tool_place_character")
def _tool_place_character(character_id: str,
                          position: Optional[List[float]] = None,
                          facing: Optional[List[float]] = None):
    character, problem = _require_character(character_id)
    if character is None:
        return problem
    if position is not None:
        character.root.location = tuple(float(v) for v in position)
    if facing is not None:
        from ..utils.geometry import facing_to_rotation_z
        character.root.rotation_euler = (
            0.0, 0.0, facing_to_rotation_z(tuple(float(v) for v in facing)))
    bpy.context.view_layer.update()
    location = tuple(round(v, 3) for v in character.root.matrix_world.translation)
    return f"角色 {character_id} 已就位：位置 {location}"


@main_thread_only("tool_character_action")
def _tool_character_action(character_id: str, action_type: str,
                           start_frame: int, end_frame: int,
                           params: Optional[Dict[str, Any]] = None):
    character, problem = _require_character(character_id)
    if character is None:
        return problem
    if action_type not in ACTION_TYPES:
        return _fail(f"未知动作类型 {action_type}。可用: "
                     f"{', '.join(ACTION_TYPES)}")
    if int(end_frame) <= int(start_frame):
        return _fail("end_frame 必须大于 start_frame")

    blender = MotionBlender(character)
    blender.add(action_type, int(start_frame), int(end_frame), **(params or {}))
    conflicts = blender.validate()
    if conflicts:
        return _fail("动作冲突：" + "；".join(conflicts))
    try:
        result = blender.bake(clear=False)      # 叠加，不清掉已有动画
    except ValueError as exc:
        return _fail(f"动作烘焙失败：{exc}")
    return (f"已为 {character_id} 添加动作 {action_type}"
            f"（{start_frame}-{end_frame} 帧，{result.keyframes} 个关键帧）")


@main_thread_only("tool_setup_camera")
def _tool_setup_camera(shot_id: str = "", shot_type: str = "MS",
                       side: str = "front", lens: Optional[float] = None):
    context = get_context()
    if context is None:
        return _fail("场景上下文为空：请先构建场景")
    shot_id = shot_id or context.current_shot_id
    if not shot_id:
        return _fail("未指定镜头，且当前没有活动镜头")
    shot = context.shot(shot_id)
    if shot is None:
        known = ", ".join(sorted(context.cameras)) or "（无）"
        return _fail(f"找不到镜头 {shot_id}。可用镜头: {known}")

    characters = [context.character(cid) for cid in shot.characters]
    characters = [c for c in characters if c is not None]
    if not characters:
        return _fail(f"镜头 {shot_id} 没有在场角色，无法解算机位")

    positions = [c.root.matrix_world.translation for c in characters]
    anchor = sum(positions, Vector()) / len(positions)
    facing = get_facing(characters[0])

    scene = bpy.context.scene
    previous = context.cameras.get(shot_id)
    if previous is not None:
        bpy.data.objects.remove(previous, do_unlink=True)
    bundle, solution = place_camera_for_shot(
        shot_id, anchor, facing=facing, shot_type=shot_type, side=side,
        lens=lens, make_scene_camera=False)
    context.cameras[shot_id] = bundle.camera
    context.shot_types[shot_id] = str(shot_type).upper()
    if shot_id == context.current_shot_id or scene.camera is previous:
        scene.camera = bundle.camera
    marker = scene.timeline_markers.get(f"BD_Cut_{shot_id}")
    if marker is not None:
        marker.camera = bundle.camera
    bpy.context.view_layer.update()
    return (f"镜头 {shot_id} 机位已重设：{shot_type} / {side}，"
            f"位置 {tuple(round(v, 3) for v in solution.position)}，"
            f"距离 {solution.distance:.2f}，焦距 {solution.lens:g}mm")


@main_thread_only("register_action_tools")
def register_action_tools(registry) -> None:
    """把"能改场景"的动作工具注册进注册表（重复调用是安全的）。"""
    registry.add(
        name="place_character",
        description="移动并转向一个已存在的角色（position 为世界坐标，"
                    "facing 为面朝方向向量）。",
        parameters={"type": "object", "additionalProperties": False,
                    "required": ["character_id"],
                    "properties": {
                        "character_id": {"type": "string"},
                        "position": {"type": "array", "minItems": 3,
                                     "maxItems": 3,
                                     "items": {"type": "number"}},
                        "facing": {"type": "array", "minItems": 3,
                                   "maxItems": 3,
                                   "items": {"type": "number"}}}},
        handler=_tool_place_character,
    )
    registry.add(
        name="character_action",
        description="给角色加一段动作（走路/转身/坐下/点头等），帧号为全局帧。",
        parameters={"type": "object", "additionalProperties": False,
                    "required": ["character_id", "action_type",
                                 "start_frame", "end_frame"],
                    "properties": {
                        "character_id": {"type": "string"},
                        "action_type": {"type": "string",
                                        "enum": list(ACTION_TYPES)},
                        "start_frame": {"type": "integer", "minimum": 1},
                        "end_frame": {"type": "integer", "minimum": 1},
                        "params": {"type": "object"}}},
        handler=_tool_character_action,
    )
    registry.add(
        name="setup_camera",
        description="按景别与方位重新解算并放置某镜头的相机（相对被摄者朝向）。",
        parameters={"type": "object", "additionalProperties": False,
                    "properties": {
                        "shot_id": {"type": "string"},
                        "shot_type": {"type": "string",
                                      "enum": list(SHOT_TYPES)},
                        "side": {"type": "string",
                                 "enum": ["front", "back", "left", "right",
                                          "front_left", "front_right",
                                          "back_left", "back_right",
                                          "over_shoulder"]},
                        "lens": {"type": "number", "minimum": 8,
                                 "maximum": 300}}},
        handler=_tool_setup_camera,
    )
    log.info("已注册动作工具：%s", ", ".join(ACTION_TOOLS))


@main_thread_only("register_all_scene_tools")
def register_all_scene_tools(registry) -> None:
    """一次注册全部场景工具（查询 + 动作）。"""
    register_scene_tools(registry)
    register_action_tools(registry)
