"""分镜列表与"重生成此镜"（执行文档 v1.2 §13.2）。

这是迭代工作流的入口：AI 视频生成不理想时，用户回到这里只调某一镜，
而不是整场重跑。界面本身很薄——真正的保护逻辑在
``layer3_engine/shot_regenerator.py``（只动这一镜 + 保留用户改动）。
"""

from __future__ import annotations

import bpy
from bpy.props import StringProperty
from bpy.types import Operator, Panel

from ..layer3_engine.scene_context import get_context
from ..layer3_engine.scene_sync import get_synchronizer, reset_synchronizer
from ..layer3_engine.shot_regenerator import ShotRegenError, regenerate_shot
from ..utils.logger import get_logger

log = get_logger("ui")


class BLOCKDIRECTOR_OT_regenerate_shot(Operator):
    """按当前计划重建单个镜头，保留用户手动改动（§8.3）。"""

    bl_idname = "blockdirector.regenerate_shot"
    bl_label = "重生成此镜"
    bl_description = "只重建这一镜的相机与动作；手动调整过的角色位置与关键帧不会被覆盖"
    bl_options = {'REGISTER', 'UNDO'}

    shot_id: StringProperty(name="镜号", default="")

    def execute(self, context):  # noqa: D102 - bpy 接口
        shot_id = self.shot_id or context.scene.bd_selected_shot
        if not shot_id:
            self.report({'ERROR'}, "没有选中镜头")
            return {'CANCELLED'}
        try:
            report = regenerate_shot(shot_id, sync=get_synchronizer())
        except ShotRegenError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        context.scene.bd_selected_shot = shot_id
        for warning in report["warnings"]:
            self.report({'WARNING'}, warning)
        self.report({'INFO'},
                    f"{shot_id} 已重生成（{report['start_frame']}-"
                    f"{report['end_frame']}，{report['keyframes']} 关键帧）")
        return {'FINISHED'}


class BLOCKDIRECTOR_PT_shots(Panel):
    """分镜列表（§13.2）：每行一个镜头 + 一键重生成。"""

    bl_label = "分镜列表"
    bl_idname = "BLOCKDIRECTOR_PT_shots"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "BlockDirector"
    bl_parent_id = "BLOCKDIRECTOR_PT_main"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        scene_context = get_context()
        plan = scene_context.plan if scene_context else None
        if plan is None or not plan.shots:
            layout.label(text="还没有分镜计划", icon='INFO')
            return

        synchronizer = get_synchronizer()
        dirty = set(synchronizer.dirty_ids())
        for shot in plan.shots:
            row = layout.row(align=True)
            selected = scene.bd_selected_shot == shot.shot_id
            icon = 'RADIOBUT_ON' if selected else 'RADIOBUT_OFF'
            row.label(text=f"{shot.shot_id}  {shot.shot_type}  "
                           f"{shot.duration_frames / 24:.1f}s", icon=icon)
            button = row.operator("blockdirector.regenerate_shot",
                                  text="", icon='FILE_REFRESH')
            button.shot_id = shot.shot_id
            if selected:
                scene_context.current_shot_id = shot.shot_id

        if dirty:
            layout.label(text=f"检测到手动改动：{', '.join(sorted(dirty))}",
                         icon='INFO')


CLASSES = (BLOCKDIRECTOR_OT_regenerate_shot, BLOCKDIRECTOR_PT_shots)

_scene_props = {
    "bd_selected_shot": StringProperty(
        name="当前镜号", default="",
        description="分镜列表里选中的镜头（§13.2）"),
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
        except Exception:  # noqa: BLE001 - 注销失败不该阻断卸载
            log.warning("注销 %s 失败", cls.__name__)
    # 卸载时摘掉 depsgraph 回调，避免插件停用后还挂在全局处理器上
    reset_synchronizer()
