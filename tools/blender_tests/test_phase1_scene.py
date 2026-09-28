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


def main() -> int:
    capture_main_thread()
    check("character_geometry", t_character_geometry)
    check("collection_routing", t_collection_routing)
    check("render_clean_and_visible", t_render_clean_and_visible)
    check("transaction_rollback", t_transaction_rollback)
    check("environment", t_environment)

    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS}, ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
