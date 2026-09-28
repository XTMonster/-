"""场景执行器：地面、墙体、道具、灯光（执行文档 v1.2 §8.2）。

光照预设默认 ``clay_studio``（§8.2：白模参考视频要求形体质感清晰、
颜色中性，最利于视频模型理解体积与遮挡）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import bpy
from bpy.types import Object

from ..utils.logger import get_logger
from ..utils.threading_guard import main_thread_only
from .collection_router import route_to_content
from .transaction import Transaction

log = get_logger("scene")

DEFAULT_LIGHTING = "clay_studio"

LIGHTING_PRESETS: Dict[str, List[Dict[str, Any]]] = {
    # 白模默认：一盏主光 + 一盏补光，中性白，形体质感清晰
    "clay_studio": [
        {"type": "SUN", "energy": 3.0, "rotation": (0.9, 0.0, 0.6), "color": (1, 1, 1)},
        {"type": "SUN", "energy": 1.2, "rotation": (1.0, 0.0, 3.6), "color": (0.9, 0.93, 1.0)},
    ],
    "indoor_soft": [
        {"type": "AREA", "energy": 120.0, "location": (0, -3, 3), "size": 4.0},
        {"type": "SUN", "energy": 0.8, "rotation": (0.8, 0.0, 0.3)},
    ],
    "outdoor_sun": [
        {"type": "SUN", "energy": 5.0, "rotation": (0.7, 0.0, 0.9)},
    ],
    "night": [
        {"type": "POINT", "energy": 60.0, "location": (0, -2, 2.5)},
    ],
    "studio3p": [
        {"type": "AREA", "energy": 200.0, "location": (-3, -3, 3), "size": 3.0},
        {"type": "AREA", "energy": 60.0, "location": (3, -2, 2), "size": 3.0},
        {"type": "AREA", "energy": 150.0, "location": (0, 4, 3), "size": 3.0},
    ],
}


@dataclass
class Environment:
    """一次场景搭建产出的对象集合。"""

    ground: Optional[Object] = None
    walls: List[Object] = field(default_factory=list)
    props: List[Object] = field(default_factory=list)
    lights: List[Object] = field(default_factory=list)
    lighting: str = DEFAULT_LIGHTING

    def all_objects(self) -> List[Object]:
        return [o for o in [self.ground, *self.walls, *self.props, *self.lights] if o]


def _ensure_material(name: str, color: Sequence[float], is_clay: bool = True):
    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    rgba = (color[0], color[1], color[2], 1.0)
    material.diffuse_color = rgba          # Workbench 用
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:                   # EEVEE 用
        bsdf.inputs["Base Color"].default_value = rgba
        if "Roughness" in bsdf.inputs:
            bsdf.inputs["Roughness"].default_value = 0.9 if is_clay else 0.5
    return material


@main_thread_only("create_ground")
def create_ground(size: Tuple[float, float] = (20.0, 20.0),
                  color: Sequence[float] = (0.78, 0.78, 0.76)) -> Object:
    bpy.ops.mesh.primitive_plane_add(size=1.0, location=(0, 0, 0))
    ground = bpy.context.object
    ground.name = "BD_Ground"
    # primitive_plane_add(size=1.0) 造的就是 1×1 单位面片，缩放到 size 即得目标
    # 边长。除以 2 会让地面只有请求尺寸的一半（Phase 6 渲染时暴露）。
    ground.scale = (float(size[0]), float(size[1]), 1.0)
    ground.data.materials.append(_ensure_material("BD_Mat_Ground", color))
    return route_to_content(ground)


@main_thread_only("create_wall")
def create_wall(index: int, position: Sequence[float],
                rotation: Sequence[float] = (0, 0, 0),
                size: Sequence[float] = (10.0, 0.2, 3.0),
                color: Sequence[float] = (0.86, 0.86, 0.84)) -> Object:
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=tuple(position))
    wall = bpy.context.object
    wall.name = f"BD_Wall_{index:02d}"
    wall.scale = (float(size[0]), float(size[1]), float(size[2]))
    wall.rotation_euler = tuple(rotation)
    wall.data.materials.append(_ensure_material("BD_Mat_Wall", color))
    return route_to_content(wall)


@main_thread_only("create_prop")
def create_prop(prop_id: str, position: Sequence[float],
                size: Sequence[float] = (1.0, 1.0, 0.8),
                color: Sequence[float] = (0.7, 0.66, 0.6)) -> Object:
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=tuple(position))
    prop = bpy.context.object
    prop.name = f"BD_Prop_{prop_id}"
    prop.scale = (float(size[0]), float(size[1]), float(size[2]))
    prop["bd_element_type"] = "prop"
    prop["bd_sdl_id"] = prop_id
    prop.data.materials.append(_ensure_material(f"BD_Mat_Prop_{prop_id}", color))
    return route_to_content(prop)


@main_thread_only("create_lights")
def create_lights(preset: str = DEFAULT_LIGHTING) -> List[Object]:
    """按预设创建灯光；未知预设回退到 clay_studio 并告警。"""
    specs = LIGHTING_PRESETS.get(preset)
    if specs is None:
        log.warning("未知光照预设 %s，回退 %s", preset, DEFAULT_LIGHTING)
        preset, specs = DEFAULT_LIGHTING, LIGHTING_PRESETS[DEFAULT_LIGHTING]

    lights: List[Object] = []
    for index, spec in enumerate(specs, start=1):
        light_data = bpy.data.lights.new(f"BD_Light_{index:02d}", type=spec["type"])
        light_data.energy = float(spec.get("energy", 1.0))
        if "size" in spec and hasattr(light_data, "size"):
            light_data.size = float(spec["size"])
        if "color" in spec:
            light_data.color = tuple(spec["color"])
        light = bpy.data.objects.new(f"BD_Light_{index:02d}", light_data)
        bpy.context.scene.collection.objects.link(light)
        light.location = tuple(spec.get("location", (0.0, 0.0, 5.0)))
        if "rotation" in spec:
            light.rotation_euler = tuple(spec["rotation"])
        lights.append(route_to_content(light))
    return lights


@main_thread_only("build_environment")
def build_environment(*, ground_size: Tuple[float, float] = (20.0, 20.0),
                      walls: Optional[List[Dict[str, Any]]] = None,
                      props: Optional[List[Dict[str, Any]]] = None,
                      lighting: str = DEFAULT_LIGHTING) -> Environment:
    """搭建场景环境。整批写入包在一个事务里，失败自动回滚。"""
    environment = Environment(lighting=lighting)
    with Transaction(f"environment:{lighting}"):
        environment.ground = create_ground(ground_size)
        for index, wall in enumerate(walls or [], start=1):
            environment.walls.append(create_wall(
                index,
                wall.get("position", (0.0, -5.0, 1.5)),
                wall.get("rotation", (0.0, 0.0, 0.0)),
                wall.get("size", (10.0, 0.2, 3.0)),
            ))
        for prop in props or []:
            environment.props.append(create_prop(
                str(prop.get("id", f"prop_{len(environment.props) + 1:02d}")),
                prop.get("position", (0.0, 0.0, 0.4)),
                prop.get("size", (1.0, 1.0, 0.8)),
            ))
        environment.lights = create_lights(lighting)
    log.info("环境搭建完成：预设=%s，物体 %d 个", lighting,
             len(environment.all_objects()))
    return environment
