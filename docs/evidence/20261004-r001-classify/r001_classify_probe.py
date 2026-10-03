"""GLM 5.3 consult F4: are the axis crossings script-required or generated?

For every shot whose audit reports R001, print: the character(s) standing on the far
side of the established axis, where they stand relative to the line, the script's
own wording for that shot, and the walk targets that put them there.

  blender --background --factory-startup --python work/_r001_classify_probe.py -- \
      --project docs/evidence/20261004_chunked_long12/project \
      --script fixtures/script_long_61.md
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def script_lines(path: str) -> dict:
    """`{镜号: (画面内容, 角色, 拍摄手法)}`——只读 fixture 的原文，不做解释。"""
    text = pathlib.Path(path).read_text(encoding="utf-8")
    out = {}
    for block in re.split(r"^镜号：", text, flags=re.M)[1:]:
        lines = block.splitlines()
        if not lines:
            continue
        try:
            number = int(lines[0].strip())
        except ValueError:
            continue
        fields = {}
        for line in lines[1:]:
            for key in ("画面内容", "角色", "拍摄手法", "拍摄距离"):
                if line.startswith(key + "："):
                    fields[key] = line.split("：", 1)[1].strip()
        out[number] = fields
    return out


def main() -> int:
    argv = sys.argv
    rest = argv[argv.index("--") + 1:] if "--" in argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--script", default="fixtures/script_long_61.md")
    parser.add_argument("--out", default="")
    args = parser.parse_args(rest)

    import block_director
    block_director.register()
    import bpy

    from block_director.layer2_sdl import sdl_to_plan, sdl_to_spec
    from block_director.layer3_engine.scene_context import get_context
    from block_director.layer3_engine.shot_auditor import BpyShotAuditor
    from block_director.layer3_engine.shot_builder import build_scene
    from block_director.layer9_persistence import load_project

    loaded = load_project(pathlib.Path(os.path.abspath(args.project)))
    plan = sdl_to_plan(loaded.sdl)
    spec = sdl_to_spec(loaded.sdl)
    build_scene(plan, spec=spec, clear_scene=True)
    context = get_context()
    scene = bpy.context.scene
    auditor = BpyShotAuditor()
    script = script_lines(args.script)
    axis = context.axis

    rows = []
    for shot in plan.shots:
        start, _end = context.schedule.get(shot.shot_id, (1, 1))
        scene.frame_set(int(start))
        bpy.context.view_layer.update()
        result = auditor.audit(shot.shot_id)
        if not any(item.rule == "R001" and item.severity == "error"
                   for item in result.errors):
            continue
        number = int(getattr(shot, "declared_shot_number", 0) or shot.order)
        crossing = []
        for cid in shot.characters:
            character = context.character(cid)
            if character is None or character.root is None or axis is None:
                continue
            loc = character.root.matrix_world.translation
            side = axis.side_of((float(loc.x), float(loc.y)))
            if side != 0 and side != int(axis.established_side):
                crossing.append({
                    "character": cid,
                    "xy": [round(float(loc.x), 2), round(float(loc.y), 2)],
                    "side": side,
                })
        walks = []
        for raw in shot.actions or []:
            if str(raw.get("action_type") or "") not in ("walk_to", "run_to"):
                continue
            params = dict(raw.get("params") or {})
            target = params.get("target_position") or raw.get("target_position")
            walks.append({"who": str(raw.get("character_id") or ""),
                          "target": [round(float(v), 2) for v in (target or [])]})
        rows.append({
            "shot": shot.shot_id, "script_number": number,
            "shot_type": str(shot.shot_type),
            "crossing": crossing, "walks_this_shot": walks,
            "script_picture": (script.get(number, {}) or {}).get("画面内容", ""),
            "script_cast": (script.get(number, {}) or {}).get("角色", ""),
        })

    payload = {
        "project": str(args.project),
        "axis": axis.to_dict() if axis is not None else None,
        "r001_shot_count": len(rows),
        "with_crossing": sum(1 for row in rows if row["crossing"]),
        "with_walk_this_shot": sum(1 for row in rows if row["walks_this_shot"]),
        "rows": rows,
    }
    if args.out:
        pathlib.Path(args.out).write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print("R001CLASS " + json.dumps({k: v for k, v in payload.items() if k != "rows"},
                                    ensure_ascii=False))
    for row in rows[:12]:
        print("ROW " + json.dumps({
            "shot": row["shot"], "script_number": row["script_number"],
            "type": row["shot_type"], "crossing": row["crossing"],
            "walks": row["walks_this_shot"],
            "script": row["script_picture"][:30]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
