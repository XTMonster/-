"""§八十五 的两条出路：把"声明固定却有运动"的那些镜头**去掉运动**重建，逐镜复评。

同一个 Blender 进程里跑两臂（未改动 / 去掉未声明的运动），做到逐镜可比：

    blender --background --factory-startup --python work/_declaration_binding_probe.py -- \
        --project docs/evidence/20261004_chunked_long17/project \
        --shots  docs/evidence/20261004_chunked_long17/export/shots.json \
        --out work/_binding_long17.json
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXED = {"固定", "固定镜头", "static", "fixed"}


def main() -> int:
    argv = sys.argv
    rest = argv[argv.index("--") + 1:] if "--" in argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--shots", required=True)
    parser.add_argument("--out", default="")
    args = parser.parse_args(rest)

    import block_director
    block_director.register()
    import bpy

    from block_director.layer2_sdl import sdl_to_plan, sdl_to_spec
    from block_director.layer3_engine.shot_auditor import BpyShotAuditor
    from block_director.layer3_engine.scene_context import get_context
    from block_director.layer3_engine.shot_builder import build_scene
    from block_director.layer9_persistence import load_project

    loaded = load_project(pathlib.Path(os.path.abspath(args.project)))
    plan = sdl_to_plan(loaded.sdl)
    spec = sdl_to_spec(loaded.sdl)

    declared = {}
    for shot in json.loads(pathlib.Path(args.shots).read_text(
            encoding="utf-8"))["shots"]:
        declared[str(shot["shot_id"])] = str(
            (shot.get("declared") or {}).get("technique") or "")

    def audit_all(label: str):
        build_scene(plan, spec=spec, clear_scene=True)
        context = get_context()
        scene = bpy.context.scene
        auditor = BpyShotAuditor()
        rows = []
        for shot in plan.shots:
            start, _end = context.schedule.get(shot.shot_id, (1, 1))
            scene.frame_set(int(start))
            bpy.context.view_layer.update()
            result = auditor.audit(shot.shot_id)
            rows.append({"shot": str(shot.shot_id), "passed": bool(result.passed),
                         "score": result.score,
                         "errors": sorted({item.rule for item in result.errors})})
        scores = [row["score"] for row in rows if row["score"] is not None]
        return {"label": label, "rows": rows,
                "passed": len([row for row in rows if row["passed"]]),
                "gate": len([s for s in scores if s >= 70]),
                "median": round(statistics.median(scores), 2) if scores else None}

    before = audit_all("delivered")

    stripped = []
    for shot in plan.shots:
        camera = dict(getattr(shot, "camera", None) or {})
        if declared.get(str(shot.shot_id), "") in FIXED and camera.get("movements"):
            camera.pop("movements", None)
            camera.pop("movement", None)
            shot.camera = camera
            stripped.append(str(shot.shot_id))
    after = audit_all("declaration-binding")

    payload = {"project": str(args.project), "stripped": stripped,
               "before": before, "after": after}
    if args.out:
        pathlib.Path(args.out).write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print("BINDING " + json.dumps({
        "project": str(args.project),
        "stripped": len(stripped),
        "passed": [before["passed"], after["passed"]],
        "gate": [before["gate"], after["gate"]],
        "median": [before["median"], after["median"]],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
