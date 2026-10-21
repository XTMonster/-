"""Probe: deterministic ruler reframe changes lens without moving the pose."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import bpy  # noqa: E402

from block_director.layer3_engine.scene_context import get_context  # noqa: E402
from block_director.layer3_engine.scene_sync import (  # noqa: E402
    reset_synchronizer,
)
from block_director.layer3_engine.shot_builder import BpySceneBuilder  # noqa: E402
from block_director.layer3_engine.tool_bindings import (  # noqa: E402
    register_action_tools,
)
from block_director.layer5_orchestrator.tool_registry import ToolRegistry  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

from test_coarse_camera_bridge_probe import _baseline, _plan  # noqa: E402


def main() -> int:
    capture_main_thread()
    reset_synchronizer()
    try:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.context.scene.render.engine = "BLENDER_WORKBENCH"
        plan = _plan()
        baseline = _baseline()
        builder = BpySceneBuilder(clear_scene=True)
        builder.attach_coarse_baseline(baseline)
        builder.prepare_scene(plan)
        builder.rebuild_shot("shot_001", plan=plan)

        context = get_context()
        camera = context.cameras["shot_001"]
        target = bpy.data.objects["BD_CamTarget_shot_001"]
        before_position = list(camera.matrix_world.translation)
        before_target = list(target.matrix_world.translation)

        registry = ToolRegistry()
        register_action_tools(registry)
        output = registry.execute(
            "reframe",
            {"shot_id": "shot_001", "lens": 61.2, "preserve_pose": True})
        ok_result = output.ok

        bpy.context.view_layer.update()
        after_position = list(camera.matrix_world.translation)
        after_target = list(target.matrix_world.translation)

        start_frame = int((context.schedule.get("shot_001") or (0, 0))[0])
        probe_frame = start_frame + 3
        bpy.context.scene.frame_set(probe_frame)
        invalid_lens = registry.execute(
            "reframe",
            {"shot_id": "shot_001", "lens": 1.0, "preserve_pose": True})
        invalid_lens_frame_restored = (
            int(bpy.context.scene.frame_current) == probe_frame)

        bpy.context.scene.frame_set(probe_frame)
        original_name = target.name
        target.name = original_name + "_missing"
        missing_target = registry.execute(
            "reframe",
            {"shot_id": "shot_001", "lens": 61.2, "preserve_pose": True})
        missing_target_frame_restored = (
            int(bpy.context.scene.frame_current) == probe_frame)
        target.name = original_name

        def close(left, right, tolerance=1e-6):
            return all(
                abs(float(left[index]) - float(right[index])) <= tolerance
                for index in range(3)
            )

        checks = {
            "tool_ok": ok_result,
            "position_preserved": close(after_position, before_position),
            "target_preserved": close(after_target, before_target),
            "lens_applied": abs(float(camera.data.lens) - 61.2) <= 1e-6,
            "invalid_lens_rejected": not invalid_lens.ok,
            "invalid_lens_frame_restored": invalid_lens_frame_restored,
            "missing_target_rejected": not missing_target.ok,
            "missing_target_frame_restored": missing_target_frame_restored,
        }
        ok = all(checks.values())
        print("BD_TEST_RESULT " + json.dumps({
            "ok": ok,
            "passed": 1 if ok else 0,
            "failed": 0 if ok else 1,
            "checks": checks,
            "before": {
                "position": before_position,
                "target": before_target,
                "lens": 85.0,
            },
            "after": {
                "position": after_position,
                "target": after_target,
                "lens": float(camera.data.lens),
            },
            "tool_output": str(output),
            "invalid_lens_output": str(invalid_lens),
            "missing_target_output": str(missing_target),
            "probe_frame": probe_frame,
        }, ensure_ascii=False))
        return 0 if ok else 1
    finally:
        reset_synchronizer()


if __name__ == "__main__":
    sys.exit(main())
