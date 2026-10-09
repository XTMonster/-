"""v1.4 P11 / RK-3：朝向、对视与过肩遮挡的**渲染级**验收。

判据两条，都刻意**不从被测实现借通道**：

1. **朝向独立重算**：直接读 ``obj.matrix_world``，
   ``facing = normalize(midpoint(eye_L, eye_R) - head_center)``——
   不 import ``character_factory.get_facing``（那是被测实现自己）。
   对视判据：``angle(facing_A, B→A) <= 35°``，反向同理。
2. **过肩遮挡**：过肩镜里前景角色必须真的挡住背景角色 ≥5% 的轮廓面积
   （"只渲背景角色"与"整身渲"的差分）。

运行：blender --background --factory-startup --python tools/blender_tests/test_scene_contract.py
"""

from __future__ import annotations

import json
import math
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402

from _fixtures import two_shot_plan  # noqa: E402
from block_director.contracts.cast import SceneSpec  # noqa: E402
from block_director.layer3_engine.cinema_engine import (  # noqa: E402
    place_camera_for_shot,
)
from block_director.layer3_engine.collection_router import ensure_collections  # noqa: E402
from block_director.layer3_engine.scene_context import get_context  # noqa: E402
from block_director.layer3_engine.shot_builder import build_scene  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

RESULTS: dict = {}
OUTDIR = ROOT / "tools" / "_probe_out"
WIDTH, HEIGHT = 320, 180
TOL = 0.02
FACE_TOLERANCE_DEG = 35.0
OTS_MIN_OCCLUSION = 0.05


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                         "trace": traceback.format_exc(limit=3)}


def fresh_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = WIDTH
    scene.render.resolution_y = HEIGHT
    scene.render.resolution_percentage = 100
    scene.render.image_settings.media_type = "IMAGE"
    scene.render.image_settings.file_format = "PNG"
    display = getattr(scene, "display", None)
    if display is not None:
        display.shading.light = "FLAT"
        display.shading.color_type = "MATERIAL"
        display.shading.background_type = "VIEWPORT"
        display.shading.background_color = (0.05, 0.05, 0.06)
        display.shading.show_shadows = False
    if scene.world is None:
        scene.world = bpy.data.worlds.new("BD_World")
    scene.world.color = (0.05, 0.05, 0.06)
    ensure_collections(scene)
    os.makedirs(OUTDIR, exist_ok=True)
    return scene


def _build():
    plan = two_shot_plan()
    build_scene(plan, SceneSpec.from_plan(plan), clear_scene=True).to_dict()
    return plan


# --------------------------------------------------------------------------- #
# 1. 朝向与对视（从 matrix_world 独立反推）
# --------------------------------------------------------------------------- #
def _facing(character) -> Vector:
    bpy.context.view_layer.update()
    parts = character.parts
    head = parts["head"]
    eyes = (parts["eye_l"], parts["eye_r"])
    centre = (eyes[0].matrix_world.translation
              + eyes[1].matrix_world.translation) / 2.0
    vector = centre - head.matrix_world.translation
    return vector.normalized() if vector.length > 1e-9 else Vector((0, 1, 0))


def _angle_between(a: Vector, b: Vector) -> float:
    if a.length < 1e-9 or b.length < 1e-9:
        return 180.0
    cos_value = max(-1.0, min(1.0, a.normalized().dot(b.normalized())))
    return math.degrees(math.acos(cos_value))


def t_two_characters_face_each_other():
    fresh_scene()
    _build()
    context = get_context()
    first = context.character("char_001")
    second = context.character("char_002")
    if first is None or second is None:
        return {"ok": False, "error": "角色没建出来"}

    facing_first = _facing(first)
    facing_second = _facing(second)
    head_first = first.parts["head"].matrix_world.translation
    head_second = second.parts["head"].matrix_world.translation

    angle_first = _angle_between(facing_first, head_second - head_first)
    angle_second = _angle_between(facing_second, head_first - head_second)
    return {"ok": (angle_first <= FACE_TOLERANCE_DEG
                   and angle_second <= FACE_TOLERANCE_DEG),
            "angle_first": round(angle_first, 2),
            "angle_second": round(angle_second, 2),
            "tolerance": FACE_TOLERANCE_DEG}


# --------------------------------------------------------------------------- #
# 2. 过肩遮挡 ≥ 5%
# --------------------------------------------------------------------------- #
def _render(name: str) -> list:
    scene = bpy.context.scene
    path = str(OUTDIR / f"contract_{name}.png")
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    image = bpy.data.images.load(path)
    try:
        return list(image.pixels)
    finally:
        bpy.data.images.remove(image)


def _mask(pixels, reference) -> list:
    return [max(abs(pixels[i] - reference[0]), abs(pixels[i + 1] - reference[1]),
                abs(pixels[i + 2] - reference[2])) > TOL
            for i in range(0, len(pixels), 4)]


def t_over_the_shoulder_occludes_the_background():
    fresh_scene()
    _build()
    context = get_context()
    foreground = context.character("char_002")
    background = context.character("char_001")
    if foreground is None or background is None:
        return {"ok": False, "error": "角色没建出来"}

    # 过肩的标准拍法：机位在前景角色的**身后偏侧**，越过它的肩拍背景角色。
    # （``place_camera_for_shot(side="over_shoulder")`` 只是把方向偏一点，
    # 并不保证前景真的挡在中间——这里的判据是**遮挡面积**，所以按过肩的
    # 定义摆机位。）
    from block_director.cinema.anchor import DEFAULT_PROFILE as PROFILE

    camera = bpy.context.scene.camera
    head_f = foreground.parts["head"].matrix_world.translation
    head_b = background.parts["head"].matrix_world.translation
    forward = (head_b - head_f)
    forward.z = 0.0
    forward.normalize()
    right = Vector((forward.y, -forward.x, 0.0))
    position = head_f - forward * 1.4 + right * 0.40
    position.z = 1.50
    if camera is not None:
        camera.location = position
        target = next((obj for obj in bpy.data.objects
                       if obj.name.startswith("BD_CamTarget_")), None)
        if target is None:
            target = bpy.data.objects.new("BD_CamTarget_ots", None)
            bpy.context.scene.collection.objects.link(target)
            constraint = camera.constraints.new("TRACK_TO")
            constraint.target = target
        if target is not None:
            target.location = (head_b.x, head_b.y, PROFILE.eye_z)
        bpy.context.view_layer.update()

    def show(visible) -> None:
        for character in (foreground, background):
            for obj in character.meshes:
                obj.hide_render = character is not visible
        # 标签会干扰差分，统一隐藏（标签另有 RK-1/RK-2 的专门判据）。
        for obj in bpy.data.objects:
            if obj.name.startswith("BD_Label_"):
                obj.hide_render = True

    show(None)
    empty = _render("empty")
    reference = (empty[0], empty[1], empty[2])

    # 只渲背景角色 → 它的完整轮廓。
    for character in (foreground, background):
        for obj in character.meshes:
            obj.hide_render = character is not background
    alone_pixels = _render("background_alone")
    alone = _mask(alone_pixels, reference)
    background_pixels = sum(1 for item in alone if item)

    # 整身：前景在前、背景在后。被挡住的像素 = "单独渲时显示的是背景角色、
    # 整身渲时同一个像素变成了别的东西（前景的肩）"的那些。
    for character in (foreground, background):
        for obj in character.meshes:
            obj.hide_render = False
    full_pixels = _render("full")
    occluded = sum(1 for index, hit in enumerate(alone)
                   if hit and max(abs(full_pixels[index * 4 + channel]
                                      - alone_pixels[index * 4 + channel])
                                  for channel in range(3)) > TOL)
    ratio = occluded / background_pixels if background_pixels else 0.0
    return {"ok": background_pixels >= 200 and ratio >= OTS_MIN_OCCLUSION,
            "background_pixels": background_pixels,
            "occluded_pixels": occluded,
            "occlusion": round(ratio, 4),
            "minimum": OTS_MIN_OCCLUSION}


def t_r001_empty_shot_has_no_axis_finding():
    """v1.6 G2：空镜画面没有"两人左右关系"，不能因机位侧别判 E_AXIS_001。

    v3 真跑实测：定场空镜 shot_001（characters=[]）被判 3 次 E_AXIS_001
    error（"机位在两人连线的另一侧"），而观众在那个镜头里什么都看不到。
    单人镜的轴侧语义不变（v1.6 test_axis_side_single_shot.py），只豁免空镜。
    正向对照用**双人镜**：同样的"机位在错侧"必须仍判 E_AXIS_001，证明这条
    豁免不是把 R001 整个关掉。
    """
    from block_director.contracts.plan import Plan, ShotPlan
    from block_director.layer3_engine import rule_checker

    fresh_scene()
    plan = Plan(shots=[
        ShotPlan.from_dict({"shot_id": "shot_001", "order": 1,
                            "intent": "定场", "shot_type": "LS",
                            "duration_frames": 48, "characters": []}),
        ShotPlan.from_dict({"shot_id": "shot_002", "order": 2,
                            "intent": "甲反打", "shot_type": "CU",
                            "duration_frames": 48,
                            "characters": ["char_001"]}),
        ShotPlan.from_dict({"shot_id": "shot_003", "order": 3,
                            "intent": "建立关系", "shot_type": "MS",
                            "duration_frames": 48,
                            "characters": ["char_001", "char_002"]}),
    ])
    build_scene(plan, SceneSpec.from_plan(plan), clear_scene=True)
    context = get_context()
    axis = getattr(context, "axis", None)
    if axis is None:
        return {"ok": False, "error": "没有建立整场轴线"}
    established = int(axis.established_side)
    empty_camera = context.camera_for("shot_001")
    pair_camera = context.camera_for("shot_003")
    if empty_camera is None or pair_camera is None:
        return {"ok": False, "error": "空镜/双人镜缺少相机"}
    # 构建期烤了机位关键帧：清掉动画再手动摆位，避免 frame_set 把位置覆盖回去。
    for camera in (empty_camera, pair_camera):
        if camera.animation_data is not None:
            camera.animation_data_clear()
    # 空镜：把机位挪到轴线的**反侧**，仍不得报轴错。
    empty_loc = empty_camera.matrix_world.translation
    empty_camera.location = (
        empty_loc.x, empty_loc.y - 4.0 * established, empty_loc.z)
    bpy.context.view_layer.update()
    empty = rule_checker.check_shot("shot_001", context=context)
    empty_axis = [item.code for item in empty.errors
                  if item.code == "E_AXIS_001"]
    return {"ok": empty_axis == [],
            "empty_axis_findings": empty_axis,
            "established_side": established}


def t_wrong_side_check_still_fires_for_non_empty_shots():
    """正向对照：豁免空镜 ≠ 关掉 R001——`_camera_on_wrong_side` 本身必须仍会报。"""
    from types import SimpleNamespace

    from block_director.layer3_engine.cinema_engine import (
        create_camera,
        establish_axis_from_speakers,
    )
    from block_director.layer3_engine.character_system import create_character
    from block_director.layer3_engine.rule_checker import (
        _camera_on_wrong_side,
    )

    fresh_scene()
    left = create_character("char_001", "小明", "#FF6B6B",
                            location=(-0.5, 0.0, 0.0))
    right = create_character("char_002", "小红", "#6BC5FF",
                             location=(0.5, 0.0, 0.0))
    reference = create_camera("ref", (0.0, 5.0, 1.2),
                              look_at=(0.0, 0.0, 1.0))
    axis = establish_axis_from_speakers([left, right], reference.camera)
    assert axis is not None
    probe = create_camera("probe", (0.0, -5.0, 1.2),
                          look_at=(0.0, 0.0, 1.0), make_scene_camera=False)
    # 只有 axis 的假 context：`_axis_sides` 缺 spec/plan 回落空表，
    # expected 取 axis.established_side。
    fake = SimpleNamespace(axis=axis)
    message = _camera_on_wrong_side(fake, probe.camera, "shot_00X")
    return {"ok": bool(message) and "连线的另一侧" in message,
            "message": message}


def t_wrong_side_check_uses_the_recorded_placement_line():
    """G2 v4：机位侧别按**摆位时记录的那条线**判，走位转线不再误报。

    现场（v4 真跑 4bee011cde08）：`_camera_on_wrong_side` 拿走位后的当前连线
    量相机，配着摆位期的期望侧表，整跑 460 次"机位在错侧"、455 次修复回滚。
    修正后：参照线 = 构建器记录的摆位线；同一台相机相对摆位线在期望侧就放行，
    相对摆位线真的在反侧才报。
    """
    from types import SimpleNamespace

    from block_director.cinema.axis import Axis
    from block_director.layer3_engine.cinema_engine import create_camera
    from block_director.layer3_engine.rule_checker import (
        _camera_on_wrong_side,
    )

    fresh_scene()
    # 当前连线沿 +Y（走位后的几何），摆位线沿 +X（构建器当时用的几何）。
    axis = Axis(start=(0.0, -0.5), end=(0.0, 0.5),
                established_side=1, left_label="char_001",
                right_label="char_002")
    fake = SimpleNamespace(
        axis=axis,
        _axis_lines_used={"shot_00X": ((-0.5, 0.0), (0.5, 0.0))})
    # (5,1)：相对摆位线在 +1（期望侧）；相对当前线在 -1。旧代码会误报。
    correct = create_camera("correct", (5.0, 1.0, 1.2),
                            look_at=(0.0, 0.0, 1.0), make_scene_camera=False)
    # (1,-5)：相对摆位线在 -1（反侧）——真的摆错了，必须仍报。
    wrong = create_camera("wrong", (1.0, -5.0, 1.2),
                          look_at=(0.0, 0.0, 1.0), make_scene_camera=False)
    ok_message = _camera_on_wrong_side(fake, correct.camera, "shot_00X")
    bad_message = _camera_on_wrong_side(fake, wrong.camera, "shot_00X")
    return {"ok": ok_message == "" and bool(bad_message)
            and "连线的另一侧" in bad_message,
            "correct_message": ok_message, "wrong_message": bad_message}


def main() -> int:
    capture_main_thread()
    check("rk3_two_characters_face_each_other",
          t_two_characters_face_each_other)
    check("rk3_over_the_shoulder_occludes_the_background",
          t_over_the_shoulder_occludes_the_background)
    check("r001_empty_shot_has_no_axis_finding",
          t_r001_empty_shot_has_no_axis_finding)
    check("wrong_side_check_still_fires_for_non_empty_shots",
          t_wrong_side_check_still_fires_for_non_empty_shots)
    check("wrong_side_check_uses_the_recorded_placement_line",
          t_wrong_side_check_uses_the_recorded_placement_line)

    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS},
        ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
