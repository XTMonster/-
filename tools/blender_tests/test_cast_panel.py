"""§13.1 角色管理（列表 / 颜色 / 添加 / 删除）的集成测试。

运行：
  blender --background --factory-startup --python tools/blender_tests/test_cast_panel.py
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy  # noqa: E402

from _fixtures import two_shot_plan  # noqa: E402
from block_director.contracts.cast import SceneSpec  # noqa: E402
from block_director.layer2_sdl import build_sdl, validate_sdl  # noqa: E402
from block_director.layer3_engine.cast_editor import (  # noqa: E402
    CastError,
    add_cast_member,
    apply_cast_color,
    list_cast,
    remove_cast_member,
)
from block_director.layer3_engine.collection_router import ensure_collections  # noqa: E402
from block_director.layer3_engine.scene_context import get_context  # noqa: E402
from block_director.layer3_engine.shot_builder import build_scene  # noqa: E402
from block_director.utils.geometry import hex_to_rgb  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

RESULTS: dict = {}


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                         "trace": traceback.format_exc(limit=3)}


def fresh_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    ensure_collections(scene)
    return scene


def built():
    fresh_scene()
    plan = two_shot_plan(with_actions=False)
    spec = SceneSpec.from_plan(plan)
    build_scene(plan, spec, clear_scene=True)
    return plan, spec


# --------------------------------------------------------------------------- #
# 1. 列表反映真实场景，而且基于 SceneContext.spec（不是重新推导）
# --------------------------------------------------------------------------- #
def t_list_shows_the_built_cast():
    _plan, spec = built()
    rows = list_cast()
    context = get_context()
    return {"ok": ([row["id"] for row in rows] == [m.id for m in spec.cast]
                   and all(row["in_scene"] for row in rows)
                   and context.spec is not None
                   and [m.id for m in context.spec.cast] == [m.id for m in spec.cast]),
            "rows": rows}


# --------------------------------------------------------------------------- #
# 2. 改颜色：材质与场景设定一起改，并且能落到 SDL
# --------------------------------------------------------------------------- #
def t_color_change_reaches_the_material_and_the_sdl():
    plan, _spec = built()
    context = get_context()
    result = apply_cast_color("char_001", "#123456")
    material = bpy.data.materials.get("BD_Mat_char_001")
    expected = hex_to_rgb("#123456")
    diffuse = tuple(round(v, 3) for v in material.diffuse_color[:3]) \
        if material else ()
    sdl = build_sdl(plan, spec=context.spec)
    member = next(m for m in sdl.characters if m.id == "char_001")
    return {"ok": (result["ok"] and material is not None
                   and diffuse == tuple(round(v, 3) for v in expected)
                   and member.color == "#123456"
                   and validate_sdl(sdl) == []
                   and list_cast()[0]["color"] == "#123456"),
            "diffuse": diffuse, "expected": [round(v, 3) for v in expected],
            "sdl_color": member.color}


# --------------------------------------------------------------------------- #
# 3. 添加角色：建对象 + 写进设定 + 下一个 id 不冲突
# --------------------------------------------------------------------------- #
def t_add_creates_a_real_character():
    _plan, _spec = built()
    context = get_context()
    before = len(context.characters)
    row = add_cast_member("老陈", color="#8AB4F8", position=(1.5, 0.0, 0.0))
    character = context.character(row["character_id"])
    roots = [obj for obj in bpy.data.objects
             if obj.name == f"BD_Char_老陈_Root"]
    return {"ok": (row["character_id"] == "char_003"
                   and character is not None and len(roots) == 1
                   and len(context.characters) == before + 1
                   and any(m.id == "char_003" for m in context.spec.cast)
                   and abs(character.root.location.x - 1.5) < 1e-6
                   and len(list_cast()) == 3),
            "row": row, "characters": sorted(context.characters),
            "cast": [m.id for m in context.spec.cast]}


# --------------------------------------------------------------------------- #
# 4. 删除角色：真的删对象；被镜头引用时拒绝
# --------------------------------------------------------------------------- #
def t_remove_deletes_objects_but_refuses_referenced_characters():
    _plan, _spec = built()
    context = get_context()
    guarded = None
    try:
        remove_cast_member("char_001")          # 两个镜头都引用了它
    except CastError as exc:
        guarded = str(exc)

    orphan = add_cast_member("路人甲")          # 没有任何镜头引用
    objects_before = len(bpy.data.objects)
    result = remove_cast_member(orphan["character_id"])
    return {"ok": (guarded is not None and "shot_001" in guarded
                   and result["removed_objects"] > 0
                   and len(bpy.data.objects) < objects_before
                   and orphan["character_id"] not in context.characters
                   and all(m.id != orphan["character_id"]
                           for m in context.spec.cast)),
            "guarded": guarded, "removed": result,
            "objects": [objects_before, len(bpy.data.objects)]}


# --------------------------------------------------------------------------- #
# 5. 面板注册/注销干净（含列表属性与 UIList）
# --------------------------------------------------------------------------- #
def t_cast_panel_registers_cleanly():
    import block_director
    from block_director.layer7_ui import panel_cast

    block_director.register()
    try:
        modules = list(block_director.registration._registered)
        registered = ("block_director.layer7_ui.panel_cast" in modules
                      and hasattr(bpy.types, "BLOCKDIRECTOR_PT_cast")
                      and hasattr(bpy.types, "BLOCKDIRECTOR_UL_cast")
                      and hasattr(bpy.types.Scene, "bd_cast")
                      and hasattr(bpy.types.Scene, "bd_cast_index"))
        build_count = panel_cast.sync_cast_properties(bpy.context.scene) \
            if get_context() is not None else 0
    finally:
        block_director.unregister()
    return {"ok": registered
            and not hasattr(bpy.types, "BLOCKDIRECTOR_PT_cast")
            and not hasattr(bpy.types.Scene, "bd_cast"),
            "registered": registered, "sync_count": build_count,
            "modules": list(modules)}


def main() -> int:
    capture_main_thread()
    import block_director

    check("list_shows_the_built_cast", t_list_shows_the_built_cast)
    check("color_change_reaches_the_material_and_the_sdl",
          t_color_change_reaches_the_material_and_the_sdl)
    check("add_creates_a_real_character", t_add_creates_a_real_character)
    check("remove_deletes_objects_but_refuses_referenced_characters",
          t_remove_deletes_objects_but_refuses_referenced_characters)
    check("cast_panel_registers_cleanly", t_cast_panel_registers_cleanly)

    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS}, ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
