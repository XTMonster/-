"""Phase 3 集成测试：轴线与构图审核（执行文档 v1.2 §10.3 / §10.4）。

运行：
  blender --background --factory-startup --python tools/blender_tests/test_phase3_audit.py
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

from block_director.layer3_engine.character_system import create_character  # noqa: E402
from block_director.layer3_engine.cinema_engine import (  # noqa: E402
    check_camera_axis,
    create_camera,
    establish_axis_from_speakers,
    evaluate_camera_composition,
    place_camera_for_shot,
    visualize_axis,
)
from block_director.layer3_engine.collection_router import (  # noqa: E402
    GUIDES_COLLECTION,
    ensure_collections,
    objects_in_collection,
)
from block_director.cinema.axis import thirty_degree_violation  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

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
    ensure_collections(scene)
    return scene


def two_characters():
    left = create_character("char_001", "小明", "#FF6B6B", location=(-0.5, 0.0, 0.0))
    right = create_character("char_002", "小红", "#6BC5FF", location=(0.5, 0.0, 0.0))
    return left, right


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                         "trace": traceback.format_exc(limit=3)}


# --------------------------------------------------------------------------- #
# 1. 轴线：首镜确立基准侧，越轴被拦下
# --------------------------------------------------------------------------- #
def t_axis_established_and_enforced():
    scene = fresh_scene()
    left, right = two_characters()
    good = create_camera("good", (0.0, 5.0, 1.2), look_at=(0.0, 0.0, 1.0))
    axis = establish_axis_from_speakers([left, right], good.camera)
    assert axis is not None

    violation_ok = check_camera_axis(axis, good.camera) is None
    bad = create_camera("bad", (0.0, -5.0, 1.2), look_at=(0.0, 0.0, 1.0),
                        make_scene_camera=False)
    violation_bad = check_camera_axis(axis, bad.camera)

    return {"ok": violation_ok and bool(violation_bad)
            and "180° 轴线" in violation_bad,
            "established_side": axis.established_side,
            "labels": [axis.left_label, axis.right_label],
            "good_camera_ok": violation_ok,
            "bad_camera_message": violation_bad}


# --------------------------------------------------------------------------- #
# 2. 轴线可视化必须落在 Guides 且不参与渲染
# --------------------------------------------------------------------------- #
def t_axis_visual_is_a_guide():
    fresh_scene()
    left, right = two_characters()
    camera = create_camera("c", (0.0, 5.0, 1.2), look_at=(0.0, 0.0, 1.0))
    axis = establish_axis_from_speakers([left, right], camera.camera)
    visual = visualize_axis(axis)
    guides = {o.name for o in objects_in_collection(GUIDES_COLLECTION)}
    return {"ok": visual.name in guides and visual.hide_render is True,
            "object": visual.name, "in_guides": visual.name in guides,
            "hide_render": bool(visual.hide_render)}


# --------------------------------------------------------------------------- #
# 3. 构图评分：合理解算高分，主体出画低分
# --------------------------------------------------------------------------- #
def t_composition_rewards_good_framing():
    scene = fresh_scene()
    left, right = two_characters()
    place_camera_for_shot("ms", (0.0, 0.0, 0.0), shot_type="MS", side="front")
    good = evaluate_camera_composition(scene.camera, [left, right], "MS")

    # 把角色整体推出画面，构图分必须掉下来
    for character in (left, right):
        character.root.location.x += 9.0
    bpy.context.view_layer.update()
    bad = evaluate_camera_composition(scene.camera, [left, right], "MS")

    return {"ok": good.passed and bad.score < good.score - 10,
            "good_score": good.score, "bad_score": bad.score,
            "good_items": {k: round(v.score, 2) for k, v in good.items.items()},
            "bad_suggestions": bad.suggestions}


# --------------------------------------------------------------------------- #
# 4. 遮挡检测（权重最高的分项）
# --------------------------------------------------------------------------- #
def t_occlusion_is_detected():
    scene = fresh_scene()
    left, right = two_characters()
    place_camera_for_shot("ms", (0.0, 0.0, 0.0), shot_type="MS", side="front")
    clean = evaluate_camera_composition(scene.camera, [left, right], "MS")

    # 在相机与角色之间塞一块挡板
    bpy.ops.mesh.primitive_cube_add(size=2.6, location=(0.0, 2.0, 0.9))
    blocker = bpy.context.object
    blocker.name = "BD_Blocker"
    bpy.context.view_layer.update()
    blocked = evaluate_camera_composition(scene.camera, [left, right], "MS")

    return {"ok": clean.items["occlusion"].score == 1.0
            and blocked.items["occlusion"].score == 0.0
            and blocked.score < clean.score,
            "clean_score": clean.score, "blocked_score": blocked.score,
            "occlusion_score": blocked.items["occlusion"].score,
            "suggestion": blocked.items["occlusion"].suggestion}


# --------------------------------------------------------------------------- #
# 5. R010：角差不足且景别未变化时报警
# --------------------------------------------------------------------------- #
def t_thirty_degree_rule():
    fresh_scene()
    target = (0.0, 0.0)
    previous = (0.0, 5.0)
    same_angle = (0.0, 5.02)
    flagged = thirty_degree_violation(previous, same_angle, target, "MS", "MS")
    allowed_by_size = thirty_degree_violation(previous, same_angle, target, "MS", "CU")
    allowed_by_angle = thirty_degree_violation(previous, (5.0, 0.0), target,
                                               "MS", "MS")
    return {"ok": bool(flagged) and allowed_by_size is None
            and allowed_by_angle is None,
            "flagged": flagged, "allowed_by_size": allowed_by_size,
            "allowed_by_angle": allowed_by_angle}


def main() -> int:
    capture_main_thread()
    check("axis_established_and_enforced", t_axis_established_and_enforced)
    check("axis_visual_is_a_guide", t_axis_visual_is_a_guide)
    check("composition_rewards_good_framing", t_composition_rewards_good_framing)
    check("occlusion_is_detected", t_occlusion_is_detected)
    check("thirty_degree_rule", t_thirty_degree_rule)

    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS}, ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
