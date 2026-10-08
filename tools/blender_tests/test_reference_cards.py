"""v1.6 E3（FR-A5）：角色定妆卡 headless 探针。

断言：
* 每角色一张 PNG，落盘路径 = ``reference/characters/<name>.png``，
  ``name`` 与登记表 label 的清洗形一致（含 CJK）；
* 固定机位设计值 3 m / 1.0 m / 50 mm ＋ 1024×1024 / HORIZONTAL / 36 mm，
  并用真实的 ``world_to_camera_view`` 投影证明脚（z=0）、头顶（1.70）与
  标签锚点（2.00）全部落在画面内且四边留 ≥3% 画面高的边距——实测值同时
  与纯层 ``card_ndc_y`` 对拍；
* 标签照生产管线烘焙到卡片相机后，字形包围盒完整落在画面内（≥8 px 边距）；
* 渲染后场景逐项还原：活动相机、分辨率、图像设置、当前帧、全部
  ``hide_render``、标签变换与卡片帧上的临时关键帧都被清掉、临时相机删除。

运行：blender --background --factory-startup --python tools/blender_tests/test_reference_cards.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy  # noqa: E402
from bpy_extras.object_utils import world_to_camera_view  # noqa: E402
from mathutils import Vector  # noqa: E402

from block_director.cinema.anchor import DEFAULT_PROFILE  # noqa: E402
from block_director.contracts.cast import SceneSpec  # noqa: E402
from block_director.contracts.config import AppConfig  # noqa: E402
from block_director.contracts.elements import build_registry  # noqa: E402
from block_director.contracts.plan import Plan  # noqa: E402
from block_director.layer3_engine.character_system.character_factory import (  # noqa: E402
    get_facing,
)
from block_director.layer3_engine.collection_router import (  # noqa: E402
    ensure_collections,
)
from block_director.layer3_engine.label_baking import (  # noqa: E402
    bake_labels,
    collect_label_entries,
)
from block_director.layer3_engine.scene_context import get_context  # noqa: E402
from block_director.layer3_engine.shot_builder import build_scene  # noqa: E402
from block_director.layer8_delivery import reference_cards as rc  # noqa: E402
from block_director.settings import reset_config, set_config  # noqa: E402
from block_director.utils.blender_compat import action_fcurves  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

RESULTS: dict = {}
MARGIN_NDC = 0.03          # 投影证明要求的最小边距（占画面比例）
GLYPH_MARGIN_PX = 8        # 标签字形到画框的最小像素边距


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {"ok": False,
                         "error": f"{type(exc).__name__}: {exc}",
                         "trace": traceback.format_exc(limit=3)}


def _plan() -> Plan:
    return Plan.from_dict({
        "scene_heading": "EXT. 广场 - 日",
        "shots": [{
            "shot_id": "shot_001", "order": 1, "intent": "两人交谈",
            "shot_type": "LS", "duration_frames": 24,
            "characters": ["char_001", "char_002"],
            "actions": [],
        }],
    })


def _build():
    config = AppConfig()
    config.character.label_render = True
    set_config(config)
    plan = _plan()
    spec = SceneSpec.from_plan(plan)
    spec.cast[0].name = "伊恩"
    spec.cast[1].name = "Maya"
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    ensure_collections(scene)
    build_scene(plan, spec, clear_scene=True)
    registry = build_registry(
        plan, cast=[member.to_dict() for member in spec.cast])
    return scene, registry


def _characters():
    context = get_context()
    return context.characters if context is not None else {}


def _is_png(path: Path) -> bool:
    return path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def _scene_fingerprint(scene) -> dict:
    settings = scene.render.image_settings
    return {
        "camera": scene.camera.name if scene.camera is not None else None,
        "engine": scene.render.engine,
        "resolution_x": scene.render.resolution_x,
        "resolution_y": scene.render.resolution_y,
        "resolution_percentage": scene.render.resolution_percentage,
        "filepath": scene.render.filepath,
        "file_format": settings.file_format,
        "color_mode": settings.color_mode,
        "color_depth": settings.color_depth,
        "media_type": getattr(settings, "media_type", None),
        "frame_current": scene.frame_current,
        "frame_start": scene.frame_start,
        "frame_end": scene.frame_end,
    }


def _visibility_map() -> dict:
    return {obj.name: {"hide_render": bool(obj.hide_render),
                       "hide_viewport": bool(obj.hide_viewport)}
            for obj in bpy.data.objects}


def _label_state() -> dict:
    state = {}
    for obj in bpy.data.objects:
        if not obj.name.startswith("BD_Label_"):
            continue
        state[obj.name] = {
            "location": tuple(round(float(v), 6) for v in obj.location),
            "rotation": tuple(round(float(v), 6) for v in obj.rotation_euler),
            "scale": tuple(round(float(v), 6) for v in obj.scale),
        }
    return state


def _marker_map() -> dict:
    return {marker.name: getattr(marker, "camera", None).name
            if getattr(marker, "camera", None) is not None else None
            for marker in bpy.context.scene.timeline_markers}


def _card_keyframes(frame: int) -> list:
    """标签对象在 ``frame`` 上的关键帧（模块恢复后应为空）。"""
    found = []
    for obj in bpy.data.objects:
        if not obj.name.startswith("BD_Label_"):
            continue
        animation = getattr(obj, "animation_data", None)
        action = getattr(animation, "action", None) if animation else None
        if action is None:
            continue
        for fcurve in action_fcurves(action):
            for point in fcurve.keyframe_points:
                if int(round(float(point.co[0]))) == int(frame):
                    found.append(f"{obj.name}.{fcurve.data_path}")
    return found


def _card_camera_names() -> list:
    return [obj.name for obj in bpy.data.objects
            if obj.name.startswith(rc.CARD_CAMERA_NAME)]


def _make_verify_camera(scene, location, look_at):
    camera_data = bpy.data.cameras.new("BD_E3_VerifyCam")
    camera_data.lens = rc.CARD_LENS_MM
    camera_data.sensor_width = rc.CARD_SENSOR_WIDTH_MM
    camera_data.sensor_fit = rc.CARD_SENSOR_FIT
    camera = bpy.data.objects.new("BD_E3_VerifyCam", camera_data)
    scene.collection.objects.link(camera)
    camera.location = tuple(location)
    camera.rotation_euler = (Vector(look_at) - Vector(location)
                             ).to_track_quat("-Z", "Y").to_euler()
    bpy.context.view_layer.update()
    return camera, camera_data


def t_one_card_per_character_with_registry_names():
    scene, registry = _build()
    out_dir = Path(tempfile.mkdtemp(prefix="bd_e3_cards_"))
    character_elements = [element for element in registry.elements
                          if element.kind == "character"]
    expected = {f"{rc.assign_card_names(character_elements)[element.id]}"
                f"{rc.CARD_EXTENSION}"
                for element in character_elements}

    written = rc.render_reference_cards(scene, registry, str(out_dir))
    paths = [Path(path) for path in written]
    actual = {path.name for path in paths}
    under_dir = {path.parent == out_dir / "reference" / "characters"
                 for path in paths}

    ok = (len(paths) == len(character_elements) == 2
          and actual == expected
          and all(under_dir)
          and all(path.exists() for path in paths)
          and all(_is_png(path) for path in paths)
          and all(path.stat().st_size > 500 for path in paths))
    return {"ok": ok, "written": [str(path) for path in paths],
            "expected_names": sorted(expected),
            "actual_names": sorted(actual),
            "sizes": {path.name: path.stat().st_size for path in paths}}


def t_card_pixels_show_character_and_label():
    """渲染出来的像素必须是**这个角色**：身体色 + 头顶白色标签。

    文件存在、命名正确不代表画面对——剪切标记会在 ``frame_set`` / 渲染时把
    ``scene.camera`` 拉回分镜相机（Blender 5.2 实测），错画面照样是合法 PNG。
    这里用像素直方图钉住内容：角色色（红主导）出现在画面中部、白色标签
    出现在上半部。
    """
    scene, registry = _build()
    out_dir = Path(tempfile.mkdtemp(prefix="bd_e3_pixels_"))
    written = rc.render_reference_cards(scene, registry, str(out_dir))
    character_elements = {element.id: element
                          for element in registry.elements
                          if element.kind == "character"}
    names = rc.assign_card_names(
        [character_elements[element_id] for element_id in character_elements])

    results = {}
    ok = True
    for path_text in written:
        path = Path(path_text)
        element_id = next(
            (element_id for element_id, name in names.items()
             if f"{name}{rc.CARD_EXTENSION}" == path.name), "")
        image = bpy.data.images.load(str(path))
        try:
            pixels = [float(value) for value in image.pixels]
            width, height = image.size
            hex_color = character_elements[element_id].color_hex
            expected = (int(hex_color[1:3], 16) / 255.0,
                        int(hex_color[3:5], 16) / 255.0,
                        int(hex_color[5:7], 16) / 255.0)
            dominant = max(range(3), key=lambda index: expected[index])
            others = [index for index in range(3) if index != dominant]
            body_pixels = 0
            stroke_pixels = 0
            for index in range(0, len(pixels), 4):
                red, green, blue = pixels[index:index + 3]
                x = (index // 4) % width
                y = (index // 4) // width
                channels = (red, green, blue)
                if channels[dominant] > 0.45 \
                        and all(channels[dominant] > channels[other] * 1.04
                                for other in others) \
                        and 0.15 * width <= x <= 0.85 * width \
                        and 0.05 * height <= y <= 0.85 * height:
                    body_pixels += 1
                # 白字在 Workbench 影棚光下渲染成 ~0.65 灰，与浅色天空几乎
                # 同色；生产标签的可读性由黑描边保证——顶带里的深色描边
                # 像素就是"标签在画内"的像素证据。
                if red + green + blue < 1.2 \
                        and y >= 0.82 * height \
                        and 0.40 * width <= x <= 0.62 * width:
                    stroke_pixels += 1
            results[element_id] = {"body_pixels": body_pixels,
                                   "label_stroke_pixels": stroke_pixels}
            ok &= body_pixels > 500 and stroke_pixels > 100
        finally:
            bpy.data.images.remove(image)
    return {"ok": ok, "per_card": results,
            "thresholds": {"body_pixels": 500, "label_stroke_pixels": 100}}


def t_fixed_camera_projection_proof():
    scene, registry = _build()
    rc.render_reference_cards(
        scene, registry, str(Path(tempfile.mkdtemp(prefix="bd_e3_proj_"))))
    character = _characters()["char_001"]
    previous_frame = scene.frame_current
    previous_res = (scene.render.resolution_x, scene.render.resolution_y)
    scene.frame_set(1)
    bpy.context.view_layer.update()

    root_pos = character.root.matrix_world.translation.copy()
    facing = get_facing(character)
    location, look_at = rc.card_camera_pose(root_pos, facing)
    camera, camera_data = _make_verify_camera(scene, location, look_at)
    scene.render.resolution_x = scene.render.resolution_y = rc.CARD_RESOLUTION
    try:
        points = {
            "feet": Vector((root_pos.x, root_pos.y, root_pos.z + 0.0)),
            "head_top": Vector((root_pos.x, root_pos.y,
                                root_pos.z + DEFAULT_PROFILE.head_top_z)),
            "label_anchor": character.label_anchor.matrix_world.translation.copy(),
        }
        measured = {}
        inside = True
        for label, point in points.items():
            projected = world_to_camera_view(scene, camera, point)
            measured[label] = {"x": round(float(projected.x), 6),
                               "y": round(float(projected.y), 6)}
            inside &= (MARGIN_NDC <= projected.x <= 1.0 - MARGIN_NDC
                       and MARGIN_NDC <= projected.y <= 1.0 - MARGIN_NDC)
        pure = {
            "feet": rc.card_ndc_y(0.0, aim_height=root_pos.z + rc.CARD_AIM_HEIGHT_M),
            "head_top": rc.card_ndc_y(DEFAULT_PROFILE.head_top_z,
                                      aim_height=root_pos.z + rc.CARD_AIM_HEIGHT_M),
            "label_anchor": rc.card_ndc_y(DEFAULT_PROFILE.label_anchor_z,
                                          aim_height=root_pos.z + rc.CARD_AIM_HEIGHT_M),
        }
        matches_pure = all(
            abs(measured[label]["y"] - pure[label]) < 1e-3 for label in pure)
        constants_ok = (rc.CARD_LENS_MM == 50.0
                        and rc.CARD_DISTANCE_M == 3.0
                        and rc.CARD_HEIGHT_M == 1.0
                        and rc.CARD_SENSOR_WIDTH_MM == 36.0
                        and rc.CARD_SENSOR_FIT == "HORIZONTAL"
                        and rc.CARD_RESOLUTION == 1024)
        frame_height_ok = abs(rc.CARD_FRAME_HEIGHT_M - 2.16) < 1e-9
        return {
            "ok": inside and matches_pure and constants_ok and frame_height_ok,
            "measured_ndc": measured,
            "pure_ndc": {key: round(float(value), 6)
                         for key, value in pure.items()},
            "frame_height_m": rc.CARD_FRAME_HEIGHT_M,
            "margin_ndc": MARGIN_NDC,
            "constants_ok": constants_ok,
        }
    finally:
        scene.render.resolution_x, scene.render.resolution_y = previous_res
        scene.frame_set(previous_frame)
        bpy.data.objects.remove(camera, do_unlink=True)
        if camera_data.name in bpy.data.cameras:
            bpy.data.cameras.remove(camera_data, do_unlink=True)


def t_label_glyph_fully_inside_card_frame():
    scene, _registry = _build()
    character = _characters()["char_001"]
    previous_frame = scene.frame_current
    previous_res = (scene.render.resolution_x, scene.render.resolution_y)
    measure_frame = min(int(scene.frame_start), 1) - 150
    scene.frame_set(measure_frame)
    bpy.context.view_layer.update()

    root_pos = character.root.matrix_world.translation.copy()
    location, look_at = rc.card_camera_pose(root_pos, get_facing(character))
    camera, camera_data = _make_verify_camera(scene, location, look_at)
    scene.render.resolution_x = scene.render.resolution_y = rc.CARD_RESOLUTION

    entries = collect_label_entries([character])
    snapshots = [(obj, tuple(obj.location), tuple(obj.rotation_euler),
                  tuple(obj.scale))
                 for entry in entries
                 for obj in (entry.get("fill"), entry.get("stroke"))
                 if obj is not None]
    #: 与生产模块同款隔离：其它角色的 ``hide_render`` 不挡 ``ray_cast``，
    #: 只有 ``hide_viewport`` 才把它从遮挡射线里摘掉（Blender 5.2 实测）。
    hidden = []
    for other_id, other in _characters().items():
        if other is character:
            continue
        for obj in other.all_objects():
            hidden.append((obj, obj.hide_render, obj.hide_viewport))
            obj.hide_render = True
            obj.hide_viewport = True
    try:
        report = bake_labels(
            scene, entries,
            {"glyph": (measure_frame, measure_frame)},
            {"glyph": camera},
            resolution=(rc.CARD_RESOLUTION, rc.CARD_RESOLUTION))
        scene.frame_set(measure_frame)
        bpy.context.view_layer.update()
        fill = next((entry["fill"] for entry in entries
                     if entry.get("fill") is not None), None)
        if fill is None:
            return {"ok": False, "error": "没有渲染标签可量"}
        matrix = fill.matrix_world
        projected = [world_to_camera_view(scene, camera,
                                          matrix @ Vector(corner))
                     for corner in fill.bound_box]
        xs = [point.x * rc.CARD_RESOLUTION for point in projected]
        ys = [point.y * rc.CARD_RESOLUTION for point in projected]
        inside = (min(xs) >= GLYPH_MARGIN_PX
                  and max(xs) <= rc.CARD_RESOLUTION - GLYPH_MARGIN_PX
                  and min(ys) >= GLYPH_MARGIN_PX
                  and max(ys) <= rc.CARD_RESOLUTION - GLYPH_MARGIN_PX)
        return {"ok": inside and not report.get("unreadable"),
                "bbox_px": [round(min(xs), 2), round(min(ys), 2),
                            round(max(xs), 2), round(max(ys), 2)],
                "glyph_margin_px": GLYPH_MARGIN_PX,
                "unreadable": list(report.get("unreadable") or [])}
    finally:
        for obj, was_render, was_viewport in reversed(hidden):
            obj.hide_render = was_render
            obj.hide_viewport = was_viewport
        for obj, location_v, rotation, scale in snapshots:
            animation = getattr(obj, "animation_data", None)
            action = getattr(animation, "action", None) if animation else None
            if action is not None:
                for fcurve in action_fcurves(action):
                    if fcurve.data_path not in ("location", "rotation_euler",
                                                "scale"):
                        continue
                    for point in list(fcurve.keyframe_points):
                        if int(round(float(point.co[0]))) == int(measure_frame):
                            fcurve.keyframe_points.remove(point, fast=True)
            obj.location = location_v
            obj.rotation_euler = rotation
            obj.scale = scale
        scene.render.resolution_x, scene.render.resolution_y = previous_res
        scene.frame_set(previous_frame)
        bpy.data.objects.remove(camera, do_unlink=True)
        if camera_data.name in bpy.data.cameras:
            bpy.data.cameras.remove(camera_data, do_unlink=True)


def t_scene_settings_and_labels_restored_after_cards():
    scene, registry = _build()
    out_dir = Path(tempfile.mkdtemp(prefix="bd_e3_restore_"))
    card_frame = min(int(scene.frame_start), 1) - rc.CARD_FRAME_OFFSET
    before_fingerprint = _scene_fingerprint(scene)
    before_visibility = _visibility_map()
    before_labels = _label_state()
    before_markers = _marker_map()

    written = rc.render_reference_cards(scene, registry, str(out_dir))

    after_fingerprint = _scene_fingerprint(scene)
    fingerprint_ok = before_fingerprint == after_fingerprint
    hide_ok = before_visibility == _visibility_map()
    labels_ok = before_labels == _label_state()
    markers_ok = before_markers == _marker_map()
    card_keyframes = _card_keyframes(card_frame)
    keyframes_ok = not card_keyframes
    cameras_gone = not _card_camera_names()
    return {"ok": (len(written) == 2 and fingerprint_ok and hide_ok
                   and labels_ok and markers_ok and keyframes_ok
                   and cameras_gone),
            "fingerprint_before": before_fingerprint,
            "fingerprint_after": after_fingerprint,
            "fingerprint_ok": fingerprint_ok,
            "visibility_flags_ok": hide_ok,
            "label_transforms_ok": labels_ok,
            "marker_cameras_ok": markers_ok,
            "leftover_card_keyframes": card_keyframes,
            "card_cameras_left": _card_camera_names()}


def main() -> int:
    capture_main_thread()
    check("one_card_per_character_with_registry_names",
          t_one_card_per_character_with_registry_names)
    check("card_pixels_show_character_and_label",
          t_card_pixels_show_character_and_label)
    check("fixed_camera_projection_proof",
          t_fixed_camera_projection_proof)
    check("label_glyph_fully_inside_card_frame",
          t_label_glyph_fully_inside_card_frame)
    check("scene_settings_and_labels_restored_after_cards",
          t_scene_settings_and_labels_restored_after_cards)
    reset_config()

    passed = [name for name, value in RESULTS.items() if value.get("ok")]
    failed = [name for name, value in RESULTS.items() if not value.get("ok")]
    # ``allow_nan=False``：任何 NaN/Inf 都会让这行抛错而不是写出非法 JSON。
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS},
        ensure_ascii=False, allow_nan=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
