"""§8.3 双向同步与单镜重生成（Phase 7 DoD：手动修改被保留）。

运行：
  blender --background --factory-startup --python tools/blender_tests/test_scene_sync.py
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
from block_director.layer3_engine import (  # noqa: E402
    SceneSynchronizer,
    get_synchronizer,
    mark_user_animated,
    regenerate_shot,
    reset_synchronizer,
    shot_ranges,
    suppress_sync,
)
from block_director.layer3_engine.collection_router import ensure_collections  # noqa: E402
from block_director.layer3_engine.scene_context import get_context  # noqa: E402
from block_director.layer3_engine.shot_builder import build_scene  # noqa: E402
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


def build(sync: SceneSynchronizer | None = None):
    fresh_scene()
    plan = two_shot_plan()
    spec = SceneSpec.from_plan(plan)
    summary = build_scene(plan, spec, clear_scene=True).to_dict()
    if sync is not None:
        with suppress_sync(sync):
            sync.record_baseline()
    return plan, spec, summary


def keyframe_count(character) -> int:
    total = 0
    for obj in character.all_objects():
        animation = obj.animation_data
        if animation is None:
            continue
        for curve in action_fcurves(animation.action):
            total += len(curve.keyframe_points)
    return total


def frames_with_keys(character) -> set:
    frames = set()
    for obj in character.all_objects():
        animation = obj.animation_data
        if animation is None:
            continue
        for curve in action_fcurves(animation.action):
            frames.update(int(point.co.x) for point in curve.keyframe_points)
    return frames


# --------------------------------------------------------------------------- #
# 1. 干净场景没有 dirty；用户挪动角色后立刻变 dirty
# --------------------------------------------------------------------------- #
def t_dirty_tracking_follows_user_edits():
    sync = SceneSynchronizer()
    sync.bind()
    try:
        plan, _spec, _summary = build(sync)
        clean = sync.dirty_ids()
        character = get_context().characters["char_001"]
        character.root.location.x += 1.5
        bpy.context.view_layer.update()
        dirty = sync.dirty_ids()
        return {"ok": clean == [] and dirty == ["char_001"],
                "clean": clean, "dirty": dirty,
                "touched": sync.touched_ids()}
    finally:
        sync.unbind()


# --------------------------------------------------------------------------- #
# 2. 插件自己的写入不算用户改动（写抑制）
# --------------------------------------------------------------------------- #
def t_plugin_writes_are_suppressed():
    sync = SceneSynchronizer()
    sync.bind()
    try:
        _plan, _spec, _summary = build(sync)
        with suppress_sync(sync):
            character = get_context().characters["char_002"]
            character.root.location.y += 2.0
            bpy.context.view_layer.update()
            sync.record_baseline()
        inside = sync.applying
        after = sync.dirty_ids()
        return {"ok": inside is False and after == [] and sync.bound,
                "applying_after": inside, "dirty": after}
    finally:
        sync.unbind()


# --------------------------------------------------------------------------- #
# 3. 回读用户改动：sync_from_blender 把新摆位写进 SceneSpec
# --------------------------------------------------------------------------- #
def t_sync_reads_the_new_placement():
    sync = SceneSynchronizer()
    sync.bind()
    try:
        plan, spec, _summary = build(sync)
        character = get_context().characters["char_001"]
        character.root.location = (2.5, -0.5, 0.0)
        character.root.rotation_euler[2] = 1.5708          # 面朝 +X
        bpy.context.view_layer.update()

        _plan2, spec2 = sync.sync_from_blender(plan, spec)
        member = next(m for m in spec2.cast if m.id == "char_001")
        untouched = next(m for m in spec2.cast if m.id == "char_002")
        return {"ok": (member.initial_location == (2.5, -0.5, 0.0)
                       and abs(member.initial_facing[0] - 1.0) < 1e-3
                       and untouched.initial_location
                       == next(m.initial_location for m in spec.cast
                               if m.id == "char_002")),
                "char_001": [member.initial_location, member.initial_facing],
                "char_002": list(untouched.initial_location)}
    finally:
        sync.unbind()


# --------------------------------------------------------------------------- #
# 4. 重生成单镜之后，用户的摆位与另一镜的关键帧都还在
# --------------------------------------------------------------------------- #
def t_regenerate_keeps_user_edits_and_other_shots():
    sync = SceneSynchronizer()
    sync.bind()
    try:
        plan, _spec, _summary = build(sync)
        context = get_context()
        ranges = shot_ranges(plan)
        other_id = "shot_001"
        target_id = "shot_002"

        other_character = context.characters["char_001"]
        other_before = frames_with_keys(other_character)
        first_camera_position = tuple(context.cameras[other_id].location)

        # 用户把 char_002 挪开，然后只重生成 shot_002
        moved = context.characters["char_002"]
        moved.root.location = (3.0, 0.5, 0.0)
        bpy.context.view_layer.update()

        report = regenerate_shot(target_id, sync=sync)

        still_there = (abs(moved.root.location.x - 3.0) < 1e-6
                       and abs(moved.root.location.y - 0.5) < 1e-6)
        other_frames = frames_with_keys(other_character)
        camera_untouched = (tuple(context.cameras[other_id].location)
                            == first_camera_position)
        # 另一镜的角色关键帧必须**一个不差**（注意它可能有 6 帧混合窗口伸到
        # 目标镜范围内，所以判据是"集合不变"，不是"目标范围内没有关键帧"）。
        return {"ok": (report["ok"] and still_there and camera_untouched
                       and other_frames == other_before
                       and report["start_frame"] == ranges[target_id][0]
                       and report["end_frame"] == ranges[target_id][1]),
                "report": report, "moved": list(moved.root.location),
                "other_frames_before": sorted(other_before),
                "other_frames_after": sorted(other_frames),
                "camera_untouched": camera_untouched}
    finally:
        sync.unbind()


# --------------------------------------------------------------------------- #
# 5. 打上 bd_user_animated 的角色整段保护
# --------------------------------------------------------------------------- #
def t_user_animated_character_is_protected():
    sync = SceneSynchronizer()
    sync.bind()
    try:
        plan, _spec, _summary = build(sync)
        context = get_context()
        character = context.characters["char_001"]
        for obj in character.all_objects():
            if obj.animation_data is not None:
                mark_user_animated(obj)
        before = keyframe_count(character)

        report = regenerate_shot("shot_001", sync=sync)
        after = keyframe_count(character)
        return {"ok": before == after and "char_001" in report["protected"],
                "before": before, "after": after,
                "protected": report["protected"],
                "warnings": report["warnings"]}
    finally:
        sync.unbind()


# --------------------------------------------------------------------------- #
# 6. 未知镜头给出可执行的错误
# --------------------------------------------------------------------------- #
def t_unknown_shot_is_refused():
    sync = SceneSynchronizer()
    try:
        build(sync)
        try:
            regenerate_shot("shot_999", sync=sync)
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            return {"ok": "shot_999" in message and "shot_001" in message,
                    "message": message}
        return {"ok": False, "message": "应当抛错但没有"}
    finally:
        sync.unbind()


# --------------------------------------------------------------------------- #
# 7. 单例路径：build_scene 之后基线已记录，UI 的"重生成此镜"才能用
# --------------------------------------------------------------------------- #
def t_singleton_records_a_baseline_after_build():
    reset_synchronizer()
    try:
        sync = get_synchronizer()          # UI/算子用的就是它
        _plan, _spec, _summary = build(sync=None)
        baseline = len(sync.baseline)
        clean = sync.dirty_ids()
        character = get_context().characters["char_001"]
        character.root.location.x += 0.75
        bpy.context.view_layer.update()
        dirty = sync.dirty_ids()
        return {"ok": baseline > 0 and clean == [] and dirty == ["char_001"],
                "baseline_entries": baseline, "clean": clean, "dirty": dirty}
    finally:
        reset_synchronizer()


# --------------------------------------------------------------------------- #
# 8. 分镜列表模块能被干净地注册/注销（§13.2）
# --------------------------------------------------------------------------- #
def t_ui_registers_and_unregisters_cleanly():
    import block_director

    block_director.register()
    try:
        registered = (hasattr(bpy.types, "BLOCKDIRECTOR_OT_regenerate_shot")
                      and hasattr(bpy.types, "BLOCKDIRECTOR_PT_shots")
                      and hasattr(bpy.types.Scene, "bd_selected_shot"))
        modules = list(block_director.registration._registered)
    finally:
        block_director.unregister()
    unregistered = (not hasattr(bpy.types, "BLOCKDIRECTOR_OT_regenerate_shot")
                    and not hasattr(bpy.types.Scene, "bd_selected_shot"))
    return {"ok": registered and unregistered
            and "block_director.layer7_ui.panel_shots" in modules,
            "registered": registered, "unregistered": unregistered,
            "modules": modules}


def main() -> int:
    capture_main_thread()
    check("dirty_tracking_follows_user_edits", t_dirty_tracking_follows_user_edits)
    check("plugin_writes_are_suppressed", t_plugin_writes_are_suppressed)
    check("sync_reads_the_new_placement", t_sync_reads_the_new_placement)
    check("regenerate_keeps_user_edits_and_other_shots",
          t_regenerate_keeps_user_edits_and_other_shots)
    check("user_animated_character_is_protected",
          t_user_animated_character_is_protected)
    check("unknown_shot_is_refused", t_unknown_shot_is_refused)
    check("singleton_records_a_baseline_after_build",
          t_singleton_records_a_baseline_after_build)
    check("ui_registers_and_unregisters_cleanly",
          t_ui_registers_and_unregisters_cleanly)

    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS}, ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
