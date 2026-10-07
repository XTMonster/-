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
from ..cinema.anchor import DEFAULT_PROFILE, hand_offset
from ..cinema.lighting import resolve_lighting
from ..cinema.props import (
    PROP_INTERACTION_ACTIONS,
    influence_keys,
    merge_windows,
    prop_interaction_windows,
)
from ..cinema.staging import solve_anchor_positions
from ..utils.geometry import hex_to_rgb
from .collection_router import mark_as_guide, route_to_content
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
    #: v1.5 §4.3：场级摆位锚点（``BD_Anchor_*`` empty，只进 Guides、不渲染）。
    anchors: List[Object] = field(default_factory=list)
    lighting: str = DEFAULT_LIGHTING
    #: v1.5 §4.3：解析不出坐标的锚点名（由调用方写进审计；求解器不猜坐标）。
    unresolved_anchors: List[str] = field(default_factory=list)
    #: v1.5 §4.5：灯光语义 → 预设的说明（回落原因 / 被忽略的 key_direction）。
    light_notes: List[str] = field(default_factory=list)

    def all_objects(self) -> List[Object]:
        return [o for o in [self.ground, *self.walls, *self.props, *self.lights,
                            *self.anchors] if o]


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
def create_lights(preset: str = DEFAULT_LIGHTING,
                  light: Optional[Dict[str, Any]] = None) -> List[Object]:
    """按预设创建灯光；未知预设回退到 clay_studio 并告警。

    v1.5 §4.5：给了**场级灯光语义**（``{time_of_day, mood, key_direction}``）
    就先用矩阵把它翻成预设；语义为空 ⇒ 完全沿用传进来的 ``preset``（行为不变）。
    语义非法/只有一半 ⇒ 矩阵回落 ``clay_studio``（TDD §4.5 的原话），
    回落原因由调用方从 :func:`resolve_lighting` 的说明里取。
    """
    if light and any(str(light.get(key) or "").strip()
                     for key in ("time_of_day", "mood", "key_direction")):
        preset = resolve_lighting(light)[0]
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


#: 道具跟随约束的名字前缀（一个道具一条；重复交互并成同一条 influence 曲线）。
PROP_FOLLOW_PREFIX = "BD_PropFollow_"


@main_thread_only("ensure_hand_proxy")
def ensure_hand_proxy(character, side: float = 1.0) -> Optional[Object]:
    """确保角色有一个**手部代理** empty（只进 Guides、不渲染），返回它。

    v1.5 §4.4：道具交互需要一个跟随目标。代理挂在 ``BodyPivot`` 下，于是它跟着
    角色的朝向与上身旋转走；偏移由 ``cinema/anchor.hand_offset`` 从冻结 profile
    派生（不在这里写数字）。角色没有 BodyPivot（异常构造）时返回 ``None``，
    调用方记一条告警而不是崩。
    """
    pivot = getattr(character, "body_pivot", None)
    if pivot is None:
        return None
    name = f"BD_Hand_{getattr(character, 'id', '')}"
    existing = bpy.data.objects.get(name)
    if existing is not None:
        return existing
    empty = bpy.data.objects.new(name, None)
    empty.empty_display_type = "PLAIN_AXES"
    empty.empty_display_size = 0.1
    bpy.context.scene.collection.objects.link(empty)
    empty.parent = pivot
    empty.location = hand_offset(DEFAULT_PROFILE, side)
    return mark_as_guide(empty)


def _prop_objects(props: Optional[Sequence[Object]]) -> Dict[str, Object]:
    """道具查找表：SDL id 与对象名都能命中同一个对象。"""
    lookup: Dict[str, Object] = {}
    for obj in props or []:
        identifier = str(obj.get("bd_sdl_id") or "")
        if identifier:
            lookup[identifier] = obj
        lookup.setdefault(str(obj.name), obj)
    return lookup


@main_thread_only("apply_prop_interactions")
def apply_prop_interactions(shot, shot_start: int, characters: Dict[str, Any],
                            props: Optional[Sequence[Object]]
                            ) -> List[str]:
    """把一镜的道具交互动词落实成**道具对象的跟随关键帧**（v1.5 §4.4）。

    * 跟随窗由纯函数 :func:`cinema.props.prop_interaction_windows` 算出
      （镜内局部帧 → 绝对帧走 :func:`cinema.schedule.action_frame_window`）；
    * 每个被点名的道具挂一条 ``CHILD_OF`` 约束，``influence`` 关键帧就是那条
      0/1 曲线：**只在声明的区间内跟随**，区间外道具停在原地；
    * ``inverse_matrix`` 取构建时刻手部代理世界矩阵的逆，于是"接管"的那一帧
      道具**不跳**（这是 Child Of 的标准用法）；
    * **没被任何动词点名的道具一个关键帧都不打**（"未交互道具不打关键帧"）。
    """
    notes: List[str] = []
    windows, problems = prop_interaction_windows(
        getattr(shot, "actions", None) or [], shot_id=shot.shot_id,
        shot_start=int(shot_start),
        duration_frames=int(shot.duration_frames or 1))
    notes.extend(problems)
    if not windows:
        return notes

    lookup = _prop_objects(props)
    #: 每个道具跟随哪只手：取**第一次**声明它的那个角色（后续交互沿用）。
    by_prop: Dict[str, str] = {}
    for raw in getattr(shot, "actions", None) or []:
        if not isinstance(raw, dict):
            continue
        if str(raw.get("action_type") or "") not in PROP_INTERACTION_ACTIONS:
            continue
        params = raw.get("params") or {}
        prop_name = str((params or {}).get("prop") or "").strip()
        if prop_name in windows and prop_name not in by_prop:
            by_prop[prop_name] = str(raw.get("character_id") or "")

    for prop_name, character_id in by_prop.items():
        spans = windows[prop_name]
        prop = lookup.get(prop_name) or lookup.get(f"BD_Prop_{prop_name}")
        if prop is None:
            notes.append(f"{shot.shot_id}: 道具交互引用了不存在的道具 "
                         f"{prop_name}，已跳过（不新建道具）")
            continue
        character = (characters or {}).get(character_id)
        if character is None:
            notes.append(f"{shot.shot_id}: 道具 {prop_name} 的交互引用了"
                         f"不在场的角色 {character_id}，已跳过")
            continue
        hand = ensure_hand_proxy(character)
        if hand is None:
            notes.append(f"{shot.shot_id}: 角色 {character_id} 没有躯干轴心，"
                         f"道具 {prop_name} 无法跟随，已跳过")
            continue
        constraint = prop.constraints.get(PROP_FOLLOW_PREFIX + prop_name)
        if constraint is None or constraint.type != "CHILD_OF":
            constraint = prop.constraints.new("CHILD_OF")
        constraint.name = PROP_FOLLOW_PREFIX + prop_name
        constraint.target = hand
        constraint.inverse_matrix = hand.matrix_world.inverted()
        keys = influence_keys(spans)
        for frame, value in keys:
            constraint.influence = float(value)
            #: Blender 5.x 的 ``keyframe_insert`` 返回的是 bool，不是 F-Curve，
            #: 所以插值必须**回头按 data_path 找**（不能拿返回值当曲线用）。
            constraint.keyframe_insert(data_path="influence", frame=int(frame))
        for curve in _constraint_curves(prop, constraint.name):
            for point in curve.keyframe_points:
                #: 跟随开关是 0/1 的**阶跃**：线性插值会把"还没拿起"的那几帧
                #: 变成半跟随（道具被手拖着斜着走）。
                point.interpolation = "CONSTANT"
        constraint.influence = 0.0
        notes.append(f"{shot.shot_id}: 道具 {prop_name} 跟随 {character_id}"
                     f"（{len(merge_windows(spans))} 段窗口）")
    return notes


def _constraint_curves(obj: Object, constraint_name: str) -> List[Any]:
    """取某个约束上的全部 F-Curve（``constraints["名"].influence`` 那条）。"""
    animation = getattr(obj, "animation_data", None)
    if animation is None or animation.action is None:
        return []
    from ..utils.blender_compat import action_fcurves

    prefix = f'constraints["{constraint_name}"].'
    return [curve for curve in action_fcurves(animation.action)
            if str(curve.data_path).startswith(prefix)]


@main_thread_only("create_anchor")
def create_anchor(name: str, position: Sequence[float]) -> Object:
    """场级锚点落成一个 ``BD_Anchor_*`` empty，只进 Guides、**不渲染**。

    v1.5 §4.3：锚点的作用是给走位/摆位一个可引用的世界坐标。它绝不能进参考
    视频，所以走 :func:`mark_as_guide`（进 Guides 集合 ＋ ``hide_render=True``）。
    导出前的审计对 ``EMPTY`` 与 ``hide_render`` 两条都放行（``EMPTY`` 本就不
    入画），这两条守卫一起保证"helper 不会泄漏进参考视频"。
    """
    empty = bpy.data.objects.new(f"BD_Anchor_{name}", None)
    empty.empty_display_type = "PLAIN_AXES"
    empty.empty_display_size = 0.5
    bpy.context.scene.collection.objects.link(empty)
    empty.location = (float(position[0]), float(position[1]), float(position[2]))
    return mark_as_guide(empty)


def _cast_positions(cast: Optional[Sequence[Any]]
                    ) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
    """剧组 → 摆位求解器的入参（``id → {position, facing}``）＋ 显示名别名表。

    接受 :class:`CastMember` 对象或等价的 dict（无 bpy 的调用方也能用）。
    """
    positions: Dict[str, Dict[str, Any]] = {}
    aliases: Dict[str, str] = {}
    for member in cast or []:
        if isinstance(member, dict):
            identifier = str(member.get("id") or "")
            display = str(member.get("name") or "")
            location = member.get("initial_location")
            facing = member.get("initial_facing")
        else:
            identifier = str(getattr(member, "id", "") or "")
            display = str(getattr(member, "name", "") or "")
            location = getattr(member, "initial_location", None)
            facing = getattr(member, "initial_facing", None)
        if not identifier:
            continue
        positions[identifier] = {"position": location, "facing": facing}
        if display and display != identifier:
            aliases[display] = identifier
    return positions, aliases


@main_thread_only("build_environment")
def build_environment(*, ground_size: Tuple[float, float] = (20.0, 20.0),
                      walls: Optional[List[Dict[str, Any]]] = None,
                      props: Optional[List[Dict[str, Any]]] = None,
                      lighting: str = DEFAULT_LIGHTING,
                      anchors: Optional[List[Dict[str, Any]]] = None,
                      cast: Optional[Sequence[Any]] = None,
                      light: Optional[Dict[str, Any]] = None) -> Environment:
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
        # v1.5 §4.3：先解算锚点坐标，再落成 empty。求解是纯函数；解析不出的
        # 锚点记进 ``unresolved_anchors``（调用方写审计），**不猜坐标**。
        if anchors:
            cast_positions, aliases = _cast_positions(cast)
            anchor_names = [str(item.get("name") or "")
                            for item in anchors if isinstance(item, dict)]
            positions, unresolved = solve_anchor_positions(
                anchors, cast_positions, aliases=aliases,
                anchor_names=[name for name in anchor_names if name])
            for item in unresolved:
                # 审计口径：``unresolved_anchor: <锚点>: <原因>``（求解器不猜坐标，
                # 只如实报告它为什么摆不出来）。
                label = (f"{item['anchor']}: {item['reason']}" if item["anchor"]
                         else item["reason"])
                environment.unresolved_anchors.append(
                    f"unresolved_anchor: {label}")
                log.warning("锚点未解析：%s", label)
            for anchor in anchors:
                name = str(anchor.get("name") or "") \
                    if isinstance(anchor, dict) else ""
                if not name or name not in positions:
                    continue
                environment.anchors.append(
                    create_anchor(name, positions[name]))
        if light and any(str(light.get(key) or "").strip()
                         for key in ("time_of_day", "mood", "key_direction")):
            preset, notes = resolve_lighting(light)
            environment.light_notes = list(notes)
            for note in notes:
                log.info("灯光语义：%s", note)
            environment.lighting = preset
        environment.lights = create_lights(environment.lighting)
    log.info("环境搭建完成：预设=%s，物体 %d 个", lighting,
             len(environment.all_objects()))
    return environment
