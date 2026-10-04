"""修复工具 `setup_camera` 与主构建器是不是**同一台相机**？

§七十九的下一步是"量修复回路的有效性"。long16 的日志给出一个刺眼数字：
7 个"真的动了手"的修复回合里 **0** 个通过，其中 4 次 `setup_camera` 之后
构图分一律掉到 **20.0**。同一台相机、同一镜、按计划自己的参数重设一次，
不该把分数打下去——除非**工具与构建器解算出的机位不同**。

本探针把这件事变成可观测量：重建冻结工程 → 逐镜记录基线 → 用**计划自己声明
的** shot_type/side/lens 调一次 `setup_camera` → 再记录一次。两次之差就是
"修复工具离主构建器有多远"。

    blender --background --factory-startup --python work/_tool_vs_builder_probe.py -- \
        --project docs/evidence/20261004_chunked_long16/project --out work/_t.json
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
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--tool", default="setup_camera",
                        choices=("setup_camera", "reframe"))
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

    def audit(shot_id):
        start, _end = context.schedule.get(shot_id, (1, 1))
        scene.frame_set(int(start))
        bpy.context.view_layer.update()
        result = auditor.audit(shot_id)
        return bool(result.passed), result.score

    shots = plan.shots[:args.limit] if args.limit else plan.shots
    before = {}
    for shot in shots:
        before[shot.shot_id] = audit(shot.shot_id)

    rows = []
    for shot in shots:
        camera = context.cameras.get(shot.shot_id)
        if camera is None:
            continue
        request = dict(getattr(shot, "camera", None) or {})
        params = {
            "shot_id": shot.shot_id,
            "shot_type": request.get("shot_type") or str(shot.shot_type),
        }
        if args.tool == "setup_camera":
            params["side"] = str(request.get("side") or "front")
        if request.get("lens"):
            params["lens"] = request["lens"]
        result = registry.execute(args.tool, params)
        ok, score = audit(shot.shot_id)
        was_ok, was_score = before[shot.shot_id]
        rows.append({
            "shot": shot.shot_id, "params": params,
            "tool_ok": bool(getattr(result, "ok", False)),
            "tool_content": str(getattr(result, "content", ""))[:400],
            "before": {"passed": was_ok, "score": was_score},
            "after": {"passed": ok, "score": score},
            "delta": (None if (score is None or was_score is None)
                      else round(score - was_score, 2)),
        })

    broke = [r for r in rows if r["before"]["passed"] and not r["after"]["passed"]]
    dropped = [r for r in rows if r["delta"] is not None and r["delta"] < -1.0]
    payload = {
        "project": str(args.project),
        "tool": args.tool,
        "shots": len(rows),
        "moved_down": len(dropped),
        "passed_to_failed": len(broke),
        "worst": sorted((r for r in rows if r["delta"] is not None),
                        key=lambda r: r["delta"])[:12],
        "passed_to_failed_shots": [r["shot"] for r in broke],
        "rows": rows,
    }
    if args.out:
        pathlib.Path(args.out).write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print("TOOLVSBUILDER " + json.dumps(
        {k: v for k, v in payload.items() if k != "rows"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
