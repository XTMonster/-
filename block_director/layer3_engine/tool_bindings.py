"""把执行引擎暴露成 LLM 可调用的工具（执行文档 v1.2 §7.4）。

工具注册表本身在 layer5（不依赖 bpy）；本模块负责把**需要 bpy 的**查询与
操作绑定进注册表。红线不变：工具永不抛异常，失败一律转成可回灌的观察文本。
"""

from __future__ import annotations

from typing import Any, Dict

from ..observation.state import format_scene_state
from ..layer5_orchestrator.tool_registry import ToolResult
from ..utils.logger import get_logger
from ..utils.threading_guard import main_thread_only
from .cinema_engine import check_camera_axis, evaluate_camera_composition
from .scene_context import get_context
from .scene_state import collect_scene_state

log = get_logger("tool-bindings")

QUERY_TOOLS = ("get_scene_state", "check_visibility", "check_composition",
               "check_axis")


def _fail(text: str) -> ToolResult:
    """领域级失败：调用没成，交给驱动器的修复循环处理。"""
    return ToolResult(False, text, error="domain_error")


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
