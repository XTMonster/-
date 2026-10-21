"""把执行引擎暴露成 LLM 可调用的工具（执行文档 v1.2 §7.4）。

工具注册表本身在 layer5（不依赖 bpy）；本模块负责把**需要 bpy 的**查询与
操作绑定进注册表。红线不变：工具永不抛异常，失败一律转成可回灌的观察文本。
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any, Dict, List, Optional

import bpy
from mathutils import Vector

from ..motion.model import (
    ACTION_TYPES,
    head_track_angles,
    normalize_action_params,
)
from ..cinema.axis import Axis
from ..cinema.camera_motion import (
    MOVEMENT_TYPES,
    TRANSLATIONS,
    describe,
    movement_samples,
)
from ..cinema.framing import (
    CAMERA_SIDES,
    shot_frame_for,
    solve_framing,
    vertical_fov,
)
from ..cinema.station import camera_direction, subject_frame
from ..contracts.enums import SHOT_TYPES, ShotType
from ..contracts.backtrack import revert_ops
from ..contracts.camera_ref import resolve_camera_ref
from ..knowledge.tool import SEARCH_KNOWLEDGE, register_knowledge_tools
from ..observation.state import format_scene_state
from ..layer5_orchestrator.tool_registry import ToolResult
from ..utils.logger import get_logger
from ..utils.threading_guard import main_thread_only
from ..utils.blender_compat import action_fcurves
from .character_system import MotionBlender, get_facing
from .cinema_engine import (
    CameraBundle,
    apply_camera_movement,
    check_camera_axis,
    evaluate_camera_composition,
    place_camera_for_shot,
)
from .scene_context import get_context
from .scene_sync import (
    get_synchronizer,
    mark_agent_edited,
    suppress_sync,
)
from .scene_state import collect_scene_state
from .world_state import ensure_consistent, note_divergence, refresh_world_state
from .shot_builder import (
    apply_declared_movements,
    axis_for_shot,
    live_subject_entries,
    place_shot_camera,
    release_shot_camera,
    speaker_of,
)

log = get_logger("tool-bindings")

#: v1.5：这三份名单搬去了 `contracts/tools.py`（单一真源）——驱动器要判断
#: "这一轮动没动手"，而它**不许 import bpy**（本模块会 import bpy）。
from ..contracts.tools import (  # noqa: E402
    ACTION_TOOLS,
    KNOWLEDGE_TOOL_NAMES as KNOWLEDGE_TOOLS,
    QUERY_TOOLS,
)

#: §9.8 道具交互（代理模式）：交互类型 → 复用哪一个动作层
INTERACTION_ACTIONS = {"sit": "sit", "stand": "stand",
                       "take": "body_tilt", "open": "body_tilt",
                       "push": "body_tilt"}
#: v1.4 BW-1：键名必须用 ``motion/model.py::body_tilt_params`` 登记过的别名。
#: 旧写法 ``{"degrees": …}`` 与 ``expand()`` 只认的 ``angle_deg`` 对不上，
#: 于是 take/open/push 的倾斜被**静默吃掉**（而改成报错之前必须先改这里，
#: 否则这三条交互会从"静默失效"变成"直接报错"，属引入回归）。
INTERACTION_PARAMS = {"take": {"angle_deg": 12.0}, "open": {"angle_deg": 10.0},
                      "push": {"angle_deg": 15.0}}


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


def _require_character_in_shot(character_id: str):
    """v1.6 A3（D-17）：动作工具的前置校验，失败返回 ``(None, ToolResult)``。"""
    context = get_context()
    if context is None:
        return None, _fail("场景上下文为空：请先构建场景")
    message = context.require_character_in_shot(character_id)
    if message:
        return None, _fail(message)
    return context.shot(), ""


def _resolve_camera(args: Dict[str, Any]):
    """按 camera_id / 当前镜头找相机；找不到返回 ``(None, 错误文本)``。

    缺陷 E：camera_id 按纯层引用解析（对象名 → 镜头键 → BD_Cam_ 前缀），
    单镜重建后旧 ID 仍能定位到当前相机对象。
    """
    context = get_context()
    if context is None:
        return None, _fail("场景上下文为空：请先构建场景")
    camera_id = str(args.get("camera_id") or "")
    if camera_id:
        camera, _shot_id, problem = resolve_camera_ref(context.cameras,
                                                       camera_id)
        if camera is None:
            return None, _fail(problem)
        return camera, ""
    camera = context.camera_for()
    if camera is None:
        return None, _fail("当前镜头没有相机")
    return camera, ""


@main_thread_only("tool_get_scene_state")
def _tool_get_scene_state() -> str:
    context = get_context()
    findings = ensure_consistent(context)
    if findings:
        note_divergence(context, findings)
    return format_scene_state(collect_scene_state(detailed=False))


@main_thread_only("tool_check_visibility")
def _tool_check_visibility(character_id: str = "", camera_id: str = ""):
    context = get_context()
    if context is None:
        return _fail("场景上下文为空：请先构建场景")
    findings = ensure_consistent(context)
    if findings:
        note_divergence(context, findings)
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
    findings = ensure_consistent(context)
    if findings:
        note_divergence(context, findings)
    camera, problem = _resolve_camera({"camera_id": camera_id})
    if camera is None:
        return problem
    shot_id = context.current_shot_id
    shot_type = context.shot_types.get(shot_id, "MS")
    shot = context.shot(shot_id)
    framing_target = getattr(shot, "framing_target", None)
    report = evaluate_camera_composition(camera, context.subjects_for(shot_id),
                                         shot_type=shot_type,
                                         framing_target=framing_target)
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
    #: 缺陷 C：agent 工具写入必须包在 suppress 窗口并打 agent 标记，否则
    #: 单镜 rebuild 前 sync_from_blender 会把模型挪过的位置回读成
    #: "用户改动"固化进 initial_location（2026-10-19 kimi 真跑实证）。
    with suppress_sync(get_synchronizer()):
        if position is not None:
            character.root.location = tuple(float(v) for v in position)
        if facing is not None:
            from ..utils.geometry import facing_to_rotation_z
            character.root.rotation_euler = (
                0.0, 0.0,
                facing_to_rotation_z(tuple(float(v) for v in facing)))
        bpy.context.view_layer.update()
        mark_agent_edited(character.root)
    location = tuple(round(v, 3) for v in character.root.matrix_world.translation)
    refresh_world_state(get_context())
    return f"角色 {character_id} 已就位：位置 {location}"


@main_thread_only("tool_character_action")
def _tool_character_action(character_id: str, action_type: str,
                           start_frame: int, end_frame: int,
                           params: Optional[Dict[str, Any]] = None):
    # Validate shot membership first: an environment subject has no Character
    # object, but still needs the shot-specific roster and vfx guidance.
    shot, problem = _require_character_in_shot(character_id)
    if shot is None:
        return problem
    character, problem = _require_character(character_id)
    if character is None:
        return problem
    if action_type not in ACTION_TYPES:
        return _fail(f"未知动作类型 {action_type}。可用: "
                     f"{', '.join(ACTION_TYPES)}")
    if int(end_frame) <= int(start_frame):
        return _fail("end_frame 必须大于 start_frame")

    params = normalize_action_params(action_type, dict(params or {}))
    #: 缺陷 C：动作烘焙也是 agent 写入，同样包 suppress + 打标记。
    with suppress_sync(get_synchronizer()):
        blender = MotionBlender(character)
        blender.add(action_type, int(start_frame), int(end_frame), **params)
        conflicts = blender.validate()
        if conflicts:
            return _fail("动作冲突：" + "；".join(conflicts))
        try:
            result = blender.bake(clear=False)      # 叠加，不清掉已有动画
        except ValueError as exc:
            return _fail(f"动作烘焙失败：{exc}")
        mark_agent_edited(character.root)
    refresh_world_state(get_context())
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
    shot, problem = _require_character_in_shot(character_id)
    if shot is None:
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
    """头部持续跟踪：目标可以是另一个角色 ID，也可以是世界坐标。

    v1.2 把目标位置塞进 ``params["target"]``，而动作层
    （``motion/model.py`` 的 ``look_at`` 分支）**只读 ``yaw_deg`` / ``pitch_deg``**
    ——目标被静默忽略，于是"看向某人"永远只是把头固定转 30°。
    这里先把目标换算成相对**身体朝向**的偏角再传下去。
    """
    character, problem = _require_character(character_id)
    if character is None:
        return problem
    shot, problem = _require_character_in_shot(character_id)
    if shot is None:
        return problem
    position: Optional[List[float]] = None
    if target_position is not None:
        position = [float(v) for v in target_position]
    elif target:
        other, problem = _require_character(target)
        if other is None:
            return problem
        position = list(other.root.matrix_world.translation)
    else:
        return _fail("look_at 需要 target（角色 ID）或 target_position（坐标）之一")

    bpy.context.view_layer.update()
    origin = tuple(character.root.matrix_world.translation)
    yaw, pitch, note = head_track_angles(origin, get_facing(character),
                                         position)
    params: Dict[str, Any] = {"yaw_deg": yaw, "pitch_deg": pitch,
                              "target": list(position)}
    if target:
        params["target_id"] = target
    result = _tool_character_action(character_id, "look_at",
                                    start_frame, end_frame, params)
    if isinstance(result, ToolResult):
        return result
    suffix = f"；{note}" if note else ""
    return f"{result}（头部偏航 {yaw:.1f}°、俯仰 {pitch:.1f}°）{suffix}"


@main_thread_only("tool_face_character")
def _tool_face_character(character_id: str, target: str = "",
                         target_position: Optional[List[float]] = None):
    """把角色的**身体**转向目标（不是只转头）。

    之所以需要单独一个工具：头部只有 ±90° 的活动范围，"看向彼此"必须由
    身体朝向承担主体，否则两人正对时谁也看不见谁（见
    ``motion.model.head_track_angles`` 的说明）。
    """
    character, problem = _require_character(character_id)
    if character is None:
        return problem
    shot, problem = _require_character_in_shot(character_id)
    if shot is None:
        return problem
    position: Optional[List[float]] = None
    if target_position is not None:
        position = [float(v) for v in target_position]
    elif target:
        other, problem = _require_character(target)
        if other is None:
            return problem
        position = list(other.root.matrix_world.translation)
    else:
        return _fail("face_character 需要 target（角色 ID）"
                     "或 target_position（坐标）之一")

    with suppress_sync(get_synchronizer()):
        bpy.context.view_layer.update()
        origin = character.root.matrix_world.translation
        dx = float(position[0]) - float(origin.x)
        dy = float(position[1]) - float(origin.y)
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            return _fail(f"角色 {character_id} 与目标位置重合，无法确定朝向")
        from ..utils.geometry import facing_to_rotation_z
        character.root.rotation_euler = (
            0.0, 0.0, facing_to_rotation_z((dx, dy, 0.0)))
        bpy.context.view_layer.update()
        mark_agent_edited(character.root)
    refresh_world_state(get_context())
    return (f"角色 {character_id} 已转身面向 "
            f"({round(float(position[0]), 2)}, {round(float(position[1]), 2)})")


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
    #: 缺陷 C：道具状态写入也是 agent 写入。
    with suppress_sync(get_synchronizer()):
        prop["bd_state"] = str(interaction_type)
        mark_agent_edited(prop)
    refresh_world_state(get_context())
    context = get_context()
    if context is not None:
        context.notes.append(f"{character_id} {interaction_type} {prop_id}"
                             f"（第 {start_frame}-{end_frame} 帧）")
    return f"{result}；道具 {prop_id} 状态 → {interaction_type}"


@main_thread_only("tool_setup_camera")
def _tool_setup_camera(shot_id: str = "", shot_type: str = "MS",
                       side: str = "front", lens: Optional[float] = None):
    """按取景解算重设某一镜的机位。

    **机位解算只有一个入口**：本工具走 `shot_builder.place_shot_camera`，与主
    构建、单镜再生同一份实现。2026-10-04 的实测（`work/_tool_vs_builder_probe.py`，
    long16 工程）证明以前这条捷径走了样：它自己拼 `axis_dir/axis_side` 再直接调
    `place_camera_for_shot`，于是**丢了三样构建器有的东西**——

    * 视线留白与头顶留白的对准点偏移（§10.4 / §六十九）；
    * `spec.room` 的房间钳制；
    * **逐镜**轴侧（顺序状态机 `_axis_sides_used`），它读的是全片一个常数的
      `context.axis.established_side`。

    还有时间点：`live_subject_entries` 读的是**当前帧**的角色站位，而本工具的
    契约是"这一镜"的机位 ⇒ 必须先把帧拨到该镜首帧（构建器就是这么做的）。
    代价实测：拿**计划自己的**参数重设一次，64 镜里 34 镜构图更差、10 镜由
    通过变不通过（最差 `shot_027` 83.2 → 20.0）。修复回路"改了却更糟"的
    主因就在这里。
    """
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

    resolved_type = str(shot_type or shot.shot_type).upper()
    if resolved_type not in SHOT_TYPES:
        return _fail(f"不认识的景别 {shot_type}；允许的取值："
                     f"{'、'.join(SHOT_TYPES)}")

    request: Dict[str, Any] = {"side": str(side or "front")}
    if lens is not None:
        request["lens"] = float(lens)
    #: 机位瞄的是**这一镜首帧**人在哪，所以先把帧拨过去；工具不该把时间轴留在
    #: 别处，摆完还原（与 `check_shot` 的"审核不改场景状态"同一口径）。
    scene = bpy.context.scene
    original_frame = int(scene.frame_current)
    start = int((context.schedule.get(shot_id) or (0, 0))[0] or 0)
    if start:
        scene.frame_set(start)
        bpy.context.view_layer.update()
    #: 缺陷 C：整段相机写入（删旧建新＋重放运镜＋剪切标记）都是 agent 写入，
    #: 必须包在 suppress 窗口内，否则 depsgraph 回调会把脏集合污染成"用户
    #: 改动"，下一次 rebuild 前 sync 就会把模型自己摆的机位固化。
    with suppress_sync(get_synchronizer()):
        try:
            axis = axis_for_shot(context, shot)
            #: 对象、**数据**与对准 Empty 一起放掉：只删对象会留下同名残留，
            #: 下一次建的相机就只能叫 `…​.001`，而按名字找对准点的地方拿的是旧的
            #: （见 `shot_builder.release_shot_camera` 的抬头）。
            release_shot_camera(shot_id)
            bundle, solution, _frame = place_shot_camera(
                replace(shot, shot_type=ShotType(resolved_type)),
                {}, context.spec, request=request, axis=axis,
                entries=live_subject_entries(shot, context.characters))
            #: 先把新相机登记进上下文——`apply_declared_movements` 是**按上下文**取
            #: 相机对象的，登记晚一步它就会去动那台已经删掉的旧对象。
            context.cameras[shot_id] = bundle.camera
            context.shot_types[shot_id] = solution.shot_type
            #: 重建相机对象会连**关键帧**一起丢；这一镜声明的运镜必须重放，
            #: 否则"修复"顺手把镜头运动删了（构图门取首/中/尾最小值，运动一没
            #: 结论就变）。与主构建共用 `apply_declared_movements`。
            applied, _keyframes, warnings = apply_declared_movements(
                replace(shot, shot_type=ShotType(resolved_type)),
                context.characters, start or 1,
                int((context.schedule.get(shot_id) or (0, 1))[1] or 1),
                camera=bundle.camera, target=bundle.target)
        finally:
            if start and int(bpy.context.scene.frame_current) != original_frame:
                bpy.context.scene.frame_set(original_frame)
                bpy.context.view_layer.update()

        marker = scene.timeline_markers.get(f"BD_Cut_{shot_id}")
        if marker is not None:
            marker.camera = bundle.camera
        bpy.context.view_layer.update()
        mark_agent_edited(bundle.camera)
        if bundle.target is not None:
            mark_agent_edited(bundle.target)
    refresh_world_state(get_context())
    return (f"镜头 {shot_id} 机位已重设：{solution.shot_type} / {side}，"
            f"位置 {tuple(round(v, 3) for v in solution.position)}，"
            f"距离 {solution.distance:.2f}，焦距 {solution.lens:g}mm"
            f"（相机稳定引用：{shot_id}）"
            + (f"，重放运镜 {applied} 段" if applied else "")
            + ("；" + "；".join(warnings) if warnings else ""))


def _shot_target_object(shot_id: str):
    """取某镜相机对应的对准 Empty（Track To 的目标）。"""
    return bpy.data.objects.get(f"BD_CamTarget_{shot_id}")


@main_thread_only("restore_world_snapshot")
def restore_world_snapshot(payload, context=None) -> List[str]:
    """按最高分世界状态快照恢复角色/相机/道具（缺陷 B / T6）。

    恢复写入包 ``suppress_sync`` 并打 agent 标记（缺陷 C 语义：这是 agent
    版本回退，不是用户改动），随后刷新 ``runtime_world_state.json``（R11）。
    返回恢复记录（每类恢复一条），失败由调用方转成工具观察文本。
    """
    from ..utils.geometry import facing_to_rotation_z

    context = context or get_context()
    notes: List[str] = []
    if context is None:
        return notes
    with suppress_sync(get_synchronizer()):
        for op in revert_ops(payload):
            kind = op["kind"]
            if kind == "character":
                character = context.characters.get(op["id"])
                if character is None or character.root is None:
                    continue
                character.root.location = tuple(float(v) for v in op["position"])
                character.root.rotation_euler = (
                    0.0, 0.0, facing_to_rotation_z(tuple(op["facing"])))
                mark_agent_edited(character.root)
                notes.append(f"{op['id']} 位置/朝向已恢复")
            elif kind == "camera":
                camera = context.cameras.get(op["id"])
                if camera is None:
                    continue
                camera.location = tuple(float(v) for v in op["position"])
                if getattr(camera, "data", None) is not None:
                    camera.data.lens = float(op["lens_mm"])
                mark_agent_edited(camera)
                target = _shot_target_object(op["id"])
                if target is not None:
                    target.location = tuple(float(v) for v in op["target"])
                    mark_agent_edited(target)
                notes.append(f"相机 {op['id']} 位置/目标/焦距已恢复")
            elif kind == "prop":
                prop = bpy.data.objects.get(f"BD_Prop_{op['id']}")
                if prop is None:
                    continue
                prop.location = tuple(float(v) for v in op["position"])
                prop.rotation_euler = (
                    float(prop.rotation_euler[0]),
                    float(prop.rotation_euler[1]),
                    float(op["rotation_z"]))
                mark_agent_edited(prop)
                notes.append(f"道具 {op['id']} 位置/旋转已恢复")
    #: 恢复后必须先求值 depsgraph：``collect_world_state`` 读的是
    #: ``matrix_world``，不刷新会把恢复前的陈旧矩阵写进 JSON（探针实测：
    #: 角色已回到 [-0.9,0,0]，JSON 却留下 [9,9,0]）。
    bpy.context.view_layer.update()
    refresh_world_state(context)
    return notes


@main_thread_only("tool_revert_shot")
def _tool_revert_shot(shot_id: str = ""):
    """把当前镜回滚到最高分版本快照（相机+角色+道具，JSON 同步刷新）。"""
    context = get_context()
    if context is None:
        return _fail("场景上下文为空：请先构建场景")
    shot_id = shot_id or context.current_shot_id
    snapshot = getattr(context, "react_best_snapshot", {}).get(shot_id)
    if snapshot is None:
        return _fail(
            f"镜头 {shot_id} 没有最高分版本快照；revert_shot 只在精修回溯阶段"
            f"可用（需先有一次审核分数并记录 best）")
    try:
        restored = restore_world_snapshot(snapshot, context)
    except Exception as exc:  # noqa: BLE001 - §16.2：工具永不抛异常
        return _fail(f"回滚失败：{type(exc).__name__}: {exc}")
    return (f"镜头 {shot_id} 已回滚到最高分版本（"
            + "、".join(restored) + "）；runtime_world_state.json 已同步刷新")


@main_thread_only("register_react_tools")
def register_react_tools(registry) -> None:
    """注册仅 ReAct 精修阶段使用的工具（缺陷 B / T6，重复调用安全）。"""
    registry.add(
        name="revert_shot",
        description="把当前镜头回滚到历史最高分版本（相机位置/目标/焦距、"
                    "角色位置/朝向、道具位置），并同步刷新运行时世界坐标 JSON。"
                    "分数没升时用它回到最高分版本再试。",
        parameters={"type": "object", "additionalProperties": False,
                    "properties": {"shot_id": {"type": "string"}}},
        handler=_tool_revert_shot,
    )


def _placement_axis(context, shot_id: str) -> Optional[Axis]:
    """修复工具用的摆位轴（与 ``rule_checker._camera_on_wrong_side`` 同参照系）。

    摆位时记录的那条线（``_axis_lines_used``）＋逐镜侧别（``_axis_sides_used``）；
    没有记录（手工场景/旧工程）返回 ``None``，不强行护栏。
    """
    lines = dict(getattr(context, "_axis_lines_used", None) or {})
    sides = dict(getattr(context, "_axis_sides_used", None) or {})
    recorded = lines.get(str(shot_id))
    side = sides.get(str(shot_id))
    if not recorded or len(recorded) != 2 or side is None:
        return None
    return Axis(start=tuple(recorded[0]), end=tuple(recorded[1]),
                established_side=int(side))


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
        #: 缺陷 E：模型手里的 camera_id 可能是对象名/旧引用，按纯层解析
        #: （对象名 → 镜头键 → BD_Cam_ 前缀），重建后旧 ID 不再失效。
        resolved, resolved_shot, problem = resolve_camera_ref(
            context.cameras, camera_id)
        if resolved is None:
            return _fail(problem)
        camera, shot_id = resolved, resolved_shot

    default_amount = 1.0 if movement_type in TRANSLATIONS else 15.0
    #: v1.6 G2：平移类运镜在写入前先采样路径——若会跨到摆位线的另一侧，就是
    #: 规则已判 error 的"机位在错侧"，工具不该帮模型制造它（v5 真跑 12 条
    #: wrong_side 正是修复回合给平移运镜跨线而来）。参照系与审核同源。
    if str(movement_type) in TRANSLATIONS:
        shot = context.shot(shot_id)
        if shot is not None:
            placement = _placement_axis(context, shot_id)
            if placement is not None:
                scene = bpy.context.scene
                original_frame = int(scene.frame_current)
                start = int((context.schedule.get(shot_id) or (0, 0))[0] or 0)
                if start:
                    scene.frame_set(start)
                    bpy.context.view_layer.update()
                try:
                    camera_pos = camera.matrix_world.translation
                    target_obj = _shot_target_object(shot_id)
                    target_pos = (target_obj.matrix_world.translation
                                  if target_obj is not None else camera_pos)
                    side_now = placement.side_of(
                        (float(camera_pos.x), float(camera_pos.y)))
                    if side_now != 0:
                        samples = movement_samples(
                            tuple(camera_pos), tuple(target_pos),
                            str(movement_type),
                            float(amount) if amount else default_amount,
                            int(start_frame), int(end_frame),
                            lens=float(getattr(camera.data, "lens", 50.0)
                                       or 50.0))
                        for sample in samples:
                            position = sample.get("position")
                            if position is not None and placement.side_of(
                                    (float(position[0]),
                                     float(position[1]))) == -side_now:
                                return _fail(
                                    f"运镜 {movement_type} 会在第 {sample.get('frame')} 帧"
                                    f"把机位带到两人连线的另一侧（180° 轴线）。"
                                    f"请改用不跨线的运镜/焦段，或先安排可见的换位。")
                finally:
                    if int(bpy.context.scene.frame_current) != original_frame:
                        scene.frame_set(original_frame)
                        bpy.context.view_layer.update()
    with suppress_sync(get_synchronizer()):
        try:
            report = apply_camera_movement(
                camera, _shot_target_object(shot_id), str(movement_type),
                float(amount) if amount else default_amount,
                int(start_frame), int(end_frame))
            #: 缺陷 C：运镜关键帧是 agent 写入，打标记防回读。
            mark_agent_edited(camera)
            target = _shot_target_object(shot_id)
            if target is not None:
                mark_agent_edited(target)
        except ValueError as exc:
            return _fail(str(exc))
    refresh_world_state(get_context())
    return (f"镜头 {shot_id} 已加运镜 {movement_type}"
            f"（{describe(str(movement_type))}，"
            f"{start_frame}-{end_frame} 帧，{report['keyframes']} 个关键帧）")


@main_thread_only("tool_reframe")
def _tool_reframe(shot_id: str = "", shot_type: Optional[str] = None,
                  lens: Optional[float] = None,
                  preserve_pose: bool = False):
    """只调取景：复用同一台相机与同一个对准 Empty，重建位置/焦距。

    **解算与主构建是同一份**（`place_shot_camera` ＋ `reuse=`）。抬头自称"与主
    构建共用同一套参考系与同一套 side 解析"、代码却写死 `side="front"` 并绕开
    留白与 room 钳制——2026-10-04 实测（`work/_tool_vs_builder_probe.py --tool
    reframe`，long16 工程）：64 镜里 9 镜构图更差、3 镜由通过变不通过。
    """
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
    if resolved_type not in SHOT_TYPES:
        return _fail(f"不认识的景别 {shot_type}；允许的取值："
                     f"{'、'.join(SHOT_TYPES)}")
    characters = [context.character(cid) for cid in shot.characters]
    characters = [item for item in characters if item is not None]
    if not characters:
        return _fail(f"镜头 {shot_id} 没有在场角色，无法重解取景")

    #: 重解取景瞄的是**这一镜首帧**人在哪（与 `setup_camera` 同一口径）。
    scene = bpy.context.scene
    original_frame = int(scene.frame_current)
    start = int((context.schedule.get(shot_id) or (0, 0))[0] or 0)
    if start:
        scene.frame_set(start)
        bpy.context.view_layer.update()
    if preserve_pose:
        def restore_original_frame() -> None:
            if start and int(scene.frame_current) != original_frame:
                scene.frame_set(original_frame)
                bpy.context.view_layer.update()

        try:
            target = _shot_target_object(shot_id)
            if target is None:
                return _fail(f"镜头 {shot_id} 缺少对准 Empty，无法只调焦距")
            previous_lens = float(camera.data.lens)
            desired_lens = (float(lens) if lens is not None
                            else (float(shot_frame_for(resolved_type).lens)
                                  if resolved_type != context.shot_types.get(
                                      shot_id, str(shot.shot_type))
                                  else previous_lens))
            if not 8.0 <= desired_lens <= 300.0:
                return _fail(f"焦距必须在 8–300mm，实际 {desired_lens:g}mm")
            with suppress_sync(get_synchronizer()):
                ratio = desired_lens / previous_lens \
                    if previous_lens > 0.0 else 1.0
                animation = camera.data.animation_data
                action = getattr(animation, "action", None)
                if action is not None and abs(ratio - 1.0) > 1e-12:
                    for curve in action_fcurves(action):
                        if curve.data_path != "lens":
                            continue
                        for point in curve.keyframe_points:
                            point.co.y *= ratio
                        curve.update()
                camera.data.lens = desired_lens
                position = tuple(camera.location)
                aim = tuple(target.location)
                distance = math.sqrt(sum(
                    (float(aim[index]) - float(position[index])) ** 2
                    for index in range(3)))
                camera["bd_frame_height"] = (
                    2.0 * distance
                    * math.tan(vertical_fov(desired_lens) / 2.0))
                camera["bd_shot_type"] = resolved_type
                context.shot_types[shot_id] = resolved_type
                mark_agent_edited(camera)
                mark_agent_edited(target)
            restore_original_frame()
            refresh_world_state(get_context())
            return (f"镜头 {shot_id} 仅调整焦距：{previous_lens:g}→"
                    f"{desired_lens:g}mm；机位与对准点保持不动")
        finally:
            restore_original_frame()
    #: side 用**计划自己声明的**那一个（以前写死 "front"）：`reframe` 的契约是
    #: "只调取景"，那就没有理由把机位挪到另一侧去。
    plan_side = str((getattr(shot, "camera", None) or {}).get("side") or "front")
    request: Dict[str, Any] = {"side": plan_side}
    if lens is not None:
        request["lens"] = float(lens)
    with suppress_sync(get_synchronizer()):
        try:
            bundle, solution, _frame = place_shot_camera(
                replace(shot, shot_type=ShotType(resolved_type)),
                {}, context.spec, request=request,
                axis=axis_for_shot(context, shot),
                entries=live_subject_entries(shot, context.characters),
                #: 复用同一台相机与同一个对准 Empty（对象不重建）。
                reuse=CameraBundle(camera=camera,
                                   target=_shot_target_object(shot_id)))
        finally:
            if start and int(bpy.context.scene.frame_current) != original_frame:
                bpy.context.scene.frame_set(original_frame)
                bpy.context.view_layer.update()
        context.shot_types[shot_id] = solution.shot_type
        #: 缺陷 C：取景调整是 agent 写入，打标记防回读。
        mark_agent_edited(camera)
        target = _shot_target_object(shot_id)
        if target is not None:
            mark_agent_edited(target)
    refresh_world_state(get_context())
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
                        #: 取值表**从 cinema/framing.py 取**（单一真源）——此前这里是
                        #: 一份手抄的枚举，而同一个值在 B1 草案 schema 里根本没声明，
                        #: 于是模型在草案里写中文句子、求解器静默折成 `front`（实测
                        #: 64 镜构图分中位 82.7 → 58.4）。两处各写一份就是这种漂的温床。
                        "side": {"type": "string",
                                 "enum": list(CAMERA_SIDES)},
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
        name="face_character",
        description="把角色的**身体**转向目标（角色 ID 或世界坐标）。"
                    "头部只有 ±90°，需要看向身后或建立对视时必须先转身。",
        parameters={"type": "object", "additionalProperties": False,
                    "required": ["character_id"],
                    "properties": {
                        "character_id": {"type": "string"},
                        "target": {"type": "string"},
                        "target_position": {"type": "array", "minItems": 3,
                                            "maxItems": 3,
                                            "items": {"type": "number"}}}},
        handler=_tool_face_character,
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
                                 "maximum": 300},
                        "preserve_pose": {"type": "boolean",
                                          "description":
                                          "只改焦距，保持已审机位与对准点"}}},
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
    register_react_tools(registry)
    register_knowledge_tools(registry)
    log.info("已注册知识工具：%s", ", ".join(KNOWLEDGE_TOOLS))
