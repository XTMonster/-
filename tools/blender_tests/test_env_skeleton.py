"""v1.6 C2（FR-A1 / D-10）：环境最小骨架与闭集映射表在真实 Blender 里成立。

纯层（``tests/test_env_anchors.py``）只能证明表算得对；这里验四件必须开
Blender 才能验的事：

1. 骨架三件套（地面 + 四周遮挡体 + 天空底色）每次构建都在、命名 ``BD_ENV_*``、
   进 Content 集合、``hide_render=False``，且不泄漏进参考视频（导出审计放行）；
2. ``brief.environment[]`` 条目按映射表**确定性**落坐标与尺寸；
3. 闭集外取值报 ``E_ENV_001`` finding（与 unresolved_anchor 同一审计通路），
   **不建对象、不静默跳过、不猜坐标**；
4. far 落点超出 ``config.scene.extent_m`` 时照表落位 ＋ ``environment_extent``
   告警（不夹取）。

运行：
  blender --background --factory-startup --python tools/blender_tests/test_env_skeleton.py
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402

from block_director.layer3_engine.collection_router import (  # noqa: E402
    CONTENT_COLLECTION,
    audit_renderable_objects,
    ensure_collections,
)
from block_director.layer3_engine.scene_executor import (  # noqa: E402
    ENVIRONMENT_OFFSETS,
    ENVIRONMENT_SKY_COLOR,
    build_environment,
)
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

RESULTS: dict = {}

#: 两条合法条目（above + right）+ 一条方位闭集外的（"画面后方" 不是闭集词）。
VALID_ITEMS = [
    {"label": "拱廊拱顶", "direction": "above", "distance": "near",
     "size": "l", "mood": "蓝绿色铸钢雕花铁艺"},
    {"label": "糖果摊位", "direction": "right", "distance": "near",
     "size": "m", "mood": ""},
]
INVALID_ITEM = {"label": "远处海面", "direction": "画面后方",
                "distance": "far", "size": "l", "mood": ""}
FAR_ITEM = {"label": "海雾尽头", "direction": "back", "distance": "far",
            "size": "l", "mood": ""}


def fresh_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    ensure_collections(scene)
    return scene


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                         "trace": traceback.format_exc(limit=3)}


def _built(extent_m=12.0, items=VALID_ITEMS):
    fresh_scene()
    environment = build_environment(
        environment_items=[dict(item) for item in items],
        extent_m=float(extent_m))
    return environment


def _in_content(obj) -> bool:
    return any(collection.name == CONTENT_COLLECTION
               for collection in obj.users_collection)


def _round_vector(vector) -> tuple:
    return tuple(round(float(value), 4) for value in vector)


def t_skeleton_three_pieces_exist_in_content_and_render():
    environment = _built()
    ground = environment.ground
    occluders = environment.occluders
    names = [obj.name for obj in occluders]
    in_content = (ground is not None and ground.name == "BD_ENV_Ground"
                  and all(_in_content(obj) for obj in [ground, *occluders]))
    renders = all(not obj.hide_render for obj in [ground, *occluders])
    static = all(obj.animation_data is None for obj in [ground, *occluders])
    expected = ["BD_ENV_Occluder_N", "BD_ENV_Occluder_S",
                "BD_ENV_Occluder_E", "BD_ENV_Occluder_W"]
    return {"ok": (in_content and renders and static
                   and sorted(names) == sorted(expected)),
            "ground": ground.name if ground is not None else None,
            "occluders": sorted(names),
            "in_content": in_content, "hide_render": not renders,
            "static": static}


def t_sky_background_colour_is_set_deterministically():
    environment = _built()
    scene = bpy.context.scene
    sky = environment.sky
    world = scene.world
    colour = tuple(round(float(value), 6) for value in world.color)
    expected = tuple(round(float(value), 6) for value in ENVIRONMENT_SKY_COLOR)
    return {"ok": (sky is not None and sky is world and colour == expected
                   and world.name == "BD_ENV_Sky"),
            "world": world.name if world is not None else None,
            "color": colour, "expected": expected}


def t_skeleton_does_not_leak_into_the_reference_video():
    environment = _built()
    _ = environment
    problems = audit_renderable_objects()
    return {"ok": problems == [], "problems": problems}


def t_environment_items_land_at_the_table_positions():
    environment = _built()
    objects = {obj.name: obj for obj in environment.pieces}
    vault = objects.get("BD_ENV_above_1")
    booth = objects.get("BD_ENV_right_1")
    vault_pos = _round_vector(vault.location) if vault is not None else None
    booth_pos = _round_vector(booth.location) if booth is not None else None
    vault_scale = (_round_vector(vault.scale) if vault is not None else None)
    booth_scale = (_round_vector(booth.scale) if booth is not None else None)
    in_content = all(_in_content(obj) for obj in environment.pieces)
    ok = (vault_pos == _round_vector(ENVIRONMENT_OFFSETS[("above", "near")])
          and booth_pos == _round_vector(ENVIRONMENT_OFFSETS[("right", "near")])
          and vault_scale == (6.0, 6.0, 4.0)
          and booth_scale == (2.5, 2.5, 2.5)
          and in_content
          and all(not obj.hide_render for obj in environment.pieces)
          and all(obj.get("bd_element_type") == "environment"
                  for obj in environment.pieces))
    return {"ok": ok, "vault": vault_pos, "booth": booth_pos,
            "vault_scale": vault_scale, "booth_scale": booth_scale,
            "names": sorted(objects), "in_content": in_content}


def t_invalid_item_is_reported_and_never_silently_dropped():
    environment = _built(items=VALID_ITEMS + [INVALID_ITEM])
    lines = [line for line in environment.unresolved_anchors
             if line.startswith("E_ENV_001:")]
    built = {obj.name for obj in environment.pieces}
    report = next((line for line in lines if "远处海面" in line), "")
    ok = (len(lines) == 1
          and report.startswith("E_ENV_001: 远处海面:")
          and "direction" in report and "画面后方" in report
          and all("海面" not in name for name in built))
    return {"ok": ok, "finding": report, "lines": lines, "built": sorted(built)}


def t_far_item_beyond_extent_is_reported_but_not_clamped():
    environment = _built(items=[FAR_ITEM], extent_m=12.0)
    piece = next((obj for obj in environment.pieces
                  if obj.name == "BD_ENV_back_1"), None)
    placed = (_round_vector(piece.location) if piece is not None else None)
    table = _round_vector(ENVIRONMENT_OFFSETS[("back", "far")])
    notes = [line for line in environment.unresolved_anchors
             if line.startswith("environment_extent:")]
    ok = (placed == table and len(notes) == 1
          and "海雾尽头" in notes[0] and "未夹取" in notes[0])
    return {"ok": ok, "placed": placed, "table": table, "note": notes}


def t_build_is_deterministic():
    first = _built()

    def fingerprint(environment) -> dict:
        entries = []
        for obj in environment.all_objects():
            entries.append((obj.name, _round_vector(obj.location),
                            _round_vector(obj.scale)))
        return {"objects": sorted(entries),
                "findings": sorted(environment.unresolved_anchors)}

    before = fingerprint(first)
    second = _built()
    after = fingerprint(second)
    return {"ok": before == after, "before": before, "after": after}


def main() -> int:
    capture_main_thread()
    check("skeleton_three_pieces_exist_in_content_and_render",
          t_skeleton_three_pieces_exist_in_content_and_render)
    check("sky_background_colour_is_set_deterministically",
          t_sky_background_colour_is_set_deterministically)
    check("skeleton_does_not_leak_into_the_reference_video",
          t_skeleton_does_not_leak_into_the_reference_video)
    check("environment_items_land_at_the_table_positions",
          t_environment_items_land_at_the_table_positions)
    check("invalid_item_is_reported_and_never_silently_dropped",
          t_invalid_item_is_reported_and_never_silently_dropped)
    check("far_item_beyond_extent_is_reported_but_not_clamped",
          t_far_item_beyond_extent_is_reported_but_not_clamped)
    check("build_is_deterministic", t_build_is_deterministic)

    passed = [key for key, value in RESULTS.items() if value.get("ok")]
    failed = [key for key, value in RESULTS.items() if not value.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS},
        ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
