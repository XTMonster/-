"""调试面板（执行文档 v1.2 §13.3，默认折叠）。

展示 LLM 调用次数 / 总 Token / 预估费用 / 总耗时 / 审核通过失败数 / 自纠错
次数 / 预算余量，并提供三个动作：查看 LLM Trace、导出 SDL、导出场景状态。

三个动作都写成算子（而不是面板里的内联代码），因为它们会写文件、会读大批
数据——那属于"用户按一下才发生"的事。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import bpy
from bpy.props import StringProperty
from bpy.types import Operator, Panel

from ..layer2_sdl import build_sdl, validate_sdl
from ..layer3_engine.scene_state import collect_scene_state
from ..layer5_orchestrator.runtime import get_active
from ..layer9_persistence import save_project
from ..utils.logger import get_logger

log = get_logger("ui")

TRACE_TEXT_NAME = "BlockDirector LLM Trace"
SCENE_STATE_FILE = "scene_state.json"


def _project_dir(context) -> Path:
    raw = (context.scene.bd_project_dir or "").strip()
    if not raw:
        raw = os.path.join(bpy.app.tempdir or ".", "blockdirector")
    return Path(bpy.path.abspath(raw))


class BLOCKDIRECTOR_OT_open_llm_trace(Operator):
    """把 LLM Trace 读进文本编辑器（没有 trace 时给出原因）。"""

    bl_idname = "blockdirector.open_llm_trace"
    bl_label = "查看 LLM Trace"
    bl_description = "把本次运行的 llm_trace.jsonl 读进 Blender 文本编辑器"

    def execute(self, context):  # noqa: D102 - bpy 接口
        driver = get_active()
        trace_path = ""
        if driver is not None:
            trace_path = str(driver.audit.trace_path or "")
        if not trace_path or not Path(trace_path).exists():
            self.report({'WARNING'}, f"还没有 LLM Trace：{trace_path or '（本次运行未落盘）'}")
            return {'CANCELLED'}

        text = bpy.data.texts.get(TRACE_TEXT_NAME)
        if text is None:
            text = bpy.data.texts.new(TRACE_TEXT_NAME)
        text.clear()
        lines = Path(trace_path).read_text(encoding="utf-8").splitlines()
        for line in lines:
            text.write(line + "\n")
        for area in context.screen.areas if context.screen else []:
            if area.type == 'TEXT_EDITOR':
                area.spaces.active.text = text
                break
        self.report({'INFO'}, f"已载入 {len(lines)} 条调用记录")
        return {'FINISHED'}


class BLOCKDIRECTOR_OT_export_sdl(Operator):
    """把当前 SDL 导出成 project.bdproj（§14.1）。"""

    bl_idname = "blockdirector.export_sdl"
    bl_label = "导出 SDL"
    bl_description = "把当前分镜计划与场景设定写成 project.bdproj"

    def execute(self, context):  # noqa: D102 - bpy 接口
        driver = get_active()
        if driver is None or driver.plan is None:
            self.report({'ERROR'}, "还没有可导出的分镜计划")
            return {'CANCELLED'}
        sdl = build_sdl(driver.plan, build_summary=driver.build_summary,
                        project_name=driver.plan.scene_heading or "BlockDirector")
        problems = validate_sdl(sdl)
        errors = [item for item in problems if item.is_error]
        if errors:
            self.report({'ERROR'},
                        f"SDL 校验未通过（{len(errors)} 项），未导出")
            return {'CANCELLED'}
        path = save_project(_project_dir(context), sdl)
        self.report({'INFO'}, f"SDL 已导出：{path}")
        return {'FINISHED'}


class BLOCKDIRECTOR_OT_export_scene_state(Operator):
    """导出完整场景状态（§7.3 的详细档）。"""

    bl_idname = "blockdirector.export_scene_state"
    bl_label = "导出场景状态"
    bl_description = "把当前场景的完整投影（含屏幕坐标）写成 JSON"

    def execute(self, context):  # noqa: D102 - bpy 接口
        state = collect_scene_state(detailed=True)
        target_dir = _project_dir(context)
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / SCENE_STATE_FILE
        path.write_text(json.dumps(state.to_dict(), ensure_ascii=False, indent=2),
                        encoding="utf-8", newline="\n")
        self.report({'INFO'}, f"场景状态已导出：{path}")
        return {'FINISHED'}


class BLOCKDIRECTOR_PT_debug(Panel):
    """调试信息（§13.3）。"""

    bl_label = "调试"
    bl_idname = "BLOCKDIRECTOR_PT_debug"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "BlockDirector"
    bl_parent_id = "BLOCKDIRECTOR_PT_main"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        layout.prop(context.scene, "bd_project_dir", text="输出目录")
        driver = get_active()
        if driver is None:
            layout.label(text="还没有运行记录", icon='INFO')
            return

        snap = driver.snapshot()
        budget = snap.get("budget") or {}
        rows = (
            ("LLM 调用", budget.get("llm_calls", snap.get("llm_calls"))),
            ("工具调用", snap.get("tool_calls")),
            ("总 Token", budget.get("total_tokens")),
            ("预估费用", f"${budget.get('cost_usd', 0.0):.4f}"),
            ("总耗时", f"{budget.get('elapsed_seconds', 0.0)}s"),
            ("审核 通过/失败", f"{snap.get('audits', 0) - _failed(snap)}"
                               f"/{_failed(snap)}"),
            ("自纠错次数", snap.get("repairs", 0)),
            ("预算余量", _remaining(budget)),
        )
        for label, value in rows:
            layout.label(text=f"{label}：{value}")
        if snap.get("degraded_reason"):
            layout.label(text=f"降级原因：{snap['degraded_reason']}", icon='ERROR')
        knowledge = snap.get("knowledge")
        if knowledge:
            layout.label(text=f"知识库：{knowledge['backend']} / "
                              f"{knowledge['cards']} 条", icon='INFO')

        row = layout.row(align=True)
        row.operator("blockdirector.open_llm_trace", icon='TEXT')
        row.operator("blockdirector.export_scene_state", icon='DUPLICATE')
        layout.operator("blockdirector.export_sdl", icon='FILE_TICK')


def _failed(snapshot) -> int:
    return int(snapshot.get("audits", 0)) - _passed(snapshot)


def _passed(snapshot) -> int:
    """驱动器快照里的通过数 = 审核总数 − 失败数（失败数由驱动器给出）。"""
    return int(snapshot.get("audits", 0)) - int(snapshot.get("failed_audits", 0))


def _remaining(budget) -> str:
    limits = budget.get("limits") or {}
    calls = limits.get("max_llm_calls") or 0
    if not calls:
        return "不限"
    used = int(budget.get("llm_calls", 0))
    return f"{max(calls - used, 0)}/{calls} 次调用"


CLASSES = (
    BLOCKDIRECTOR_OT_open_llm_trace,
    BLOCKDIRECTOR_OT_export_scene_state,
    BLOCKDIRECTOR_OT_export_sdl,
    BLOCKDIRECTOR_PT_debug,
)

_scene_props = {
    "bd_project_dir": StringProperty(
        name="输出目录", subtype='DIR_PATH', default="",
        description="导出 SDL / 场景状态 / 缩略图的落盘目录（§13.3）"),
}


def register() -> None:
    for name, prop in _scene_props.items():
        setattr(bpy.types.Scene, name, prop)
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for name in _scene_props:
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:  # noqa: BLE001
            log.warning("注销 %s 失败", cls.__name__)
