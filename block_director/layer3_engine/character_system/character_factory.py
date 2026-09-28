"""角色几何体创建（执行文档 v1.2 §9.1 / §9.2）。

严格按 §9.1 的 Pivot 世界坐标表搭建骨架，而不是"堆部件"：

    脚底 0.00 | 髋 pivot 0.40 | 身体 0.40–1.10 | 头心 1.10 | 头顶 1.45 | 标签锚 1.75

总高 1.45 单位（1 单位 = 1 米）。这是 §9.1 修正版数值，不是 v1.0 那句
"总高约 1.5、但按部件尺寸堆起来却有 1.8"的矛盾写法。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import bpy
from bpy.types import Object
from mathutils import Vector

from ...utils.geometry import facing_to_rotation_z, hex_to_rgb
from ...utils.logger import get_logger
from ...utils.threading_guard import main_thread_only
from ..collection_router import route_to_content
from ..transaction import Transaction

log = get_logger("character")

# ---------------------------------------------------------------- 几何常量
HEAD_RADIUS = 0.35
BODY_RADIUS = 0.25
BODY_HEIGHT = 0.70
LEG_RADIUS = 0.08
LEG_HEIGHT = 0.40
EYE_RADIUS = 0.06
EYE_SEPARATION = 0.12
EYE_FORWARD = 0.30
LEG_SEPARATION = 0.12

PIVOT_Z = {
    "leg": 0.40,      # 髋部
    "body": 0.40,     # 腰部（BodyPivot 原点）
    "head": 1.10,     # 头球中心
    "label": 1.75,    # 标签锚点
}
BODY_CENTER_LOCAL = 0.35                                  # 身体中心相对 BodyPivot
HEAD_LOCAL = PIVOT_Z["head"] - PIVOT_Z["body"]            # 0.70
LABEL_ANCHOR_LOCAL = PIVOT_Z["label"] - PIVOT_Z["head"]   # 0.65
EXPECTED_TOTAL_HEIGHT = PIVOT_Z["head"] + HEAD_RADIUS     # 1.45


@dataclass
class Character:
    """一个角色的对象句柄。"""

    id: str
    name: str
    color: str = "#FFFFFF"
    root: Optional[Object] = None
    body_pivot: Optional[Object] = None
    head_pivot: Optional[Object] = None
    label_anchor: Optional[Object] = None
    leg_pivots: List[Object] = field(default_factory=list)
    meshes: List[Object] = field(default_factory=list)
    parts: Dict[str, Object] = field(default_factory=dict)

    def all_objects(self) -> List[Object]:
        return [o for o in [self.root, self.body_pivot, self.head_pivot,
                            self.label_anchor, *self.leg_pivots, *self.meshes] if o]


def _empty(name: str, parent: Optional[Object] = None,
           local: Tuple[float, float, float] = (0.0, 0.0, 0.0)) -> Object:
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_type = 'PLAIN_AXES'
    obj.empty_display_size = 0.15
    bpy.context.scene.collection.objects.link(obj)
    if parent is not None:
        obj.parent = parent
    obj.location = local
    return obj


def _adopt_last_object(name: str, parent: Object,
                       local: Tuple[float, float, float],
                       material) -> Object:
    """接管刚由 primitive_*_add 创建的对象：命名、挂父级、设局部位置。"""
    obj = bpy.context.object
    obj.name = name
    obj.parent = parent
    obj.location = local
    if material is not None:
        obj.data.materials.append(material)
    obj["bd_element_type"] = "character_part"
    return obj


def _character_material(color: str, character_id: str):
    material = bpy.data.materials.get(f"BD_Mat_{character_id}")
    if material is None:
        material = bpy.data.materials.new(f"BD_Mat_{character_id}")
    rgba = (*hex_to_rgb(color), 1.0)
    material.diffuse_color = rgba          # Workbench 用
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:                   # EEVEE 用
        bsdf.inputs["Base Color"].default_value = rgba
        if "Roughness" in bsdf.inputs:
            bsdf.inputs["Roughness"].default_value = 0.9
    return material


@main_thread_only("create_character")
def create_character(character_id: str, name: str, color: str = "#FFFFFF",
                     location: Sequence[float] = (0.0, 0.0, 0.0),
                     facing: Sequence[float] = (0.0, 1.0, 0.0)) -> Character:
    """按 §9.2 的层级创建 Q 版白模角色。"""
    character = Character(id=character_id, name=name, color=color)
    material = _character_material(color, character_id)
    with Transaction(f"character:{character_id}"):
        root = _empty(f"BD_Char_{name}_Root")
        root.location = tuple(location)
        root.rotation_euler = (0.0, 0.0, facing_to_rotation_z(facing))
        root["bd_sdl_id"] = character_id
        root["bd_element_type"] = "character_root"
        character.root = route_to_content(root)

        body_pivot = _empty(f"BD_Char_{name}_BodyPivot", root,
                            (0.0, 0.0, PIVOT_Z["body"]))
        character.body_pivot = route_to_content(body_pivot)

        bpy.ops.mesh.primitive_cylinder_add(radius=BODY_RADIUS, depth=BODY_HEIGHT)
        body = _adopt_last_object(f"BD_Char_{name}_Body", character.body_pivot,
                                  (0.0, 0.0, BODY_CENTER_LOCAL), material)
        character.parts["body"] = route_to_content(body)

        head_pivot = _empty(f"BD_Char_{name}_HeadPivot", character.body_pivot,
                            (0.0, 0.0, HEAD_LOCAL))
        character.head_pivot = route_to_content(head_pivot)

        bpy.ops.mesh.primitive_uv_sphere_add(radius=HEAD_RADIUS, segments=24,
                                             ring_count=12)
        head = _adopt_last_object(f"BD_Char_{name}_Head", character.head_pivot,
                                  (0.0, 0.0, 0.0), material)
        character.parts["head"] = route_to_content(head)

        for side, sign in (("L", -1.0), ("R", 1.0)):
            bpy.ops.mesh.primitive_uv_sphere_add(radius=EYE_RADIUS, segments=12,
                                                 ring_count=8)
            eye = _adopt_last_object(f"BD_Char_{name}_Eye_{side}",
                                     character.head_pivot,
                                     (sign * EYE_SEPARATION, EYE_FORWARD, 0.0),
                                     material)
            character.parts[f"eye_{side.lower()}"] = route_to_content(eye)

        anchor = _empty(f"BD_Char_{name}_LabelAnchor", character.head_pivot,
                        (0.0, 0.0, LABEL_ANCHOR_LOCAL))
        character.label_anchor = route_to_content(anchor)

        for side, sign in (("L", -1.0), ("R", 1.0)):
            pivot = _empty(f"BD_Char_{name}_Leg{side}_Pivot", root,
                           (sign * LEG_SEPARATION, 0.0, PIVOT_Z["leg"]))
            pivot["bd_element_type"] = "leg_pivot"
            character.leg_pivots.append(route_to_content(pivot))

            bpy.ops.mesh.primitive_cylinder_add(radius=LEG_RADIUS, depth=LEG_HEIGHT)
            leg = _adopt_last_object(f"BD_Char_{name}_Leg{side}", pivot,
                                     (0.0, 0.0, -LEG_HEIGHT / 2.0), material)
            character.parts[f"leg_{side.lower()}"] = route_to_content(leg)

        character.meshes = list(character.parts.values())
    log.info("角色已创建：%s（%s）", name, character_id)
    return character


def _is_descendant(obj: Object, root: Object) -> bool:
    node: Optional[Object] = obj
    while node is not None:
        if node is root:
            return True
        node = node.parent
    return False


@main_thread_only("get_facing")
def get_facing(character) -> Tuple[float, float, float]:
    """按 §9.3 由眼睛位置算面朝方向：``眼睛中点 − 头心``。

    读取 ``matrix_world`` 前必须让 depsgraph 求值（§7.3 规则 1）。
    """
    bpy.context.view_layer.update()
    head_pivot = getattr(character, "head_pivot", None)
    if head_pivot is None:
        return (0.0, 1.0, 0.0)
    parts = getattr(character, "parts", {})
    head = parts.get("head")
    eye_l = parts.get("eye_l")
    eye_r = parts.get("eye_r")
    if head is None or eye_l is None or eye_r is None:
        return (0.0, 1.0, 0.0)
    center = (eye_l.matrix_world.translation + eye_r.matrix_world.translation) / 2.0
    direction = center - head.matrix_world.translation
    if direction.length < 1e-9:
        return (0.0, 1.0, 0.0)
    direction.normalize()
    return (round(direction.x, 4), round(direction.y, 4), round(direction.z, 4))


@main_thread_only("measure_height")
def measure_height(root: Object) -> float:
    """用世界包围盒量出角色实际总高（验收 §9.1 的几何规格）。"""
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    zs: List[float] = []
    for obj in bpy.data.objects:
        if obj.type != 'MESH' or not _is_descendant(obj, root):
            continue
        evaluated = obj.evaluated_get(depsgraph)
        matrix = evaluated.matrix_world
        for corner in evaluated.bound_box:
            zs.append((matrix @ Vector(corner)).z)
    return round(max(zs) - min(zs), 4) if zs else 0.0
