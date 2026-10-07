"""v1.5 P3-T3：道具交互的跟随关键帧 ＋ 灯光语义矩阵的引擎侧落地。

纯 Python 那边（`tests/test_prop_interaction.py` / `tests/test_lighting_matrix.py`）
验的是"窗口与预设算得对"；这里验必须开 Blender 才能看的三件事：

1. 被点名的道具真的挂上一条 Child Of 约束、``influence`` 有关键帧；
2. **没被点名的道具一个关键帧都不打**（"未交互道具不打关键帧"）；
3. 灯光语义真的换了预设（矩阵 → `LIGHTING_PRESETS` 的键集与纯层的键名契约
   逐键相同——**双向断言**，纯层不能 import bpy，只能这样对拍）。

运行：
  blender --background --factory-startup --python tools/blender_tests/test_prop_interaction.py
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
from block_director.cinema.lighting import LIGHTING_PRESET_NAMES  # noqa: E402
from block_director.contracts.cast import SceneSpec  # noqa: E402
from block_director.contracts.plan import Plan, ShotPlan  # noqa: E402
from block_director.layer3_engine.collection_router import (  # noqa: E402
    GUIDES_COLLECTION,
    audit_renderable_objects,
    ensure_collections,
)
from block_director.layer3_engine.scene_executor import LIGHTING_PRESETS  # noqa: E402
from block_director.layer3_engine.shot_builder import build_scene  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

RESULTS: dict = {}

PROPS = [
    {"id": "cup", "position": [0.6, 0.0, 0.9], "size": [0.2, 0.2, 0.2],
     "shape": "cylinder"},
    {"id": "tray", "position": [-0.6, 0.0, 0.9], "size": [0.6, 0.4, 0.1]},
    {"id": "idle", "position": [2.0, 2.0, 0.4], "size": [0.4, 0.4, 0.8]},
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


def _prop_plan() -> Plan:
    """三镜各一个道具动词；``idle`` 道具从不被交互。"""
    first = ShotPlan.from_dict({
        "shot_id": "shot_001", "order": 1, "intent": "放下杯子",
        "shot_type": "MS", "duration_frames": 48,
        "characters": ["char_001"],
        "actions": [{"character_id": "char_001", "action_type": "place_prop",
                     "start_frame": 10, "end_frame": 30,
                     "params": {"prop": "cup"}}],
    })
    second = ShotPlan.from_dict({
        "shot_id": "shot_002", "order": 2, "intent": "端起托盘",
        "shot_type": "MCU", "duration_frames": 60,
        "characters": ["char_002"],
        "actions": [{"character_id": "char_002", "action_type": "pick_up",
                     "start_frame": 5, "end_frame": 25,
                     "params": {"prop": "tray"}}],
    })
    third = ShotPlan.from_dict({
        "shot_id": "shot_003", "order": 3, "intent": "把托盘递过去",
        "shot_type": "MS", "duration_frames": 72,
        "characters": ["char_001", "char_002"],
        "actions": [{"character_id": "char_002", "action_type": "hand_to",
                     "start_frame": 20, "end_frame": 55,
                     #: 注：``toward`` 是**倾身方向量**（x/y/left/front…），
                     #: 不是接收者的角色 id——"递给谁"这一层本版没有契约字段，
                     #: 如实记在卡的执行记录里，不在这里让测试假装它有。
                     "params": {"prop": "tray", "toward": "front"}}],
    })
    return Plan(shots=[first, second, third], scene_heading="INT. 厨房 - 日")


def _built(light=None):
    fresh_scene()
    plan = _prop_plan()
    if light is not None:
        plan.environment = {"light": dict(light)}
    spec = SceneSpec.from_plan(plan)
    spec.props = [dict(item) for item in PROPS]
    summary = build_scene(plan, spec, clear_scene=True)
    return plan, spec, summary


def t_prop_verbs_create_follow_keyframes():
    _plan, _spec, _summary = _built()
    report = {}
    for name in ("cup", "tray"):
        prop = bpy.data.objects[f"BD_Prop_{name}"]
        constraints = {item.name: item for item in prop.constraints}
        follow = constraints.get(f"BD_PropFollow_{name}")
        frames = []
        if follow is not None:
            for fcurve in _fcurves(follow):
                frames.extend(int(point.co[0]) for point in fcurve.keyframe_points)
        report[name] = {"has_constraint": follow is not None,
                        "type": (follow.type if follow else ""),
                        "target": (follow.target.name if follow and follow.target
                                   else ""),
                        "frames": sorted(set(frames))}
    # 排片：shot_001 = 1–48、shot_002 = 49–108、shot_003 = 109–180。
    # cup  place_prop 局部 10–30 → 绝对 10–30  → 键 9/10/30/31
    # tray pick_up   局部  5–25 → 绝对 53–73 → 键 52/53/73/74
    # tray hand_to   局部 20–55 → 绝对 128–163 → 键 127/128/163/164
    return {"ok": (report["cup"]["has_constraint"]
                   and report["cup"]["type"] == "CHILD_OF"
                   and report["cup"]["frames"] == [9, 10, 30, 31]
                   and report["tray"]["has_constraint"]
                   and report["tray"]["frames"] == [52, 53, 73, 74,
                                                    127, 128, 163, 164]
                   and report["cup"]["target"].startswith("BD_Hand_")),
            "report": report}


def _fcurves(constraint):
    """取约束上 ``influence`` 的 F-Curve（Blender 5.x 的 action slot 结构）。"""
    animation = constraint.id_data.animation_data
    if animation is None or animation.action is None:
        return []
    from block_director.utils.blender_compat import action_fcurves

    prefix = f'constraints["{constraint.name}"].influence'
    return [curve for curve in action_fcurves(animation.action)
            if curve.data_path == prefix]


def t_untouched_props_get_no_keyframes():
    _plan, _spec, _summary = _built()
    idle = bpy.data.objects["BD_Prop_idle"]
    animated = idle.animation_data is not None and idle.animation_data.action
    return {"ok": (len(idle.constraints) == 0 and not animated),
            "constraints": [item.name for item in idle.constraints],
            "animated": bool(animated)}


def t_the_hand_proxy_is_a_guide():
    _plan, _spec, _summary = _built()
    hands = [obj for obj in bpy.data.objects if obj.name.startswith("BD_Hand_")]
    ok = bool(hands)
    for hand in hands:
        ok = ok and hand.type == "EMPTY" and hand.hide_render
        ok = ok and any(collection.name == GUIDES_COLLECTION
                        for collection in hand.users_collection)
        ok = ok and hand.parent is not None \
            and hand.parent.name.endswith("_BodyPivot")
    return {"ok": ok, "hands": [obj.name for obj in hands],
            "problems": audit_renderable_objects()}


def t_the_preset_keys_are_the_same_on_both_sides():
    """纯层的键名契约 ⇄ 引擎的预设表：**双向**逐键相等（不是子集）。"""
    return {"ok": tuple(LIGHTING_PRESETS) == tuple(LIGHTING_PRESET_NAMES),
            "engine": sorted(LIGHTING_PRESETS),
            "pure": sorted(LIGHTING_PRESET_NAMES)}


def t_a_light_declaration_switches_the_preset():
    _plan, _spec, _summary = _built(light={"time_of_day": "night",
                                          "mood": "gloomy"})
    lights = [obj for obj in bpy.data.objects
              if obj.name.startswith("BD_Light_")]
    expected = LIGHTING_PRESETS["night"]
    energies = sorted(round(float(obj.data.energy), 4) for obj in lights)
    expected_energies = sorted(round(float(spec.get("energy", 1.0)), 4)
                               for spec in expected)
    return {"ok": bool(lights) and energies == expected_energies,
            "energies": energies, "expected": expected_energies,
            "types": sorted(str(obj.data.type) for obj in lights)}


def t_an_invalid_light_declaration_falls_back_and_says_so():
    _plan, _spec, summary = _built(light={"time_of_day": "midnight",
                                          "mood": "bright"})
    warnings = [line for line in summary.to_dict()["warnings"]
                if line.startswith("light ")]
    lights = [obj for obj in bpy.data.objects
              if obj.name.startswith("BD_Light_")]
    fallback = sorted(round(float(spec.get("energy", 1.0)), 4)
                      for spec in LIGHTING_PRESETS["clay_studio"])
    energies = sorted(round(float(obj.data.energy), 4) for obj in lights)
    return {"ok": (len(warnings) == 1 and energies == fallback),
            "warnings": warnings, "energies": energies, "fallback": fallback}


def main() -> int:
    capture_main_thread()
    check("prop_verbs_create_follow_keyframes",
          t_prop_verbs_create_follow_keyframes)
    check("untouched_props_get_no_keyframes",
          t_untouched_props_get_no_keyframes)
    check("the_hand_proxy_is_a_guide", t_the_hand_proxy_is_a_guide)
    check("the_preset_keys_are_the_same_on_both_sides",
          t_the_preset_keys_are_the_same_on_both_sides)
    check("a_light_declaration_switches_the_preset",
          t_a_light_declaration_switches_the_preset)
    check("an_invalid_light_declaration_falls_back_and_says_so",
          t_an_invalid_light_declaration_falls_back_and_says_so)

    passed = [key for key, value in RESULTS.items() if value.get("ok")]
    failed = [key for key, value in RESULTS.items() if not value.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS},
        ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
