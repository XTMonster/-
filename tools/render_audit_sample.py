"""渲染一张"辅助物齐全但不入画"的样张（Phase 3 收尾验证）。

场景里同时存在：轴线可视化、两个中文标签、相机目标 Empty。
它们都必须**不出现**在渲染结果里——这是参考视频能被 AI 视频模型使用的前提。

运行：
  blender --background --factory-startup --python tools/render_audit_sample.py
产物：tools/_probe_out/audit_sample.png + 一行 AUDIT_SAMPLE {json}
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
from block_director.layer3_engine.cinema_engine import (  # noqa: E402
    establish_axis_from_speakers,
    place_camera_for_shot,
    visualize_axis,
)
from block_director.layer3_engine.collection_router import (  # noqa: E402
    audit_renderable_objects,
    ensure_collections,
)
from block_director.layer3_engine.scene_executor import build_environment  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

OUTDIR = ROOT / "tools" / "_probe_out"
PRESETS = (("clay", "STUDIO"), ("flat", "FLAT"))


def main() -> int:
    capture_main_thread()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 640
    scene.render.resolution_y = 360
    scene.render.resolution_percentage = 100
    scene.render.image_settings.media_type = "IMAGE"
    scene.render.image_settings.file_format = "PNG"
    display = getattr(scene, "display", None)
    if display is not None:
        display.shading.color_type = "MATERIAL"
        display.shading.background_type = "VIEWPORT"
        display.shading.background_color = (0.10, 0.11, 0.14)
    if scene.world is None:
        scene.world = bpy.data.worlds.new("BD_World")

    ensure_collections(scene)
    build_environment(ground_size=(20.0, 20.0), lighting="clay_studio")
    left = create_character("char_001", "小明", "#FF6B6B", location=(-0.75, 0, 0))
    right = create_character("char_002", "小红", "#6BC5FF", location=(0.75, 0, 0))
    create_label(left, "小明")
    create_label(right, "小红")

    blender = MotionBlender(left)
    blender.add("nod", 1, 48, cycles=2)
    blender.bake()

    bundle = place_camera_for_shot("sample", (0.0, 0.0, 0.0), shot_type="MS",
                                   side="front")[0]
    axis = establish_axis_from_speakers([left, right], bundle.camera)
    visualize_axis(axis)

    os.makedirs(OUTDIR, exist_ok=True)
    rendered = {}
    for name, shading in PRESETS:
        if display is not None:
            display.shading.light = shading
        path = str(OUTDIR / f"audit_sample_{name}.png")
        scene.frame_set(12)
        scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        rendered[name] = path

    leaks = audit_renderable_objects()
    print("AUDIT_SAMPLE " + json.dumps(
        {"rendered": rendered, "leaks": leaks,
         "axis_visible_in_render": leaks != []},
        ensure_ascii=False))
    return 0 if not leaks else 1


if __name__ == "__main__":
    sys.exit(main())
