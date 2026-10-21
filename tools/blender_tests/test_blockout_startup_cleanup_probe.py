"""R2 回归探针：无 --factory-startup 时默认启动残留的清理与可见比。

真实 resume/UI 运行不带 ``--factory-startup``，Blender 默认场景的
Cube（原点 1×1×1）会留在场景里挡在机位与主体之间，旧可见性 ray_cast
命中 Cube 而非角色体块，把 visible_ratio 压到 0.44/0.22 并误报
E_BLOCKOUT_EMPTY_WALL。本探针：

1. 故意保留默认 Cube/Light/Camera（不 fresh_scene 清场）；
2. ``build_blockout_scene(clear_scene=True)`` 必须清掉它们；
3. 朝机面 3×3 采样可见比应为 1.0（无前景遮挡），不再误报空墙。

运行：blender --background --python tools/blender_tests/
test_blockout_startup_cleanup_probe.py -- --out <dir>
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


def _design() -> dict:
    """单镜正面近景：米迦尔在机位正前方，无遮挡（复用冒烟设计）。"""
    return {
        "schema_version": "spatial-design-snapshot/v1",
        "scene_id": "startup_cleanup",
        "characters": [
            {"name": "米迦尔", "position": {"x": -0.9, "y": 0.0, "z": 0.0},
             "facing": [0.0, 1.0, 0.0], "rotation": None, "motion": None,
             "gaze": None, "provenance": "plan_intent"},
        ],
        "props": [],
        "anchors": [],
        "camera_intents": [
            {"shot_id": "shot_001", "position": [-0.9, 4.6, 1.2],
             "target": [-0.9, 0.0, 1.0], "lens": 50.0, "fov_deg": 39.6,
             "provenance": "algorithmic_measurement", "resolved": True},
        ],
        "notes": ["R2 回归：默认启动残留清理 + 可见比修复"],
    }


def _plan() -> dict:
    return {
        "scene_heading": "INT. 码头市场 - 白天",
        "shots": [
            {"shot_id": "shot_001", "order": 1, "intent": "米迦尔近景",
             "intent_type": "推进", "shot_type": "MS",
             "duration_frames": 24,
             "characters": ["米迦尔"],
             "dialogue_ids": [],
             "prompt": "米迦尔站在生蚝摊旁",
             "axis_note": "",
             "continuity_in": "开场",
             "camera": {"side": "front", "lens": 50}},
        ],
    }


def main() -> int:
    out = ROOT / "docs" / "evidence" / "20261019-startup-cleanup-probe"
    argv = list(sys.argv)
    if "--" in argv:
        args = argv[argv.index("--") + 1:]
        if "--out" in args:
            out = Path(args[args.index("--out") + 1])
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)

    checks: dict = {}
    try:
        #: 不 fresh_scene：保留默认启动三件套（模拟真实 resume/UI 运行）。
        from block_director.contracts.plan import Plan
        from block_director.cinema.blockout import build_blockout_manifest
        from block_director.layer3_engine.blockout_scene import (
            build_blockout_scene,
        )
        from block_director.layer8_delivery.blockout_preview import (
            _foreground_occlusion_fraction,
            _visible_fraction,
            _world_bounds,
        )
        from mathutils import Vector

        startup_before = sorted(
            o.name for o in bpy.data.objects
            if o.name in {"Cube", "Light", "Camera"})
        checks["startup_before"] = startup_before

        manifest = build_blockout_manifest(
            design=_design(), plan=Plan.from_dict(_plan()))
        build_blockout_scene(manifest, clear_scene=True)

        startup_after = sorted(
            o.name for o in bpy.data.objects
            if o.name in {"Cube", "Light", "Camera"})
        checks["startup_after"] = startup_after

        scene = bpy.context.scene
        camera_obj = bpy.data.objects.get("BD_Blockout_cam_shot_001")
        block = bpy.data.objects.get("BD_Blockout_char_米迦尔")
        scene.frame_set(1)
        bpy.context.view_layer.update()
        depsgraph = bpy.context.evaluated_depsgraph_get()
        camera_pos = Vector(camera_obj.matrix_world.translation)
        bounds = _world_bounds(block)
        visible = _visible_fraction(scene, camera_pos, block, depsgraph)
        foreground, _occluders = _foreground_occlusion_fraction(
            scene, camera_pos, block, ["BD_Blockout_char_米迦尔"],
            depsgraph)
        checks["visible_ratio"] = round(visible, 4)
        checks["foreground_occlusion"] = round(foreground, 4)

        mismatches: list = []
        if not startup_after:
            checks["startup_cleanup"] = True
        else:
            mismatches.append(f"默认启动残留未清: {startup_after}")
        if visible >= 0.9:
            checks["visible_ratio_ok"] = True
        else:
            mismatches.append(f"可见比过低 {visible:.3f} < 0.9")
        if foreground <= 0.5:
            checks["foreground_ok"] = True
        else:
            mismatches.append(f"前景遮挡异常 {foreground:.3f}")

        result = {
            "ok": not mismatches,
            "passed": 0 if mismatches else 3,
            "failed": len(mismatches),
            "checks": checks,
            "mismatches": mismatches,
        }
        (out / "startup_cleanup_result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8")
    except Exception:  # noqa: BLE001 - 探针必须落证据
        result = {
            "ok": False,
            "passed": 0,
            "failed": 1,
            "checks": checks,
            "mismatches": [traceback.format_exc()],
        }
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": result["passed"], "failed": result["failed"],
         "checks": result["checks"]},
        ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
