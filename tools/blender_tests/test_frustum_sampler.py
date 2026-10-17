"""v1.6 B3（FR-C1 引擎层）：bpy 视锥采样器 headless 探针（TDD §4.2 / 卡 B3）。

合成 3 镜场景，断言：

* 采样帧数 = 步长网格 ∪ 末帧 ∪ extra_frames，主体/帧数对拍；
* 已知摆放的 NDC 与独立 ``world_to_camera_view`` 对拍（容差 1e-3），
  并带绝对居中 sanity（相机正对包围盒中心时投影中心 ≈ (0.5, 0.5)）；
* 无遮挡可见比例 == 1.0；加遮挡物后 0 < ratio < 1；
* 相机后方（任一角点 z<0）→ ``behind_camera``；
* 采样失败抛 ``SamplingError`` 且携带 ``E_GUARD_001``、当前帧还原；
* 采样前后渲染设置不变；
* 输出直接喂 ``frustum_metrics.shot_warnings`` 不报错；
* 主体首/末帧站位不同 ⇒ 投影盒随帧变化（``frame_set`` + 求值后的
  ``matrix_world`` 真的生效，而不是每帧读同一个姿态）；
* 100 帧 < 5 s（NFR-3）。

运行：
  blender --background --factory-startup --python tools/blender_tests/test_frustum_sampler.py
输出：一行 ``BD_TEST_RESULT {json}``（不含 NaN/Inf 字面量）；退出码 0 = 全通过。
"""
from __future__ import annotations

import json
import math
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bmesh  # noqa: E402
import bpy  # noqa: E402
from bpy_extras.object_utils import world_to_camera_view  # noqa: E402
from mathutils import Vector  # noqa: E402

from block_director.cinema.composition import SubjectBox  # noqa: E402
from block_director.cinema.frustum_metrics import (  # noqa: E402
    DeclaredShot,
    guard_config_from,
    shot_warnings,
)
from block_director.contracts.config import AppConfig  # noqa: E402
from block_director.contracts.plan import Plan, ShotPlan  # noqa: E402
from block_director.layer3_engine.character_system.character_factory import (  # noqa: E402
    Character,
    create_character,
)
from block_director.layer3_engine.frustum_sampler import (  # noqa: E402
    GUARD_001_CODE,
    SamplingError,
    sample_shot,
)
from block_director.layer3_engine.scene_context import (  # noqa: E402
    SceneContext,
    set_context,
)
from block_director.settings import reset_config, set_config  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

RESULTS: dict = {}
_CTX = None

STEP = 4
SPAN_1 = (1, 97)
SPAN_3 = (1, 397)
NDC_TOL = 1e-3
CENTER_TOL = 2e-2
TIME_BUDGET_S = 5.0


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                         "trace": traceback.format_exc(limit=4)}


def _cube(name, location, size=1.0):
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=size)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = tuple(location)
    return obj


def _camera(name, location, look_at=(0.0, 0.0, 0.5), lens=50.0):
    data = bpy.data.cameras.new(name)
    data.lens = lens
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = tuple(location)
    #: 与 camera_manager.create_camera 同款对齐：-Z 看向目标、+Y 向上。
    direction = Vector(look_at) - Vector(location)
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    return obj


def _build():
    """合成 3 镜场景 + 三个错误/边界辅助镜头（机后、无相机、无网格）。"""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100

    char_001 = _cube("subj_char_001", (0.0, 0.0, 0.5), 1.0)
    char_behind = _cube("subj_char_behind", (0.0, -10.0, 0.5), 1.0)
    char_nomesh = Character(id="char_nomesh", name="char_nomesh")
    #: 真实角色（v1.6 B3 修复探针）：create_character 建的是躯干圆柱
    #: （r=BODY_RADIUS）+ 头球（r=head_r）+ 眼球——**不是立方体**。旧采样器
    #: 在含眼球的 AABB 朝机面上取点，9 条射线全部落在空处 ⇒ 可见比例恒 0。
    char_real = create_character("char_real", "char_real", "#FF6B6B",
                                 location=(4.0, 0.0, 0.0))

    cameras = {}
    for shot_id in ("shot_001", "shot_002", "shot_003", "shot_behind",
                    "shot_nomesh", "shot_real"):
        if shot_id == "shot_real":
            #: 与原点处的测试立方体隔开，避免射线先打到立方体。
            cameras[shot_id] = _camera(f"cam_{shot_id}", (4.0, -8.0, 0.5),
                                       look_at=(4.0, 0.0, 0.5))
        else:
            cameras[shot_id] = _camera(f"cam_{shot_id}", (0.0, -8.0, 0.5))

    shot_rows = [
        ("shot_001", 1, 97, ["char_001"]),
        ("shot_002", 2, 1, ["char_001"]),
        ("shot_003", 3, 397, ["char_001"]),
        ("shot_behind", 4, 5, ["char_behind"]),
        ("shot_bad", 5, 9, ["char_001"]),
        ("shot_nomesh", 6, 9, ["char_nomesh"]),
        ("shot_real", 7, 1, ["char_real"]),
    ]
    shots = [
        ShotPlan.from_dict({
            "shot_id": shot_id, "order": order, "intent": "合成采样探针",
            "shot_type": "MS", "duration_frames": duration,
            "characters": list(characters),
        })
        for shot_id, order, duration, characters in shot_rows
    ]
    context = SceneContext(
        characters={
            "char_001": Character(id="char_001", name="char_001",
                                  root=char_001, meshes=[char_001]),
            "char_behind": Character(id="char_behind", name="char_behind",
                                     root=char_behind, meshes=[char_behind]),
            "char_nomesh": char_nomesh,
            "char_real": char_real,
        },
        cameras=cameras,
        shot_types={shot_id: "MS" for shot_id, _o, _d, _c in shot_rows},
        schedule={shot_id: (1, duration)
                  for shot_id, _o, duration, _c in shot_rows},
        plan=Plan(shots=shots, scene_heading="INT. 合成采样场 - 日"),
    )
    set_context(context)
    return context


def t_sample_frames_step_and_extras():
    start, end = SPAN_1
    expected = set(range(start, end + 1, STEP)) | {end} | {19, 20, 21}
    samples = sample_shot("shot_001", step=STEP, extra_frames=(19, 20, 21))
    unique = sorted({sample.frame for sample in samples})
    ok = (unique == sorted(expected)
          and len(samples) == len(expected)
          and all(sample.shot_id == "shot_001"
                  and sample.subject == "char_001"
                  and isinstance(sample.box, SubjectBox)
                  and 0.0 <= sample.visible_ratio <= 1.0
                  and isinstance(sample.behind_camera, bool)
                  for sample in samples))
    return {"ok": ok, "expected_frames": len(expected),
            "sampled_frames": len(unique), "samples": len(samples)}


def t_ndc_and_unobstructed_ratio():
    scene = bpy.context.scene
    samples = sample_shot("shot_002", step=1)
    if len(samples) != 1:
        return {"ok": False, "reason": f"期望 1 帧 1 主体，实得 {len(samples)}"}
    sample = samples[0]
    scene.frame_set(1)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    camera = _CTX.camera_for("shot_002")
    camera_eval = camera.evaluated_get(depsgraph)
    subject = _CTX.character("char_001")
    evaluated = subject.meshes[0].evaluated_get(depsgraph)
    corners = [evaluated.matrix_world @ Vector(corner)
               for corner in evaluated.bound_box]
    projected = [world_to_camera_view(scene, camera_eval, corner)
                 for corner in corners]
    expected = SubjectBox(
        name=sample.box.name,
        left=min(p.x for p in projected),
        right=max(p.x for p in projected),
        top=max(p.y for p in projected),
        bottom=min(p.y for p in projected),
    )
    deltas = {
        "left": abs(sample.box.left - expected.left),
        "right": abs(sample.box.right - expected.right),
        "top": abs(sample.box.top - expected.top),
        "bottom": abs(sample.box.bottom - expected.bottom),
    }
    centered = (abs(sample.box.center_x - 0.5) <= CENTER_TOL
                and abs(sample.box.center_y - 0.5) <= CENTER_TOL)
    ok = (max(deltas.values()) <= NDC_TOL
          and centered
          and sample.visible_ratio == 1.0
          and not sample.behind_camera)
    return {"ok": ok, "max_ndc_delta": round(max(deltas.values()), 6),
            "ndc_tol": NDC_TOL, "center": [round(sample.box.center_x, 4),
                                           round(sample.box.center_y, 4)],
            "visible_ratio": sample.visible_ratio, "deltas": deltas}


def t_occluder_reduces_visible_ratio():
    occluder = _cube("occluder", (0.0, -1.5, 0.5), 1.0)
    occluder.scale = (1.2, 1.2, 0.6)
    occluder["bd_element_type"] = "prop"
    occluder["bd_sdl_id"] = "stall_01"
    bpy.context.view_layer.update()
    try:
        samples = sample_shot("shot_002", step=1)
        ratio = samples[0].visible_ratio
        by_class = samples[0].occlusion_by_class
        attributed = round(sum(by_class.values()), 6)
        ok = (0.0 < ratio < 1.0
              and by_class.get("道具:stall_01", 0.0) > 0.0
              and abs(attributed - (1.0 - ratio)) <= 1e-5)
        return {"ok": ok, "visible_ratio": round(ratio, 6),
                "occlusion_by_class": by_class}
    finally:
        bpy.data.objects.remove(occluder, do_unlink=True)


def t_occluder_class_character_attribution():
    """另一角色的网格挡在主体前 ⇒ 归因到 ``角色:<id>``（非匿名"未知"）。"""
    blocker = _cube("char_occluder_mesh", (0.0, -1.5, 0.5), 1.2)
    blocker.scale = (1.2, 1.2, 0.6)
    blocker["bd_element_type"] = "character_part"
    blocker_character = Character(
        id="char_occluder", name="char_occluder",
        root=blocker, meshes=[blocker])
    _CTX.characters["char_occluder"] = blocker_character
    bpy.context.view_layer.update()
    try:
        samples = sample_shot("shot_002", step=1)
        ratio = samples[0].visible_ratio
        by_class = samples[0].occlusion_by_class
        ok = (0.0 < ratio < 1.0
              and by_class.get("角色:char_occluder", 0.0) > 0.0
              and set(by_class) == {"角色:char_occluder"})
        return {"ok": ok, "visible_ratio": round(ratio, 6),
                "occlusion_by_class": by_class}
    finally:
        _CTX.characters.pop("char_occluder", None)
        bpy.data.objects.remove(blocker, do_unlink=True)


def t_occlusion_attribution_reaches_guard_warning():
    """遮挡归因要走完端到端：采样器 → 纯层告警 evidence。

    ``shot_003`` 是 397 帧长镜（sustain 包络成立），在相机与主体之间放一个
    带 ``bd_sdl_id`` 的道具。``shot_warnings`` 应产出 occlusion 告警，且
    ``evidence["occlusion_by_class"]`` 带 ``"道具:stall_99"``；计划声明刻意
    前景遮挡后同一采样不再告警。
    """
    occluder = _cube("long_occluder", (0.0, -1.5, 0.5), 1.0)
    occluder.scale = (1.2, 1.2, 0.6)
    occluder["bd_element_type"] = "prop"
    occluder["bd_sdl_id"] = "stall_99"
    bpy.context.view_layer.update()
    try:
        samples = sample_shot("shot_003", step=4)
        cfg = guard_config_from(AppConfig())
        plain = shot_warnings(
            samples,
            DeclaredShot(shot_id="shot_003", shot_type="MS",
                         subject="char_001"), cfg)
        occ = [item for item in plain if item.type == "occlusion"]
        declared = shot_warnings(
            samples,
            DeclaredShot(shot_id="shot_003", shot_type="MS",
                         subject="char_001",
                         front_occlusion_declared=True), cfg)
        declared_occ = [item for item in declared
                        if item.type == "occlusion"]
        sample_by_class = next(
            item.occlusion_by_class for item in samples
            if item.occlusion_by_class)
        ok = (occ
              and occ[0].evidence.get("occlusion_by_class", {}).get(
                  "道具:stall_99", 0.0) > 0.0
              and not declared_occ
              and sample_by_class.get("道具:stall_99", 0.0) > 0.0)
        return {"ok": ok,
                "evidence": (occ[0].evidence if occ else {}),
                "declared_occlusion_warnings": len(declared_occ),
                "sample_occlusion_by_class": sample_by_class}
    finally:
        bpy.data.objects.remove(occluder, do_unlink=True)


def t_behind_camera_detected():
    samples = sample_shot("shot_behind", step=1)
    return {"ok": (len(samples) == 5
                   and all(sample.behind_camera for sample in samples)
                   and all(sample.visible_ratio == 0.0 for sample in samples)),
            "frames": [sample.frame for sample in samples]}


def t_sampling_error_and_frame_restore():
    scene = bpy.context.scene
    scene.frame_set(3)
    bpy.context.view_layer.update()
    outcomes = {}
    try:
        sample_shot("shot_bad", step=1)
        outcomes["no_camera"] = "no exception"
    except SamplingError as exc:
        outcomes["no_camera"] = exc.code
    outcomes["frame_after_no_camera"] = int(scene.frame_current)
    try:
        sample_shot("shot_nomesh", step=1)
        outcomes["no_mesh"] = "no exception"
    except SamplingError as exc:
        outcomes["no_mesh"] = exc.code
    outcomes["frame_after_no_mesh"] = int(scene.frame_current)
    return {"ok": (outcomes["no_camera"] == GUARD_001_CODE
                   and outcomes["no_mesh"] == GUARD_001_CODE
                   and outcomes["frame_after_no_camera"] == 3
                   and outcomes["frame_after_no_mesh"] == 3),
            "outcomes": outcomes}


def t_render_settings_untouched():
    scene = bpy.context.scene
    keys = ("engine", "resolution_x", "resolution_y",
            "resolution_percentage", "fps")
    before = {key: getattr(scene.render, key) for key in keys}
    before["camera"] = scene.camera.name if scene.camera else None
    before["frame_current"] = int(scene.frame_current)
    before["lens"] = float(_CTX.camera_for("shot_002").data.lens)
    sample_shot("shot_002", step=1)
    after = {key: getattr(scene.render, key) for key in keys}
    after["camera"] = scene.camera.name if scene.camera else None
    after["frame_current"] = int(scene.frame_current)
    after["lens"] = float(_CTX.camera_for("shot_002").data.lens)
    return {"ok": before == after, "before": before, "after": after}


def t_output_feeds_pure_layer():
    samples = sample_shot("shot_002", step=1)
    cfg = guard_config_from(AppConfig())
    warnings = shot_warnings(
        samples,
        DeclaredShot(shot_id="shot_002", shot_type="MS", subject="char_001"),
        cfg)
    ok = isinstance(warnings, list) and all(not item.problems()
                                            for item in warnings)
    return {"ok": ok, "frames_sampled": len(samples),
            "warning_types": [item.type for item in warnings]}


def t_default_step_from_config():
    cfg = AppConfig()
    cfg.guard.sample_step = 8
    set_config(cfg)
    try:
        start, end = SPAN_3
        expected = set(range(start, end + 1, 8)) | {end}
        samples = sample_shot("shot_003")
        unique = sorted({sample.frame for sample in samples})
        return {"ok": (unique == sorted(expected)
                       and len(samples) == len(expected)),
                "step": 8, "sampled_frames": len(unique),
                "samples": len(samples)}
    finally:
        reset_config()


def t_hundred_frames_under_budget():
    start, end = SPAN_3
    expected = set(range(start, end + 1, STEP)) | {end}
    started = time.perf_counter()
    samples = sample_shot("shot_003", step=STEP)
    elapsed = time.perf_counter() - started
    unique = sorted({sample.frame for sample in samples})
    return {"ok": (unique == sorted(expected)
                   and len(samples) == len(expected)
                   and elapsed < TIME_BUDGET_S),
            "frames_sampled": len(unique), "samples": len(samples),
            "elapsed_s": round(elapsed, 3), "budget_s": TIME_BUDGET_S}


def t_keyframe_neighborhood_densifies():
    camera = _CTX.camera_for("shot_001")
    camera.keyframe_insert(data_path="location", frame=20)
    try:
        samples = sample_shot("shot_001", step=100)
        unique = sorted({sample.frame for sample in samples})
        expected = {1, 19, 20, 21, 97}
        return {"ok": (unique == sorted(expected)
                       and len(samples) == len(expected)),
                "frames": unique}
    finally:
        camera.animation_data_clear()


def t_frame_set_updates_evaluated_pose():
    """主体在首/末帧站位不同 ⇒ 投影盒随帧变化（depsgraph 求值真的生效）。"""
    scene = bpy.context.scene
    root = _CTX.character("char_001").root
    scene.frame_set(1)
    root.location = (0.0, 0.0, 0.5)
    root.keyframe_insert(data_path="location", frame=1)
    scene.frame_set(97)
    root.location = (3.0, 0.0, 0.5)
    root.keyframe_insert(data_path="location", frame=97)
    try:
        samples = sample_shot("shot_001", step=96)
        frames = sorted({sample.frame for sample in samples})
        first = next(sample for sample in samples if sample.frame == 1)
        last = next(sample for sample in samples if sample.frame == 97)
        ok = (frames == [1, 2, 96, 97]
              and last.box.center_x > first.box.center_x + 1e-6)
        return {"ok": ok, "frames": frames,
                "center_x_first": round(first.box.center_x, 4),
                "center_x_last": round(last.box.center_x, 4)}
    finally:
        root.animation_data_clear()
        root.location = (0.0, 0.0, 0.5)
        scene.frame_set(1)
        bpy.context.view_layer.update()


def t_real_character_unobstructed_ratio():
    """真实角色（create_character，非立方体）无遮挡 ⇒ 可见比例 == 1.0。"""
    samples = sample_shot("shot_real", step=1)
    if len(samples) != 1:
        return {"ok": False, "reason": f"期望 1 帧 1 主体，实得 {len(samples)}"}
    sample = samples[0]
    return {"ok": sample.visible_ratio == 1.0 and not sample.behind_camera,
            "visible_ratio": sample.visible_ratio,
            "behind_camera": sample.behind_camera}


def t_real_character_half_occluded_ratio():
    """挡板盖住躯干（下半身）⇒ 0 < 可见比例 < 1（头球采样点仍可见）。"""
    occluder = _cube("half_occluder", (4.0, -1.5, 0.45), 0.9)
    occluder.scale = (2.0, 2.0, 1.0)      # 世界：x±0.9 / y[-2.6,-0.4] / z[0,0.9]
    bpy.context.view_layer.update()
    try:
        samples = sample_shot("shot_real", step=1)
        ratio = samples[0].visible_ratio
        return {"ok": 0.0 < ratio < 1.0, "visible_ratio": round(ratio, 6)}
    finally:
        bpy.data.objects.remove(occluder, do_unlink=True)


def t_real_character_fully_occluded_ratio():
    """挡板盖住整个角色 ⇒ 可见比例 == 0.0。"""
    occluder = _cube("full_occluder", (4.0, -1.5, 0.95), 1.9)
    occluder.scale = (2.0, 2.0, 1.0)      # 世界：x±1.9 / y[-3.4,0.4] / z[0,1.9]
    bpy.context.view_layer.update()
    try:
        samples = sample_shot("shot_real", step=1)
        ratio = samples[0].visible_ratio
        return {"ok": ratio == 0.0, "visible_ratio": ratio}
    finally:
        bpy.data.objects.remove(occluder, do_unlink=True)


def _jsonable(value):
    """把 NaN/Inf 转成字符串字面量，保证 BD_TEST_RESULT 是严格 JSON。"""
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return "inf" if value > 0 else ("-inf" if value < 0 else "nan")
    return value


def main() -> int:
    global _CTX
    capture_main_thread()
    _CTX = _build()
    check("sample_frames_step_and_extras", t_sample_frames_step_and_extras)
    check("ndc_and_unobstructed_ratio", t_ndc_and_unobstructed_ratio)
    check("occluder_reduces_visible_ratio", t_occluder_reduces_visible_ratio)
    check("occluder_class_character_attribution",
          t_occluder_class_character_attribution)
    check("occlusion_attribution_reaches_guard_warning",
          t_occlusion_attribution_reaches_guard_warning)
    check("behind_camera_detected", t_behind_camera_detected)
    check("sampling_error_and_frame_restore", t_sampling_error_and_frame_restore)
    check("render_settings_untouched", t_render_settings_untouched)
    check("output_feeds_pure_layer", t_output_feeds_pure_layer)
    check("default_step_from_config", t_default_step_from_config)
    check("hundred_frames_under_budget", t_hundred_frames_under_budget)
    check("frame_set_updates_evaluated_pose", t_frame_set_updates_evaluated_pose)
    check("keyframe_neighborhood_densifies", t_keyframe_neighborhood_densifies)
    check("real_character_unobstructed_ratio", t_real_character_unobstructed_ratio)
    check("real_character_half_occluded_ratio", t_real_character_half_occluded_ratio)
    check("real_character_fully_occluded_ratio", t_real_character_fully_occluded_ratio)

    passed = [name for name, value in RESULTS.items() if value.get("ok")]
    failed = [name for name, value in RESULTS.items() if not value.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": _jsonable(RESULTS)},
        ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
