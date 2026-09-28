"""角色管理面板（执行文档 v1.2 §13.1）。

列表 + 颜色 + 添加 + 删除。真正的改动在 ``layer3_engine/cast_editor.py``；
这里只负责把界面上的输入翻过去，并把失败原因原样报给用户（例如"这个角色还
被镜头引用"）。
"""

from __future__ import annotations

import bpy
from bpy.props import BoolProperty, CollectionProperty, FloatVectorProperty
from bpy.props import IntProperty, StringProperty
from bpy.types import Operator, Panel, PropertyGroup, UIList

from ..layer3_engine.cast_editor import (
    CastError,
    add_cast_member,
    apply_cast_color,
    list_cast,
    remove_cast_member,
)
from ..layer3_engine.scene_context import get_context
from ..utils.logger import get_logger

log = get_logger("ui")


class BDCastMember(PropertyGroup):
    """列表行（与场景上下文同步，不持有真源）。"""

    character_id: StringProperty(name="ID", default="")
    display_name: StringProperty(name="角色", default="")
    color: FloatVectorProperty(name="颜色", subtype='COLOR', size=4,
                               min=0.0, max=1.0, default=(1.0, 1.0, 1.0, 1.0))
    in_scene: BoolProperty(name="已建对象", default=False)


def _hex_to_rgba(text: str):
    from ..utils.geometry import hex_to_rgb

    return (*hex_to_rgb(text), 1.0)


def _rgba_to_hex(values) -> str:
    return "#" + "".join(f"{max(0, min(255, int(round(v * 255)))):02X}"
                         for v in values[:3])


def sync_cast_properties(scene) -> int:
    """把场景上下文的角色同步到面板列表（保留已选行）。"""
    rows = list_cast()
    scene.bd_cast.clear()
    for row in rows:
        item = scene.bd_cast.add()
        item.character_id = row["id"]
        item.display_name = row["label"]
        item.color = _hex_to_rgba(row["color"])
        item.in_scene = row["in_scene"]
    if scene.bd_cast_index >= len(scene.bd_cast):
        scene.bd_cast_index = max(len(scene.bd_cast) - 1, 0)
    return len(scene.bd_cast)


class BLOCKDIRECTOR_UL_cast(UIList):
    """角色列表行：色块 + 名字 + 是否已建对象。"""

    bl_idname = "BLOCKDIRECTOR_UL_cast"

    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            row.prop(item, "color", text="")
            row.label(text=item.display_name or item.character_id)
            row.label(text="" if item.in_scene else "（未建对象）",
                      icon='INFO' if not item.in_scene else 'NONE')
        else:                                   # GRID
            layout.label(text=item.display_name or item.character_id)


class BLOCKDIRECTOR_OT_cast_sync(Operator):
    bl_idname = "blockdirector.cast_sync"
    bl_label = "刷新角色列表"
    bl_description = "从当前场景重新读取角色"

    def execute(self, context):  # noqa: D102 - bpy 接口
        count = sync_cast_properties(context.scene)
        self.report({'INFO'}, f"共 {count} 个角色")
        return {'FINISHED'}


class BLOCKDIRECTOR_OT_cast_add(Operator):
    bl_idname = "blockdirector.cast_add"
    bl_label = "添加角色"
    bl_description = "新建一个白色 Q 版角色并加入场景设定"

    def execute(self, context):  # noqa: D102 - bpy 接口
        try:
            row = add_cast_member(context.scene.bd_new_character_name,
                                  position=(0.0, 0.0, 0.0))
        except CastError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        context.scene.bd_new_character_name = ""
        sync_cast_properties(context.scene)
        self.report({'INFO'}, f"已添加 {row['name']}（{row['character_id']}）")
        return {'FINISHED'}


class BLOCKDIRECTOR_OT_cast_remove(Operator):
    bl_idname = "blockdirector.cast_remove"
    bl_label = "删除角色"
    bl_description = "删除选中角色（被镜头引用时会被拒绝）"

    def execute(self, context):  # noqa: D102 - bpy 接口
        scene = context.scene
        if not (0 <= scene.bd_cast_index < len(scene.bd_cast)):
            self.report({'ERROR'}, "没有选中角色")
            return {'CANCELLED'}
        character_id = scene.bd_cast[scene.bd_cast_index].character_id
        try:
            row = remove_cast_member(character_id)
        except CastError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        sync_cast_properties(scene)
        self.report({'INFO'}, f"已删除 {row['name']}（{row['removed_objects']} 个对象）")
        return {'FINISHED'}


class BLOCKDIRECTOR_OT_cast_apply_color(Operator):
    bl_idname = "blockdirector.cast_apply_color"
    bl_label = "应用颜色"
    bl_description = "把列表里选中的颜色写回材质与场景设定"

    def execute(self, context):  # noqa: D102 - bpy 接口
        scene = context.scene
        if not (0 <= scene.bd_cast_index < len(scene.bd_cast)):
            self.report({'ERROR'}, "没有选中角色")
            return {'CANCELLED'}
        item = scene.bd_cast[scene.bd_cast_index]
        try:
            apply_cast_color(item.character_id, _rgba_to_hex(item.color))
        except CastError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        sync_cast_properties(scene)
        self.report({'INFO'},
                    f"{item.display_name} 颜色 → {_rgba_to_hex(item.color)}")
        return {'FINISHED'}


class BLOCKDIRECTOR_PT_cast(Panel):
    bl_label = "角色"
    bl_idname = "BLOCKDIRECTOR_PT_cast"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "BlockDirector"
    bl_parent_id = "BLOCKDIRECTOR_PT_main"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        if get_context() is None:
            layout.label(text="还没有场景：先生成一次预演", icon='INFO')
            return
        # 列表与场景可能不同步（比如刚生成完、或模型用工具加了角色）：
        # 每次绘制时按数量对齐，省得用户先想起来点刷新。
        if len(scene.bd_cast) != len(list_cast()):
            sync_cast_properties(scene)
        layout.template_list("BLOCKDIRECTOR_UL_cast", "", scene, "bd_cast",
                             scene, "bd_cast_index", rows=3)
        row = layout.row(align=True)
        row.operator("blockdirector.cast_sync", text="", icon='FILE_REFRESH')
        row.operator("blockdirector.cast_add", text="", icon='ADD')
        row.operator("blockdirector.cast_remove", text="", icon='REMOVE')
        row.operator("blockdirector.cast_apply_color", text="", icon='COLOR')
        layout.prop(scene, "bd_new_character_name", text="新角色")
        if 0 <= scene.bd_cast_index < len(scene.bd_cast):
            layout.prop(scene.bd_cast[scene.bd_cast_index], "color", text="颜色")
        layout.operator("blockdirector.cast_sync", icon='FILE_REFRESH')


CLASSES = (BDCastMember, BLOCKDIRECTOR_UL_cast,
           BLOCKDIRECTOR_OT_cast_sync, BLOCKDIRECTOR_OT_cast_add,
           BLOCKDIRECTOR_OT_cast_remove, BLOCKDIRECTOR_OT_cast_apply_color,
           BLOCKDIRECTOR_PT_cast)

_scene_props = {
    "bd_cast": CollectionProperty(type=BDCastMember),
    "bd_cast_index": IntProperty(name="角色索引", default=0),
    "bd_new_character_name": StringProperty(name="新角色名字", default="新角色"),
}


def register() -> None:
    # 顺序要紧：CollectionProperty(type=BDCastMember) 引用的是 PropertyGroup，
    # 必须先把类注册好，否则赋值会抛异常——而 register_all 会把它吞掉，
    # 表现为"面板静默缺失"。
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    for name, prop in _scene_props.items():
        setattr(bpy.types.Scene, name, prop)


def unregister() -> None:
    for name in _scene_props:
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:  # noqa: BLE001
            log.warning("注销 %s 失败", cls.__name__)
