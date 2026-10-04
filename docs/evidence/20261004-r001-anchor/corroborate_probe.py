"""给 §77.3 的开放问题取证：锚口径多报的那些镜头，画面判据证实得了吗？

对每一镜同时算四件事：

* `angle_now` / `bridged_now`：**现行判据**（相对规范首镜线；桥接 = 中性 或 全片
  可见旋转累计覆盖漂移）；
* `angle_anchor` / `bridged_anchor`：**锚口径**（`cinema/axis.drift_report`，自带
  重新起锚）；
* `screen_flip`：**独立**的画面判据 `_screen_polarity_flip`（相邻两人镜的屏幕左右序
  有没有在没人看见时翻转——既不读首镜线也不读锚）；
* `both_on_screen`。

    blender --background --factory-startup --python work/_anchor_corroborate.py -- \
        --project docs/evidence/20261003_chunked_long9/project --out work/_anchor_long9.json
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

    from block_director.cinema.axis import (AXIS_DRIFT_DEG, drift_is_bridged,
                                            drift_report, pair_spans)
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
    axis = context.axis
    initial = RC._initial_positions(context)
    spans = pair_spans(axis, plan, initial)

    #: 中性表（与规则侧同款：每镜切入点、读相机）。
    neutral = {}
    restore = int(scene.frame_current)
    for shot in plan.shots:
        shot_id = str(shot.shot_id)
        camera = context.camera_for(shot_id)
        if camera is None:
            continue
        start, _end = RC.shot_frame_span(shot_id, context)
        scene.frame_set(int(start))
        bpy.context.view_layer.update()
        live = RC.current_line(axis, RC._character_xy_by_label(context))
        neutral[shot_id] = bool(RC._camera_is_neutral(live, camera))
    scene.frame_set(restore)
    bpy.context.view_layer.update()

    report = drift_report(axis, plan, initial, neutral)
    #: 现行判据里的那个"全片可见旋转累计"。
    visible_total = sum(event.rotated_deg
                        for event in RC._crossing_map(context).values()
                        if event.visible)

    rows = []
    for shot in plan.shots:
        shot_id = str(shot.shot_id)
        row = report.get(shot_id)
        if row is None:
            continue
        camera = context.camera_for(shot_id)
        start, _end = RC.shot_frame_span(shot_id, context)
        scene.frame_set(int(start))
        bpy.context.view_layer.update()
        subjects = [context.character(cid) for cid in (shot.characters or [])]
        screen_flip = ""
        if camera is not None:
            screen_flip = RC._screen_polarity_flip(context, camera, shot, subjects)
        left, right = axis.left_label, axis.right_label
        both = len([cid for cid in (shot.characters or [])
                    if str(cid) in (left, right)]) >= 2
        #: 现行口径：角度相对**首镜线**、桥接用**全片**可见旋转累计。
        span = spans.get(shot_id)
        angle_now = 0.0
        if span is not None:
            from block_director.cinema.axis import _angle_between, _unit
            start_dir = _unit(span[0], span[1])
            if start_dir != (0.0, 0.0):
                angle_now = _angle_between(axis.direction, start_dir)
        bridged_now = drift_is_bridged(angle_now, visible_total,
                                       bool(neutral.get(shot_id, False)))
        rows.append({
            "shot": shot_id,
            "both_on_screen": bool(both),
            "angle_now": round(float(angle_now), 1),
            "bridged_now": bool(bridged_now),
            "error_now": bool(angle_now >= AXIS_DRIFT_DEG and not bridged_now),
            "angle_anchor": round(float(row["angle"]), 1),
            "bridged_anchor": bool(row["bridged"]),
            "error_anchor": bool(row["angle"] >= AXIS_DRIFT_DEG and not row["bridged"]),
            "acknowledged": bool(row["acknowledged"]),
            "screen_flip": bool(screen_flip),
        })
    scene.frame_set(restore)
    bpy.context.view_layer.update()

    extra = [row for row in rows if row["error_anchor"] and not row["error_now"]]
    lost = [row for row in rows if row["error_now"] and not row["error_anchor"]]
    #: 无相机的那几镜（`drift_report` 里被跳过）也要如实计数。
    skipped = [str(shot.shot_id) for shot in plan.shots
               if str(shot.shot_id) not in report]
    summary = {
        "project": str(args.project),
        "shots": len(rows),
        "error_now": len([row for row in rows if row["error_now"]]),
        "error_anchor": len([row for row in rows if row["error_anchor"]]),
        "extra_anchor_errors": len(extra),
        "extra_with_screen_flip": len([row for row in extra if row["screen_flip"]]),
        "extra_both_on_screen": len([row for row in extra if row["both_on_screen"]]),
        "lost_from_now": len(lost),
        "shots_without_report": skipped,
    }
    if args.out:
        pathlib.Path(args.out).write_text(
            json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1),
            encoding="utf-8")
    print("ANCHOR " + json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
