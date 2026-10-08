"""v1.6 A7（D-19）：标签互斥从采样帧扩到**成片每一帧**（RK-2 的 5% 判据不变）。

量法复用 ``test_label_layout.py`` 的 ``_overlap`` / ``_screen_box``（逐字同式，
不新造）；覆盖范围从"每镜 5 个采样帧"扩到 shot 内每一帧。

归因样片：两人沿同向先后 ``walk_to``（世界 X 间距 0.25 m），后者在前者停下后
从身后追上并超过——深度交错让两枚标签的屏幕纵向换位发生在**两个采样点之间**
（89/93），于是 91/92 两帧在采样间隙被贝塞尔插值压在一起。

断言：
* 固定步长（关闭自适应/全帧自检）时确实检出超限帧，且全部落在**插值帧**
  （采样帧受互斥松弛保护）——这是归因，也是本探针的判别力自证；
* 默认配置烘焙后：**每一帧**两两交叠 ≤5%；``label_overlap_report`` 四键齐备；
  报告里的 ``overlap_frames`` 与独立全帧量法一致（不隐藏）；
* 自适应加密把此前超限的帧烘成关键帧（区段加密到每帧），且只加密那一区段。

运行：blender --background --factory-startup --python tools/blender_tests/test_label_fullframe.py
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
from bpy_extras.object_utils import world_to_camera_view  # noqa: E402
from mathutils import Vector  # noqa: E402

from block_director.contracts.cast import SceneSpec  # noqa: E402
from block_director.contracts.config import AppConfig  # noqa: E402
from block_director.contracts.plan import Plan  # noqa: E402
from block_director.layer3_engine.collection_router import (  # noqa: E402
    LABELS_COLLECTION,
    ensure_collections,
)
from block_director.layer3_engine.shot_builder import build_scene  # noqa: E402
from block_director.settings import reset_config, set_config  # noqa: E402
from block_director.utils.blender_compat import action_fcurves  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

RESULTS: dict = {}
BASELINE: dict = {}
WIDTH, HEIGHT = 1920, 1080
OVERLAP_LIMIT = 0.05


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                         "trace": traceback.format_exc(limit=3)}


def _plan() -> Plan:
    """归因样片：深度交错发生在第 89/93 两个采样点之间（见模块 docstring）。"""
    return Plan.from_dict({
        "scene_heading": "EXT. 广场 - 日",
        "shots": [{
            "shot_id": "shot_001", "order": 1, "intent": "两人交错走过",
            "shot_type": "LS", "duration_frames": 96,
            "characters": ["char_001", "char_002"],
            "actions": [
                {"character_id": "char_001", "action_type": "walk_to",
                 "start_frame": 1, "end_frame": 48,
                 "params": {"target_position": [-0.125, 1.0, 0.0]}},
                {"character_id": "char_002", "action_type": "walk_to",
                 "start_frame": 49, "end_frame": 96,
                 "params": {"target_position": [0.125, 1.2, 0.0]}},
            ],
        }],
    })


def _build(*, adaptive: bool, verify: bool):
    config = AppConfig()
    config.character.label_render = True
    config.labels.adaptive_sampling = bool(adaptive)
    config.labels.fullframe_verify = bool(verify)
    set_config(config)
    plan = _plan()
    spec = SceneSpec.from_plan(plan)
    spec.cast[0].initial_location = (-0.125, -1.0, 0.0)
    spec.cast[1].initial_location = (0.125, -1.1, 0.0)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = WIDTH
    scene.render.resolution_y = HEIGHT
    ensure_collections(scene)
    summary = build_scene(plan, spec, clear_scene=True).to_dict()
    collection = bpy.data.collections.get(LABELS_COLLECTION)
    fills = sorted((obj.name, obj) for obj in collection.objects
                   if obj.name.endswith("_Fill"))
    return scene, summary, [obj for _, obj in fills]


def _screen_box(scene, camera, obj) -> tuple:
    """与 ``test_label_layout._screen_box`` 逐字同式（D-19 要求复用，不新造）。"""
    matrix = obj.matrix_world
    corners = [matrix @ Vector(corner) for corner in obj.bound_box]
    points = [world_to_camera_view(scene, camera, point) for point in corners]
    xs = [point.x * WIDTH for point in points]
    ys = [point.y * HEIGHT for point in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _overlap(a, b) -> float:
    """与 ``test_label_layout._overlap`` 逐字同式（D-19 要求复用，不新造）。"""
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    if width <= 0.0 or height <= 0.0:
        return 0.0
    smaller = min((a[2] - a[0]) * (a[3] - a[1]),
                  (b[2] - b[0]) * (b[3] - b[1]))
    return (width * height) / smaller if smaller > 0 else 0.0


def _baked_frames(fill) -> list:
    """烘焙写进 location 曲线的帧号（含自适应加密与重烘的键）。"""
    action = fill.animation_data.action
    location = next(curve for curve in action_fcurves(action)
                    if curve.data_path == "location"
                    and curve.array_index == 0)
    return sorted({int(round(float(point.co[0])))
                   for point in location.keyframe_points})


def _measure(scene, fills) -> dict:
    """全帧两两交叠：每帧最大交叠率 + 超限帧清单（采样帧由调用方另行判定）。"""
    camera = scene.camera
    worst = 0.0
    worst_frame = None
    over = []
    for frame in range(1, int(scene.frame_end) + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        boxes = [_screen_box(scene, camera, fill) for fill in fills]
        maximum = 0.0
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                maximum = max(maximum, _overlap(boxes[i], boxes[j]))
        if maximum > worst:
            worst, worst_frame = maximum, frame
        if maximum > OVERLAP_LIMIT:
            over.append(frame)
    return {"worst": round(float(worst), 6),
            "worst_frame": int(worst_frame) if worst_frame else None,
            "over_limit_frames": [int(frame) for frame in over]}


def t_fixed_step_overlaps_sit_on_interpolated_frames():
    """步骤 1 的归因：固定步长烘焙下超限帧全在插值帧（采样帧受松弛保护）。"""
    scene, _summary, fills = _build(adaptive=False, verify=False)
    measured = _measure(scene, fills)
    sampled = set(_baked_frames(fills[0]))
    over = measured["over_limit_frames"]
    sampled_over = sorted(frame for frame in over if frame in sampled)
    interpolated_over = sorted(frame for frame in over if frame not in sampled)
    BASELINE.clear()
    BASELINE.update({"over_limit_frames": over, "sampled": sorted(sampled),
                     "worst": measured["worst"],
                     "worst_frame": measured["worst_frame"],
                     "sampled_over": sampled_over,
                     "interpolated_over": interpolated_over})
    ok = bool(over) and not sampled_over and bool(interpolated_over)
    return {"ok": ok, "over_limit_frames": over,
            "sampled_over": sampled_over,
            "interpolated_over": interpolated_over,
            "worst": measured["worst"],
            "worst_frame": measured["worst_frame"],
            "limit": OVERLAP_LIMIT}


def t_adaptive_densification_fixes_every_frame():
    """默认配置：全帧 ≤5% ＋ ``label_overlap_report`` 四键齐备且与实测一致。"""
    scene, summary, fills = _build(adaptive=True, verify=True)
    measured = _measure(scene, fills)
    baked = set(_baked_frames(fills[0]))
    report = (summary.get("label_report") or {}).get(
        "label_overlap_report") or {}
    baseline_over = list(BASELINE.get("over_limit_frames") or [])

    keys_ok = all(key in report for key in
                  ("max_overlap_ratio", "overlap_frames",
                   "frames_checked", "limit"))
    fixed = (measured["worst"] <= OVERLAP_LIMIT
             and not measured["over_limit_frames"])
    densified = (all(frame in baked for frame in baseline_over)
                 and 50 not in baked)
    honest = sorted(int(frame)
                    for frame in (report.get("overlap_frames") or [])) \
        == sorted(measured["over_limit_frames"])
    checked_ok = int(report.get("frames_checked") or -1) == \
        int(scene.frame_end)
    limit_ok = abs(float(report.get("limit") or -1.0) - OVERLAP_LIMIT) < 1e-9

    return {"ok": keys_ok and fixed and densified and honest
            and checked_ok and limit_ok,
            "measured_worst": measured["worst"],
            "measured_over_limit_frames": measured["over_limit_frames"],
            "report": report, "report_keys_ok": keys_ok,
            "report_matches_measurement": honest,
            "frames_checked_ok": checked_ok, "limit_ok": limit_ok,
            "baseline_over_frames": baseline_over,
            "baseline_frames_now_baked": sorted(
                frame for frame in baseline_over if frame in baked),
            "densified_baked_frames": sorted(baked),
            "local_densification": 50 not in baked}


def main() -> int:
    capture_main_thread()
    check("fixed_step_overlaps_sit_on_interpolated_frames",
          t_fixed_step_overlaps_sit_on_interpolated_frames)
    check("adaptive_densification_fixes_every_frame",
          t_adaptive_densification_fixes_every_frame)
    reset_config()

    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS},
        ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
