"""Probe: single-shot rebuild must preserve continuity, motion and Agent cameras.

Three independent behaviours are checked on the real bpy path:

1. regenerating the second shot starts its walk from the character's live
   position at that shot's first frame, not from the script's initial position;
2. declaring ``camera.movements`` survives a non-preserving rebuild;
3. ``preserve_camera_edits=True`` keeps the exact Agent camera object and its
   authored animation without adding a second copy of the declared movement.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy  # noqa: E402

from block_director.contracts.cast import SceneSpec  # noqa: E402
from block_director.contracts.plan import Plan, ShotPlan  # noqa: E402
from block_director.layer3_engine.scene_context import get_context  # noqa: E402
from block_director.layer3_engine.scene_sync import (  # noqa: E402
    is_agent_edited,
    mark_agent_edited,
    reset_synchronizer,
)
from block_director.layer3_engine.shot_builder import build_scene  # noqa: E402
from block_director.layer3_engine.shot_regenerator import regenerate_shot  # noqa: E402
from block_director.utils.blender_compat import action_fcurves  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402


def _plan() -> Plan:
    return Plan(
        scene_heading="shot-regen-camera-motion-probe",
        shots=[
            ShotPlan.from_dict({
                "shot_id": "shot_001",
                "order": 1,
                "intent": "走到镜头二起点",
                "shot_type": "MS",
                "duration_frames": 24,
                "characters": ["char_001"],
                "actions": [{
                    "character_id": "char_001",
                    "action_type": "walk_to",
                    "start_frame": 1,
                    "end_frame": 24,
                    "params": {"target_position": [2.0, 0.0, 0.0]},
                }],
                "camera": {"side": "front", "lens": 35},
            }),
            ShotPlan.from_dict({
                "shot_id": "shot_002",
                "order": 2,
                "intent": "从连续位置继续走，且声明推镜",
                "shot_type": "MS",
                "duration_frames": 24,
                "characters": ["char_001"],
                "actions": [{
                    "character_id": "char_001",
                    "action_type": "walk_to",
                    "start_frame": 1,
                    "end_frame": 24,
                    "params": {"target_position": [3.0, 0.0, 0.0]},
                }],
                "camera": {
                    "side": "front",
                    "lens": 35,
                    "movements": [{
                        "type": "dolly_in",
                        "amount": 0.2,
                        "start_frame": 1,
                        "end_frame": 24,
                    }],
                },
            }),
            ShotPlan.from_dict({
                "shot_id": "shot_003",
                "order": 3,
                "intent": "单镜重建不得改写下一镜",
                "shot_type": "MS",
                "duration_frames": 24,
                "characters": ["char_001"],
                "actions": [{
                    "character_id": "char_001",
                    "action_type": "walk_to",
                    "start_frame": 1,
                    "end_frame": 24,
                    "params": {"target_position": [4.0, 0.0, 0.0]},
                }],
                "camera": {"side": "front", "lens": 35},
            }),
        ],
    )


def _fresh_build():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.render.engine = "BLENDER_WORKBENCH"
    reset_synchronizer()
    plan = _plan()
    build_scene(plan, SceneSpec.from_plan(plan), clear_scene=True)
    return plan, get_context()


def _action_keyframes(camera) -> list[tuple]:
    action = (camera.animation_data.action
              if camera.animation_data and camera.animation_data.action else None)
    if action is None:
        return []
    return sorted(
        (
            str(curve.data_path),
            int(curve.array_index),
            round(float(point.co.x), 4),
            round(float(point.co.y), 6),
        )
        for curve in action_fcurves(action)
        for point in curve.keyframe_points
    )


def _root_x_at(character, frames: list[int]) -> list[float]:
    scene = bpy.context.scene
    previous = int(scene.frame_current)
    samples: list[float] = []
    try:
        for frame in frames:
            scene.frame_set(int(frame))
            bpy.context.view_layer.update()
            samples.append(round(
                float(character.root.matrix_world.translation.x), 4))
    finally:
        scene.frame_set(previous)
        bpy.context.view_layer.update()
    return samples


def _overall_ok(result: dict) -> bool:
    return all(
        value.get("ok") is True
        for key, value in result.items()
        if key.startswith("t_")
    )


def main() -> None:
    capture_main_thread()
    argv = list(sys.argv)
    out = ROOT / "docs" / "evidence" / "20261021-shot-regen-camera-motion"
    if "--" in argv:
        args = argv[argv.index("--") + 1:]
        if "--out" in args:
            out = Path(args[args.index("--out") + 1])
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    results: dict = {}

    try:
        plan, context = _fresh_build()
        scene = bpy.context.scene
        start = int(context.schedule["shot_002"][0])
        scene.frame_set(start)
        bpy.context.view_layer.update()
        character = context.characters["char_001"]
        continuity_before = tuple(
            round(float(value), 4)
            for value in character.root.matrix_world.translation)
        sample_frames = [start, start + 11, start + 23]
        root_x_before = _root_x_at(character, sample_frames)
        next_shot_frames = [49, 50, 51, 54, 60, 72]
        next_shot_before = _root_x_at(character, next_shot_frames)

        old_camera = context.cameras["shot_002"]
        rebuild = regenerate_shot(
            "shot_002", plan=plan, context=context, sync_edits=False)
        new_camera = context.cameras["shot_002"]
        scene.frame_set(start)
        bpy.context.view_layer.update()
        continuity_after = tuple(
            round(float(value), 4)
            for value in character.root.matrix_world.translation)
        root_x_after = _root_x_at(character, sample_frames)
        camera_keys = _action_keyframes(new_camera)
        results["t_live_start_and_declared_motion"] = {
            "ok": (
                rebuild.get("ok") is True
                and new_camera is not old_camera
                and abs(continuity_before[0] - 2.0) <= 1e-3
                and abs(continuity_after[0] - continuity_before[0]) <= 1e-3
                and len(root_x_after) == 3
                and abs(root_x_after[0] - 2.0) <= 1e-3
                and root_x_after[0] <= root_x_after[1] <= root_x_after[2]
                and abs(root_x_after[2] - 3.0) <= 1e-3
                and bool(camera_keys)
            ),
            "continuity_before": continuity_before,
            "continuity_after": continuity_after,
            "sample_frames": sample_frames,
            "root_x_before": root_x_before,
            "root_x_after": root_x_after,
            "camera_replaced": new_camera is not old_camera,
            "camera_keyframes": camera_keys,
        }
        next_shot_after = _root_x_at(character, next_shot_frames)
        results["t_rebuild_does_not_rewrite_next_shot"] = {
            "ok": next_shot_after == next_shot_before,
            "sample_frames": next_shot_frames,
            "next_shot_before": next_shot_before,
            "next_shot_after": next_shot_after,
        }
    finally:
        reset_synchronizer()

    try:
        plan, context = _fresh_build()
        camera = context.cameras["shot_002"]
        camera["bd_agent_approval"] = "approved-shot-002-r3"
        mark_agent_edited(camera)
        before_keys = _action_keyframes(camera)
        report = regenerate_shot(
            "shot_002", plan=plan, context=context, sync_edits=False,
            preserve_camera_edits=True)
        after_camera = context.cameras["shot_002"]
        after_keys = _action_keyframes(after_camera)
        results["t_agent_camera_preserved_without_duplicate_motion"] = {
            "ok": (
                report.get("ok") is True
                and after_camera is camera
                and is_agent_edited(after_camera)
                and after_camera.get("bd_agent_approval")
                == "approved-shot-002-r3"
                and after_keys == before_keys
            ),
            "same_camera": after_camera is camera,
            "agent_marker": bool(is_agent_edited(after_camera)),
            "approval": after_camera.get("bd_agent_approval"),
            "before_key_count": len(before_keys),
            "after_key_count": len(after_keys),
            "keys_identical": after_keys == before_keys,
        }
    finally:
        reset_synchronizer()

    payload = {
        "ok": _overall_ok(results),
        "checks": results,
        "out": str(out),
    }
    (out / "shot_regen_camera_motion_probe.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print("BD_TEST_RESULT " + json.dumps({
        "ok": _overall_ok(results),
        "passed": sum(1 for value in results.values() if value.get("ok")),
        "failed": sum(1 for value in results.values()
                      if not value.get("ok")),
        "checks": results,
        "out": str(out),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
