"""为什么 `describe()` 数到的关键帧是 0？直接看这台相机身上有什么。"""

from __future__ import annotations

import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    import block_director
    block_director.register()
    import bpy

    from block_director.layer2_sdl import sdl_to_plan, sdl_to_spec
    from block_director.layer3_engine.scene_context import get_context
    from block_director.layer3_engine.shot_builder import build_scene
    from block_director.layer9_persistence import load_project
    from block_director.utils.blender_compat import action_fcurves

    loaded = load_project(pathlib.Path(os.path.abspath(
        "docs/evidence/20261004_chunked_long16/project")))
    plan = sdl_to_plan(loaded.sdl)
    spec = sdl_to_spec(loaded.sdl)
    build_scene(plan, spec=spec, clear_scene=True)
    context = get_context()
    out = {}
    for shot_id in ("shot_044", "shot_001"):
        camera = context.cameras.get(shot_id)
        anim = camera.animation_data
        action = anim.action if anim else None
        named = bpy.data.objects.get(f"BD_Cam_{shot_id}")
        named_action = (named.animation_data.action
                        if named is not None and named.animation_data else None)
        out[shot_id] = {
            "has_anim": anim is not None,
            "action": getattr(action, "name", None),
            "layers": len(getattr(action, "layers", []) or []),
            "fcurves": len(action_fcurves(action)),
            "location": [round(float(v), 3) for v in camera.location],
            "same_object_as_named": named is camera,
            "named_fcurves": len(action_fcurves(named_action)),
            "anim_objects": sorted(o.name for o in bpy.data.objects
                                   if o.animation_data is not None),
            "all_actions": sorted(a.name for a in bpy.data.actions),
        }
    print("KF " + json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
