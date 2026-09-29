"""v1.3 P7：声明式运镜与关键帧质量的 Blender 端验收。

覆盖三件在纯 Python 里验证不了的事：

1. 计划里写了 ``camera.movements`` 就**自动**生成相机关键帧（不靠 LLM 调工具）；
2. 变焦类真的写进 ``camera.data.lens``（只写位置等于没变焦）；
3. RK-3 探针：运镜与 Track To 叠加后的逐帧位移是否平滑（不抖动）。

运行：
  blender --background --factory-startup --python tools/blender_tests/test_camera_motion.py
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy  # noqa: E402

from _fixtures import two_shot_plan  # noqa: E402
from block_director.contracts.cast import SceneSpec  # noqa: E402
from block_director.layer3_engine.collection_router import ensure_collections  # noqa: E402
from block_director.layer3_engine.shot_builder import build_scene  # noqa: E402
from block_director.utils.blender_compat import action_fcurves  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

RESULTS: dict = {}


def fresh_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    ensure_collections(scene)
    return scene


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                         "trace": traceback.format_exc(limit=3)}


def _plan_with_movements(movement: str, **extra) -> object:
    plan = two_shot_plan()
    plan.shots[1].camera = {"side": "front",
                            "movements": [dict({"type": movement,
                                                "start_frame": 1,
                                                "end_frame": 60}, **extra)]}
    return plan


def _position_curve(camera, frame: int):
    scene = bpy.context.scene
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    return tuple(camera.matrix_world.translation)


def t_declared_movement_becomes_camera_keyframes():
    """不给 LLM 任何工具调用，只靠计划里的声明就要动起来。"""
    fresh_scene()
    plan = _plan_with_movements("dolly_in", amount=1.0)
    summary = build_scene(plan, SceneSpec.from_plan(plan),
                          clear_scene=True).to_dict()
    camera = bpy.data.objects["BD_Cam_shot_002"]
    curves = len(action_fcurves(camera.animation_data.action)) \
        if camera.animation_data else 0
    start = _position_curve(camera, 97)
    end = _position_curve(camera, 156)
    moved = ((start[0] - end[0]) ** 2 + (start[1] - end[1]) ** 2
             + (start[2] - end[2]) ** 2) ** 0.5
    other = bpy.data.objects["BD_Cam_shot_001"]
    return {"ok": (summary["movements"] == 1 and curves >= 3 and moved > 0.5
                   and other.animation_data is None),
            "movements": summary["movements"], "curves": curves,
            "travelled": round(moved, 3),
            "other_shot_still": other.animation_data is None}


def t_zoom_writes_the_lens_channel():
    fresh_scene()
    plan = _plan_with_movements("zoom_in", amount=20.0)
    summary = build_scene(plan, SceneSpec.from_plan(plan),
                          clear_scene=True).to_dict()
    camera = bpy.data.objects["BD_Cam_shot_002"]
    scene = bpy.context.scene
    scene.frame_set(97)
    bpy.context.view_layer.update()
    before = float(camera.data.lens)
    scene.frame_set(156)
    bpy.context.view_layer.update()
    after = float(camera.data.lens)
    paths = {f"location" for _ in ()}
    # 焦距的关键帧在**相机数据块**自己的 action 上，位置的在对象上
    animated = {curve.data_path for curve in
                action_fcurves(camera.animation_data.action)} \
        if camera.animation_data else set()
    if camera.data.animation_data:
        animated |= {f"data.{curve.data_path}" for curve in
                     action_fcurves(camera.data.animation_data.action)}
    return {"ok": (summary["movements"] == 1 and after > before + 5
                   and "data.lens" in animated),
            "lens": [before, after], "animated": sorted(animated),
            "paths": sorted(paths)}


def t_follow_subject_keeps_the_offset():
    """跟拍：主体走动时相机跟着走，且与主体的相对偏移保持不变。"""
    fresh_scene()
    plan = two_shot_plan(with_actions=False)
    plan.shots[1].characters = ["char_002"]
    plan.shots[1].actions = [
        {"character_id": "char_002", "action_type": "walk_to",
         "start_frame": 1, "end_frame": 60,
         "params": {"target_position": [3.0, 0.0, 0.0]}}]
    plan.shots[1].camera = {"side": "front",
                            "movements": [{"type": "follow_subject",
                                           "subject": "char_002",
                                           "start_frame": 1,
                                           "end_frame": 60}]}
    summary = build_scene(plan, SceneSpec.from_plan(plan),
                          clear_scene=True).to_dict()
    camera = bpy.data.objects["BD_Cam_shot_002"]
    subject = bpy.data.objects["BD_Char_char_002_Root"]
    offsets = []
    for frame in (100, 130, 156):
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        offsets.append(tuple(round(camera.matrix_world.translation[i]
                                   - subject.matrix_world.translation[i], 3)
                             for i in range(3)))
    moved = abs(offsets[-1][0] - offsets[0][0]) < 0.35
    return {"ok": summary["movements"] == 1 and moved,
            "offsets": offsets, "movements": summary["movements"]}


def t_rk3_movement_is_smooth():
    """RK-3：逐帧位移单调或单峰，二阶差分符号反复不超过 2 次。"""
    fresh_scene()
    plan = _plan_with_movements("crane_arc_up", amount=30.0)
    summary = build_scene(plan, SceneSpec.from_plan(plan),
                          clear_scene=True).to_dict()
    camera = bpy.data.objects["BD_Cam_shot_002"]
    scene = bpy.context.scene
    start, end = 97, 156
    positions = []
    for frame in range(start, end + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        positions.append(tuple(camera.matrix_world.translation))
    deltas = [((positions[i + 1][0] - positions[i][0]) ** 2
               + (positions[i + 1][1] - positions[i][1]) ** 2
               + (positions[i + 1][2] - positions[i][2]) ** 2) ** 0.5
              for i in range(len(positions) - 1)]
    # 速度方向：单调递增 -> 单峰 -> 单调递减，符号反复次数
    signs = [1 if deltas[i + 1] - deltas[i] >= 0 else -1
             for i in range(len(deltas) - 1)]
    flips = sum(1 for i in range(len(signs) - 1) if signs[i] != signs[i + 1])
    travelled = sum(deltas)
    scene.frame_set(1)
    bpy.context.view_layer.update()
    return {"ok": flips <= 2 and travelled > 0.2,
            "flips": flips, "travelled": round(travelled, 3),
            "movements": summary["movements"],
            "samples": len(positions)}


def t_handheld_is_reproducible():
    """同一份计划重建两次，手持噪声必须逐帧一致（seed 落盘的意义）。"""
    frames = []
    for _attempt in range(2):
        fresh_scene()
        plan = _plan_with_movements("handheld", amount=0.08, seed=11,
                                    start_frame=1, end_frame=60)
        build_scene(plan, SceneSpec.from_plan(plan), clear_scene=True)
        camera = bpy.data.objects["BD_Cam_shot_002"]
        scene = bpy.context.scene
        here = []
        for frame in (97, 110, 125, 156):
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            here.append(tuple(round(v, 6)
                              for v in camera.matrix_world.translation))
        frames.append(here)
    return {"ok": frames[0] == frames[1], "first": frames[0],
            "second": frames[1]}


def t_rk17_camera_determinism():
    """RK-17（v1.4 §4.1）：**同参数**两次构建，逐帧 6 自由度最大差 ≤1e-6。

    与 ``t_handheld_is_reproducible``（同 seed 两次一致，§4.1 的旧名"确定性"）
    的分工：那条只用 4 帧比位置；这条把**位置 + 旋转 + 焦距**在整段采样帧上
    逐帧比，且要求的是"确定性求解"的数值界，而不是"两次字符串相等"。
    运镜没有随机输入（``move_camera`` 无 seed 参数），所以这是可判定的硬界。
    """
    samples = []
    for _attempt in range(2):
        fresh_scene()
        plan = _plan_with_movements("dolly_in", amount=0.4,
                                    start_frame=1, end_frame=60)
        build_scene(plan, SceneSpec.from_plan(plan), clear_scene=True)
        camera = bpy.data.objects["BD_Cam_shot_002"]
        scene = bpy.context.scene
        here = []
        for frame in range(97, 157, 4):
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            matrix = camera.matrix_world
            location = matrix.translation
            rotation = matrix.to_euler()
            here.append((location.x, location.y, location.z,
                         rotation.x, rotation.y, rotation.z,
                         float(camera.data.lens)))
        samples.append(here)

    first, second = samples
    worst_pos = 0.0
    worst_rot = 0.0
    worst_lens = 0.0
    for a, b in zip(first, second):
        for index in range(3):
            worst_pos = max(worst_pos, abs(a[index] - b[index]))
        for index in range(3, 6):
            worst_rot = max(worst_rot, abs(a[index] - b[index]))
        worst_lens = max(worst_lens, abs(a[6] - b[6]))
    return {"ok": (worst_pos <= 1e-6 and worst_rot <= 1e-6
                   and worst_lens <= 1e-6 and len(first) >= 8),
            "samples": len(first),
            "max_delta_position": worst_pos,
            "max_delta_rotation": worst_rot,
            "max_delta_lens": worst_lens,
            "tolerance": 1e-6}


def main() -> int:
    capture_main_thread()
    check("declared_movement_becomes_camera_keyframes",
          t_declared_movement_becomes_camera_keyframes)
    check("zoom_writes_the_lens_channel", t_zoom_writes_the_lens_channel)
    check("follow_subject_keeps_the_offset", t_follow_subject_keeps_the_offset)
    check("rk3_movement_is_smooth", t_rk3_movement_is_smooth)
    check("handheld_is_reproducible", t_handheld_is_reproducible)
    check("rk17_camera_determinism", t_rk17_camera_determinism)

    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS},
        ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
