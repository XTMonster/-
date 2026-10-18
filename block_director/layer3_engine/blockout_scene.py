"""Ticket 03：Blockout 体块建场景器（bpy 侧）。

按 ``cinema.blockout.build_blockout_manifest`` 产出的 BlockoutManifest 只搭
大型体块（长方体基础几何体）+ 相机先行（位置/目标/镜头/运动轨迹一次落位），
不做角色细节几何：

* 体块命名统一 ``BD_Blockout_<manifest.id>``，全部进独立 ``Blockout`` 集合；
* ``z_anchor=foot`` 的几何原点放脚底（角色 human scale 站姿），``=center``
  的几何原点放中心（道具/锚点）；
* 相机按 ``BD_Blockout_cam_<shot_id>`` 命名，Track To 对准
  ``BD_Blockout_CamTarget_<shot_id>``，焦距/运动轨迹复用既有相机运动落场逻辑；
* 共享资产（asset_registry 同名）只实例化一次，逐分镜引用不重建；
* 地面与灯光复用既有场景执行器（clay_studio），命名 ``BD_Blockout_Ground``。

确定性：同一 manifest 两次构建物体名/数量/坐标逐位一致；bpy 操作全部走
``@main_thread_only`` 守卫。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence

import bpy
from mathutils import Vector

from ..cinema.blockout import BLOCKOUT_COLOR
from ..utils.logger import get_logger
from ..utils.threading_guard import main_thread_only
from .cinema_engine.camera_motion import apply_camera_movement
from .collection_router import clear_blockdirector_objects, route_object
from .scene_executor import create_ground, create_lights

log = get_logger("blockout-scene")

#: 体块对象名前缀（manifest id -> BD_Blockout_<id>）。
BD_BLOCKOUT_PREFIX = "BD_Blockout_"

#: 体块集合名（独立集合，后续检查点/渲染按集合引用）。
BLOCKOUT_COLLECTION = "Blockout"


def _blockout_collection(scene) -> bpy.types.Collection:
    collection = scene.collection.children.get(BLOCKOUT_COLLECTION)
    if collection is None:
        collection = bpy.data.collections.new(BLOCKOUT_COLLECTION)
        scene.collection.children.link(collection)
    return collection


def _gray_material() -> bpy.types.Material:
    material = bpy.data.materials.get("BD_Blockout_Mat")
    if material is None:
        material = bpy.data.materials.new("BD_Blockout_Mat")
        material.diffuse_color = (0.56, 0.54, 0.50, 1.0)  # #8f8f8f 附近灰
    return material


def _hex_to_rgb(value: str) -> Sequence[float]:
    hex_value = str(value or BLOCKOUT_COLOR).lstrip("#")
    if len(hex_value) != 6:
        return (0.56, 0.54, 0.50)
    try:
        return tuple(int(hex_value[i:i + 2], 16) / 255.0
                     for i in (0, 2, 4))
    except ValueError:
        return (0.56, 0.54, 0.50)


def _material_for(color: str) -> bpy.types.Material:
    rgb = _hex_to_rgb(color)
    name = f"BD_Blockout_Mat_{color.lstrip('#')}"
    material = bpy.data.materials.get(name)
    if material is None:
        material = bpy.data.materials.new(name)
        material.diffuse_color = (*rgb, 1.0)
    return material


def _place_box(primitive: Mapping[str, Any], collection,
               material) -> bpy.types.Object:
    """按 manifest 体块建一个长方体（原点按 z_anchor 落位）。"""
    block_id = str(primitive.get("id") or "block")
    name = f"{BD_BLOCKOUT_PREFIX}{block_id}"
    if bpy.data.objects.get(name) is not None:
        raise ValueError(f"体块对象已存在：{name}（共享资产只实例化一次）")
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.0, 0.0, 0.0))
    obj = bpy.context.active_object
    obj.name = name
    size = primitive.get("size") or {}
    dims = (float(size.get("x") or 0.9), float(size.get("y") or 0.9),
            float(size.get("z") or 1.2))
    obj.scale = Vector((dims[0], dims[1], dims[2]))
    position = primitive.get("position") or {}
    x, y, z = (float(position.get("x") or 0.0),
               float(position.get("y") or 0.0),
               float(position.get("z") or 0.0))
    z_anchor = str(primitive.get("z_anchor") or "center")
    origin_z = z + (dims[2] / 2.0) if z_anchor == "foot" else z
    obj.location = Vector((x, y, origin_z))
    obj.data.materials.append(material)
    route_object(obj, BLOCKOUT_COLLECTION)
    return obj


def _place_camera(camera: Mapping[str, Any], collection) -> bpy.types.Object:
    """按 manifest 机位建相机 + Track To 目标 Empty + 镜头/运镜。"""
    shot_id = str(camera.get("shot_id") or "")
    camera_id = str(camera.get("camera_id") or f"cam_{shot_id}")
    camera_name = f"{BD_BLOCKOUT_PREFIX}{camera_id}"
    if camera.get("position") is None:
        log.info("机位 %s 未解析，跳过（manifest 照实 unresolved）", shot_id)
        return None
    camera_data = bpy.data.cameras.new(camera_name)
    camera_data.lens = float(camera.get("lens_mm") or 50.0)
    camera_obj = bpy.data.objects.new(camera_name, camera_data)
    collection.objects.link(camera_obj)
    camera_obj.location = Vector(
        [float(v) for v in (camera.get("position") or [])])
    #: matrix_world 需要先入图并求值：不在 view layer 里先 update，运镜
    #: 采样会把起点读成单位矩阵 (0,0,0)（Blender 实测）。
    bpy.context.view_layer.update()

    target_name = f"{BD_BLOCKOUT_PREFIX}CamTarget_{shot_id}"
    target_obj = bpy.data.objects.get(target_name)
    if target_obj is None:
        target_obj = bpy.data.objects.new(target_name, None)
        collection.objects.link(target_obj)
    target_obj.location = Vector(
        [float(v) for v in (camera.get("target") or camera.get("position")
                            or [])])
    track = camera_obj.constraints.new(type="TRACK_TO")
    track.target = target_obj
    track.track_axis = "TRACK_NEGATIVE_Z"
    track.up_axis = "UP_Y"

    movements = camera.get("movements") or []
    for movement in movements:
        apply_camera_movement(
            camera_obj, target_obj,
            str(movement.get("type") or ""),
            float(movement.get("amount") or 0.0),
            int(movement.get("start_frame") or camera.get("start_frame") or 1),
            int(movement.get("end_frame") or camera.get("end_frame") or 1))
    return camera_obj


def _add_cut_markers(scene, shot_table: Sequence[Mapping[str, Any]]) -> int:
    """按分镜表在每镜起始帧打 ``BD_Cut_<shot_id>`` 时间轴标记。"""
    added = 0
    for row in shot_table:
        shot_id = str(row.get("shot_id") or "")
        if not shot_id:
            continue
        start = int(row.get("start_frame") or 1)
        marker_name = f"BD_Cut_{shot_id}"
        if scene.timeline_markers.get(marker_name) is None:
            scene.timeline_markers.new(marker_name, frame=start)
            added += 1
    return added


@main_thread_only("build_blockout_scene")
def build_blockout_scene(manifest: Mapping[str, Any], *,
                         clear_scene: bool = True) -> Dict[str, Any]:
    """按 BlockoutManifest 建体块场景，返回可验证的构建摘要。

    ``clear_scene=True`` 清掉既有 ``BD_`` 对象（体块场景整体重来，符合
    "粗排重生成"语义）；不动非 BD_ 用户对象。
    """
    if clear_scene:
        clear_blockdirector_objects()
    scene = bpy.context.scene
    collection = _blockout_collection(scene)
    material = _gray_material()

    placed_primitives = 0
    seen_assets: set = set()
    skipped_duplicates = 0
    for primitive in manifest.get("primitives") or []:
        asset_ref = primitive.get("asset_ref")
        if asset_ref is not None and str(asset_ref) in seen_assets:
            skipped_duplicates += 1
            continue
        if asset_ref is not None:
            seen_assets.add(str(asset_ref))
        _place_box(primitive, collection, _material_for(
            str(primitive.get("color") or BLOCKOUT_COLOR)))
        placed_primitives += 1

    placed_cameras = 0
    for camera in manifest.get("cameras") or []:
        if _place_camera(camera, collection) is not None:
            placed_cameras += 1

    ground = create_ground(size=(20.0, 20.0))
    if ground is not None:
        ground.name = "BD_Blockout_Ground"
        route_object(ground, BLOCKOUT_COLLECTION)

    create_lights(preset="clay_studio")
    markers = _add_cut_markers(scene, manifest.get("shot_table") or [])

    frame_starts = [int(c.get("start_frame") or 1)
                    for c in manifest.get("cameras") or []]
    frame_ends = [int(c.get("end_frame") or 1)
                  for c in manifest.get("cameras") or []]
    if frame_starts:
        scene.frame_start = min(frame_starts)
        scene.frame_end = max(frame_ends)

    return {
        "objects": placed_primitives + placed_cameras,
        "primitives": placed_primitives,
        "cameras": placed_cameras,
        "markers": markers,
        "skipped_duplicates": skipped_duplicates,
        "collection": BLOCKOUT_COLLECTION,
        "frame_range": [scene.frame_start, scene.frame_end]
        if frame_starts else None,
    }


__all__ = ["build_blockout_scene", "BD_BLOCKOUT_PREFIX",
           "BLOCKOUT_COLLECTION"]
