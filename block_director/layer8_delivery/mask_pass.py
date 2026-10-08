"""逐元素遮罩通道（v1.6 FR-A3 / 卡 E2，TDD §5）。

每镜导出一套 ``masks/<shot_id>/frame_%04d.png``：角色/道具逐对象纯色
（色表 = :mod:`block_director.contracts.elements` 的 ``color_hex``，**只从登记表
读，不从图像反推**）、环境件统一 ``#808080``、世界覆盖纯黑、标签与辅助件
``hide_render=True``。

实现路线（v1.6.1 修正，TDD §5 逐字）：

- **不是 Workbench**，也**不是 ``view_layer.material_override``**——override 整
  场景只有一份材质，做不了逐对象分色。与深度 pass 同引擎：场景引擎必须是
  EEVEE（``depth_pass.py`` 同一判据），逐对象**材质槽**挂纯色自发光材质
  （每元素一份 ``BD_Mask_<element_id>``，环境件共用 ``BD_Mask_environment``）。
  Blender 5.2 实测：渲染读的是**对象级** ``Object.material_slots``，而
  ``Mesh.materials`` 只是网格数据的缺省列表（改它不影响已建对象的渲染）——
  因此挂载与快照一律走 ``obj.material_slots[i].material``。
- 自发光材质不受灯光影响；配合 ``film_transparent=False``、世界覆盖纯黑、
  ``dither_intensity=0`` 与 ``view_transform="Raw"``（后两项是深度 pass
  没有的：遮罩的验收是**逐像素颜色对拍**，色调映射与 8 位抖动都会改色。
  实测 Blender 5.2：``Standard`` 在落盘时仍按显示设备做 sRGB 编码——0.502
  的灰自发光存成 0.737；只有 ``Raw`` 把 0.502 原样写进 PNG。Raw + 抖动关 +
  自发光 ⇒ 中心像素逐通道精确命中登记表色）。
- 帧范围由调用方传入（``cinema/schedule.shot_ranges(plan)``，与分镜 mp4
  同一份帧表，不另算）；文件名用**绝对帧号**（与 depth pass 同口径）。
- 快照/恢复纪律照抄 ``depth_pass.py:109/137``：渲染前快照材质槽、世界、
  ``hide_render`` 与渲染设置，``finally`` 里逐项恢复**之后**原异常继续抛出
  （不吞错误）；目录清理与分类校验发生在任何改动**之前**，失败时场景原样。
- 确定性：材质按元素 id 命名并就地重建、帧目录渲染前清掉本 pass 自己的
  ``frame_*.png`` 陈帧、``use_overwrite=True``——同一场景两次跑像素数据逐字节
  相同。Blender 5.2 实测：PNG 的 IDAT 与除 ``RenderTime`` 外的全部元数据块跨
  运行逐字节相同；``RenderTime`` 是 Blender 无条件内嵌的墙钟时间
  （``metadata_input`` 在 5.2 只有 ``SCENE``/``STRIPS``，关不掉它），因此本 pass
  把 ``metadata_input`` 设为 ``STRIPS`` 去掉同样易变的 ``Date`` 块，文件的确定性
  以「IDAT 逐字节相同 ＋ 其余元数据块逐字节相同」为口径。
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple

import bpy
from bpy.types import Collection, Object

from ..contracts.elements import ENVIRONMENT_COLOR
from ..layer3_engine.collection_router import LABEL_NAME_RE, LABELS_COLLECTION
from ..utils.blender_compat import engine_identifier
from ..utils.logger import get_logger
from ..utils.threading_guard import main_thread_only

log = get_logger("delivery.mask")

#: 交付包里的遮罩根目录（TDD §5：``masks/shot_00X/``）。
MASK_ROOT_DIR = "masks"
#: 帧文件前缀（Blender 按绝对帧号补 ``%04d``，与 depth pass 同口径）。
MASK_FRAME_PREFIX = "frame_"
#: 每元素一份遮罩材质（TDD §5 / 卡 E2：``BD_Mask_<element_id>``）。
MASK_MATERIAL_PREFIX = "BD_Mask_"
#: 环境件共用的灰阶材质（色表 = elements.ENVIRONMENT_COLOR = #808080）。
ENVIRONMENT_MATERIAL_NAME = f"{MASK_MATERIAL_PREFIX}environment"
#: 纯黑世界（背景 = #000000），与 depth 的 ``BD_DepthWorld`` 同一命名套路。
MASK_WORLD_NAME = "BD_MaskWorld"

#: 会进渲染的几何体类型；EMPTY/CAMERA/LIGHT/ARMATURE 不参与分类。
_GEOMETRY_TYPES = {
    "MESH", "CURVE", "SURFACE", "FONT", "META", "LATTICE",
    "POINTCLOUD", "VOLUME", "GREASEPENCIL",
}
#: 环境件的对象名前缀（``scene_executor.py``：``BD_ENV_*`` / ``BD_Wall_*``）。
_ENV_NAME_PREFIXES = ("BD_ENV_", "BD_Wall_")
#: 道具对象名前缀（``scene_executor.py::create_prop``：``BD_Prop_<id>``）。
_PROP_NAME_PREFIX = "BD_Prop_"
#: content 列表里的“环境件”哨兵（环境件统一灰阶，不按登记表 id 分色）。
_ENV_SENTINEL = "__environment__"


class MaskUnavailable(RuntimeError):
    """当前配置/环境出不了遮罩。消息里给出可执行的下一步。"""


def _strict_hex_to_rgb(color_hex: str) -> Tuple[float, float, float]:
    """``#RRGGBB`` → 0..1 三元组；非法色值**报错**（遮罩色即身份，不许静默回落）。"""
    text = str(color_hex or "").strip()
    if text.startswith("#"):
        text = text[1:]
    if len(text) != 6:
        raise MaskUnavailable(f"元素色值必须是 #RRGGBB，收到 {color_hex!r}")
    try:
        channels = [int(text[index:index + 2], 16) for index in (0, 2, 4)]
    except ValueError:
        raise MaskUnavailable(f"元素色值不是合法十六进制：{color_hex!r}") from None
    return tuple(channel / 255.0 for channel in channels)


def _mask_material(element_id: str, color_hex: str):
    """一份纯色自发光遮罩材质（按元素 id 命名，重复调用就地重建）。"""
    name = f"{MASK_MATERIAL_PREFIX}{element_id}"
    material = bpy.data.materials.get(name)
    if material is None:
        material = bpy.data.materials.new(name)
    rgba = (*_strict_hex_to_rgb(color_hex), 1.0)
    material.use_nodes = True
    material.diffuse_color = rgba          # 视口/Workbench 显示兜底
    tree = material.node_tree
    tree.nodes.clear()
    emission = tree.nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = rgba
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    tree.links.new(emission.outputs[0], output.inputs["Surface"])
    return material


def _mask_world():
    """纯黑世界：背景 = #000000。"""
    world = bpy.data.worlds.get(MASK_WORLD_NAME)
    if world is None:
        world = bpy.data.worlds.new(MASK_WORLD_NAME)
    world.use_nodes = True
    tree = world.node_tree
    tree.nodes.clear()
    background = tree.nodes.new("ShaderNodeBackground")
    background.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
    background.inputs["Strength"].default_value = 1.0
    output = tree.nodes.new("ShaderNodeOutputWorld")
    tree.links.new(background.outputs[0], output.inputs["Surface"])
    return world


def _character_roots(registry) -> Dict[str, Object]:
    """登记表角色 id → 场景里的角色根对象（``bd_sdl_id`` 为主键）。"""
    character_ids = {element.id for element in registry.elements
                     if element.kind == "character"}
    labels = {element.id: element.label for element in registry.elements
              if element.kind == "character"}
    by_sdl: Dict[str, List[Object]] = {}
    for obj in bpy.data.objects:
        if str(obj.get("bd_element_type", "")) != "character_root":
            continue
        sdl_id = str(obj.get("bd_sdl_id", "") or "").strip()
        if sdl_id:
            by_sdl.setdefault(sdl_id, []).append(obj)

    roots: Dict[str, Object] = {}
    missing: List[str] = []
    for element_id in sorted(character_ids):
        candidates = by_sdl.get(element_id, [])
        if len(candidates) == 1:
            roots[element_id] = candidates[0]
            continue
        if len(candidates) > 1:
            raise MaskUnavailable(
                f"元素 {element_id} 对应多个角色根对象："
                + "、".join(obj.name for obj in candidates))
        for obj in bpy.data.objects:
            if obj.name == f"BD_Char_{labels[element_id]}_Root":
                roots[element_id] = obj
                break
        else:
            missing.append(element_id)
    if missing:
        raise MaskUnavailable(
            "以下登记表角色在场景里没有角色根对象（bd_sdl_id 对不上）："
            + "、".join(missing))
    return roots


def _is_label_object(obj: Object, labels: Optional[Collection]) -> bool:
    """标签三类判据（与 ``collection_router`` 同一套外生判据，不自证）："""
    if str(obj.get("bd_element_type", "")) in ("label", "label_render"):
        return True
    if LABEL_NAME_RE.match(obj.name):
        return True
    if labels is not None and any(
            collection.name == labels.name
            for collection in obj.users_collection):
        return True
    return False


def _is_environment_object(obj: Object) -> bool:
    if str(obj.get("bd_element_type", "")) == "environment":
        return True
    return obj.name.startswith(_ENV_NAME_PREFIXES)


def _classify_objects(registry, labels: Optional[Collection]
                      ) -> Tuple[List[Tuple[Object, str]], List[Object]]:
    """把场景几何分成 (content, hidden)。content 条目 = ``(对象, 元素 id)``，
    环境件用 ``_ENV_SENTINEL``。分类只读，不碰场景状态。"""
    prop_elements = {element.id: element for element in registry.elements
                     if element.kind == "prop"}
    roots = _character_roots(registry)
    root_ids = {id(root): element_id for element_id, root in roots.items()}

    content: List[Tuple[Object, str]] = []
    hidden: List[Object] = []
    missing_props: List[str] = []
    for obj in bpy.data.objects:
        if obj.type not in _GEOMETRY_TYPES:
            continue
        if _is_label_object(obj, labels):
            hidden.append(obj)
            continue

        #: 角色部件（身体/头/眼/腿）：沿父链找到角色根。根对象本身是 EMPTY，
        #: 不进几何分类；部件才是要挂遮罩材质的网格。
        node: Optional[Object] = obj
        element_id = ""
        while node is not None:
            found = root_ids.get(id(node))
            if found:
                element_id = found
                break
            node = node.parent
        if element_id:
            content.append((obj, element_id))
            continue

        if str(obj.get("bd_element_type", "")) == "prop":
            prop_id = str(obj.get("bd_sdl_id", "") or "").strip()
            if not prop_id and obj.name.startswith(_PROP_NAME_PREFIX):
                prop_id = obj.name[len(_PROP_NAME_PREFIX):]
            if prop_id not in prop_elements:
                missing_props.append(prop_id or obj.name)
                continue
            content.append((obj, prop_id))
            continue

        if _is_environment_object(obj):
            content.append((obj, _ENV_SENTINEL))
            continue
        #: 其余可渲染几何（crowd/vfx/guide 曲线/未知对象）遮罩里不可见——
        #: 它们没有登记表颜色，猜色等于伪造身份；hide_render 快照后恢复。
        hidden.append(obj)

    if missing_props:
        raise MaskUnavailable(
            "以下道具对象在元素登记表里没有对应条目（遮罩色只从登记表读）："
            + "、".join(missing_props))
    return content, hidden


def _normalise_schedule(schedule: Mapping[str, Tuple[int, int]]
                        ) -> List[Tuple[str, int, int]]:
    shots: List[Tuple[str, int, int]] = []
    for shot_id, pair in (schedule or {}).items():
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            raise ValueError(f"镜头 {shot_id!r} 的帧范围必须是 (start, end)")
        start, end = int(pair[0]), int(pair[1])
        if start < 1 or end < start:
            raise ValueError(
                f"镜头 {shot_id!r} 帧范围非法：({start}, {end})")
        shots.append((str(shot_id), start, end))
    if not shots:
        raise MaskUnavailable("遮罩导出没有镜头帧表（schedule 为空）")
    return shots


def _render_animation(scene):
    """渲染一段动画。独立成函数只是为了让失败路径可注入（探针钉恢复纪律）。"""
    bpy.ops.render.render(animation=True)


def _snapshot(scene, content: List[Tuple[Object, str]],
              hidden: List[Object], labels: Optional[Collection]
              ) -> Dict[str, object]:
    settings = scene.render.image_settings
    return {
        #: 对象级材质槽才是 Blender 5.2 渲染真正读取的槽（见模块 docstring）。
        "materials": [(obj, [slot.material for slot in obj.material_slots])
                      for obj, _ in content],
        "hidden": [(obj, obj.hide_render) for obj in hidden],
        "labels_hide_render": labels.hide_render if labels is not None else None,
        "world_override": getattr(bpy.context.view_layer, "world_override", None),
        "filepath": scene.render.filepath,
        "frame_start": scene.frame_start,
        "frame_end": scene.frame_end,
        "film_transparent": scene.render.film_transparent,
        "dither_intensity": scene.render.dither_intensity,
        "use_overwrite": scene.render.use_overwrite,
        "use_placeholder": scene.render.use_placeholder,
        "media_type": getattr(settings, "media_type", None),
        "metadata_input": getattr(scene.render, "metadata_input", None),
        "file_format": settings.file_format,
        "color_mode": settings.color_mode,
        "color_depth": settings.color_depth,
        "view_transform": scene.view_settings.view_transform,
        "look": scene.view_settings.look,
    }


def _restore(scene, previous: Dict[str, object]) -> None:
    settings = scene.render.image_settings
    for obj, saved in previous["materials"]:  # type: ignore[assignment]
        slots = obj.material_slots
        if saved:
            for index, material in enumerate(saved):
                slots[index].material = material
        else:
            #: 0 槽对象在 pass 里被 ``data.materials.append`` 补了 1 槽，
            #: 清掉即回到 0（Blender 5.2 实测：data.clear() 会同步对象槽）。
            obj.data.materials.clear()
    for obj, was_hidden in previous["hidden"]:  # type: ignore[assignment]
        obj.hide_render = was_hidden
    labels = bpy.data.collections.get(LABELS_COLLECTION)
    if labels is not None and previous["labels_hide_render"] is not None:
        labels.hide_render = previous["labels_hide_render"]
    if hasattr(bpy.context.view_layer, "world_override"):
        bpy.context.view_layer.world_override = previous["world_override"]
    if previous["media_type"] is not None:
        settings.media_type = previous["media_type"]
    if previous["metadata_input"] is not None:
        scene.render.metadata_input = previous["metadata_input"]
    settings.file_format = previous["file_format"]
    settings.color_mode = previous["color_mode"]
    settings.color_depth = previous["color_depth"]
    scene.render.filepath = previous["filepath"]
    scene.frame_start = previous["frame_start"]
    scene.frame_end = previous["frame_end"]
    scene.render.film_transparent = previous["film_transparent"]
    scene.render.dither_intensity = previous["dither_intensity"]
    scene.render.use_overwrite = previous["use_overwrite"]
    scene.render.use_placeholder = previous["use_placeholder"]
    scene.view_settings.view_transform = previous["view_transform"]
    scene.view_settings.look = previous["look"]


@main_thread_only("render_mask_pass")
def render_mask_pass(scene, registry, schedule, out_dir
                     ) -> List[Dict[str, object]]:
    """渲染全部镜头的逐元素遮罩序列，返回每镜一条结果。

    ``schedule`` = :func:`block_director.cinema.schedule.shot_ranges` 的返回值
    （``{shot_id: (start_frame, end_frame)}``，与分镜 mp4 同一帧表）。
    帧数不符会**报错**而不是只告警——遮罩是下游模型的布局信号，缺帧即废品。
    """
    if scene.render.engine != engine_identifier("eevee"):
        raise MaskUnavailable(
            f"遮罩通道需要 EEVEE（当前引擎 {scene.render.engine}）；"
            f"请把 delivery.render_backend 设为 eevee 后重试")

    shots = _normalise_schedule(schedule)
    labels = bpy.data.collections.get(LABELS_COLLECTION)
    content, hidden = _classify_objects(registry, labels)

    #: 目录与陈帧清理发生在**任何场景改动之前**：这里失败时场景保持原样。
    directories: Dict[str, Path] = {}
    for shot_id, _start, _end in shots:
        directory = Path(out_dir) / MASK_ROOT_DIR / shot_id
        directory.mkdir(parents=True, exist_ok=True)
        for stale in sorted(directory.glob(f"{MASK_FRAME_PREFIX}*.png")):
            stale.unlink()
        directories[shot_id] = directory

    previous = _snapshot(scene, content, hidden, labels)
    try:
        environment_material = _mask_material("environment", ENVIRONMENT_COLOR)
        element_materials = {
            element.id: _mask_material(element.id, element.color_hex)
            for element in registry.elements
            if element.kind in ("character", "prop")
        }
        for obj, element_id in content:
            target = (environment_material if element_id == _ENV_SENTINEL
                      else element_materials[element_id])
            slots = obj.material_slots
            if len(slots):
                for slot in slots:
                    slot.material = target
            else:
                #: 0 槽网格：先经数据列表建出槽，对象槽随之同步（5.2 实测）。
                obj.data.materials.append(target)
        for obj in hidden:
            obj.hide_render = True
        if labels is not None:
            labels.hide_render = True
        if hasattr(bpy.context.view_layer, "world_override"):
            bpy.context.view_layer.world_override = _mask_world()

        settings = scene.render.image_settings
        if previous["media_type"] is not None:
            settings.media_type = "IMAGE"
        if previous["metadata_input"] is not None:
            scene.render.metadata_input = "STRIPS"
        settings.file_format = "PNG"
        settings.color_mode = "RGB"
        settings.color_depth = "8"
        scene.render.film_transparent = False
        scene.render.dither_intensity = 0.0
        scene.render.use_overwrite = True
        scene.render.use_placeholder = False
        scene.view_settings.view_transform = "Raw"
        scene.view_settings.look = "None"

        results: List[Dict[str, object]] = []
        for shot_id, start, end in shots:
            scene.frame_start = int(start)
            scene.frame_end = int(end)
            scene.render.filepath = str(directories[shot_id] / MASK_FRAME_PREFIX)
            _render_animation(scene)
            written = sorted(directories[shot_id].glob(
                f"{MASK_FRAME_PREFIX}*.png"))
            expected = int(end) - int(start) + 1
            if len(written) != expected:
                raise MaskUnavailable(
                    f"{shot_id}: 遮罩帧数不符：期望 {expected}，"
                    f"实际 {len(written)}")
            results.append({
                "shot_id": shot_id,
                "dir": str(directories[shot_id]),
                "start_frame": int(start),
                "end_frame": int(end),
                "frames": len(written),
                "expected": expected,
                "files": [str(path) for path in written],
            })
            log.info("遮罩序列 %s：%d 帧 → %s", shot_id, len(written),
                     directories[shot_id])
        return results
    finally:
        _restore(scene, previous)


def mask_supported(scene) -> bool:
    """当前场景是否具备出遮罩的条件（与 depth_supported 同判据）。"""
    return scene.render.engine == engine_identifier("eevee")


__all__ = [
    "MaskUnavailable", "MASK_ROOT_DIR", "MASK_FRAME_PREFIX",
    "MASK_MATERIAL_PREFIX", "ENVIRONMENT_MATERIAL_NAME", "MASK_WORLD_NAME",
    "render_mask_pass", "mask_supported",
]
