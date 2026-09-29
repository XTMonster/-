"""Phase 3 集成测试：取景解算真的把被摄者框进画面（执行文档 v1.2 §10）。

运行：
  blender --background --factory-startup --python tools/blender_tests/test_phase3_framing.py
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
from bpy_extras.object_utils import world_to_camera_view  # noqa: E402
from mathutils import Vector  # noqa: E402

from block_director.layer3_engine.character_system import create_character  # noqa: E402
from block_director.layer3_engine.cinema_engine import (  # noqa: E402
    create_camera,
    place_camera_for_shot,
)
from block_director.layer3_engine.collection_router import ensure_collections  # noqa: E402
from block_director.cinema.anchor import DEFAULT_PROFILE as PROFILE  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

RESULTS: dict = {}
OUTDIR = ROOT / "tools" / "_probe_out"
# v1.4 P10（§1.6 #14）：这三个常量必须是 §2.1 的 profile——旧值 1.45/0.75
# 是 v1.3 的几何，不会变红，只会**一直量错人**。
HEAD_TOP = PROFILE.head_top_z
FEET = PROFILE.ground_z
HEAD_CENTER = PROFILE.head_center_z
HEAD_BOTTOM = PROFILE.head_center_z - PROFILE.head_r


def fresh_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 320
    scene.render.resolution_y = 180
    scene.render.resolution_percentage = 100
    scene.render.image_settings.media_type = "IMAGE"
    scene.render.image_settings.file_format = "PNG"
    ensure_collections(scene)
    return scene


def project(z: float):
    """把角色中轴线上高度 z 的点投影到归一化视口坐标。"""
    scene = bpy.context.scene
    bpy.context.view_layer.update()
    co = world_to_camera_view(scene, scene.camera, Vector((0.0, 0.0, z)))
    return round(co.x, 4), round(co.y, 4)


def in_frame(z: float) -> bool:
    x, y = project(z)
    return 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                         "trace": traceback.format_exc(limit=3)}


# --------------------------------------------------------------------------- #
# 1. 景别真的决定取景：MS 只框上半身，LS 框全身
# --------------------------------------------------------------------------- #
def t_shot_type_controls_framing():
    fresh_scene()
    create_character("char_001", "小明", "#FF6B6B")

    place_camera_for_shot("ms", (0.0, 0.0, 0.0), shot_type="MS")
    ms_head, ms_feet = in_frame(HEAD_TOP), in_frame(FEET)
    place_camera_for_shot("ls", (0.0, 0.0, 0.0), shot_type="LS")
    ls_head, ls_feet = in_frame(HEAD_TOP), in_frame(FEET)

    ok = ms_head and not ms_feet and ls_head and ls_feet
    return {"ok": ok, "ms": {"head": ms_head, "feet": ms_feet},
            "ls": {"head": ls_head, "feet": ls_feet}}


# --------------------------------------------------------------------------- #
# 2. 特写确实更紧（画面里头部占比更大）
# --------------------------------------------------------------------------- #
def t_close_up_fills_more_of_frame():
    fresh_scene()
    create_character("char_001", "小明", "#FF6B6B")

    def head_span(shot_type: str) -> float:
        place_camera_for_shot(shot_type.lower(), (0.0, 0.0, 0.0), shot_type=shot_type)
        top = project(HEAD_TOP)[1]
        chin = project(HEAD_BOTTOM)[1]
        return round(top - chin, 4)

    span_cu = head_span("CU")
    span_ms = head_span("MS")
    return {"ok": span_cu > span_ms > 0,
            "head_span_cu": span_cu, "head_span_ms": span_ms}


# --------------------------------------------------------------------------- #
# 3. 机位方向相对角色朝向
# --------------------------------------------------------------------------- #
def t_camera_direction_follows_facing():
    fresh_scene()
    create_character("char_001", "小明", "#FF6B6B")

    bundle_front, solution_front = place_camera_for_shot(
        "front", (0.0, 0.0, 0.0), facing=(0.0, 1.0, 0.0), shot_type="MS",
        side="front")
    bundle_left, _ = place_camera_for_shot(
        "left", (0.0, 0.0, 0.0), facing=(0.0, 1.0, 0.0), shot_type="MS",
        side="left")
    front_x, front_y, _ = solution_front.position
    left_x, _, _ = bundle_left.camera.location
    return {"ok": front_y > 0 and abs(front_x) < 1e-6 and left_x < 0,
            "front_position": tuple(round(v, 4) for v in solution_front.position),
            "left_x": round(left_x, 4)}


# --------------------------------------------------------------------------- #
# 4. 室内 far 机位不得穿墙（§10.1 的可用性前提）
# --------------------------------------------------------------------------- #
def t_room_clamp_keeps_camera_inside():
    fresh_scene()
    create_character("char_001", "小明", "#FF6B6B")
    # v1.4 P10：取景距离变小（几何 1.70 + 按 profile 重算的画面高度）之后，
    # ±6 m 的房间已经装得下 ELS 的 4.6 m 机位——改用 ±4 m 的室内才能
    # 真正测到"夹回房间内"这条分支。
    room = (-4.0, 4.0, -4.0, 4.0)
    bundle, solution = place_camera_for_shot(
        "wide", (0.0, 0.0, 0.0), shot_type="ELS", side="front", room=room)
    x, y, _ = bundle.camera.location
    inside = room[0] <= x <= room[1] and room[2] <= y <= room[3]
    return {"ok": inside and solution.clamped and bool(solution.warnings),
            "camera": (round(x, 4), round(y, 4)),
            "requested_distance": round(solution.distance, 3),
            "warnings": solution.warnings}


# --------------------------------------------------------------------------- #
# 5. 渲染出的画面里确实有角色（端到端）
# --------------------------------------------------------------------------- #
def render_luma(path: str) -> float:
    scene = bpy.context.scene
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


def t_solve_then_render():
    scene = fresh_scene()
    character = create_character("char_001", "小明", "#FF6B6B")
    display = getattr(scene, "display", None)
    if display is not None:
        display.shading.light = "FLAT"
        display.shading.color_type = "MATERIAL"
        display.shading.background_type = "VIEWPORT"
        display.shading.background_color = (0.05, 0.05, 0.06)
    if scene.world is None:
        scene.world = bpy.data.worlds.new("BD_World")
    scene.world.color = (0.05, 0.05, 0.06)

    os.makedirs(OUTDIR, exist_ok=True)
    place_camera_for_shot("ms", (0.0, 0.0, 0.0), shot_type="MS", side="front")
    solved_luma = render_luma(str(OUTDIR / "phase3_solved_ms.png"))

    # 正对照：把角色移出渲染，画面必须变暗
    for obj in character.meshes:
        obj.hide_render = True
    empty_luma = render_luma(str(OUTDIR / "phase3_no_subject.png"))

    return {"ok": solved_luma > empty_luma + 0.02,
            "luma_solved": solved_luma,
            "luma_without_subject": empty_luma,
            "camera": tuple(round(v, 3) for v in scene.camera.location)}


def main() -> int:
    capture_main_thread()
    check("shot_type_controls_framing", t_shot_type_controls_framing)
    check("close_up_fills_more_of_frame", t_close_up_fills_more_of_frame)
    check("camera_direction_follows_facing", t_camera_direction_follows_facing)
    check("room_clamp_keeps_camera_inside", t_room_clamp_keeps_camera_inside)
    check("solve_then_render", t_solve_then_render)

    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS}, ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
