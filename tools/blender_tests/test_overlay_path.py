"""§13.4 视口叠加与 §9.5 画线工具的集成测试。

运行：
  blender --background --factory-startup --python tools/blender_tests/test_overlay_path.py
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
    ensure_collections,
)
from block_director.layer3_engine.scene_context import get_context  # noqa: E402
from block_director.layer3_engine.shot_builder import build_scene  # noqa: E402
from block_director.layer7_ui import draw_overlay, operator_path_draw  # noqa: E402
from block_director.settings import get_config  # noqa: E402
from block_director.utils.blender_compat import action_fcurves  # noqa: E402
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
    plan = two_shot_plan()
    build_scene(plan, SceneSpec.from_plan(plan), clear_scene=True)
    return plan


def curve_channels(character):
    """返回角色根节点上有 keyframe 的数据路径集合。"""
    root = character.root
    animation = root.animation_data
    if animation is None:
        return set()
    return {curve.data_path for curve in action_fcurves(animation.action)}


def render_audit_leaks():
    """导出前的画面审计（§15.2）：返回会混进参考视频的对象名。"""
    from block_director.layer3_engine.collection_router import audit_renderable_objects
    return audit_renderable_objects()


# --------------------------------------------------------------------------- #
# 1. 叠加几何真的从场景里取到了数据（网格 / 安全框 / 轴线 / 视锥）
# --------------------------------------------------------------------------- #
def t_overlay_geometry_comes_from_the_scene():
    built()
    geometry = draw_overlay.collect_geometry(bpy.context)
    return {"ok": (len(geometry.thirds) == 4 and len(geometry.safe_areas) == 2
                   and len(geometry.axis_lines) > 0
                   and len(geometry.frustums) == 2
                   and all(len(item) == 16 for item in geometry.frustums)),
            "thirds": len(geometry.thirds),
            "safe_areas": len(geometry.safe_areas),
            "axis_segments": len(geometry.axis_lines),
            "frustums": len(geometry.frustums),
            "frustum_points": [len(item) for item in geometry.frustums]}


# --------------------------------------------------------------------------- #
# 2. 配置开关真的关得掉
# --------------------------------------------------------------------------- #
def t_configuration_toggles_the_geometry():
    built()
    config = get_config()
    original = (config.ui.show_axis, config.ui.show_composition,
                config.ui.show_safe_area)
    try:
        config.ui.show_axis = False
        config.ui.show_composition = False
        config.ui.show_safe_area = False
        off = draw_overlay.collect_geometry(bpy.context)
        config.ui.show_axis = True
        config.ui.show_composition = True
        config.ui.show_safe_area = True
        on = draw_overlay.collect_geometry(bpy.context)
    finally:
        (config.ui.show_axis, config.ui.show_composition,
         config.ui.show_safe_area) = original
    return {"ok": (off.thirds == [] and off.safe_areas == []
                   and off.axis_lines == []
                   and len(on.thirds) == 4 and len(on.axis_lines) > 0),
            "off": {"thirds": len(off.thirds), "safe": len(off.safe_areas),
                    "axis": len(off.axis_lines)},
            "on": {"thirds": len(on.thirds), "axis": len(on.axis_lines)}}


# --------------------------------------------------------------------------- #
# 3. draw_handler 挂得上、摘得掉、重复调用安全
# --------------------------------------------------------------------------- #
def t_overlay_handler_lifecycle():
    draw_overlay.unregister()
    draw_overlay.register()
    draw_overlay.register()                   # 幂等
    enabled = draw_overlay.is_enabled()
    timer_on = bpy.app.timers.is_registered(draw_overlay._flash_tick)
    draw_overlay.unregister()
    after = draw_overlay.is_enabled()
    timer_off = not bpy.app.timers.is_registered(draw_overlay._flash_tick)
    return {"ok": enabled and not after and timer_on and timer_off,
            "enabled": enabled, "after": after,
            "flash_timer": [timer_on, timer_off]}


# --------------------------------------------------------------------------- #
# 4. 画线落成：Guides 里的曲线 + 角色位置/朝向关键帧
# --------------------------------------------------------------------------- #
def t_drawn_path_becomes_curve_and_keyframes():
    built()
    context = get_context()
    character = context.characters["char_001"]
    points = [(0.0, 0.0, 0.0), (0.8, 0.4, 0.0), (1.6, 0.2, 0.0),
              (2.4, 0.0, 0.0)]
    report = operator_path_draw.commit_drawn_path(points,
                                                 character_id="char_001",
                                                 start_frame=1)
    obj = bpy.data.objects.get(report["path_object"])
    paths = {curve.data_path for curve in action_fcurves(
        character.root.animation_data.action)}
    in_guides = obj is not None and any(
        collection.name == GUIDES_COLLECTION for collection in obj.users_collection)
    return {"ok": (report["ok"] and obj is not None and in_guides
                   and obj.hide_render is True
                   and report["points"] >= len(points)
                   and report["keyframes"] > 0
                   and report["frames"] == report["end_frame"] - 1
                   and "location" in paths
                   and "rotation_euler" in paths),
            "report": report, "in_guides": in_guides,
            "hide_render": bool(obj.hide_render) if obj else None,
            "channels": sorted(paths)}


# --------------------------------------------------------------------------- #
# 5. 路径曲线是辅助物，导出审计看不到它
# --------------------------------------------------------------------------- #
def t_path_curve_stays_out_of_the_render_audit():
    built()
    operator_path_draw.commit_drawn_path(
        [(0.0, 0.0, 0.0), (1.0, 1.0, 0.0)], character_id="char_001")
    leaks = render_audit_leaks()
    return {"ok": leaks == [], "leaks": list(leaks)}


# --------------------------------------------------------------------------- #
# 6. 坏输入被明确拒绝
# --------------------------------------------------------------------------- #
def t_bad_path_input_is_refused():
    built()
    messages = []
    for points, character_id in ([[(0.0, 0.0, 0.0)], "char_001"],
                                 [[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)], "nobody"]):
        try:
            operator_path_draw.commit_drawn_path(points,
                                                  character_id=character_id)
            messages.append("（没有报错）")
        except ValueError as exc:
            messages.append(str(exc))
    return {"ok": ("两个点" in messages[0] and "char_001" in messages[1]),
            "messages": messages}


# --------------------------------------------------------------------------- #
# 7. 画线算子在注册后可用
# --------------------------------------------------------------------------- #
def t_draw_operator_is_registered():
    import block_director

    block_director.register()
    try:
        registered = hasattr(bpy.types, "BLOCKDIRECTOR_OT_draw_path")
        overlay_on = draw_overlay.is_enabled()
    finally:
        block_director.unregister()
    return {"ok": registered and not draw_overlay.is_enabled(),
            "registered": registered, "overlay_was_on": overlay_on,
            "overlay_after": draw_overlay.is_enabled()}


def main() -> int:
    capture_main_thread()
    check("overlay_geometry_comes_from_the_scene",
          t_overlay_geometry_comes_from_the_scene)
    check("configuration_toggles_the_geometry",
          t_configuration_toggles_the_geometry)
    check("overlay_handler_lifecycle", t_overlay_handler_lifecycle)
    check("drawn_path_becomes_curve_and_keyframes",
          t_drawn_path_becomes_curve_and_keyframes)
    check("path_curve_stays_out_of_the_render_audit",
          t_path_curve_stays_out_of_the_render_audit)
    check("bad_path_input_is_refused", t_bad_path_input_is_refused)
    check("draw_operator_is_registered", t_draw_operator_is_registered)

    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS}, ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
