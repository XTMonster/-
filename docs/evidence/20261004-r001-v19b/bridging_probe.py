"""每镜的轴线诊断：漂移角、可见旋转累计、中性、桥接、是否两人同框。

    blender --background --factory-startup --python work/_bridging_probe.py -- --project <dir> --out <json>

用来裁决"会诊 F1 的记账式判据"到底是在抓真的暗重建，还是在把合法镜头判红。
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
    parser.add_argument("--out", default="")
    args = parser.parse_args(rest)

    import block_director
    block_director.register()
    import bpy

    from block_director.layer2_sdl import sdl_to_plan, sdl_to_spec
    from block_director.layer3_engine import rule_checker as RC
    from block_director.layer3_engine.scene_context import get_context
    from block_director.layer3_engine.shot_builder import build_scene
    from block_director.layer9_persistence import load_project

    loaded = load_project(pathlib.Path(os.path.abspath(args.project)))
    plan = sdl_to_plan(loaded.sdl)
    spec = sdl_to_spec(loaded.sdl)
    build_scene(plan, spec=spec, clear_scene=True)
    context = get_context()
    scene = bpy.context.scene

    base = context.axis
    left, right = (base.left_label, base.right_label) if base is not None else ("", "")
    events = RC._crossing_map(context)
    visible_deg = sum(event.rotated_deg for event in events.values() if event.visible)

    rows = []
    for shot in plan.shots:
        start, _end = context.schedule.get(shot.shot_id, (1, 1))
        scene.frame_set(int(start))
        bpy.context.view_layer.update()
        camera = context.camera_for(shot.shot_id)
        both = len([cid for cid in (shot.characters or [])
                    if str(cid) in (left, right)]) >= 2
        rebuild = RC._axis_rebuild(context, camera) if camera is not None else {}
        neutral_here = None
        if camera is not None and base is not None:
            live = RC.current_line(base, RC._character_xy_by_label(context))
            neutral_here = bool(RC._camera_is_neutral(live, camera))
        event = events.get(str(shot.shot_id))
        rows.append({
            "shot": str(shot.shot_id),
            "both_on_screen": bool(both),
            "angle": round(float(rebuild.get("angle", 0.0)), 1),
            "bridged": bool(rebuild.get("bridged", True)),
            "neutral_here": neutral_here,
            "visible_deg_total": round(float(visible_deg), 1),
            "event_visible": bool(event.visible) if event is not None else False,
            "event_rotated": round(float(event.rotated_deg), 1) if event is not None else 0.0,
        })
    payload = {"project": str(args.project), "visible_deg_total": visible_deg,
               "rows": rows}
    if args.out:
        pathlib.Path(args.out).write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    drifted = [row for row in rows if row["angle"] >= RC.AXIS_DRIFT_DEG]
    print("BRIDGING " + json.dumps({
        "project": str(args.project),
        "visible_deg_total": round(float(visible_deg), 1),
        "drifted": len(drifted),
        "drifted_bridged": len([row for row in drifted if row["bridged"]]),
        "drifted_unbridged": len([row for row in drifted if not row["bridged"]]),
        "unbridged_showing_both": len(
            [row for row in drifted if not row["bridged"] and row["both_on_screen"]]),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
