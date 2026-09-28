"""Phase 4 集成测试：分镜计划真的落成场景（执行文档 v1.2 §7.1 阶段 B2）。

运行：
  blender --background --factory-startup --python tools/blender_tests/test_phase4_build.py
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402

from block_director.contracts.plan import Plan, ShotPlan  # noqa: E402
from block_director.layer3_engine.shot_builder import (  # noqa: E402
    BpySceneBuilder,
    build_scene,
)
from block_director.layer3_engine.collection_router import ensure_collections  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fixtures import two_shot_plan  # noqa: E402

RESULTS: dict = {}
OUTDIR = ROOT / "tools" / "_probe_out"


def fresh_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 320
    scene.render.resolution_y = 180
    scene.render.resolution_percentage = 100
    scene.render.image_settings.media_type = "IMAGE"
    scene.render.image_settings.file_format = "PNG"
    display = getattr(scene, "display", None)
    if display is not None:
        display.shading.light = "STUDIO"
        display.shading.color_type = "MATERIAL"
        display.shading.background_type = "VIEWPORT"
        display.shading.background_color = (0.10, 0.11, 0.14)
    if scene.world is None:
        scene.world = bpy.data.worlds.new("BD_World")
    ensure_collections(scene)
    return scene


def demo_plan(actions: bool = True) -> Plan:
    return two_shot_plan(with_actions=actions)


def render_luma(name: str, frame: int) -> float:
    scene = bpy.context.scene
    os.makedirs(OUTDIR, exist_ok=True)
    path = str(OUTDIR / f"phase4_{name}.png")
    scene.frame_set(frame)
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    if not os.path.exists(path):
        return -1.0
    image = bpy.data.images.load(path)
    try:
        pixels = list(image.pixels)
    finally:
        bpy.data.images.remove(image)
    rgb = [v for i, v in enumerate(pixels) if i % 4 != 3]
    return round(sum(rgb) / max(len(rgb), 1), 5)


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                         "trace": traceback.format_exc(limit=3)}


# --------------------------------------------------------------------------- #
# 1. 场景真的被建出来：角色 / 相机 / 剪切标记 / 帧范围
# --------------------------------------------------------------------------- #
def t_build_creates_scene():
    scene = fresh_scene()
    summary = build_scene(demo_plan())

    markers = {m.name: m for m in scene.timeline_markers}
    markers_have_cameras = all(m.camera is not None for m in markers.values())
    characters = [o for o in bpy.data.objects if o.name.startswith("BD_Char_")]
    cameras = [o for o in bpy.data.objects if o.type == "CAMERA"]

    ok = (summary.characters == 2 and summary.cameras == 2
          and len(markers) == 2 and markers_have_cameras
          and scene.frame_start == 1 and scene.frame_end == 216
          and len(characters) >= 14 and len(cameras) == 2)
    return {"ok": ok, "summary": summary.to_dict(),
            "markers": sorted(markers), "frame_range": [scene.frame_start, scene.frame_end],
            "character_objects": len(characters), "cameras": len(cameras)}


# --------------------------------------------------------------------------- #
# 2. 两个镜头渲染出来确实不同（剪切生效）
# --------------------------------------------------------------------------- #
def t_shots_render_differently():
    fresh_scene()
    build_scene(demo_plan())
    first = render_luma("shot1", 24)
    second = render_luma("shot2", 150)
    return {"ok": abs(first - second) > 0.005 and first > 0.05,
            "luma_shot1_f24": first, "luma_shot2_f150": second}


# --------------------------------------------------------------------------- #
# 3. 动作被烘上去了，且摆位没被清零
# --------------------------------------------------------------------------- #
def t_motions_applied():
    scene = fresh_scene()
    build_scene(demo_plan())
    char1 = bpy.data.objects.get("BD_Char_char_001_Root")
    char2 = bpy.data.objects.get("BD_Char_char_002_Root")
    head1 = bpy.data.objects.get("BD_Char_char_001_HeadPivot")

    head_animated = head1 is not None and head1.animation_data is not None

    scene.frame_set(97)
    bpy.context.view_layer.update()
    start = tuple(round(v, 3) for v in char2.matrix_world.translation)
    scene.frame_set(156)
    bpy.context.view_layer.update()
    sat = tuple(round(v, 3) for v in char2.matrix_world.translation)

    placement_kept = abs(sat[0] - start[0]) < 0.01
    lowered = round(start[2] - sat[2], 3)
    return {"ok": head_animated and placement_kept and abs(lowered - 0.2) < 0.02,
            "head_animated": head_animated,
            "char2_start": start, "char2_sitting": sat,
            "drop": lowered, "placement_kept": placement_kept}


# --------------------------------------------------------------------------- #
# 4. 没有动作的镜头保持静止（不替 LLM 编造动作）
# --------------------------------------------------------------------------- #
def t_plan_without_actions_stays_static():
    scene = fresh_scene()
    summary = build_scene(demo_plan(actions=False))
    char1 = bpy.data.objects.get("BD_Char_char_001_Root")
    char2 = bpy.data.objects.get("BD_Char_char_002_Root")
    animated = any(o is not None and o.animation_data is not None
                   for o in (char1, char2))
    return {"ok": not animated and summary.keyframes == 0 and summary.motions == 0,
            "keyframes": summary.keyframes, "motions": summary.motions,
            "any_animation": animated}


# --------------------------------------------------------------------------- #
# 5. 构建器满足驱动器协议，摘要字段齐全
# --------------------------------------------------------------------------- #
def t_builder_protocol_and_summary():
    from block_director.layer5_orchestrator.builder import SceneBuilder

    fresh_scene()
    builder = BpySceneBuilder()
    payload = builder.build(demo_plan())
    expected = {"shots", "characters", "cameras", "motions", "keyframes",
                "total_frames", "warnings", "results"}
    return {"ok": isinstance(builder, SceneBuilder)
            and expected <= set(payload)
            and payload["shots"] == 2,
            "is_scene_builder": isinstance(builder, SceneBuilder),
            "keys": sorted(payload), "results": payload["results"]}


def main() -> int:
    capture_main_thread()
    check("build_creates_scene", t_build_creates_scene)
    check("shots_render_differently", t_shots_render_differently)
    check("motions_applied", t_motions_applied)
    check("plan_without_actions_stays_static", t_plan_without_actions_stays_static)
    check("builder_protocol_and_summary", t_builder_protocol_and_summary)

    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS}, ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
