"""v1.5 P3-T2：场级锚点在 Blender 里落成 empty、且**不泄漏进参考视频**。

纯 Python 那边（`tests/test_staging_anchors.py`）只能证明坐标算得对；这里证明
三件必须开 Blender 才能验的事：

1. 锚点真的被建成 ``BD_Anchor_*`` empty，坐标 = 求解器的结果；
2. 它们进 Guides 集合 ＋ ``hide_render=True``；
3. **导出前的审计不把它们算成"会入画的 helper"**——否则参考视频会被拒导出；
4. 解析不出的锚点进 ``summary.warnings``（审计），且仍被放到缺省位。

运行：
  blender --background --factory-startup --python tools/blender_tests/test_anchor_staging.py
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
from block_director.layer3_engine.collection_router import (  # noqa: E402
    GUIDES_COLLECTION,
    audit_renderable_objects,
    ensure_collections,
)
from block_director.layer3_engine.shot_builder import build_scene  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

RESULTS: dict = {}

#: 一条能解的（乙 背后的门）、一条显式坐标（窗）、一条解不出的（"靠近他"）。
ANCHORS = [
    {"name": "door", "depth": "bg", "relation": "behind char_002"},
    {"name": "window", "depth": "fg", "position": [3.0, -1.0, 1.2]},
    {"name": "vague", "depth": "mid", "relation": "靠近他"},
]


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


def _built():
    fresh_scene()
    plan = two_shot_plan()
    plan.environment = {"anchors": [dict(item) for item in ANCHORS],
                        "light": {}}
    spec = SceneSpec.from_plan(plan)
    summary = build_scene(plan, spec, clear_scene=True)
    return plan, spec, summary


def t_anchors_become_empties_with_the_solved_positions():
    _plan, spec, _summary = _built()
    objects = {obj.name: obj for obj in bpy.data.objects
               if obj.name.startswith("BD_Anchor_")}
    second = next(member for member in spec.cast if member.id == "char_002")
    facing = second.initial_facing
    # 乙 的朝向是 (-1, 0, 0) ⇒ 背后是 +X：中点 + 2.0 m
    expected_door = (round(second.initial_location[0] + 2.0, 4),
                     round(second.initial_location[1], 4),
                     round(second.initial_location[2], 4))
    door = tuple(round(value, 4) for value in objects["BD_Anchor_door"].location)
    window = tuple(round(value, 4)
                   for value in objects["BD_Anchor_window"].location)
    vague = tuple(round(value, 4)
                  for value in objects["BD_Anchor_vague"].location)
    return {"ok": (sorted(objects) == ["BD_Anchor_door", "BD_Anchor_vague",
                                       "BD_Anchor_window"]
                   and door == expected_door
                   and window == (3.0, -1.0, 1.2)
                   and all(obj.type == "EMPTY" for obj in objects.values())
                   and round(abs(facing[0]), 4) == 1.0),
            "door": door, "expected_door": expected_door, "window": window,
            "vague": vague, "names": sorted(objects)}


def t_anchors_are_guides_and_do_not_render():
    _plan, _spec, _summary = _built()
    objects = [obj for obj in bpy.data.objects
               if obj.name.startswith("BD_Anchor_")]
    in_guides = all(any(collection.name == GUIDES_COLLECTION
                        for collection in obj.users_collection)
                    for obj in objects)
    hidden = all(obj.hide_render for obj in objects)
    guides = bpy.data.collections.get(GUIDES_COLLECTION)
    return {"ok": (len(objects) == 3 and in_guides and hidden
                   and guides is not None and guides.hide_render),
            "count": len(objects), "in_guides": in_guides,
            "hide_render": hidden}


def t_the_export_audit_does_not_flag_anchors():
    """导出前的审计必须放行锚点；否则"helper 泄漏"检查会拒掉整个导出。"""
    _plan, _spec, _summary = _built()
    problems = audit_renderable_objects()
    leaked = [name for name in problems if "Anchor" in name]
    return {"ok": problems == [] and not leaked,
            "problems": problems, "leaked": leaked}


def t_unresolved_anchors_are_reported_and_still_placed():
    _plan, _spec, summary = _built()
    payload = summary.to_dict()
    lines = [line for line in payload["warnings"]
             if line.startswith("unresolved_anchor:")]
    vague = bpy.data.objects.get("BD_Anchor_vague")
    placed = vague is not None and (
        round(vague.location[0], 4), round(vague.location[1], 4)) != (0.0, 0.0)
    return {"ok": (len(lines) == 1 and "vague" in lines[0] and placed),
            "lines": lines, "placed": bool(placed),
            "vague_location": (list(vague.location) if vague else None)}


def main() -> int:
    capture_main_thread()
    check("anchors_become_empties_with_the_solved_positions",
          t_anchors_become_empties_with_the_solved_positions)
    check("anchors_are_guides_and_do_not_render",
          t_anchors_are_guides_and_do_not_render)
    check("the_export_audit_does_not_flag_anchors",
          t_the_export_audit_does_not_flag_anchors)
    check("unresolved_anchors_are_reported_and_still_placed",
          t_unresolved_anchors_are_reported_and_still_placed)

    passed = [key for key, value in RESULTS.items() if value.get("ok")]
    failed = [key for key, value in RESULTS.items() if not value.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS},
        ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
