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
    from block_director.cinema.axis import axis_state, camera_side_of, pair_spans
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
    #: 精确路径有没有真的被走到：机位表、以及"计划期近似 vs 真机位"的侧别分歧。
    cameras = RC._built_camera_positions(context, plan)
    spans = pair_spans(base, plan, RC._initial_positions(context)) if base else {}
    side_plan = axis_state(base, plan, RC._initial_positions(context)) if base else {}
    side_exact = (axis_state(base, plan, RC._initial_positions(context), cameras)
                  if base and cameras else side_plan)
    divergent = sorted(shot for shot, side in side_plan.items()
                       if side_exact.get(shot) != side)
    cached_sides = RC._axis_sides(context)
    used_sides = {name: int(side)
                  for name, side in (getattr(context, "_axis_sides_used", None) or {}).items()}
    common = sorted(set(used_sides) & set(side_exact))
    used_vs_exact = [name for name in common if used_sides[name] != side_exact[name]]
    used_vs_plan = [name for name in common if used_sides[name] != side_plan.get(name)]

    def _flips(table):
        order = sorted(table)
        return [order[i] for i in range(1, len(order)) if table[order[i]] != table[order[i - 1]]]

    cache_report = {"equals_exact": cached_sides == side_exact,
                    "equals_plan": cached_sides == side_plan,
                    "n_exact": len(side_exact), "n_cached": len(cached_sides),
                    "used_n": len(used_sides),
                    "used_equals_plan": used_sides == side_plan,
                    "used_equals_exact": used_sides == side_exact,
                    "used_vs_exact_diffs": len(used_vs_exact),
                    "used_vs_plan_diffs": len(used_vs_plan),
                    "flips_plan": _flips(side_plan),
                    "flips_exact": _flips(side_exact),
                    "flips_used": _flips(used_sides)}

    rows = []
    for shot in plan.shots:
        start, _end = context.schedule.get(shot.shot_id, (1, 1))
        scene.frame_set(int(start))
        bpy.context.view_layer.update()
        camera = context.camera_for(shot.shot_id)
        both = len([cid for cid in (shot.characters or [])
                    if str(cid) in (left, right)]) >= 2
        camera_side = None
        if camera is not None and base is not None:
            from block_director.cinema.axis import current_line as _cl
            live_line = _cl(base, RC._character_xy_by_label(context))
            camera_side = live_line.side_of(
                (float(camera.matrix_world.translation.x),
                 float(camera.matrix_world.translation.y)))
        rebuild = RC._axis_rebuild(context, camera) if camera is not None else {}
        neutral_here = None
        if camera is not None and base is not None:
            live = RC.current_line(base, RC._character_xy_by_label(context))
            neutral_here = bool(RC._camera_is_neutral(live, camera))
        #: 与"机位在哪一侧"**互不相干**的另一条判据：相邻两人镜的**画面左右序**有没有
        #: 在没人看见时翻转。用它给两张侧别表投票（谁报的越轴在画面上真看得见）。
        screen_flip = ""
        if camera is not None:
            subjects = [context.character(cid) for cid in (shot.characters or [])]
            screen_flip = RC._screen_polarity_flip(context, camera, shot, subjects)
        event = events.get(str(shot.shot_id))
        sweep = None
        span = spans.get(str(shot.shot_id))
        if span is not None and camera is not None:
            cam_xy = (float(camera.matrix_world.translation.x),
                      float(camera.matrix_world.translation.y))
            left_side = camera_side_of(span[0], span[1], cam_xy)
            right_side = camera_side_of(span[2], span[3], cam_xy)
            sweep = (left_side != 0 and right_side != 0 and left_side != right_side)
        rows.append({
            "shot": str(shot.shot_id),
            "both_on_screen": bool(both),
            "camera_seen": str(shot.shot_id) in cameras,
            "side_plan": side_plan.get(str(shot.shot_id)),
            "side_exact": side_exact.get(str(shot.shot_id)),
            "camera_side_now": camera_side,
            "wrong_vs_plan": (camera_side not in (None, 0)
                              and camera_side != side_plan.get(str(shot.shot_id))),
            "wrong_vs_exact": (camera_side not in (None, 0)
                               and camera_side != side_exact.get(str(shot.shot_id))),
            "screen_flip": bool(screen_flip),
            "camera_swept": sweep,
            "angle": round(float(rebuild.get("angle", 0.0)), 1),
            "bridged": bool(rebuild.get("bridged", True)),
            "neutral_here": neutral_here,
            "visible_deg_total": round(float(visible_deg), 1),
            "event_visible": bool(event.visible) if event is not None else False,
            "event_rotated": round(float(event.rotated_deg), 1) if event is not None else 0.0,
        })
    payload = {"project": str(args.project), "visible_deg_total": visible_deg,
               "cameras_seen": len(cameras), "divergent_shots": divergent,
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
        "cameras_seen": len(cameras),
        "divergent_shots": divergent,
        "wrong_side_vs_plan": len([row for row in rows if row["wrong_vs_plan"]]),
        "wrong_side_vs_exact": len([row for row in rows if row["wrong_vs_exact"]]),
        "screen_flips": len([row for row in rows if row["screen_flip"]]),
        "heuristic_flips": len([row for row in rows if row["both_on_screen"]
                                and row["event_rotated"] >= 90.0]),
        "camera_sweeps": len([row for row in rows if row["camera_swept"]]),
        "camera_sweeps_both": len([row for row in rows if row["camera_swept"]
                                   and row["both_on_screen"]]),
        "wrong_exact_only": len([row for row in rows if row["wrong_vs_exact"]
                                 and not row["wrong_vs_plan"]]),
        "wrong_exact_only_with_screen_flip": len(
            [row for row in rows if row["wrong_vs_exact"] and not row["wrong_vs_plan"]
             and row["screen_flip"]]),
        "rule_cache": cache_report,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
