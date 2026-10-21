"""§7.4 工具层的扩展工具（Phase 7 补齐）。

覆盖：move_character / look_at / interact_with / move_camera / reframe，以及
estimate_shot_duration 的注册。运行：

  blender --background --factory-startup --python tools/blender_tests/test_tools_extended.py
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
from block_director.contracts.cast import CastMember, SceneSpec  # noqa: E402
from block_director.layer3_engine.collection_router import ensure_collections  # noqa: E402
from block_director.layer3_engine.scene_context import get_context  # noqa: E402
from block_director.layer3_engine.scene_executor import build_environment  # noqa: E402
from block_director.layer3_engine.shot_builder import build_scene  # noqa: E402
from block_director.layer3_engine.tool_bindings import register_all_scene_tools  # noqa: E402
from block_director.layer5_orchestrator.control_tools import (  # noqa: E402
    CONTROL_TOOL_NAMES,
)
from block_director.layer5_orchestrator.driver import default_registry  # noqa: E402
from block_director.layer5_orchestrator.tool_registry import ToolRegistry  # noqa: E402
from block_director.utils.blender_compat import action_fcurves  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

RESULTS: dict = {}
EXTRA_TOOLS = ("move_character", "look_at", "face_character", "interact_with",
               "move_camera", "reframe", "estimate_shot_duration")


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


def built(with_prop: bool = False, with_actions: bool = True):
    fresh_scene()
    plan = two_shot_plan(with_actions=with_actions)
    spec = SceneSpec.from_plan(plan)
    if with_prop:
        spec.props = [{"id": "chair", "type": "chair", "position": [0.75, 0.0, 0.0],
                       "size": [0.5, 0.5, 0.5]}]
    build_scene(plan, spec, clear_scene=True)
    registry = ToolRegistry()
    register_all_scene_tools(registry)
    return plan, registry


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
# 1. 九个工具全部在线
# --------------------------------------------------------------------------- #
def t_extended_tools_are_registered():
    _plan, registry = built()
    names = set(registry.names())
    return {"ok": set(EXTRA_TOOLS) <= names,
            "missing": sorted(set(EXTRA_TOOLS) - names),
            "tools": sorted(names)}


# --------------------------------------------------------------------------- #
# 1b. 模型真正看到的工具表 = 驱动器默认集 + 场景工具集（§7.4 全覆盖）
# --------------------------------------------------------------------------- #
def t_the_llm_facing_registry_is_complete():
    fresh_scene()
    registry = default_registry()          # emit_plan + 三个控制工具
    register_all_scene_tools(registry)
    names = set(registry.names())
    spec_tools = {
        "place_character", "move_character", "character_action", "look_at",
        "face_character",
        "interact_with", "setup_camera", "move_camera", "reframe",
        "get_scene_state", "check_composition", "check_axis",
        "check_visibility", "estimate_shot_duration", "search_knowledge",
        "request_self_review", "finish_shot", "abort"}
    return {"ok": spec_tools <= names and set(CONTROL_TOOL_NAMES) <= names,
            "missing": sorted(spec_tools - names),
            "total": len(names), "tools": sorted(names)}


# --------------------------------------------------------------------------- #
# 2. move_character：真的生成行走关键帧，并落在指定帧段
# --------------------------------------------------------------------------- #
def t_move_character_walks():
    # 不带内置动作：否则原动画已经把 1–102 帧铺满，看不出"新加的关键帧"
    _plan, registry = built(with_actions=False)
    character = get_context().characters["char_001"]
    before_frames = frames_with_keys(character)
    before_x = float(character.root.matrix_world.translation.x)
    result = registry.execute("move_character", {
        "character_id": "char_001", "target_position": [2.0, 0.0, 0.0],
        "start_frame": 10, "end_frame": 40})
    after = frames_with_keys(character)
    # 走位是否真实生效要在**走位结束帧**上求值后读（世界坐标刷新后 raw
    # location 反映的是当前帧的真实姿态；在帧 1 读只会拿到起点 -0.9）。
    bpy.context.scene.frame_set(40)
    bpy.context.view_layer.update()
    moved_x = float(character.root.matrix_world.translation.x)
    # 走位的收尾会带 6 帧混合窗口（§9.7），因此关键帧到 46 为止
    return {"ok": (result.ok and before_frames == set()
                   and after == set(range(10, 47))
                   and moved_x > before_x),
            "content": result.content,
            "frames": [min(after, default=0), max(after, default=0)],
            "count": len(after),
            "root_x": [round(before_x, 3), round(moved_x, 3)]}


# --------------------------------------------------------------------------- #
# 3. look_at：头部朝向目标，且目标可以是角色 ID
# --------------------------------------------------------------------------- #
def t_look_at_tracks_another_character():
    _plan, registry = built(with_actions=False)
    character = get_context().characters["char_001"]
    before = frames_with_keys(character)
    result = registry.execute("look_at", {
        "character_id": "char_001", "target": "char_002",
        "start_frame": 1, "end_frame": 24})
    new_frames = sorted(frames_with_keys(character) - before)
    missing_target = registry.execute("look_at", {
        "character_id": "char_001", "start_frame": 1, "end_frame": 24})
    # 同样带 6 帧混合窗口：1–24 的动作 → 关键帧铺到 30
    return {"ok": result.ok and new_frames == list(range(1, 31))
            and not missing_target.ok
            and "target" in missing_target.content,
            "content": result.content, "new_frames": len(new_frames),
            "missing_target": missing_target.content}


def t_look_at_actually_aims_at_the_target():
    """v1.3 诉求 2：``look_at`` 必须真的对准目标。

    v1.2 把目标位置放进 ``params["target"]``，而动作层只读 ``yaw_deg`` /
    ``pitch_deg``——目标被静默忽略，无论看向谁都是固定转 30°。
    """
    _plan, registry = built(with_actions=False)
    context = get_context()
    a = context.characters["char_001"]
    b = context.characters["char_002"]
    a.root.location = (-0.9, 0.0, 0.0)
    a.root.rotation_euler = (0.0, 0.0, -1.5707963267948966)   # 面朝 +X
    b.root.location = (0.9, 0.0, 0.0)
    bpy.context.view_layer.update()

    result = registry.execute("look_at", {
        "character_id": "char_001", "target": "char_002",
        "start_frame": 1, "end_frame": 24})
    bpy.context.scene.frame_set(30)
    head_yaw = float(a.head_pivot.rotation_euler[2])
    return {"ok": (result.ok and abs(head_yaw) < 0.05
                   and "偏航" in result.content),
            "head_yaw_deg": round(head_yaw * 57.29577951308232, 3),
            "content": result.content}


def t_face_character_turns_the_body():
    """身体朝向必须由 root 承担——头部只有 ±90°，转头转不过去。"""
    _plan, registry = built(with_actions=False)
    context = get_context()
    a = context.characters["char_001"]
    b = context.characters["char_002"]
    a.root.location = (0.0, 0.0, 0.0)
    b.root.location = (2.0, 0.0, 0.0)
    bpy.context.view_layer.update()

    result = registry.execute("face_character", {
        "character_id": "char_001", "target": "char_002"})
    bpy.context.view_layer.update()
    from block_director.layer3_engine.character_system import get_facing
    facing = get_facing(a)
    return {"ok": (result.ok and facing[0] > 0.99 and abs(facing[1]) < 0.02),
            "facing": list(facing), "content": result.content}


# --------------------------------------------------------------------------- #
# 4. interact_with：动作落地 + 道具状态写入台账
# --------------------------------------------------------------------------- #
def t_interact_with_updates_the_prop_ledger():
    _plan, registry = built(with_prop=True)
    context = get_context()
    result = registry.execute("interact_with", {
        "character_id": "char_001", "prop_id": "chair",
        "interaction_type": "sit", "start_frame": 1, "end_frame": 40})
    prop = next((obj for obj in bpy.data.objects
                 if str(obj.get("bd_sdl_id") or "") == "chair"), None)
    notes = list(context.notes)
    unknown = registry.execute("interact_with", {
        "character_id": "char_001", "prop_id": "ghost",
        "interaction_type": "sit", "start_frame": 1, "end_frame": 10})
    return {"ok": (result.ok and prop is not None
                   and prop.get("bd_state") == "sit"
                   and any("chair" in note for note in notes)
                   and not unknown.ok and "找不到道具" in unknown.content),
            "content": result.content, "prop_state": prop.get("bd_state") if prop else None,
            "notes": notes, "unknown": unknown.content}


# --------------------------------------------------------------------------- #
# 5. move_camera：给这一镜的相机插入关键帧，别的镜头不受影响
# --------------------------------------------------------------------------- #
def t_move_camera_animates_only_its_shot():
    _plan, registry = built()
    context = get_context()
    camera = context.cameras["shot_001"]
    other = context.cameras["shot_002"]
    before = tuple(other.location)
    result = registry.execute("move_camera", {
        "camera_id": "shot_001", "movement_type": "dolly_in", "amount": 1.0,
        "start_frame": 1, "end_frame": 48})
    curves = len(action_fcurves(camera.animation_data.action)) \
        if camera.animation_data else 0
    return {"ok": (result.ok and curves >= 3
                   and tuple(other.location) == before
                   and any("运镜" in event.message
                           for event in []) is False),
            "content": result.content, "curves": curves,
            "other_untouched": tuple(other.location) == before}


# --------------------------------------------------------------------------- #
# 6. reframe：复用同一台相机，只改位置与焦距
# --------------------------------------------------------------------------- #
def t_reframe_reuses_the_camera():
    _plan, registry = built()
    context = get_context()
    camera = context.cameras["shot_001"]
    name = camera.name
    before_lens = float(camera.data.lens)
    count_before = len(bpy.data.objects)
    result = registry.execute("reframe", {"shot_id": "shot_001",
                                          "shot_type": "CU"})
    after = context.cameras["shot_001"]
    return {"ok": (result.ok and after is camera and after.name == name
                   and len(bpy.data.objects) == count_before
                   and float(after.data.lens) != before_lens
                   and context.shot_types["shot_001"] == "CU"),
            "content": result.content, "same_object": after is camera,
            "objects_before": count_before, "objects_after": len(bpy.data.objects),
            "lens": [before_lens, float(after.data.lens)]}


def t_character_action_reports_the_current_roster_and_vfx_for_nonparticipants():
    """A3 checks the LLM-facing registry, not just SceneContext's message helper."""
    _plan, registry = built(with_actions=False)
    context = get_context()
    context.current_shot_id = "shot_002"  # only char_002 participates here
    start = context.schedule["shot_002"][0]
    before = {cid: frames_with_keys(character)
              for cid, character in context.characters.items()}
    rejected = {}
    for subject in ("environment_flag", "char_001"):
        result = registry.execute("character_action", {
            "character_id": subject, "action_type": "nod",
            "start_frame": start, "end_frame": start + 12,
        })
        assert result.ok is False, result.content
        assert subject in result.content, result.content
        assert "{char_002}" in result.content, result.content
        assert "vfx 字段" in result.content, result.content
        assert "create_vfx" in result.content, result.content
        rejected[subject] = result.content
    assert {cid: frames_with_keys(character)
            for cid, character in context.characters.items()} == before
    accepted = registry.execute("character_action", {
        "character_id": "char_002", "action_type": "nod",
        "start_frame": start, "end_frame": start + 12,
    })
    assert accepted.ok, accepted.content
    assert frames_with_keys(context.characters["char_002"]) > before["char_002"]
    assert frames_with_keys(context.characters["char_001"]) == before["char_001"]
    return {"ok": True, "rejected": rejected, "accepted": accepted.content}


def main() -> int:
    capture_main_thread()
    check("extended_tools_are_registered", t_extended_tools_are_registered)
    check("the_llm_facing_registry_is_complete",
          t_the_llm_facing_registry_is_complete)
    check("move_character_walks", t_move_character_walks)
    check("look_at_tracks_another_character", t_look_at_tracks_another_character)
    check("look_at_actually_aims_at_the_target",
          t_look_at_actually_aims_at_the_target)
    check("face_character_turns_the_body", t_face_character_turns_the_body)
    check("interact_with_updates_the_prop_ledger",
          t_interact_with_updates_the_prop_ledger)
    check("move_camera_animates_only_its_shot",
          t_move_camera_animates_only_its_shot)
    check("reframe_reuses_the_camera", t_reframe_reuses_the_camera)
    check("character_action_reports_roster_and_vfx",
          t_character_action_reports_the_current_roster_and_vfx_for_nonparticipants)

    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS}, ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
