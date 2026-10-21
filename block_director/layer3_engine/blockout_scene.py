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
from ..cinema.camera_motion import movement_curve, movement_spec
from ..contracts.blockout import manifest_fingerprint
from ..utils.logger import get_logger
from ..utils.threading_guard import main_thread_only
from .cinema_engine.camera_motion import apply_camera_movement
from .collection_router import (
    clear_blockdirector_objects,
    purge_orphan_data,
    route_object,
)
from .scene_executor import create_ground, create_lights

log = get_logger("blockout-scene")

#: 体块对象名前缀（manifest id -> BD_Blockout_<id>）。
BD_BLOCKOUT_PREFIX = "BD_Blockout_"

#: 场景里记录当前 BlockoutManifest 的指纹。细排阶段据此判断现有实时场景
#: 是否可以原样复用；对象名碰巧相同但 manifest 已换代时不能把旧世界当新世界。
BLOCKOUT_MANIFEST_FINGERPRINT_PROP = "bd_blockout_manifest_fingerprint"

#: Blender 默认启动场景的占位对象（无 ``--factory-startup`` 时一定存在）。
#: 默认 Cube 在原点 (0,0,0) 且 1×1×1，正好夹在机位与主体体块之间，会让
#: 可见性 ray_cast 命中占位物而非主体（E_BLOCKOUT_EMPTY_WALL 误报）。
#: 判定从严：对象名与 data 名都等于默认名才清，用户资产不受影响。
_DEFAULT_STARTUP_OBJECTS = {
    "Cube": "Cube",
    "Light": "Light",
    "Camera": "Camera",
}


def _purge_default_startup_objects() -> int:
    """删除 Blender 默认启动三件套（Cube/Light/Camera），返回删除数。

    UI 与 headless（不带 ``--factory-startup``）都会把默认场景带进来；
    体块场景是“整体重来”语义，占位对象不应参与遮挡判定。只删对象名
    与 data 名同时等于默认名的对象，避免误删用户资产。
    """
    removed = 0
    for obj in list(bpy.data.objects):
        expected_data = _DEFAULT_STARTUP_OBJECTS.get(obj.name)
        if expected_data is None:
            continue
        data = getattr(obj, "data", None)
        data_name = str(getattr(data, "name", "") or "")
        if data_name != expected_data:
            continue
        bpy.data.objects.remove(obj, do_unlink=True)
        removed += 1
    if removed:
        purge_orphan_data()
    return removed


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
    rotation = primitive.get("rotation")
    if isinstance(rotation, Mapping):
        obj.rotation_euler = (
            float(rotation.get("x") or 0.0),
            float(rotation.get("y") or 0.0),
            float(rotation.get("z") or 0.0),
        )
    elif isinstance(rotation, (list, tuple)) and len(rotation) >= 3:
        obj.rotation_euler = tuple(float(value) for value in rotation[:3])
    obj.data.materials.append(material)
    route_object(obj, BLOCKOUT_COLLECTION)
    return obj


def _shot_position_origin(
    primitive: Mapping[str, Any],
    position: Mapping[str, Any],
) -> Vector:
    """Convert a manifest position to the object origin for this primitive."""
    size = primitive.get("size") or {}
    dims_z = float(size.get("z") or 0.0)
    foot_z = float(position.get("z") or 0.0)
    return Vector((
        float(position.get("x") or 0.0),
        float(position.get("y") or 0.0),
        foot_z + (dims_z / 2.0
                  if primitive.get("z_anchor") == "foot" else 0.0),
    ))


def _bake_character_shot_positions(
    manifest: Mapping[str, Any],
    scene,
) -> int:
    """Bake each character's resolved shot staging into location keyframes.

    Coarse staging is a per-shot fact. Keeping only one object location would
    make the manifest claim a local revision while Blender continues to render
    the global plan position. Start and end keys pin the same value across the
    shot; the next shot's start key changes only at its own boundary.
    """
    inserted = 0
    previous_frame = int(scene.frame_current)
    try:
        for primitive in manifest.get("primitives") or []:
            if (not isinstance(primitive, Mapping)
                    or primitive.get("kind") != "character"):
                continue
            object_name = f"{BD_BLOCKOUT_PREFIX}{primitive.get('id')}"
            obj = bpy.data.objects.get(object_name)
            if obj is None:
                continue
            rows = sorted(
                (
                    row for row in (primitive.get("shot_positions") or [])
                    if isinstance(row, Mapping)
                    and isinstance(row.get("position"), Mapping)
                ),
                key=lambda row: (
                    int(row.get("start_frame") or 1),
                    str(row.get("shot_id") or ""),
                ),
            )
            for row in rows:
                start = int(row.get("start_frame") or 1)
                end = int(row.get("end_frame") or start)
                if end < start:
                    raise ValueError(
                        f"{object_name}: shot {row.get('shot_id')!r} has "
                        f"end_frame {end} before start_frame {start}")
                obj.location = _shot_position_origin(
                    primitive, row.get("position") or {})
                obj.keyframe_insert(data_path="location", frame=start)
                obj.keyframe_insert(data_path="location", frame=end)
                inserted += 2
    finally:
        scene.frame_set(previous_frame)
        bpy.context.view_layer.update()
    return inserted


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
    #: 目标 Empty 刚写入 location 后必须立即求值。否则带运镜镜头的
    #: ``apply_camera_movement`` 会读到它创建时的旧 matrix_world（通常是
    #: (0, 0, 0)），把错误的 look_at 写进关键帧；真实后果是 dolly_in /
    #: dolly_out 镜头直接拍向地面/墙体，主体 on_screen=0。相机位置的更新
    #: 不能替代目标更新，二者都要在采样前进入 depsgraph。
    bpy.context.view_layer.update()
    track = camera_obj.constraints.new(type="TRACK_TO")
    track.target = target_obj
    track.track_axis = "TRACK_NEGATIVE_Z"
    track.up_axis = "UP_Y"

    movements = camera.get("movements") or []
    for movement in movements:
        shot_start = int(camera.get("start_frame") or 1)
        shot_end = int(camera.get("end_frame") or shot_start)
        try:
            move = movement_spec(
                movement, shot_start=shot_start, shot_end=shot_end)
            curve = movement_curve(movement)
            apply_camera_movement(
                camera_obj, target_obj,
                str(move["type"]),
                float(move["amount"]),
                int(move["start_frame"]),
                int(move["end_frame"]),
                seed=int(move["seed"]),
                curve=curve)
        except ValueError as exc:
            log.warning("%s: 运镜声明无效（%s），已跳过",
                        camera.get("shot_id") or camera_name, exc)
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


def _expected_scene_objects(manifest: Mapping[str, Any]) -> set[str]:
    """返回构建该 manifest 时必须存在的 Blockout 对象名。"""
    expected: set[str] = set()
    seen_assets: set[str] = set()
    for primitive in manifest.get("primitives") or []:
        asset_ref = primitive.get("asset_ref")
        if asset_ref is not None:
            key = str(asset_ref)
            if key in seen_assets:
                continue
            seen_assets.add(key)
        expected.add(f"{BD_BLOCKOUT_PREFIX}{primitive.get('id')}")
    for camera in manifest.get("cameras") or []:
        if camera.get("position") is None:
            continue
        shot_id = str(camera.get("shot_id") or "")
        camera_id = str(camera.get("camera_id") or f"cam_{shot_id}")
        expected.add(f"{BD_BLOCKOUT_PREFIX}{camera_id}")
        expected.add(f"{BD_BLOCKOUT_PREFIX}CamTarget_{shot_id}")
    return expected


def _shot_position_keyframes_match(
    manifest: Mapping[str, Any],
    scene,
) -> bool:
    """Verify every recorded shot-local character placement in the live scene.

    A manifest fingerprint plus object names only proves that an older build
    belonged to this plan, not that it contains the per-shot location keys
    added later.  Reusing such a scene silently renders every shot at the
    object's base location.  User/Agent-owned animation is the explicit
    exception: those edits are intentionally preserved instead of overwritten.
    """
    from ..utils.blender_compat import action_fcurves
    from .scene_sync import is_agent_edited, is_user_animated

    previous_frame = int(scene.frame_current)
    try:
        for primitive in manifest.get("primitives") or []:
            if (not isinstance(primitive, Mapping)
                    or primitive.get("kind") != "character"):
                continue
            rows = [
                row for row in (primitive.get("shot_positions") or [])
                if isinstance(row, Mapping)
                and isinstance(row.get("position"), Mapping)
            ]
            if not rows:
                continue
            object_name = f"{BD_BLOCKOUT_PREFIX}{primitive.get('id')}"
            obj = bpy.data.objects.get(object_name)
            if obj is None:
                return False
            if is_user_animated(obj) or is_agent_edited(obj):
                continue
            action = (
                obj.animation_data.action
                if obj.animation_data and obj.animation_data.action
                else None
            )
            if action is None:
                return False
            curves = {
                int(curve.array_index): curve
                for curve in action_fcurves(action)
                if str(curve.data_path or "") == "location"
            }
            if set(curves) != {0, 1, 2}:
                return False
            keyed_frames = [
                {
                    round(float(point.co[0]), 6)
                    for point in curves[index].keyframe_points
                }
                for index in range(3)
            ]
            for row in rows:
                start = int(row.get("start_frame") or 1)
                end = int(row.get("end_frame") or start)
                expected = _shot_position_origin(
                    primitive, row.get("position") or {})
                for frame in (start, end):
                    rounded_frame = round(float(frame), 6)
                    if any(rounded_frame not in frames
                           for frames in keyed_frames):
                        return False
                    scene.frame_set(frame)
                    bpy.context.view_layer.update()
                    actual = obj.matrix_world.translation
                    if any(abs(float(actual[index]) - expected[index])
                           > 1e-5 for index in range(3)):
                        return False
        return True
    finally:
        scene.frame_set(previous_frame)
        bpy.context.view_layer.update()


@main_thread_only("blockout_scene_is_current")
def blockout_scene_is_current(manifest: Mapping[str, Any], scene=None) -> bool:
    """当前 Blender 场景是否就是这份 manifest 的未换代实时场景。

    指纹相同只证明 manifest 没换；还必须逐个确认本镜头应存在的对象仍在。
    这样 Agent 对变换/关键帧/自定义对象做过改动时仍返回 True（语义就是：
    允许在实时场景上继续审核），而错误 manifest 或无场景时会如实返回 False。
    """
    scene = scene or bpy.context.scene
    stored = str(scene.get(BLOCKOUT_MANIFEST_FINGERPRINT_PROP) or "")
    if not stored or stored != manifest_fingerprint(manifest):
        return False
    expected = _expected_scene_objects(manifest)
    if not expected or not all(
            bpy.data.objects.get(name) is not None for name in expected):
        return False
    return _shot_position_keyframes_match(manifest, scene)


@main_thread_only("ensure_blockout_scene")
def ensure_blockout_scene(manifest: Mapping[str, Any], *,
                          clear_scene: bool = True) -> Dict[str, Any]:
    """复用同一 manifest 的实时场景；缺失或换代时才构建。

    细排必须在粗排已经建好的实时世界上继续。无条件
    ``build_blockout_scene(clear_scene=True)`` 会删掉 Agent 的相机关键帧、
    Agent 追加对象和编辑标记，再拿计划默认值冒充最终交付世界。
    """
    if blockout_scene_is_current(manifest):
        return {
            "reused": True,
            "objects": len(_expected_scene_objects(manifest)),
            "manifest_fingerprint": manifest_fingerprint(manifest),
        }
    summary = dict(build_blockout_scene(
        manifest, clear_scene=clear_scene))
    summary["reused"] = False
    summary["manifest_fingerprint"] = manifest_fingerprint(manifest)
    return summary


@main_thread_only("build_blockout_scene")
def build_blockout_scene(manifest: Mapping[str, Any], *,
                         clear_scene: bool = True) -> Dict[str, Any]:
    """按 BlockoutManifest 建体块场景，返回可验证的构建摘要。

    ``clear_scene=True`` 清掉既有 ``BD_`` 对象（体块场景整体重来，符合
    "粗排重生成"语义）；不动非 BD_ 用户对象。
    """
    if clear_scene:
        clear_blockdirector_objects()
        #: 无 --factory-startup 时默认 Cube/Light/Camera 会留在场景里挡射线；
        #: 体块场景整体重来，占位对象一并清掉（只清默认名组合，不动用户资产）。
        _purge_default_startup_objects()
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

    shot_position_keys = _bake_character_shot_positions(manifest, scene)

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
    scene[BLOCKOUT_MANIFEST_FINGERPRINT_PROP] = manifest_fingerprint(manifest)

    return {
        "objects": placed_primitives + placed_cameras,
        "primitives": placed_primitives,
        "cameras": placed_cameras,
        "markers": markers,
        "skipped_duplicates": skipped_duplicates,
        "shot_position_keys": shot_position_keys,
        "collection": BLOCKOUT_COLLECTION,
        "frame_range": [scene.frame_start, scene.frame_end]
        if frame_starts else None,
    }


__all__ = [
    "BD_BLOCKOUT_PREFIX",
    "BLOCKOUT_COLLECTION",
    "BLOCKOUT_MANIFEST_FINGERPRINT_PROP",
    "blockout_scene_is_current",
    "build_blockout_scene",
    "ensure_blockout_scene",
]
