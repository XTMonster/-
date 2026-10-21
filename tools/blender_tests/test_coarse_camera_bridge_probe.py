"""Probe: an approved coarse camera survives prepare_scene and rebuild_shot.

The coarse gate approves and freezes one camera per shot.  The detail driver
must build that same camera instead of independently solving a second pose
from the plan, otherwise composition is approved on one shot and audited on
another.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402

from block_director.contracts.plan import Plan, ShotPlan  # noqa: E402
from block_director.layer3_engine.scene_context import get_context  # noqa: E402
from block_director.layer3_engine.scene_sync import (  # noqa: E402
    reset_synchronizer,
)
from block_director.layer3_engine.shot_builder import BpySceneBuilder  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402


def _plan() -> Plan:
    return Plan(
        scene_heading="coarse-camera-bridge-probe",
        shots=[ShotPlan.from_dict({
            "shot_id": "shot_001",
            "order": 1,
            "intent": "审批相机必须原样进入详细预演",
            "shot_type": "CU",
            "duration_frames": 24,
            "characters": ["米迦尔"],
            "actions": [],
            "camera": {"side": "front", "lens": 35},
        })],
    )


def _baseline() -> dict:
    return {
        "schema_version": "coarse-baseline/v1",
        "state": "frozen",
        "reference": {
            "schema_version": "coarse-world-reference/v1",
            "scene_id": "coarse-camera-bridge-probe",
            "characters": [{
                "name": "米迦尔",
                "position": {"x": 0.0, "y": 0.0, "z": 0.0},
                "facing": [0.0, 1.0, 0.0],
            }],
            "props": [],
            "anchors": [],
            "camera_intents": [{
                "shot_id": "shot_001",
                "position": [4.25, -1.75, 1.35],
                "target": [-0.2, 0.15, 1.05],
                "lens": 85.0,
            }],
        },
        "manifest": {
            "schema_version": "blockout-manifest/v1",
            "cameras": [{
                "shot_id": "shot_001",
                "camera_id": "cam_shot_001",
                "position": [4.25, -1.75, 1.35],
                "target": [-0.2, 0.15, 1.05],
                "lens_mm": 85.0,
                "movements": [],
                "start_frame": 1,
                "end_frame": 24,
                "resolved": True,
            }],
            "shot_table": [],
            "primitives": [],
        },
        "report": {"verdict": "pass", "findings": [], "checks": []},
    }


def _close(actual, expected, tolerance: float = 1e-6) -> bool:
    return all(
        abs(float(actual[index]) - float(expected[index])) <= tolerance
        for index in range(3)
    )


def main() -> int:
    capture_main_thread()
    reset_synchronizer()
    try:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.context.scene.render.engine = "BLENDER_WORKBENCH"
        plan = _plan()
        baseline = _baseline()
        approved = baseline["manifest"]["cameras"][0]

        builder = BpySceneBuilder(clear_scene=True)
        attached = builder.attach_coarse_baseline(baseline)
        builder.prepare_scene(plan)
        rebuilt = builder.rebuild_shot("shot_001", plan=plan)

        context = get_context()
        camera = context.cameras["shot_001"]
        target = bpy.data.objects.get("BD_CamTarget_shot_001")
        actual = {
            "position": list(camera.matrix_world.translation),
            "target": (list(target.matrix_world.translation)
                       if target is not None else None),
            "lens": float(camera.data.lens),
        }
        missing_error = ""
        try:
            builder.rebuild_shot("shot_002", plan=plan)
        except Exception as exc:  # noqa: BLE001 - probe asserts the failure
            missing_error = f"{type(exc).__name__}: {exc}"
        checks = {
            "baseline_attached": attached == 1,
            "rebuild_ok": rebuilt.get("ok") is True,
            "position_matches": _close(actual["position"],
                                       approved["position"]),
            "target_matches": (
                actual["target"] is not None
                and _close(actual["target"], approved["target"])
            ),
            "lens_matches": (
                abs(actual["lens"] - float(approved["lens_mm"])) <= 1e-6
            ),
            "missing_shot_rejected": (
                "不在已冻结的粗排相机基准内" in missing_error
            ),
        }
        ok = all(checks.values())
        print("BD_TEST_RESULT " + json.dumps({
            "ok": ok,
            "passed": 1 if ok else 0,
            "failed": 0 if ok else 1,
            "checks": checks,
            "approved": approved,
            "actual": actual,
            "missing_error": missing_error,
        }, ensure_ascii=False))
        return 0 if ok else 1
    finally:
        reset_synchronizer()


if __name__ == "__main__":
    sys.exit(main())
