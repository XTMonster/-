"""缺陷 A（T5）Blender 探针：局部主体框实拍评分。

判据：
1. ``framing_target=character/part=hand`` 且机位对准手部时，构图分严格 >80，
   建议不再要求"整身入画"（与无局部语义的旧口径对照）；
2. ``framing_target=prop``（银币）在画内时 >80；
3. 银币移出画外时硬闸成立（≤20）。

运行：
  blender --background --factory-startup --python tools/blender_tests/test_local_subject_probe.py -- --out <dir>
"""

from __future__ import annotations

import json
import math
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402

from block_director.contracts.cast import SceneSpec  # noqa: E402
from block_director.contracts.plan import Plan, ShotPlan  # noqa: E402
from block_director.layer3_engine.cinema_engine import (  # noqa: E402
    evaluate_camera_composition,
)
from block_director.layer3_engine.scene_context import get_context  # noqa: E402
from block_director.layer3_engine.scene_sync import reset_synchronizer  # noqa: E402
from block_director.layer3_engine.shot_builder import build_scene  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

RESULTS: dict = {}


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
    return scene


def local_plan() -> Plan:
    """两镜：CU 拍米迦尔右手特写 + ECU 拍掌中银币。"""
    hand_shot = ShotPlan.from_dict({
        "shot_id": "shot_001", "order": 1, "intent": "右手特写",
        "shot_type": "CU", "duration_frames": 84,
        "characters": ["char_001"],
        "framing_target": {"kind": "character", "ref": "char_001",
                           "part": "hand", "anchor_offset": None},
    })
    coin_shot = ShotPlan.from_dict({
        "shot_id": "shot_002", "order": 2, "intent": "银币大特写",
        "shot_type": "ECU", "duration_frames": 108,
        "characters": ["char_001"],
        "framing_target": {"kind": "prop", "ref": "coin",
                           "part": "none", "anchor_offset": None},
    })
    return Plan(shots=[hand_shot, coin_shot],
                scene_heading="INT. 第十四街区码头市场 - 日")


def _build():
    reset_synchronizer()
    fresh_scene()
    plan = local_plan()
    spec = SceneSpec.from_plan(
        plan,
        props=[{"id": "coin", "position": (0.0, 0.0, 1.0),
                "size": (0.12, 0.12, 0.03), "shape": "cylinder"}])
    build_scene(plan, spec, clear_scene=True)
    return plan, get_context()


def _hand_anchor(context) -> Vector:
    """与 composition_guide._anchored_hand_box 同源的锚点（右拳位置）。"""
    from block_director.cinema.anchor import DEFAULT_PROFILE, hand_offset
    from mathutils import Vector as V
    character = context.characters["char_001"]
    pivot = character.body_pivot
    return pivot.matrix_world @ V(hand_offset(DEFAULT_PROFILE, side=1.0))


def aim(camera, target, *, distance: float, lens: float,
        screen=(1.0 / 3.0, 0.60)) -> None:
    """把相机对准 target，让它在屏幕上落在 ``screen``（归一化 x,y）。

    相机走 Track To 约束（§10.1，``camera_manager.create_camera``）：旋转由
    约束目标 Empty 推出，直接写 ``rotation_euler`` 会被约束覆盖。这里挪约束
    目标，不写旋转。
    """
    sensor_h = 36.0 / (16.0 / 9.0)
    half_fov_v = math.atan(sensor_h / 2.0 / lens)
    visible_h = 2.0 * distance * math.tan(half_fov_v)
    visible_w = visible_h * (16.0 / 9.0)
    target = Vector(target)
    cam_pos = target - Vector((0.0, 1.0, 0.0)) * distance
    right = Vector((1.0, 0.0, 0.0))
    up = Vector((0.0, 0.0, 1.0))
    aim_target = target + right * (screen[0] - 0.5) * visible_w \
        + up * (screen[1] - 0.5) * visible_h
    camera.location = cam_pos
    constraint = next(c for c in camera.constraints if c.type == "TRACK_TO")
    constraint.target.location = aim_target
    camera.data.lens = lens


def _eval(context, shot_id: str, framing_target, camera):
    return evaluate_camera_composition(
        camera, context.subjects_for(shot_id),
        shot_type=str(context.shot_types.get(shot_id, "MS")),
        framing_target=framing_target)


def t_hand_cu_passes_with_target():
    plan, context = _build()
    try:
        shot = plan.shots[0]
        camera = context.cameras["shot_001"]
        hand = _hand_anchor(context)
        #: 手部约 22 cm，按 0.65 画面高取距离 → 严格 >80 且无整身建议。
        aim(camera, hand, distance=1.42, lens=85.0)
        with_target = _eval(context, "shot_001", shot.framing_target, camera)
        suggestions = "；".join(with_target.suggestions)
        ok_target = (with_target.score > 80.0
                     and "整身" not in suggestions
                     and "主体部分出画" not in suggestions)
        return {"ok": ok_target,
                "score_with_target": with_target.score,
                "suggestions_with_target": with_target.suggestions,
                "provenance_ok": True}
    finally:
        reset_synchronizer()


def t_prop_in_frame_passes_and_out_frame_hard_caps():
    plan, context = _build()
    try:
        shot = plan.shots[1]
        camera = context.cameras["shot_002"]
        prop = next(obj for obj in bpy.context.scene.objects
                    if obj.get("bd_element_type") == "prop")
        center = prop.matrix_world.translation.copy()
        #: 银币 12 cm，按 0.72 画面高取距离 → 在画内 >80。
        #: 银币放右手代理锚点附近（持币姿势）：角色身体在银币后面，按局部
        #: 主体口径不构成前景遮挡。
        prop.location = (0.22, 0.25, 0.41)
        bpy.context.view_layer.update()
        center = prop.matrix_world.translation.copy()
        aim(camera, center, distance=0.78, lens=85.0)
        in_frame = _eval(context, "shot_002", shot.framing_target, camera)

        #: 挪出画：硬闸对局部主体成立。
        prop.location = (10.0, 10.0, 10.0)
        bpy.context.view_layer.update()
        out_frame = _eval(context, "shot_002", shot.framing_target, camera)
        ok = (in_frame.score > 80.0 and out_frame.score <= 20.0)
        return {"ok": ok,
                "score_in_frame": in_frame.score,
                "score_out_frame": out_frame.score,
                "suggestions_in": in_frame.suggestions,
                "suggestions_out": out_frame.suggestions}
    finally:
        reset_synchronizer()


def main() -> int:
    capture_main_thread()
    check("hand_cu_passes_with_target", t_hand_cu_passes_with_target)
    check("prop_in_frame_passes_and_out_frame_hard_caps",
          t_prop_in_frame_passes_and_out_frame_hard_caps)
    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS},
        ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
