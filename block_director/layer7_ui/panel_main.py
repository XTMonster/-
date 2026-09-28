"""主面板：N 面板 → BlockDirector（执行文档 v1.2 §13.1）。

六块内容对应 §13.1 的六条：输入、生成控制、运行、工具、交付、状态与日志。
面板上的设置**不直接改配置文件**：运行与导出前用
``run_settings.apply_scene_settings()`` 覆盖到一个进程内的配置副本上，配置
文件仍是唯一的持久真源。
"""

from __future__ import annotations

import copy
from pathlib import Path

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty
from bpy.props import StringProperty
from bpy.types import Operator, Panel

from ..layer3_engine.scene_context import get_context
from ..layer5_orchestrator.runtime import get_active
from ..settings import get_config
from ..utils.logger import get_logger
from .run_settings import (
    APPEARANCES,
    AUDIT_LEVELS,
    BACKENDS,
    PRESETS,
    PROVIDERS,
    apply_scene_settings,
    collect_settings,
)

log = get_logger("ui")


def _enum_items(values):
    return [(value, value, "") for value in values]


class BLOCKDIRECTOR_OT_export_delivery(Operator):
    """按当前计划导出交付包（§15）。"""

    bl_idname = "blockdirector.export_delivery"
    bl_label = "导出交付包"
    bl_description = "渲染分镜视频、首帧与清单（导出前会做画面审计）"

    def execute(self, context):  # noqa: D102 - bpy 接口
        from ..layer8_delivery import export_project

        driver = get_active()
        plan = driver.plan if driver is not None else None
        build_summary = driver.build_summary if driver is not None else None
        if plan is None:
            scene_context = get_context()
            plan = scene_context.plan if scene_context else None
        if plan is None:
            self.report({'ERROR'}, "还没有分镜计划：先运行一次生成")
            return {'CANCELLED'}

        config = copy.deepcopy(get_config())
        _config, problems = apply_scene_settings(config, collect_settings(context.scene))
        if problems:
            self.report({'ERROR'}, "；".join(problems))
            return {'CANCELLED'}

        out_dir = context.scene.bd_project_dir or bpy.app.tempdir
        report = export_project(plan, build_summary=build_summary,
                                out_dir=Path(bpy.path.abspath(out_dir)),
                                config=config.delivery,
                                project=plan.scene_heading or "BlockDirector")
        if not report.ok:
            self.report({'ERROR'}, report.reason or "导出未完成")
            return {'CANCELLED'}
        for warning in report.warnings:
            self.report({'WARNING'}, warning)
        self.report({'INFO'}, f"交付包已生成：{len(report.files)} 个文件 → "
                              f"{report.out_dir}")
        return {'FINISHED'}


class BLOCKDIRECTOR_PT_main(Panel):
    bl_label = "白模导演"
    bl_idname = "BLOCKDIRECTOR_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "BlockDirector"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        _sync_overlay(scene)

        box = layout.box()
        box.label(text="输入", icon='FILE_TEXT')
        box.prop(scene, "bd_script_path", text="剧本")
        if not scene.bd_script_path:
            box.label(text="留空则用文本块 BlockDirector Script", icon='INFO')
        box.prop(scene, "bd_offline", text="离线自检（不联网）")

        control = layout.box()
        control.label(text="生成控制", icon='SETTINGS')
        control.prop(scene, "bd_provider", text="供应商")
        control.prop(scene, "bd_model", text="模型")
        row = control.row(align=True)
        row.prop(scene, "bd_audit_level", text="审核")
        row.prop(scene, "bd_max_llm_calls", text="调用上限")
        row = control.row(align=True)
        row.prop(scene, "bd_max_cost_usd", text="费用$")
        row.prop(scene, "bd_max_wall_minutes", text="分钟")

        row = layout.row(align=True)
        row.scale_y = 1.4
        row.operator("blockdirector.run_previs", icon='PLAY')
        row.operator("blockdirector.pause_previs", icon='PAUSE')
        row.operator("blockdirector.cancel_previs", icon='CANCEL')

        tools = layout.box()
        tools.label(text="工具", icon='TOOL_SETTINGS')
        tools.operator("blockdirector.draw_path", icon='CURVE_DATA')
        tools.prop(scene, "bd_show_overlay", text="视口叠加")
        if scene.bd_show_overlay:
            column = tools.column(align=True)
            column.prop(scene, "bd_show_axis", text="轴线")
            column.prop(scene, "bd_show_composition", text="构图辅助线")
            column.prop(scene, "bd_show_safe_area", text="安全框")

        delivery = layout.box()
        delivery.label(text="交付", icon='FILE_TICK')
        delivery.prop(scene, "bd_project_dir", text="输出目录")
        row = delivery.row(align=True)
        row.prop(scene, "bd_preset", text="")
        row.prop(scene, "bd_appearance", text="")
        delivery.prop(scene, "bd_render_backend", text="后端")
        delivery.operator("blockdirector.export_delivery", icon='RENDER_ANIMATION')

        driver = get_active()
        status = layout.box()
        status.label(text="状态", icon='INFO')
        if driver is None:
            status.label(text="空闲")
            return

        snap = driver.snapshot()
        for key, label in (("state", "阶段"), ("shots", "镜头"),
                           ("llm_calls", "LLM 调用"), ("tool_calls", "工具调用"),
                           ("steps", "步数")):
            status.label(text=f"{label}：{snap.get(key)}")
        if snap.get("error"):
            status.label(text=f"错误：{snap['error']}", icon='ERROR')

        events = driver.audit.recent(6)
        if events:
            log_box = layout.box()
            log_box.label(text="最近事件", icon='TEXT')
            for event in reversed(events):
                icon = 'ERROR' if event.level == "error" else 'DOT'
                log_box.label(text=f"{event.kind}: {event.message}"[:60], icon=icon)


CLASSES = (BLOCKDIRECTOR_OT_export_delivery, BLOCKDIRECTOR_PT_main)


def _sync_overlay(scene) -> None:
    """让 draw_handler 与场景开关保持一致（§13.4）。

    用"每次绘制时同步"而不是属性 ``update`` 回调：属性可能来自 .blend 文件的
    旧值，回调不一定被触发，而这里每次都能对齐。
    """
    from . import draw_overlay

    wanted = bool(getattr(scene, "bd_show_overlay", True))
    if wanted and not draw_overlay.is_enabled():
        draw_overlay.register()
    elif not wanted and draw_overlay.is_enabled():
        draw_overlay.unregister()


_scene_props = {
    "bd_script_path": StringProperty(
        name="剧本路径", subtype='FILE_PATH',
        description="导入的剧本文件（.fountain/.txt/.fdx/.pdf）"),
    "bd_offline": BoolProperty(
        name="离线自检", default=True,
        description="不联网，用内置确定性计划验证链路"),
    "bd_provider": EnumProperty(
        name="供应商", items=_enum_items(PROVIDERS), default=PROVIDERS[0],
        description="LLM 供应商（§21.5 的 llm.provider）"),
    "bd_model": StringProperty(name="模型", default="gpt-4o",
                               description="覆盖 llm.model"),
    "bd_audit_level": EnumProperty(
        name="审核级别", items=_enum_items(AUDIT_LEVELS),
        default="standard"),
    "bd_max_llm_calls": IntProperty(
        name="调用上限", default=8, min=0, max=1000,
        description="本次场景的 LLM 调用额度（§12.6）"),
    "bd_max_cost_usd": FloatProperty(
        name="费用上限", default=5.0, min=0.0, max=1000.0),
    "bd_max_wall_minutes": FloatProperty(
        name="时间上限", default=30.0, min=0.0, max=1440.0),
    "bd_preset": EnumProperty(name="分辨率", items=_enum_items(PRESETS),
                              default=PRESETS[0]),
    "bd_appearance": EnumProperty(name="外观", items=_enum_items(APPEARANCES),
                                  default=APPEARANCES[0]),
    "bd_render_backend": EnumProperty(name="渲染后端",
                                      items=_enum_items(BACKENDS),
                                      default=BACKENDS[0]),
    "bd_project_dir": StringProperty(
        name="输出目录", subtype='DIR_PATH', default="",
        description="导出 SDL / 场景状态 / 交付包的落盘目录"),
    "bd_show_overlay": BoolProperty(
        name="视口叠加", default=True,
        description="显示轴线 / 三分法网格 / 安全框（§13.4）"),
    "bd_show_axis": BoolProperty(name="轴线", default=True),
    "bd_show_composition": BoolProperty(name="构图辅助线", default=True),
    "bd_show_safe_area": BoolProperty(name="安全框", default=True),
}


def register() -> None:
    for name, prop in _scene_props.items():
        setattr(bpy.types.Scene, name, prop)
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception as exc:  # noqa: BLE001
            log.debug("注销 %s 失败: %s", cls.__name__, exc)
    for name in _scene_props:
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)
