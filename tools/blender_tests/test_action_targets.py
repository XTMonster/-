"""卡 G8-C headless：结构化 look/hand 目标走完构建层后的真实结果。

判据（卡 G8-C）：``look_at.target=<另一角色>`` 经构建层折算成 yaw/pitch 后，
头部**最终朝向**确实指向该角色（眼位），误差 ≤ 2°；解析不出的目标必须如实
告警并跳过该动作（确定性错误），绝不静默取默认角。

运行：
  blender --background --factory-startup --python tools/blender_tests/test_action_targets.py
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

import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402

from block_director.cinema.anchor import DEFAULT_PROFILE  # noqa: E402
from block_director.contracts.cast import CastMember  # noqa: E402
from block_director.contracts.enums import ShotType  # noqa: E402
from block_director.contracts.plan import ShotPlan  # noqa: E402
from block_director.layer3_engine.character_system import (  # noqa: E402
    MotionBlender,
    create_character,
)
from block_director.layer3_engine.collection_router import (  # noqa: E402
    ensure_collections,
)
from block_director.layer3_engine.shot_builder import (  # noqa: E402
    action_requests,
)
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

RESULTS: dict = {}
EYE = DEFAULT_PROFILE.eye_z


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
                         "trace": traceback.format_exc(limit=4)}


def _cast():
    return {
        "char_001": CastMember(id="char_001", name="甲",
                               initial_location=(0.0, 0.0, 0.0),
                               initial_facing=(0.0, 1.0, 0.0)),
        "char_002": CastMember(id="char_002", name="乙",
                               initial_location=(3.0, 0.0, 0.0),
                               initial_facing=(0.0, 1.0, 0.0)),
    }


def _shot(target):
    return ShotPlan(
        shot_id="shot_001", intent="对视", shot_type=ShotType.MS,
        duration_frames=48, characters=["char_001", "char_002"],
        actions=[{"character_id": "char_001", "action_type": "look_at",
                  "start_frame": 1, "end_frame": 24,
                  "params": {"target": target}}])


def _head_facing_error_deg(subject, target_eye):
    """头部世界前向与"眼位 → 目标眼位"方向的夹角（度）。"""
    bpy.context.view_layer.update()
    forward = (subject.head_pivot.matrix_world.to_3x3()
               @ Vector((0.0, 1.0, 0.0))).normalized()
    eye = subject.head_pivot.matrix_world.translation
    direction = (Vector(target_eye) - eye).normalized()
    return math.degrees(forward.angle(direction))


def _bake_look_at(target):
    scene = fresh_scene()
    scene.frame_start, scene.frame_end = 1, 48
    subject = create_character("char_001", "甲", "#FF6B6B",
                               location=(0.0, 0.0, 0.0),
                               facing=(0.0, 1.0, 0.0))
    create_character("char_002", "乙", "#4ECDC4",
                     location=(3.0, 0.0, 0.0), facing=(0.0, 1.0, 0.0))
    warnings: list = []
    requests = action_requests(_shot(target), 1, _cast(), warnings)
    if not requests:
        return subject, requests, warnings
    blender = MotionBlender(subject)
    blender.requests.extend(requests)
    blender.bake()
    scene.frame_set(24)
    return subject, requests, warnings


def t_look_at_target_bare_character_id():
    subject, requests, warnings = _bake_look_at("char_002")
    error = _head_facing_error_deg(subject, (3.0, 0.0, EYE))
    resolved = requests[0].params
    return {"ok": warnings == [] and error <= 2.0
            and "target" not in resolved,
            "error_deg": round(error, 4), "warnings": warnings,
            "params": resolved}


def t_look_at_target_dict_character():
    subject, requests, warnings = _bake_look_at({"character": "char_002"})
    error = _head_facing_error_deg(subject, (3.0, 0.0, EYE))
    return {"ok": warnings == [] and error <= 2.0,
            "error_deg": round(error, 4), "warnings": warnings}


def t_unresolvable_target_is_a_deterministic_error():
    """不在位置表的目标：动作跳过 + 警告点名目标——不是静默 0 / 默认 30°。"""
    scene = fresh_scene()
    create_character("char_001", "甲", "#FF6B6B",
                     location=(0.0, 0.0, 0.0), facing=(0.0, 1.0, 0.0))
    warnings: list = []
    requests = action_requests(_shot("不在场"), 1, _cast(), warnings)
    return {"ok": requests == [] and len(warnings) == 1
            and "无法解析" in warnings[0] and "不在场" in warnings[0],
            "warnings": warnings}


def t_hand_to_toward_character_resolves_to_a_direction():
    """道具动作的结构化 toward → 主体到目标的方向量，烘焙不崩。"""
    scene = fresh_scene()
    scene.frame_start, scene.frame_end = 1, 48
    subject = create_character("char_001", "甲", "#FF6B6B",
                               location=(0.0, 0.0, 0.0),
                               facing=(0.0, 1.0, 0.0))
    shot = ShotPlan(
        shot_id="shot_001", intent="递物", shot_type=ShotType.MS,
        duration_frames=48, characters=["char_001", "char_002"],
        actions=[{"character_id": "char_001", "action_type": "hand_to",
                  "start_frame": 1, "end_frame": 24,
                  "params": {"prop": "钱袋",
                             "toward": {"character": "char_002"}}}])
    warnings: list = []
    requests = action_requests(shot, 1, _cast(), warnings)
    assert requests and warnings == [], warnings
    assert requests[0].params["toward"] == [3.0, 0.0, 0.0]
    blender = MotionBlender(subject)
    blender.requests.extend(requests)
    blender.bake()
    scene.frame_set(24)
    bpy.context.view_layer.update()
    tilt = math.degrees(float(subject.body_pivot.rotation_euler[0]))
    return {"ok": warnings == [] and abs(tilt - 8.0) <= 0.5,
            "toward": requests[0].params["toward"], "tilt_deg": round(tilt, 3)}


def main() -> int:
    capture_main_thread()
    check("look_at_target_bare_character_id", t_look_at_target_bare_character_id)
    check("look_at_target_dict_character", t_look_at_target_dict_character)
    check("unresolvable_target_is_a_deterministic_error",
          t_unresolvable_target_is_a_deterministic_error)
    check("hand_to_toward_character_resolves_to_a_direction",
          t_hand_to_toward_character_resolves_to_a_direction)

    passed = [key for key, value in RESULTS.items() if value.get("ok")]
    failed = [key for key, value in RESULTS.items() if not value.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS},
        ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
