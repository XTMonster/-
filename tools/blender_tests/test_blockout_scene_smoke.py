"""Ticket 03：Blockout 体块建场景的 Blender 端到端冒烟。

链：空间设计快照 + 计划 -> build_blockout_manifest（纯层）-> 体块建场景
（bpy）-> 断言：体块对象名/数量/坐标/z_anchor/尺寸与 manifest 逐位一致、
共享资产不重复实例化、相机位置/焦距/Track To 目标/运镜关键帧正确、分镜表
打标。全部结论落 BD_TEST_RESULT JSON。

运行：blender --background --factory-startup --python tools/blender_tests/test_blockout_scene_smoke.py -- --out <dir>
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

RESULTS: dict = {}


def fresh_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()


def _design() -> dict:
    return {
        "schema_version": "spatial-design-snapshot/v1",
        "scene_id": "dock_market",
        "characters": [
            {"name": "米迦尔", "position": {"x": -0.9, "y": 0.0, "z": 0.0},
             "facing": [0.0, 1.0, 0.0], "rotation": None, "motion": None,
             "gaze": None, "provenance": "plan_intent"},
            {"name": "伊恩", "position": {"x": 0.9, "y": 0.0, "z": 0.0},
             "facing": [0.0, 1.0, 0.0], "rotation": None, "motion": None,
             "gaze": None, "provenance": "plan_intent"},
        ],
        "props": [
            {"id": "生蚝摊", "kind": "stall", "owner": None, "parent": None,
             "position": [2.5, 1.0, 0.0], "rotation": None, "motion": None,
             "provenance": "script_declaration"},
        ],
        "anchors": [
            {"label": "入口", "position": [0.0, 6.0, 0.0], "provenance":
             "algorithmic_measurement", "resolved": True},
        ],
        "camera_intents": [
            {"shot_id": "shot_001", "position": [-0.9, 4.66, 0.62],
             "target": [-0.9, 0.0, 1.0], "lens": 35.0, "fov_deg": 54.4,
             "provenance": "algorithmic_measurement", "resolved": True},
            {"shot_id": "shot_002", "position": [0.9, 5.0, 0.8],
             "target": [0.9, 0.0, 1.0], "lens": 35.0, "fov_deg": 54.4,
             "provenance": "algorithmic_measurement", "resolved": True},
        ],
        "notes": ["冒烟测试设计快照"],
    }


def _plan():
    from block_director.contracts.plan import Plan, ShotPlan

    return Plan(shots=[
        ShotPlan(
            shot_id="shot_001", intent="双人对话", shot_type="MS",
            duration_frames=24, order=1, characters=["米迦尔", "伊恩"],
            camera={"side": "front", "lens": 35,
                    "movements": [{"type": "dolly_in", "amount": 0.4,
                                   "start_frame": 1, "end_frame": 24}]},
        ),
        ShotPlan(
            shot_id="shot_002", intent="空镜：市场通道", shot_type="MS",
            duration_frames=12, order=2, characters=[],
            camera={"lens": 35},
        ),
    ])


def run_smoke(out_dir: Path) -> dict:
    from block_director.cinema.blockout import build_blockout_manifest
    from block_director.layer3_engine.blockout_scene import (
        BD_BLOCKOUT_PREFIX,
        build_blockout_scene,
    )
    from block_director.utils.blender_compat import action_fcurves

    manifest = build_blockout_manifest(design=_design(), plan=_plan())
    summary = build_blockout_scene(manifest, clear_scene=True)

    checks: dict = {}
    mismatches: list = []
    for primitive in manifest["primitives"]:
        name = f"{BD_BLOCKOUT_PREFIX}{primitive['id']}"
        obj = bpy.data.objects.get(name)
        if obj is None:
            mismatches.append(f"缺体块对象 {name}")
            continue
        dims = obj.dimensions
        size = primitive["size"]
        expected_dim = (size["x"], size["y"], size["z"])
        if any(abs(dims[i] - expected_dim[i]) > 1e-3 for i in range(3)):
            mismatches.append(f"{name} 尺寸 {tuple(dims)} != {expected_dim}")
        pos = primitive["position"]
        z_anchor = primitive["z_anchor"]
        origin_z = pos["z"] + (size["z"] / 2.0) if z_anchor == "foot" \
            else pos["z"]
        if any(abs(obj.location[i] - [pos["x"], pos["y"], origin_z][i]) > 1e-3
               for i in range(3)):
            mismatches.append(
                f"{name} 位置 {tuple(obj.location)} != "
                f"{[pos['x'], pos['y'], origin_z]}")
    checks["primitive_objects"] = len(manifest["primitives"])
    checks["primitive_mismatches"] = mismatches

    for camera in manifest["cameras"]:
        camera_name = f"{BD_BLOCKOUT_PREFIX}{camera['camera_id']}"
        cam = bpy.data.objects.get(camera_name)
        if cam is None:
            mismatches.append(f"缺相机 {camera_name}")
            continue
        #: 运镜会在镜内移动相机：基准位置在该镜起始帧比对（manifest 机位
        #: 是起点），末帧偏离是运镜的预期结果，不是误差。
        bpy.context.scene.frame_set(int(camera["start_frame"]))
        bpy.context.view_layer.update()
        if any(abs(cam.location[i] - camera["position"][i]) > 1e-3
               for i in range(3)):
            mismatches.append(f"{camera_name} 位置偏离")
        if abs(cam.data.lens - camera["lens_mm"]) > 1e-3:
            mismatches.append(f"{camera_name} 焦距偏离")
        target = bpy.data.objects.get(
            f"{BD_BLOCKOUT_PREFIX}CamTarget_{camera['shot_id']}")
        if target is None:
            mismatches.append(f"缺对准目标 {camera['shot_id']}")
        elif camera.get("movements"):
            expected_target = tuple(float(v) for v in camera.get("target") or ())
            actual_target = tuple(float(v) for v in target.matrix_world.translation)
            if len(expected_target) == 3 and any(
                    abs(actual_target[i] - expected_target[i]) > 1e-3
                    for i in range(3)):
                mismatches.append(
                    f"{camera_name} 运镜起始对准点偏离："
                    f"{actual_target} != {expected_target}")
        if camera["movements"]:
            action = (cam.animation_data.action
                      if cam.animation_data and cam.animation_data.action
                      else None)
            fcurves = action_fcurves(action) if action is not None else []
            if not fcurves:
                mismatches.append(f"{camera_name} 运镜无关键帧")
    checks["camera_objects"] = len(manifest["cameras"])

    #: 共享资产不重复实例化：每个 prop 体块一个对象
    prop_objects = [obj for obj in bpy.data.objects
                    if obj.name.startswith(f"{BD_BLOCKOUT_PREFIX}prop_")]
    checks["prop_object_count"] = len(prop_objects)
    if len(prop_objects) != len(manifest["asset_registry"]):
        mismatches.append(
            f"共享资产实例数 {len(prop_objects)} != 资产登记 "
            f"{len(manifest['asset_registry'])}")

    marker_names = [m.name for m in bpy.context.scene.timeline_markers]
    for row in manifest["shot_table"]:
        if f"BD_Cut_{row['shot_id']}" not in marker_names:
            mismatches.append(f"缺切点标记 {row['shot_id']}")
    checks["markers"] = len([m for m in marker_names if m.startswith("BD_Cut_")])

    checks["summary"] = summary
    checks["mismatches"] = mismatches

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "blockout_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "blockout_scene_summary.json").write_text(
        json.dumps({"summary": summary, "checks": checks},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "ok": not mismatches,
        "checks": checks,
        "outputs": {
            "manifest": str(out_dir / "blockout_manifest.json"),
            "summary": str(out_dir / "blockout_scene_summary.json"),
        },
    }


def main() -> int:
    argv = list(sys.argv)
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    out_dir = ROOT / "docs" / "evidence" / "20261018-blockout-scene-smoke"
    for index, item in enumerate(argv):
        if item == "--out" and index + 1 < len(argv):
            out_dir = Path(argv[index + 1])
            break
    try:
        fresh_scene()
        RESULTS["blockout_scene_smoke"] = run_smoke(out_dir)
    except Exception as exc:  # noqa: BLE001 - 冒烟归一为结果记录
        RESULTS["blockout_scene_smoke"] = {
            "ok": False, "error": f"{type(exc).__name__}: {exc}",
            "trace": traceback.format_exc(limit=5),
        }

    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS},
        ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
