"""小助手面板（v1.7 D2）。

只读 driver 状态行 ＋ 精灵开关。设置**不改配置文件**（真源在磁盘，与
``run_settings`` 同纪律）：勾选只写进程内副本，保存请在 Web 设置页。
"""

from __future__ import annotations

import bpy
from bpy.props import BoolProperty
from bpy.types import Panel

from ..layer5_orchestrator.runtime import get_active
from ..settings import get_config


#: 进程内精灵开关副本（默认跟随配置；勾选只改这里，不落盘）。
_SPRITE_OVERRIDE: dict = {}


def sprite_enabled() -> bool:
    """当前精灵开关：进程内副本优先，缺省读配置（真源在磁盘）。"""
    if "value" in _SPRITE_OVERRIDE:
        return bool(_SPRITE_OVERRIDE["value"])
    return bool(getattr(get_config().ui, "viewport_sprite", True))


class BLOCKDIRECTOR_PT_assistant(Panel):
    bl_label = "小助手"
    bl_idname = "BLOCKDIRECTOR_PT_assistant"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "BlockDirector"

    def draw(self, context):
        layout = self.layout
        driver = get_active()
        layout.prop(context.scene, "bd_assistant_sprite", text="视口精灵")
        layout.label(
            text="保存配置请在 Web 设置页" if "value" in _SPRITE_OVERRIDE
            else "勾选只改本次会话（配置真源在磁盘）")
        row = layout.row()
        row.label(text="驱动状态：")
        row.label(text=str(getattr(driver, "state", "未运行"))
                  if driver is not None else "未运行")


def _sync_sprite_prop(scene) -> None:
    """把进程内副本同步到场景属性（显示值）。"""
    scene.bd_assistant_sprite = sprite_enabled()


def _on_sprite_toggle(scene, _context) -> None:
    """勾选只写进程内副本（不落盘；保存配置请在 Web 设置页）。"""
    _SPRITE_OVERRIDE["value"] = bool(scene.bd_assistant_sprite)


CLASSES = (BLOCKDIRECTOR_PT_assistant,)


def register() -> None:
    bpy.types.Scene.bd_assistant_sprite = BoolProperty(
        name="视口精灵", default=True,
        description="视口内小助手动画（v1.7 D2；勾选只写进程内副本）",
        update=_on_sprite_toggle)
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception as exc:  # noqa: BLE001 - 单个模块注销失败不中断
            from ..utils.logger import get_logger

            get_logger("ui").debug("注销 %s 失败: %s", cls.__name__, exc)
    if hasattr(bpy.types.Scene, "bd_assistant_sprite"):
        delattr(bpy.types.Scene, "bd_assistant_sprite")
