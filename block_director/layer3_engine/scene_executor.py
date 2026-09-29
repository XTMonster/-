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
from ..utils.geometry import hex_to_rgb
from .collection_router import route_to_content
from .transaction import Transaction

log = get_logger("scene")

DEFAULT_LIGHTING = "clay_studio"

#: 没给颜色时道具用的中性灰（与 v1.2 的 create_prop 默认值一致）
DEFAULT_PROP_COLOR = (0.7, 0.66, 0.6)


def resolve_prop_color(value, default=DEFAULT_PROP_COLOR
                       ) -> Tuple[float, float, float]:
    """道具颜色：接受 ``#RRGGBB`` 字符串或 0..1 三元组。

    v1.2 的 ``build_environment`` 压根没把 ``prop["color"]`` 传下来，
    而且 SDL / 项目文件里写的是十六进制字符串、``create_prop`` 只认浮点三元组
    ——即便传了也会抛 TypeError。实测结果是所有摊位一律是默认灰色，
    与 SDL 里声明的颜色无关。
    """
    if isinstance(value, str):
        return hex_to_rgb(value)
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        try:
            return (float(value[0]), float(value[1]), float(value[2]))
        except (TypeError, ValueError):
            return default
    return default

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
                color: Sequence[float] = DEFAULT_PROP_COLOR,
                rotation: Sequence[float] = (0.0, 0.0, 0.0),
                shape: str = "box") -> Object:
    """建一个道具。``shape`` 见 :data:`PROP_SHAPES`。

    v1.2 无论 SDL 里写什么形状都只造盒子——摊位、柱子、桶、伞全是一个方块，
    白模里读不出"这是什么"。v1.3 补上形状库（§3.6）。
    """
    _add_primitive(shape)
    prop = bpy.context.object
    prop.name = f"BD_Prop_{prop_id}"
    prop.scale = (float(size[0]), float(size[1]), float(size[2]))
    prop.rotation_euler = (float(rotation[0]), float(rotation[1]),
                           float(rotation[2]))
    prop["bd_element_type"] = "prop"
    prop["bd_sdl_id"] = prop_id
    prop["bd_shape"] = str(shape)
    prop.data.materials.append(
        _ensure_material(f"BD_Mat_Prop_{prop_id}",
                         resolve_prop_color(color)))
    return route_to_content(prop)


#: 道具形状库（§3.6）。``plane_stack`` 用一块薄板代理"一摞平面"。
PROP_SHAPES = ("box", "cylinder", "sphere", "cone", "plane", "plane_stack",
               "torus")


def _add_primitive(shape: str) -> None:
    """按形状调用对应的 primitive 算子；未知形状退回盒子并告警。"""
    kind = str(shape or "box").lower()
    if kind == "cylinder":
        bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=0.5, depth=1.0)
    elif kind == "sphere":
        bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8,
                                             radius=0.5)
    elif kind == "cone":
        bpy.ops.mesh.primitive_cone_add(vertices=16, radius1=0.5, depth=1.0)
    elif kind == "plane":
        bpy.ops.mesh.primitive_plane_add(size=1.0)
    elif kind == "plane_stack":
        bpy.ops.mesh.primitive_cube_add(size=1.0)
        bpy.context.object.scale = (1.0, 1.0, 0.08)
    elif kind == "torus":
        bpy.ops.mesh.primitive_torus_add(major_radius=0.5, minor_radius=0.15)
    elif kind != "box":
        log.warning("未知道具形状 %s，按 box 处理", shape)
        bpy.ops.mesh.primitive_cube_add(size=1.0)
    else:
        bpy.ops.mesh.primitive_cube_add(size=1.0)


#: 特效代理的配色与形状（Workbench 只有不透明实色，见 §3.6 的如实标注）
VFX_STYLES: Dict[str, Dict[str, Any]] = {
    # 代理的颜色必须**看得见**：白模背景是中灰，深色代理会和环境糊在一起。
    # RK-2 的量化判据是"代理区域与背景的平均亮度差 > 0.05"（见 §6.4）。
    "flame": {"shape": "cone", "color": (1.0, 0.32, 0.06),
              "scale": (0.45, 0.45, 1.0)},
    "glow": {"shape": "sphere", "color": (1.0, 0.9, 0.35),
             "scale": (0.3, 0.3, 0.3)},
    "spark": {"shape": "sphere", "color": (1.0, 1.0, 0.75),
              "scale": (0.08, 0.08, 0.08)},
    "smoke": {"shape": "sphere", "color": (0.55, 0.55, 0.60),
              "scale": (0.6, 0.6, 0.45)},
}


@main_thread_only("create_vfx")
def create_vfx(vfx_id: str, kind: str, position: Sequence[float],
               size: Sequence[float] = (0.0, 0.0, 0.0)) -> Object:
    """建一个**可渲染**的特效代理（火焰 / 发光 / 火花 / 烟雾）。

    如实标注：默认的 Workbench 后端只用 ``material.diffuse_color`` 的 RGB，
    **没有 alpha 通道**，因此这里的代理是不透明实色；需要自发光或半透明
    必须切 EEVEE（§3.6）。
    """
    style = VFX_STYLES.get(str(kind or "").lower(), VFX_STYLES["glow"])
    _add_primitive(str(style["shape"]))
    obj = bpy.context.object
    obj.name = f"BD_VFX_{vfx_id}"
    scale = [float(value) for value in style["scale"]]
    for index in range(3):
        if float(size[index]) > 0:
            scale[index] = float(size[index])
    obj.scale = tuple(scale)
    obj.location = tuple(position)
    obj["bd_element_type"] = "vfx"
    obj["bd_vfx_kind"] = str(kind)
    obj.data.materials.append(_ensure_material(
        f"BD_Mat_VFX_{vfx_id}", tuple(style["color"])))
    return route_to_content(obj)


def _crowd_vertex_mesh(name: str, height: float):
    """群众的共享网格：一个极简人形（躯干 + 头）。

    所有实例共用同一份 mesh——40 个独立低模会让文件与重建时间都失控，
    而白模里的路人只需要"有个东西在那边"。
    """
    import bmesh  # noqa: PLC0415 - bpy 侧模块，只在需要时载入
    from mathutils import Matrix

    mesh = bpy.data.meshes.new(name)
    builder = bmesh.new()
    body_h = height * 0.72
    head_r = height * 0.11
    bmesh.ops.create_cube(builder, size=1.0)
    for vert in builder.verts:
        vert.co.x *= height * 0.18
        vert.co.y *= height * 0.12
        vert.co.z = vert.co.z * body_h + body_h / 2.0
    bmesh.ops.create_uvsphere(builder, u_segments=10, v_segments=6,
                              radius=head_r,
                              matrix=Matrix.Translation(
                                  (0.0, 0.0, body_h + head_r)))
    builder.to_mesh(mesh)
    builder.free()
    mesh.materials.append(_ensure_material("BD_Mat_Crowd",
                                           (0.55, 0.55, 0.58)))
    return mesh


def _crowd_hash(seed: int, index: int, channel: int) -> float:
    """确定性伪随机（与运镜的手持噪声同一套整数哈希）。"""
    value = (int(seed) * 73856093) ^ (int(index) * 19349663) ^ (channel * 83492791)
    value &= 0x7FFFFFFF
    return (value % 20011) / 20011.0


@main_thread_only("build_crowd")
def build_crowd(entries: Optional[List[Dict[str, Any]]] = None, *,
                height: float = 1.65, spacing: float = 1.6,
                walk_frames: Optional[Tuple[int, int]] = None) -> List[Object]:
    """按声明实例化群众代理（§3.6）。

    * **共享 mesh**：所有实例引用同一份低模；
    * **确定性排布**：位置只由 ``seed`` 与序号决定，同一份工程重建两次一致；
    * ``walk`` 是"漂移 + 微起伏"的近似，不是骨骼走姿（如实标注）；
    * 群众**不建标签**，也不进 ``context.characters``。
    """
    objects: List[Object] = []
    mesh = _crowd_vertex_mesh("BD_Crowd_Mesh", float(height))
    for entry in entries or []:
        count = max(int((entry or {}).get("count") or 0), 0)
        seed = int((entry or {}).get("seed") or 0)
        mode = str((entry or {}).get("mode") or "static")
        spread = float((entry or {}).get("spread") or 6.0)
        for local in range(count):
            index = len(objects) + 1
            obj = bpy.data.objects.new(f"BD_Crowd_{index:03d}", mesh)
            bpy.context.scene.collection.objects.link(obj)
            jitter_x = (_crowd_hash(seed, local, 1) - 0.5) * spread
            jitter_y = (_crowd_hash(seed, local, 2) - 0.5) * spread
            obj.location = (round(jitter_x, 3), round(jitter_y, 3), 0.0)
            obj.rotation_euler = (0.0, 0.0,
                                  _crowd_hash(seed, local, 3) * 6.28318)
            obj["bd_element_type"] = "crowd"
            obj["bd_crowd_index"] = index
            objects.append(route_to_content(obj))
            if mode == "walk" and walk_frames:
                _bake_crowd_walk(obj, start=int(walk_frames[0]),
                                 end=int(walk_frames[1]),
                                 drift=spacing * (0.5 + _crowd_hash(seed, local, 4)))
    log.info("群众代理 %d 个（共享 1 份网格）", len(objects))
    return objects


def _bake_crowd_walk(obj: Object, *, start: int, end: int,
                     drift: float) -> None:
    """给一个群众实例烘一段"走"：水平漂移 + 两个周期的上下微起伏。

    这是**近似**：白模群众的职责是提供"有人、在动"的信息量，
    不是可用的走姿资产（§6.2 明确不做物理级模拟）。
    """
    span = max(int(end) - int(start), 1)
    origin = tuple(obj.location)
    for step, frame in enumerate((start, start + span // 2, end)):
        progress = step / 2.0
        bob = 0.03 * (1.0 if step != 1 else 0.0)
        obj.location = (origin[0] + drift * progress, origin[1],
                        origin[2] + bob)
        obj.keyframe_insert(data_path="location", frame=frame)
    if obj.animation_data and obj.animation_data.action:
        from ..utils.blender_compat import action_fcurves

        for curve in action_fcurves(obj.animation_data.action):
            for point in curve.keyframe_points:
                point.interpolation = 'BEZIER'


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
                prop.get("color", DEFAULT_PROP_COLOR),
                prop.get("rotation", (0.0, 0.0, 0.0)),
                prop.get("shape", "box"),
            ))
        environment.lights = create_lights(lighting)
    log.info("环境搭建完成：预设=%s，物体 %d 个", lighting,
             len(environment.all_objects()))
    return environment
