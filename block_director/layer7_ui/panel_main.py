"""主面板：N 面板 → BlockDirector（执行文档 v1.2 §13.1）。

Phase 0 版本展示运行状态与最近事件，并提供运行/取消入口。分镜列表（§13.2）
与交付按钮（§15）随后续阶段加入。
"""

from __future__ import annotations

import bpy
from bpy.props import BoolProperty, StringProperty
from bpy.types import Panel

from ..layer5_orchestrator.runtime import get_active
from ..utils.logger import get_logger

log = get_logger("ui")


class BLOCKDIRECTOR_PT_main(Panel):
    bl_label = "白模导演"
    bl_idname = "BLOCKDIRECTOR_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "BlockDirector"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        box = layout.box()
        box.label(text="输入", icon='FILE_TEXT')
        box.prop(scene, "bd_script_path", text="剧本")
        if not scene.bd_script_path:
            box.label(text="留空则用文本块 BlockDirector Script",
                      icon='INFO')
        box.prop(scene, "bd_offline", text="离线自检（不联网）")

        row = layout.row(align=True)
        row.scale_y = 1.4
        row.operator("blockdirector.run_previs", icon='PLAY')
        row.operator("blockdirector.cancel_previs", icon='CANCEL')

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


CLASSES = (BLOCKDIRECTOR_PT_main,)

_scene_props = {
    "bd_script_path": StringProperty(
        name="剧本路径", subtype='FILE_PATH',
        description="导入的剧本文件（.fountain/.txt/.fdx/.pdf）"),
    "bd_offline": BoolProperty(
        name="离线自检", default=True,
        description="不联网，用内置确定性计划验证链路"),
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
