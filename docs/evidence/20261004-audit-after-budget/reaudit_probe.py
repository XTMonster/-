"""Re-audit a frozen run's project with the CURRENT rule set (zero LLM).

This is the "same artefact, new rules" measurement: rebuild the saved project and
run the shot auditor exactly as the driver does, so a rule-scope or rule-semantics
fix can be compared against the numbers that run originally recorded.

  blender --background --factory-startup --python work/_reaudit_probe.py -- \
      --project docs/evidence/20261004_chunked_long12/project --out work/_x.json
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import pathlib
import statistics
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
    from block_director.layer3_engine.shot_auditor import BpyShotAuditor
    from block_director.layer3_engine.shot_builder import build_scene
    from block_director.layer3_engine.scene_context import get_context
    from block_director.layer9_persistence import load_project

    loaded = load_project(pathlib.Path(os.path.abspath(args.project)))
    plan = sdl_to_plan(loaded.sdl)
    spec = sdl_to_spec(loaded.sdl)
    build_scene(plan, spec=spec, clear_scene=True)
    context = get_context()
    scene = bpy.context.scene
    auditor = BpyShotAuditor()

    rules = collections.Counter()
    passed = []
    rows = []
    for shot in plan.shots:
        start, _end = context.schedule.get(shot.shot_id, (1, 1))
        scene.frame_set(int(start))
        bpy.context.view_layer.update()
        result = auditor.audit(shot.shot_id)
        errors = list(result.errors)
        for item in errors:
            rules[item.rule] += 1
        if result.passed:
            passed.append(shot.shot_id)
        rows.append({"shot": shot.shot_id, "passed": bool(result.passed),
                     "score": result.score,
                     "errors": [item.rule for item in errors]})

    scores = [row["score"] for row in rows if row["score"] is not None]
    payload = {
        "project": str(args.project), "shots": len(rows),
        "passed": len(passed), "passed_shots": sorted(passed),
        "rules": dict(rules.most_common()),
        "composition_median": (round(statistics.median(scores), 2)
                               if scores else None),
        "rows": rows,
    }
    if args.out:
        pathlib.Path(args.out).write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print("REAUDIT " + json.dumps({k: v for k, v in payload.items()
                                   if k != "rows"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
