"""把执行引擎暴露成 LLM 可调用的工具（执行文档 v1.2 §7.4）。

工具注册表本身在 layer5（不依赖 bpy）；本模块负责把**需要 bpy 的**查询与
操作绑定进注册表。红线不变：工具永不抛异常，失败一律转成可回灌的观察文本。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import bpy
from mathutils import Vector

from ..motion.model import ACTION_TYPES
from ..cinema.camera_motion import MOVEMENT_TYPES, TRANSLATIONS, describe
from ..cinema.framing import solve_framing
from ..contracts.enums import SHOT_TYPES
from ..knowledge.tool import SEARCH_KNOWLEDGE, register_knowledge_tools
from ..observation.state import format_scene_state
from ..layer5_orchestrator.tool_registry import ToolResult
from ..utils.logger import get_logger
from ..utils.threading_guard import main_thread_only
from .character_system import MotionBlender, get_facing
from .cinema_engine import (
    apply_camera_movement,
    check_camera_axis,
    evaluate_camera_composition,
    place_camera_for_shot,
)
from .scene_context import get_context
from .scene_state import collect_scene_state

log = get_logger("tool-bindings")

QUERY_TOOLS = ("get_scene_state", "check_visibility", "check_composition",
               "check_axis", "estimate_shot_duration")
ACTION_TOOLS = ("place_character", "move_character", "character_action",
                "look_at", "interact_with", "setup_camera", "move_camera",
                "reframe")
KNOWLEDGE_TOOLS = (SEARCH_KNOWLEDGE,)

#: §9.8 道具交互（代理模式）：交互类型 → 复用哪一个动作层
INTERACTION_ACTIONS = {"sit": "sit", "stand": "stand",
                       "take": "body_tilt", "open": "body_tilt",
                       "push": "body_tilt"}
INTERACTION_PARAMS = {"take": {"degrees": 12.0}, "open": {"degrees": 10.0},
                      "push": {"degrees": 15.0}}


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
    # 时长估算不碰 bpy，注册逻辑在被测过的纯模块里（§7.4）
    from ..layer5_orchestrator.timing_tool import register_timing_tools

    register_timing_tools(registry)
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


@main_thread_only("tool_move_character")
def _tool_move_character(character_id: str, target_position: List[float],
                         start_frame: int, end_frame: int,
                         speed: str = "walk", style: Optional[str] = None):
    """走位：等价于给角色加一段 ``walk_to`` / ``run_to``（§9.5 的移动语义）。"""
    character, problem = _require_character(character_id)
    if character is None:
        return problem
    action_type = "run_to" if str(speed) == "run" else "walk_to"
    params: Dict[str, Any] = {"target_position": [float(v)
                                                 for v in target_position],
                              # 起点必须是角色**当前**位置：动作模型里 from
                              # 默认是原点，不补这一条角色会从世界原点走过来。
                              "from": list(character.root.matrix_world.translation),
                              "speed": "run" if str(speed) == "run" else "walk"}
    if style:
        params["style"] = style
    return _tool_character_action(character_id, action_type,
                                  start_frame, end_frame, params)


@main_thread_only("tool_look_at")
def _tool_look_at(character_id: str, start_frame: int, end_frame: int,
                  target: str = "", target_position: Optional[List[float]] = None):
    """头部持续跟踪：目标可以是另一个角色 ID，也可以是世界坐标。"""
    params: Dict[str, Any] = {}
    if target_position is not None:
        params["target"] = [float(v) for v in target_position]
    elif target:
        other, problem = _require_character(target)
        if other is None:
            return problem
        params["target"] = list(other.root.matrix_world.translation)
        params["target_id"] = target
    else:
        return _fail("look_at 需要 target（角色 ID）或 target_position（坐标）之一")
    return _tool_character_action(character_id, "look_at",
                                  start_frame, end_frame, params)


@main_thread_only("tool_interact_with")
def _tool_interact_with(character_id: str, prop_id: str, interaction_type: str,
                        start_frame: int, end_frame: int):
    """道具交互（代理模式，§9.8）：动作复用 + 道具状态写入连贯性台账。"""
    action_type = INTERACTION_ACTIONS.get(str(interaction_type))
    if action_type is None:
        return _fail(f"未知交互类型 {interaction_type}。可用: "
                     f"{', '.join(sorted(INTERACTION_ACTIONS))}")
    prop = bpy.data.objects.get(f"BD_Prop_{prop_id}")
    if prop is None:
        prop = next((obj for obj in bpy.data.objects
                     if str(obj.get("bd_sdl_id") or "") == prop_id), None)
    if prop is None:
        return _fail(f"找不到道具 {prop_id}；请先在场景设定里声明这个道具")

    params: Dict[str, Any] = dict(INTERACTION_PARAMS.get(str(interaction_type), {}))
    if str(interaction_type) in ("take", "open", "push"):
        params.setdefault("toward", list(prop.matrix_world.translation))
    result = _tool_character_action(character_id, action_type,
                                    start_frame, end_frame, params)
    if isinstance(result, ToolResult):
        return result
    prop["bd_state"] = str(interaction_type)
    context = get_context()
    if context is not None:
        context.notes.append(f"{character_id} {interaction_type} {prop_id}"
                             f"（第 {start_frame}-{end_frame} 帧）")
    return f"{result}；道具 {prop_id} 状态 → {interaction_type}"


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


def _shot_target_object(shot_id: str):
    """取某镜相机对应的对准 Empty（Track To 的目标）。"""
    return bpy.data.objects.get(f"BD_CamTarget_{shot_id}")


@main_thread_only("tool_move_camera")
def _tool_move_camera(movement_type: str, start_frame: int, end_frame: int,
                      camera_id: str = "", amount: float = 0.0):
    """给某镜的相机加一段运镜（§10.2）。amount：平移=米，旋转=度。"""
    context = get_context()
    if context is None:
        return _fail("场景上下文为空：请先构建场景")
    shot_id = camera_id or context.current_shot_id
    camera = context.cameras.get(shot_id)
    if camera is None:
        known = ", ".join(sorted(context.cameras)) or "（无）"
        return _fail(f"找不到镜头 {shot_id} 的相机。可用镜头: {known}")

    default_amount = 1.0 if movement_type in TRANSLATIONS else 15.0
    try:
        report = apply_camera_movement(
            camera, _shot_target_object(shot_id), str(movement_type),
            float(amount) if amount else default_amount,
            int(start_frame), int(end_frame))
    except ValueError as exc:
        return _fail(str(exc))
    return (f"镜头 {shot_id} 已加运镜 {movement_type}"
            f"（{describe(str(movement_type))}，"
            f"{start_frame}-{end_frame} 帧，{report['keyframes']} 个关键帧）")


@main_thread_only("tool_reframe")
def _tool_reframe(shot_id: str = "", shot_type: Optional[str] = None,
                  lens: Optional[float] = None):
    """只调取景：复用同一台相机与同一个对准 Empty，重建位置/焦距。"""
    context = get_context()
    if context is None:
        return _fail("场景上下文为空：请先构建场景")
    shot_id = shot_id or context.current_shot_id
    shot = context.shot(shot_id)
    camera = context.cameras.get(shot_id)
    if shot is None or camera is None:
        known = ", ".join(sorted(context.cameras)) or "（无）"
        return _fail(f"找不到镜头 {shot_id}。可用镜头: {known}")

    resolved_type = str(shot_type or context.shot_types.get(
        shot_id, shot.shot_type))
    characters = [context.character(cid) for cid in shot.characters]
    characters = [item for item in characters if item is not None]
    if not characters:
        return _fail(f"镜头 {shot_id} 没有在场角色，无法重解取景")
    positions = [item.root.matrix_world.translation for item in characters]
    anchor = sum(positions, Vector()) / len(positions)
    facing = get_facing(characters[0])

    solution = solve_framing(subject_pos=anchor, facing=facing,
                             shot_type=resolved_type, side="front",
                             lens=lens, room=None)
    camera.location = solution.position
    camera.data.lens = float(solution.lens)
    target = _shot_target_object(shot_id)
    if target is not None:
        target.location = solution.target
    camera["bd_shot_type"] = solution.shot_type
    camera["bd_frame_height"] = solution.frame_height
    context.shot_types[shot_id] = solution.shot_type
    bpy.context.view_layer.update()
    return (f"镜头 {shot_id} 取景已调整：{solution.shot_type}，"
            f"位置 {tuple(round(v, 3) for v in solution.position)}，"
            f"焦距 {solution.lens:g}mm（相机对象未重建）")


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
    registry.add(
        name="move_character",
        description="让角色走到目标位置并生成行走动画（帧号为全局帧）。",
        parameters={"type": "object", "additionalProperties": False,
                    "required": ["character_id", "target_position",
                                 "start_frame", "end_frame"],
                    "properties": {
                        "character_id": {"type": "string"},
                        "target_position": {"type": "array", "minItems": 3,
                                            "maxItems": 3,
                                            "items": {"type": "number"}},
                        "speed": {"type": "string",
                                  "enum": ["walk", "run"]},
                        "style": {"type": "string"},
                        "start_frame": {"type": "integer", "minimum": 1},
                        "end_frame": {"type": "integer", "minimum": 1}}},
        handler=_tool_move_character,
    )
    registry.add(
        name="look_at",
        description="让角色头部持续看向某个目标（角色 ID 或世界坐标）。",
        parameters={"type": "object", "additionalProperties": False,
                    "required": ["character_id", "start_frame", "end_frame"],
                    "properties": {
                        "character_id": {"type": "string"},
                        "target": {"type": "string"},
                        "target_position": {"type": "array", "minItems": 3,
                                            "maxItems": 3,
                                            "items": {"type": "number"}},
                        "start_frame": {"type": "integer", "minimum": 1},
                        "end_frame": {"type": "integer", "minimum": 1}}},
        handler=_tool_look_at,
    )
    registry.add(
        name="interact_with",
        description="角色与道具交互（坐/起/拿/开/推）；道具状态写进连贯性台账。",
        parameters={"type": "object", "additionalProperties": False,
                    "required": ["character_id", "prop_id", "interaction_type",
                                 "start_frame", "end_frame"],
                    "properties": {
                        "character_id": {"type": "string"},
                        "prop_id": {"type": "string"},
                        "interaction_type": {
                            "type": "string",
                            "enum": list(INTERACTION_ACTIONS)},
                        "start_frame": {"type": "integer", "minimum": 1},
                        "end_frame": {"type": "integer", "minimum": 1}}},
        handler=_tool_interact_with,
    )
    registry.add(
        name="move_camera",
        description="给某镜的相机加一段运镜（推/拉/摇/移/跟/升降）。",
        parameters={"type": "object", "additionalProperties": False,
                    "required": ["movement_type", "start_frame", "end_frame"],
                    "properties": {
                        "camera_id": {"type": "string"},
                        "movement_type": {"type": "string",
                                          "enum": list(MOVEMENT_TYPES)},
                        "amount": {"type": "number", "minimum": 0,
                                   "maximum": 180},
                        "start_frame": {"type": "integer", "minimum": 1},
                        "end_frame": {"type": "integer", "minimum": 1}}},
        handler=_tool_move_camera,
    )
    registry.add(
        name="reframe",
        description="只调整取景（景别/焦距），复用同一台相机，不重建。",
        parameters={"type": "object", "additionalProperties": False,
                    "properties": {
                        "shot_id": {"type": "string"},
                        "shot_type": {"type": "string",
                                      "enum": list(SHOT_TYPES)},
                        "lens": {"type": "number", "minimum": 8,
                                 "maximum": 300}}},
        handler=_tool_reframe,
    )
    log.info("已注册动作工具：%s", ", ".join(ACTION_TOOLS))


@main_thread_only("register_all_scene_tools")
def register_all_scene_tools(registry) -> None:
    """一次注册全部工具（查询 + 动作 + 知识）。

    知识工具不碰 bpy（语料是纯数据），但和其它工具共享同一个入口，LLM 看到的
    工具列表因此只有一份真源。
    """
    register_scene_tools(registry)
    register_action_tools(registry)
    register_knowledge_tools(registry)
    log.info("已注册知识工具：%s", ", ".join(KNOWLEDGE_TOOLS))
