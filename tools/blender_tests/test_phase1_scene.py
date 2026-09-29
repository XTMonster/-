"""Phase 1 集成测试：在真实 Blender 内构建白模场景并验证（执行文档 v1.2 §9 / §8）。

运行：
  blender --background --factory-startup --python tools/blender_tests/test_phase1_scene.py
输出：一行 ``BD_TEST_RESULT {json}``；退出码 0 = 全通过。
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402

from block_director.layer3_engine.character_system import (  # noqa: E402
    EXPECTED_TOTAL_HEIGHT,
    PIVOT_Z,
    create_character,
    create_label,
    measure_height,
)
from block_director.layer3_engine.cinema_engine import create_camera  # noqa: E402
from block_director.layer3_engine.collection_router import (  # noqa: E402
    CONTENT_COLLECTION,
    GUIDES_COLLECTION,
    audit_renderable_objects,
    ensure_collections,
    objects_in_collection,
)
from block_director.layer3_engine.scene_executor import build_environment  # noqa: E402
from block_director.layer3_engine.transaction import Transaction  # noqa: E402
from block_director.utils.geometry import hex_to_rgb  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

RESULTS: dict = {}
OUTDIR = ROOT / "tools" / "_probe_out"


def fresh_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 160
    scene.render.resolution_y = 90
    scene.render.resolution_percentage = 100
    scene.render.image_settings.media_type = "IMAGE"
    scene.render.image_settings.file_format = "PNG"
    display = getattr(scene, "display", None)
    if display is not None:
        display.shading.light = "FLAT"
        display.shading.color_type = "MATERIAL"
        display.shading.background_type = "VIEWPORT"
        display.shading.background_color = (0.05, 0.05, 0.06)
    if scene.world is None:
        scene.world = bpy.data.worlds.new("BD_World")
    scene.world.color = (0.05, 0.05, 0.06)
    ensure_collections(scene)
    return scene


def render_luma(name: str) -> float:
    scene = bpy.context.scene
    os.makedirs(OUTDIR, exist_ok=True)
    path = str(OUTDIR / f"phase1_{name}.png")
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    if not os.path.exists(path):
        return -1.0
    image = bpy.data.images.load(path)
    try:
        pixels = list(image.pixels)
    finally:
        bpy.data.images.remove(image)
    rgb = [v for i, v in enumerate(pixels) if i % 4 != 3]
    return round(sum(rgb) / max(len(rgb), 1), 5)


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                         "trace": traceback.format_exc(limit=3)}


# --------------------------------------------------------------------------- #
# 1. 角色几何严格符合 §9.1
# --------------------------------------------------------------------------- #
def t_character_geometry():
    fresh_scene()
    character = create_character("char_001", "小明", "#FF6B6B",
                                 location=(0.0, 0.0, 0.0))
    bpy.context.view_layer.update()

    world_z = {
        "root": round(character.root.matrix_world.translation.z, 4),
        "body_pivot": round(character.body_pivot.matrix_world.translation.z, 4),
        "head_pivot": round(character.head_pivot.matrix_world.translation.z, 4),
        "label_anchor": round(character.label_anchor.matrix_world.translation.z, 4),
        "leg_L": round(character.leg_pivots[0].matrix_world.translation.z, 4),
    }
    expected = {"root": 0.0, "body_pivot": PIVOT_Z["body"],
                "head_pivot": PIVOT_Z["head"],
                "label_anchor": PIVOT_Z["label"], "leg_L": PIVOT_Z["leg"]}
    height = measure_height(character.root)

    pivot_ok = all(abs(world_z[k] - expected[k]) < 1e-3 for k in expected)
    height_ok = abs(height - EXPECTED_TOTAL_HEIGHT) < 0.02
    return {"ok": pivot_ok and height_ok, "height": height,
            "expected_height": EXPECTED_TOTAL_HEIGHT, "world_z": world_z,
            "pivots_ok": pivot_ok}


# --------------------------------------------------------------------------- #
# 2. 集合路由：内容进 Content，标签进 Guides 且不参与渲染
# --------------------------------------------------------------------------- #
def t_collection_routing():
    fresh_scene()
    character = create_character("char_001", "小明", "#FF6B6B")
    label = create_label(character, "小明")

    content_names = {o.name for o in objects_in_collection(CONTENT_COLLECTION)}
    guide_names = {o.name for o in objects_in_collection(GUIDES_COLLECTION)}
    mesh_names = {o.name for o in character.meshes}

    meshes_in_content = mesh_names <= content_names
    label_in_guides = label.name in guide_names
    label_hidden = bool(label.hide_render)
    return {"ok": meshes_in_content and label_in_guides and label_hidden,
            "meshes_in_content": meshes_in_content,
            "label_in_guides": label_in_guides,
            "label_hide_render": label_hidden,
            "label_text": label.data.body}


# --------------------------------------------------------------------------- #
# 3. 渲染：白模可见，且辅助物不入画（含正对照）
# --------------------------------------------------------------------------- #
def t_render_clean_and_visible():
    fresh_scene()
    build_environment(ground_size=(20.0, 20.0), lighting="clay_studio")
    left = create_character("char_001", "小明", "#FF6B6B", location=(-0.8, 0, 0))
    right = create_character("char_002", "小红", "#6BC5FF", location=(0.8, 0, 0))
    create_label(left, "小明")
    create_label(right, "小红")
    create_camera("shot_001", (0.0, -6.0, 1.2), look_at=(0.0, 0.0, 0.9), lens=50.0)

    audit_before = audit_renderable_objects()
    luma_with = render_luma("with_characters")

    # 正对照：把角色网格排除出渲染，亮度必须下降
    for character in (left, right):
        for obj in character.meshes:
            obj.hide_render = True
    luma_without = render_luma("without_characters")

    # 泄漏检测：把标签放出来，审计必须报出来
    for character in (left, right):
        for obj in bpy.data.objects:
            if obj.name.startswith("BD_Char_") and obj.type == 'FONT':
                obj.hide_render = False
    audit_leak = audit_renderable_objects()

    ok = (audit_before == [] and luma_with > 0.10
          and luma_with - luma_without > 0.02 and len(audit_leak) >= 2)
    return {"ok": ok, "audit_before": audit_before,
            "luma_with_characters": luma_with,
            "luma_without_characters": luma_without,
            "audit_leak_detected": audit_leak}


# --------------------------------------------------------------------------- #
# 4. 事务回滚 + 孤儿数据回收（§8.1）
# --------------------------------------------------------------------------- #
def t_transaction_rollback():
    fresh_scene()
    before_objects = len(bpy.data.objects)
    before_meshes = len(bpy.data.meshes)
    try:
        with Transaction("unit"):
            bpy.ops.mesh.primitive_cube_add()
            bpy.context.object.name = "BD_TX_Test"
            raise RuntimeError("intentional failure")
    except RuntimeError:
        pass
    after_objects = len(bpy.data.objects)
    after_meshes = len(bpy.data.meshes)
    return {"ok": after_objects == before_objects and after_meshes == before_meshes,
            "objects": [before_objects, after_objects],
            "meshes": [before_meshes, after_meshes]}


# --------------------------------------------------------------------------- #
# 5. 环境搭建（地面/墙体/道具/灯光）
# --------------------------------------------------------------------------- #
def t_environment():
    scene = fresh_scene()
    environment = build_environment(
        ground_size=(12.0, 12.0),
        walls=[{"position": (0.0, -6.0, 1.5), "size": (12.0, 0.2, 3.0)}],
        props=[{"id": "table_01", "position": (0.0, 0.0, 0.4)}],
        lighting="clay_studio",
    )
    content = {o.name for o in objects_in_collection(CONTENT_COLLECTION)}
    objects = environment.all_objects()
    all_in_content = all(o.name in content for o in objects)
    lights_have_energy = all(light.data.energy > 0 for light in environment.lights)
    return {"ok": all_in_content and lights_have_energy and len(environment.lights) == 2,
            "counts": {"ground": 1 if environment.ground else 0,
                       "walls": len(environment.walls),
                       "props": len(environment.props),
                       "lights": len(environment.lights)},
            "all_in_content": all_in_content,
            "scene_camera": scene.camera.name if scene.camera else None}


# --------------------------------------------------------------------------- #
# 6. 尺寸必须与请求一致（曾把地面缩成一半，导致地面远边缘入画）
# --------------------------------------------------------------------------- #
def t_environment_sizes():
    fresh_scene()
    environment = build_environment(
        ground_size=(30.0, 24.0),
        walls=[{"position": (0.0, -6.0, 1.5), "size": (12.0, 2.0, 3.0)}],
        props=[{"id": "table_01", "position": (0.0, 0.0, 0.4),
                "size": (2.0, 1.0, 0.8)}],
        lighting="clay_studio",
    )
    bpy.context.view_layer.update()

    def dimensions(obj):
        return tuple(round(v, 3) for v in obj.dimensions)

    ground = dimensions(environment.ground)
    wall = dimensions(environment.walls[0])
    prop = dimensions(environment.props[0])
    ok = (ground[0] == 30.0 and ground[1] == 24.0
          and wall == (12.0, 2.0, 3.0)
          and prop == (2.0, 1.0, 0.8))
    return {"ok": ok, "ground": ground, "wall": wall, "prop": prop}


# --------------------------------------------------------------------------- #
# 7. 非本插件对象必须被审计抓出来（Phase 6 被默认 Cube 坑过）
# --------------------------------------------------------------------------- #
def t_prop_color_and_rotation_are_applied():
    """v1.3 P0-7：``build_environment`` 曾经把 color / rotation 直接丢掉。

    实测后果：SDL 里声明的摊位颜色（#B98C5A）渲染出来全是默认灰。
    """
    fresh_scene()
    environment = build_environment(
        ground_size=(20.0, 20.0), walls=[],
        props=[{"id": "tent", "position": (1.0, 2.0, 0.5),
                "size": (3.0, 1.0, 1.0), "color": "#B98C5A",
                "rotation": (0.0, 0.0, 0.5)}],
        lighting="clay_studio",
    )
    prop = environment.props[0]
    material = prop.data.materials[0]
    got = tuple(round(float(v), 3) for v in material.diffuse_color[:3])
    want = tuple(round(float(v), 3) for v in hex_to_rgb("#B98C5A"))
    return {"ok": got == want and abs(float(prop.rotation_euler[2]) - 0.5) < 1e-6,
            "color": got, "expected": want,
            "rotation": round(float(prop.rotation_euler[2]), 4)}


# --------------------------------------------------------------------------- #
# 8. 标签必须真的吃配置（v1.3 P0-11）
# --------------------------------------------------------------------------- #
def t_eyes_use_a_separate_dark_material():
    """v1.3 诉求 1：眼睛必须与身体**分材质**，且是深色。

    v1.2 的 ``create_character`` 把身体材质直接挂到眼睛上，
    于是眼睛与身体同色，看上去像没有五官。
    """
    fresh_scene()
    character = create_character("char_001", "小明", "#FF6B6B",
                                 (0.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    eye = character.parts["eye_l"]
    body = character.parts["body"]
    eye_material = eye.data.materials[0]
    body_material = body.data.materials[0]
    eye_rgb = tuple(round(float(v), 3) for v in eye_material.diffuse_color[:3])
    body_rgb = tuple(round(float(v), 3) for v in body_material.diffuse_color[:3])
    dark = sum(eye_rgb) / 3.0 < 0.2

    # 改身体颜色不得波及眼睛
    from block_director.layer3_engine.character_system import (
        set_character_color,
    )
    set_character_color(character, "#00FF00")
    after_rgb = tuple(round(float(v), 3)
                      for v in eye.data.materials[0].diffuse_color[:3])
    return {"ok": (eye_material is not body_material and dark
                   and eye_rgb != body_rgb and after_rgb == eye_rgb),
            "eye": eye_rgb, "body": body_rgb, "after_body_recolour": after_rgb,
            "same_material": eye_material is body_material}


def t_label_config_is_wired():
    """``character.label_font_path`` / ``ui.show_labels`` 在 v1.2 里是死配置。

    v1.2 定义了它们、启动时还会提示"未指定中文字体"，但 ``build_scene``
    从来没有把值传给 ``create_label``——用户按提示配了路径也无效。
    """
    from block_director.contracts.cast import SceneSpec
    from block_director.layer3_engine.shot_builder import build_scene
    from block_director.settings import get_config

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _fixtures import two_shot_plan

    font_path = r"C:\Windows\Fonts\msyh.ttc"
    if not os.path.exists(font_path):
        return {"ok": True, "skipped": "系统无 msyh.ttc"}

    config = get_config()
    original_font = config.character.label_font_path
    original_show = config.ui.show_labels
    original_render = config.character.label_render
    try:
        config.character.label_font_path = font_path
        config.ui.show_labels = False
        # v1.3 起标签默认走"渲染可见"（BlockDirector/Labels）。这一条测的是
        # Guides 标签的字体/视口接线，所以显式关掉渲染标签这条新路径。
        config.character.label_render = False
        fresh_scene()
        plan = two_shot_plan()
        build_scene(plan, SceneSpec.from_plan(plan), clear_scene=True)
        labels = [o for o in bpy.data.objects
                  if o.type == "FONT" and o.name.endswith("_Label")]
        loaded = []
        for obj in labels:
            font = getattr(obj.data, "font", None)
            path = str(getattr(font, "filepath", "") or "")
            if path and os.path.exists(path) and os.path.samefile(path, font_path):
                loaded.append(obj)
        hidden = [o for o in labels if o.hide_viewport]
        return {"ok": bool(labels) and len(loaded) == len(labels)
                and len(hidden) == len(labels),
                "labels": len(labels), "with_font": len(loaded),
                "hidden_in_viewport": len(hidden)}
    finally:
        config.character.label_font_path = original_font
        config.ui.show_labels = original_show
        config.character.label_render = original_render


def t_foreign_object_is_flagged():
    fresh_scene()
    bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0.0, 0.0, 0.0))
    cube = bpy.context.object          # 默认名字 "Cube"，不是 BD_ 前缀
    leaks = audit_renderable_objects()
    cube.hide_render = True
    clean_after_hiding = audit_renderable_objects()
    return {"ok": cube.name in leaks and clean_after_hiding == [],
            "cube": cube.name, "leaks": leaks,
            "after_hiding": clean_after_hiding}


def t_clear_scene_removes_default_cube():
    """复现 Phase 6 的缺陷：启动场景自带的 Cube 会被渲进参考视频。"""
    from block_director.layer3_engine.shot_builder import build_scene
    from block_director.contracts.plan import Plan

    bpy.ops.wm.read_factory_settings(use_empty=False)   # 带默认 Cube/Camera/Light
    ensure_collections(bpy.context.scene)
    had_cube = bpy.data.objects.get("Cube") is not None

    plan = Plan.from_dict({"shots": [{
        "shot_id": "shot_001", "order": 1, "intent": "x", "shot_type": "MS",
        "duration_frames": 24, "characters": ["char_001"]}]})
    build_scene(plan, clear_scene=True)

    cube_gone = bpy.data.objects.get("Cube") is None
    leaks = audit_renderable_objects()
    return {"ok": had_cube and cube_gone and leaks == [],
            "had_default_cube": had_cube, "cube_removed": cube_gone,
            "leaks": leaks}


def main() -> int:
    capture_main_thread()
    check("character_geometry", t_character_geometry)
    check("collection_routing", t_collection_routing)
    check("render_clean_and_visible", t_render_clean_and_visible)
    check("transaction_rollback", t_transaction_rollback)
    check("environment", t_environment)
    check("environment_sizes", t_environment_sizes)
    check("prop_color_and_rotation_are_applied",
          t_prop_color_and_rotation_are_applied)
    check("eyes_use_a_separate_dark_material",
          t_eyes_use_a_separate_dark_material)
    check("label_config_is_wired", t_label_config_is_wired)
    check("foreign_object_is_flagged", t_foreign_object_is_flagged)
    check("clear_scene_removes_default_cube", t_clear_scene_removes_default_cube)

    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS}, ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
