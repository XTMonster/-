"""深度序列导出（执行文档 v1.2 §15.6）。

**实现方式与文档有一处差异，理由如下**：§15.6 的方式 A 建议"EEVEE Z Pass +
Compositor 输出归一化深度图"。实测 Blender 5.2 的合成器已被重写——File Output
节点**只能写 multi-layer EXR**（`format.file_format` 的枚举里只有
`OPEN_EXR_MULTILAYER`），拿不到 16 位灰度 PNG；而 Workbench 的
`color_type` 枚举里也没有 depth 着色（方式 B 同样走不通）。

因此改用等价的第三条路：**相机数据（View Z Depth）+ 材质覆盖**。逐像素的
"相机空间 Z 距离"经固定的 0.1–50 米映射成 0–1 灰色自发光，整场景材质换上这
一份就得到一张真正的逐像素深度图，且：

- 归一化完全可控（就是我们在 `delivery/depth.py` 里定死的那一段），
- 输出走普通渲染设置，天然是 16 位灰度 PNG，
- 背景用世界覆盖置为纯白（= 超出远端的 1.0），符合 ControlNet-depth 的读法。

方法调用的都是稳定 API（`material_override` / `world_override` /
`ShaderNodeCameraData`），不依赖 5.x 尚在变动的新合成器节点。
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

import bpy

from ..delivery.depth import DEPTH_FRAME_PREFIX, DEPTH_RANGE, depth_dir_name
from ..utils.blender_compat import engine_identifier, map_range_node
from ..utils.logger import get_logger
from ..utils.threading_guard import main_thread_only

log = get_logger("delivery.depth")

DEPTH_MATERIAL = "BD_DepthMaterial"
DEPTH_WORLD = "BD_DepthWorld"


class DepthUnavailable(RuntimeError):
    """当前配置/环境拿不到深度。消息里给出可执行的下一步。"""


def _depth_material(near: float, far: float):
    """View Z Depth → 归一化 → 自发光。"""
    material = bpy.data.materials.get(DEPTH_MATERIAL)
    if material is None:
        material = bpy.data.materials.new(DEPTH_MATERIAL)
    material.use_nodes = True
    tree = material.node_tree
    for node in list(tree.nodes):
        tree.nodes.remove(node)

    camera_data = tree.nodes.new("ShaderNodeCameraData")
    camera_data.location = (-500, 0)
    mapping = map_range_node(tree)
    mapping.location = (-250, 0)
    emission = tree.nodes.new("ShaderNodeEmission")
    emission.location = (0, 0)
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    output.location = (250, 0)

    tree.links.new(camera_data.outputs["View Z Depth"], mapping.inputs[0])
    mapping.inputs["From Min"].default_value = float(near)
    mapping.inputs["From Max"].default_value = float(far)
    mapping.inputs["To Min"].default_value = 0.0
    mapping.inputs["To Max"].default_value = 1.0
    if "Clamp" in mapping.inputs:
        mapping.inputs["Clamp"].default_value = True
    tree.links.new(mapping.outputs[0], emission.inputs["Color"])
    tree.links.new(emission.outputs[0], output.inputs["Surface"])
    return material


def _depth_world():
    """纯白世界：背景 = 超出远端的 1.0。"""
    world = bpy.data.worlds.get(DEPTH_WORLD)
    if world is None:
        world = bpy.data.worlds.new(DEPTH_WORLD)
    world.use_nodes = True
    tree = world.node_tree
    for node in list(tree.nodes):
        tree.nodes.remove(node)
    background = tree.nodes.new("ShaderNodeBackground")
    background.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
    background.inputs["Strength"].default_value = 1.0
    output = tree.nodes.new("ShaderNodeOutputWorld")
    tree.links.new(background.outputs[0], output.inputs["Surface"])
    return world


@main_thread_only("render_depth_sequence")
def render_depth_sequence(scene, start_frame: int, end_frame: int,
                          export_dir: str, shot_id: str,
                          *, depth_range: Tuple[float, float] = DEPTH_RANGE
                          ) -> Dict[str, object]:
    """渲染一个镜头的深度序列（16 位灰度 PNG，逐帧与视频对应）。"""
    if scene.render.engine != engine_identifier("eevee"):
        raise DepthUnavailable(
            f"深度序列需要 EEVEE（当前引擎 {scene.render.engine}）；"
            f"请把 delivery.render_backend 设为 eevee 后重试")

    near, far = float(depth_range[0]), float(depth_range[1])
    directory = Path(export_dir) / depth_dir_name(shot_id)
    directory.mkdir(parents=True, exist_ok=True)

    view_layer = bpy.context.view_layer
    settings = scene.render.image_settings
    previous = {
        "material_override": view_layer.material_override,
        "world_override": getattr(view_layer, "world_override", None),
        "media_type": getattr(settings, "media_type", None),
        "file_format": settings.file_format,
        "color_mode": settings.color_mode,
        "color_depth": settings.color_depth,
        "filepath": scene.render.filepath,
        "frame_start": scene.frame_start,
        "frame_end": scene.frame_end,
        "film_transparent": scene.render.film_transparent,
    }

    view_layer.material_override = _depth_material(near, far)
    if hasattr(view_layer, "world_override"):
        view_layer.world_override = _depth_world()
    if hasattr(settings, "media_type"):
        settings.media_type = "IMAGE"
    settings.file_format = "PNG"
    settings.color_mode = "BW"
    settings.color_depth = "16"
    scene.render.film_transparent = False

    try:
        scene.frame_start = int(start_frame)
        scene.frame_end = int(end_frame)
        scene.render.filepath = str(directory / DEPTH_FRAME_PREFIX)
        bpy.ops.render.render(animation=True)
    finally:
        view_layer.material_override = previous["material_override"]
        if hasattr(view_layer, "world_override"):
            view_layer.world_override = previous["world_override"]
        if previous["media_type"] is not None:
            settings.media_type = previous["media_type"]
        settings.file_format = previous["file_format"]
        settings.color_mode = previous["color_mode"]
        settings.color_depth = previous["color_depth"]
        scene.render.filepath = previous["filepath"]
        scene.frame_start = previous["frame_start"]
        scene.frame_end = previous["frame_end"]
        scene.render.film_transparent = previous["film_transparent"]

    written = sorted(directory.glob(f"{DEPTH_FRAME_PREFIX}*.png"))
    expected = int(end_frame) - int(start_frame) + 1
    if len(written) != expected:
        log.warning("深度帧数不符：期望 %d，实际 %d", expected, len(written))
    log.info("深度序列 %s：%d 帧 → %s", shot_id, len(written), directory)
    return {"shot_id": shot_id, "dir": str(directory),
            "frames": len(written), "expected": expected,
            "range_m": [near, far], "files": [str(path) for path in written]}


def depth_supported(scene) -> bool:
    """当前场景是否具备出深度的条件。"""
    return scene.render.engine == engine_identifier("eevee")
