"""`setup_camera` 复现构建器机位时，那点残余差从哪来？

对给定的几个镜头，打印"构建器的相机"与"工具重设后的相机"的
位置/目标/焦距，以及场景里 `BD_Cam*` 对象的**名字**——名字冲突会暴露
"旧对象没删干净"这类泄漏。
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    argv = sys.argv
    rest = argv[argv.index("--") + 1:] if "--" in argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--shots", default="shot_001,shot_055,shot_057")
    args = parser.parse_args(rest)

    import block_director
    block_director.register()
    import bpy

    from block_director.layer2_sdl import sdl_to_plan, sdl_to_spec
    from block_director.layer3_engine.scene_context import get_context
    from block_director.layer3_engine.shot_auditor import BpyShotAuditor
    from block_director.layer3_engine.shot_builder import build_scene
    from block_director.layer3_engine.tool_bindings import register_all_scene_tools
    from block_director.layer5_orchestrator.tool_registry import ToolRegistry
    from block_director.layer9_persistence import load_project

    loaded = load_project(pathlib.Path(os.path.abspath(args.project)))
    plan = sdl_to_plan(loaded.sdl)
    spec = sdl_to_spec(loaded.sdl)
    build_scene(plan, spec=spec, clear_scene=True)
    context = get_context()
    scene = bpy.context.scene
    auditor = BpyShotAuditor()
    registry = ToolRegistry()
    register_all_scene_tools(registry)

    def describe(shot_id):
        camera = context.cameras.get(shot_id)
        if camera is None:
            return None
        start, _end = context.schedule.get(shot_id, (1, 1))
        scene.frame_set(int(start))
        bpy.context.view_layer.update()
        target = camera.constraints[0].target if camera.constraints else None
        keyed = 0
        if camera.animation_data and camera.animation_data.action:
            from block_director.layer3_engine.cinema_engine.camera_motion import (
                _fcurves,
            )
            for curve in _fcurves(camera.animation_data.action):
                keyed += len(curve.keyframe_points)
        return {
            "camera_name": camera.name,
            "data_name": camera.data.name,
            "location": [round(float(v), 4) for v in camera.matrix_world.translation],
            "lens": float(camera.data.lens),
            "target_name": getattr(target, "name", None),
            "target_location": ([round(float(v), 4) for v in target.matrix_world.translation]
                                if target is not None else None),
            "camera_keyframes": keyed,
        }

    report = {}
    for shot_id in args.shots.split(","):
        shot = context.shot(shot_id)
        if shot is None:
            continue
        before = describe(shot_id)
        start, _end = context.schedule.get(shot_id, (1, 1))
        scene.frame_set(int(start))
        result = auditor.audit(shot_id)
        before["audit"] = {"passed": bool(result.passed), "score": result.score}
        before["per_frame"] = per_frame_scores(shot_id, auditor)
        request = dict(getattr(shot, "camera", None) or {})
        params = {"shot_id": shot_id,
                  "shot_type": request.get("shot_type") or str(shot.shot_type),
                  "side": str(request.get("side") or "front")}
        if request.get("lens"):
            params["lens"] = request["lens"]
        registry.execute("setup_camera", params)
        after = describe(shot_id)
        result = auditor.audit(shot_id)
        after["audit"] = {"passed": bool(result.passed), "score": result.score}
        after["per_frame"] = per_frame_scores(shot_id, auditor)
        report[shot_id] = {
            "params": params, "request": request,
            "before": before, "after": after,
            "targets_in_scene": sorted(o.name for o in bpy.data.objects
                                       if o.name.startswith("BD_CamTarget_")),
            "camera_data_in_file": sorted(d.name for d in bpy.data.cameras),
        }
    print("TOOLDELTA " + json.dumps(report, ensure_ascii=False))
    return 0


def per_frame_scores(shot_id, auditor):
    """首/中/尾三帧各自的构图分（构图门取最小值）。"""
    import bpy

    from block_director.layer3_engine.scene_context import get_context
    from block_director.layer3_engine.cinema_engine import (
        evaluate_camera_composition,
    )

    context = get_context()
    scene = bpy.context.scene
    start, end = context.schedule.get(shot_id, (1, 1))
    camera = context.cameras.get(shot_id)
    characters = context.subjects_for(shot_id)
    shot_type = context.shot_types.get(shot_id, "MS")
    out = {}
    for label, frame in (("first", int(start)), ("mid", (int(start) + int(end)) // 2),
                         ("last", int(end))):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        report = evaluate_camera_composition(camera, characters, shot_type=shot_type)
        out[label] = round(float(report.score), 1)
    return out


if __name__ == "__main__":
    raise SystemExit(main())
