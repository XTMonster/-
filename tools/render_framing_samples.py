"""渲染同一角色的不同景别，用于人工核对取景解算（Phase 3）。

运行：
  blender --background --factory-startup --python tools/render_framing_samples.py
产物：tools/_probe_out/framing_<景别>.png
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402

from block_director.layer3_engine.character_system import (  # noqa: E402
    MotionBlender,
    create_character,
    create_label,
)
from block_director.layer3_engine.cinema_engine import place_camera_for_shot  # noqa: E402
from block_director.layer3_engine.collection_router import (  # noqa: E402
    audit_renderable_objects,
    ensure_collections,
)
from block_director.layer3_engine.scene_executor import build_environment  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

OUTDIR = ROOT / "tools" / "_probe_out"
SHOTS = ("CU", "MCU", "MS", "MLS", "LS")


def main() -> int:
    capture_main_thread()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 480
    scene.render.resolution_y = 270
    scene.render.resolution_percentage = 100
    scene.render.image_settings.media_type = "IMAGE"
    scene.render.image_settings.file_format = "PNG"
    display = getattr(scene, "display", None)
    if display is not None:
        display.shading.light = "FLAT"
        display.shading.color_type = "MATERIAL"
        display.shading.background_type = "VIEWPORT"
        display.shading.background_color = (0.08, 0.08, 0.10)
    if scene.world is None:
        scene.world = bpy.data.worlds.new("BD_World")
    ensure_collections(scene)

    build_environment(ground_size=(20.0, 20.0), lighting="clay_studio")
    left = create_character("char_001", "小明", "#FF6B6B", location=(-0.45, 0, 0))
    right = create_character("char_002", "小红", "#6BC5FF", location=(0.45, 0, 0))
    create_label(left, "小明")
    create_label(right, "小红")

    # 让其中一个角色抬手指路，验证动作与取景能同时生效
    blender = MotionBlender(left)
    blender.add("nod", 1, 48, cycles=2)
    blender.bake()

    os.makedirs(OUTDIR, exist_ok=True)
    rendered = {}
    for shot in SHOTS:
        # 以两名角色的中间点为被摄中心
        bundle, solution = place_camera_for_shot(
            f"sample_{shot}", (0.0, 0.0, 0.0), facing=(0.0, 1.0, 0.0),
            shot_type=shot, side="front")
        path = str(OUTDIR / f"framing_{shot}.png")
        scene.frame_set(12)
        scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        rendered[shot] = {
            "file": path,
            "camera": tuple(round(v, 3) for v in bundle.camera.location),
            "distance": round(solution.distance, 3),
            "lens": solution.lens,
        }

    print("FRAMING_SAMPLES " + json.dumps(
        {"rendered": rendered, "audit": audit_renderable_objects()},
        ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
