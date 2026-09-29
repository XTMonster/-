"""Phase 2 集成测试：动作烘焙、动画可见性、冲突拒绝（执行文档 v1.2 §9.6 / §9.7）。

运行：
  blender --background --factory-startup --python tools/blender_tests/test_phase2_motion.py
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

from block_director.layer3_engine.character_system import (  # noqa: E402
    MotionBlender,
    PIVOT_Z,
    create_character,
)
from block_director.layer3_engine.cinema_engine import create_camera  # noqa: E402
from block_director.layer3_engine.collection_router import ensure_collections  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

RESULTS: dict = {}
OUTDIR = ROOT / "tools" / "_probe_out"


def fresh_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 160
    scene.render.resolution_y = 90
    scene.render.resolution_percentage = 100
    scene.render.image_settings.media_type = "IMAGE"
    scene.render.image_settings.file_format = "PNG"
    display = getattr(scene, "display", None)
    if display is not None:
        display.shading.light = "FLAT"
        display.shading.color_type = "MATERIAL"
        display.shading.background_type = "VIEWPORT"
        display.shading.background_color = (0.05, 0.05, 0.06)
    if scene.world is None:
        scene.world = bpy.data.worlds.new("BD_World")
    scene.world.color = (0.05, 0.05, 0.06)
    ensure_collections(scene)
    return scene


def render_luma(name: str, frame: int) -> float:
    scene = bpy.context.scene
    os.makedirs(OUTDIR, exist_ok=True)
    path = str(OUTDIR / f"phase2_{name}.png")
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


def _setup_character_scene():
    scene = fresh_scene()
    scene.frame_start, scene.frame_end = 1, 96
    character = create_character("char_001", "小明", "#FF6B6B",
                                 location=(0.0, 0.0, 0.0))
    create_camera("shot_001", (0.0, -6.0, 1.2), look_at=(0.0, 0.0, 0.9), lens=50.0)
    return scene, character


# --------------------------------------------------------------------------- #
# 1. 烘焙出关键帧
# --------------------------------------------------------------------------- #
def t_bake_creates_keyframes():
    scene, character = _setup_character_scene()
    blender = MotionBlender(character)
    blender.add("walk_to", 1, 48, from_=(0.0, 0.0, 0.0),
                target_position=(2.0, 0.0, 0.0), speed="walk")
    blender.add("nod", 1, 48, cycles=2)
    result = blender.bake()

    root_animated = character.root.animation_data is not None
    head_animated = character.head_pivot.animation_data is not None
    leg_animated = character.leg_pivots[0].animation_data is not None
    return {"ok": result.keyframes > 0 and root_animated and head_animated
            and leg_animated,
            "keyframes": result.keyframes, "frames": result.frames,
            "channels": result.channels,
            "root_animated": root_animated, "head_animated": head_animated,
            "leg_animated": leg_animated}


# --------------------------------------------------------------------------- #
# 2. 根节点真的随时间移动
# --------------------------------------------------------------------------- #
def t_root_moves_over_time():
    scene, character = _setup_character_scene()
    blender = MotionBlender(character)
    blender.add("walk_to", 1, 48, from_=(0.0, 0.0, 0.0),
                target_position=(2.0, 0.0, 0.0))
    blender.bake()

    scene.frame_set(1)
    x_start = round(character.root.matrix_world.translation.x, 4)
    scene.frame_set(48)
    x_end = round(character.root.matrix_world.translation.x, 4)
    scene.frame_set(24)
    x_mid = round(character.root.matrix_world.translation.x, 4)
    return {"ok": abs(x_start) < 0.01 and x_end > 1.9 and 0.05 < x_mid < 1.95,
            "x_start": x_start, "x_mid": x_mid, "x_end": x_end}


# --------------------------------------------------------------------------- #
# 3. 渲染出来的画面随动画变化（这才是"能动"的证据）
# --------------------------------------------------------------------------- #
def t_render_frames_differ():
    scene, character = _setup_character_scene()
    blender = MotionBlender(character)
    blender.add("walk_to", 1, 48, from_=(0.0, 0.0, 0.0),
                target_position=(2.0, 0.0, 0.0))
    blender.add("shake_head", 1, 48)
    blender.bake()

    luma_start = render_luma("frame_01", 1)
    luma_mid = render_luma("frame_24", 24)
    luma_end = render_luma("frame_48", 48)
    moved = abs(luma_end - luma_start) > 0.005
    distinct = len({luma_start, luma_mid, luma_end}) == 3
    return {"ok": moved and distinct,
            "luma": {"f01": luma_start, "f24": luma_mid, "f48": luma_end}}


# --------------------------------------------------------------------------- #
# 4. 语义冲突被拒绝（§9.7）
# --------------------------------------------------------------------------- #
def t_conflict_rejected():
    scene, character = _setup_character_scene()
    blender = MotionBlender(character)
    blender.add("walk_to", 1, 48, from_=(0, 0, 0), target_position=(2, 0, 0))
    blender.add("fall_down", 20, 60)
    problems = blender.validate()
    raised = False
    try:
        blender.bake()
    except ValueError:
        raised = True
    return {"ok": bool(problems) and raised,
            "problems": problems, "bake_raised": raised}


# --------------------------------------------------------------------------- #
# 5. 先坐后站精确回到地面（接管冻结语义的端到端验证）
# --------------------------------------------------------------------------- #
def t_sit_then_stand_returns_to_ground():
    scene, character = _setup_character_scene()
    blender = MotionBlender(character)
    blender.add("sit", 1, 24, drop=0.2)
    blender.add("stand", 25, 48, drop=0.2)
    blender.bake()

    def body_z(frame: int) -> float:
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        return round(character.body_pivot.matrix_world.translation.z, 4)

    z_start = body_z(1)
    z_sit = body_z(24)
    z_end = body_z(48)
    return {"ok": abs(z_start - PIVOT_Z["body"]) < 0.02
            and abs(z_sit - (PIVOT_Z["body"] - 0.2)) < 0.02
            and abs(z_end - PIVOT_Z["body"]) < 0.02,
            "z": {"start": z_start, "sitting": z_sit, "end": z_end},
            "expected": {"start": PIVOT_Z["body"], "sitting": PIVOT_Z["body"] - 0.2,
                         "end": PIVOT_Z["body"]}}


# --------------------------------------------------------------------------- #
# 6. 头部动作只动头（不污染根节点）
# --------------------------------------------------------------------------- #
def t_head_motion_is_isolated():
    scene, character = _setup_character_scene()
    blender = MotionBlender(character)
    blender.add("nod", 1, 24, cycles=2)
    blender.bake()

    angles = []
    for frame in (1, 7, 13, 19, 24):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        angles.append(round(character.head_pivot.rotation_euler[0], 4))
    root_moved = character.root.animation_data is not None
    return {"ok": len(set(angles)) > 1 and not root_moved,
            "head_pitch": angles, "root_animated": root_moved}


def t_bake_keeps_the_authored_facing():
    """v1.3：动作烘焙不得抹掉角色的身体朝向。

    v1.2 的 ``clear_animation`` 把 root 的 ``rotation_euler`` 也清零了，
    而 ``apply_motions`` 又在清除**之后**才读基姿态——于是角色第一次烘焙动作
    时，"创建时设定的朝向"就被抹掉，两人相对而立会一起弹回面朝 +Y。
    """
    scene = fresh_scene()
    scene.frame_start, scene.frame_end = 1, 48
    character = create_character("char_001", "小明", "#FF6B6B",
                                 location=(0.0, 0.0, 0.0),
                                 facing=(1.0, 0.0, 0.0))   # 面朝 +X
    create_camera("shot_001", (3.0, 0.0, 1.2), look_at=(0.0, 0.0, 0.9), lens=50.0)

    blender = MotionBlender(character)
    blender.add("nod", 1, 48, cycles=2)          # 只动头，不该动身体
    blender.bake()
    scene.frame_set(48)
    bpy.context.view_layer.update()

    from block_director.layer3_engine.character_system import get_facing
    facing = get_facing(character)
    return {"ok": facing[0] > 0.99 and abs(facing[1]) < 0.02,
            "facing": list(facing),
            "root_yaw": round(float(character.root.rotation_euler[2]), 4)}


def main() -> int:
    capture_main_thread()
    check("bake_creates_keyframes", t_bake_creates_keyframes)
    check("bake_keeps_the_authored_facing", t_bake_keeps_the_authored_facing)
    check("root_moves_over_time", t_root_moves_over_time)
    check("render_frames_differ", t_render_frames_differ)
    check("conflict_rejected", t_conflict_rejected)
    check("sit_then_stand_returns_to_ground", t_sit_then_stand_returns_to_ground)
    check("head_motion_is_isolated", t_head_motion_is_isolated)

    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS}, ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
