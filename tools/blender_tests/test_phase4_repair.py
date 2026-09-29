"""Phase 4 集成测试：规则校验 → 定向修复的闭环（执行文档 v1.2 §7.1 B3/B4）。

运行：
  blender --background --factory-startup --python tools/blender_tests/test_phase4_repair.py
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
from block_director.layer3_engine.cinema_engine import create_camera  # noqa: E402
from block_director.layer3_engine.collection_router import ensure_collections  # noqa: E402
from block_director.layer3_engine.scene_context import get_context  # noqa: E402
from block_director.layer3_engine.scene_executor import create_prop  # noqa: E402
from block_director.layer3_engine.shot_auditor import BpyShotAuditor  # noqa: E402
from block_director.layer3_engine.shot_builder import build_scene  # noqa: E402
from block_director.layer3_engine.tool_bindings import register_all_scene_tools  # noqa: E402
from block_director.layer5_orchestrator.tool_registry import ToolRegistry  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

RESULTS: dict = {}


def fresh_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 320
    scene.render.resolution_y = 180
    ensure_collections(scene)
    return scene


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                         "trace": traceback.format_exc(limit=3)}


def _built_with_tools():
    fresh_scene()
    summary = build_scene(two_shot_plan())
    registry = ToolRegistry()
    register_all_scene_tools(registry)
    return summary, get_context(), registry, BpyShotAuditor()


def _break_axis(context):
    """把 shot_001 的相机换到轴线**另一侧**，制造 R001。

    v1.2 这里把机位写死在 (0, -6)：默认站位改成"两人相对而立"之后，
    首镜机位本身落在 -Y 侧，(0, -6) 反而是合法的一侧，越轴就制造不出来了。
    所以这里按**已确立的侧别取反**。
    """
    scene = bpy.context.scene
    axis = context.axis
    opposite = -1.0 if (axis is None or axis.established_side > 0) else 1.0
    bundle = create_camera("broken", (0.0, opposite * 6.0, 1.2),
                           look_at=(0.0, 0.0, 1.0),
                           make_scene_camera=False)
    context.cameras["shot_001"] = bundle.camera
    scene.camera = bundle.camera
    bpy.context.view_layer.update()
    return bundle.camera


# --------------------------------------------------------------------------- #
# 1. 审核器抓出越轴
# --------------------------------------------------------------------------- #
def t_auditor_reports_axis_violation():
    _summary, context, _registry, auditor = _built_with_tools()
    clean = auditor.audit("shot_001")
    _break_axis(context)
    broken = auditor.audit("shot_001")

    rules = {f.rule for f in broken.errors}
    return {"ok": clean.passed and not broken.passed and "R001" in rules,
            "clean_score": clean.score, "clean_passed": clean.passed,
            "broken_passed": broken.passed,
            "broken_errors": [f.to_dict() for f in broken.errors]}


# --------------------------------------------------------------------------- #
# 2. 修复工具真的把问题改掉
# --------------------------------------------------------------------------- #
def t_setup_camera_fixes_the_violation():
    _summary, context, registry, auditor = _built_with_tools()
    _break_axis(context)
    before = auditor.audit("shot_001")

    repaired = registry.execute("setup_camera",
                                {"shot_id": "shot_001", "shot_type": "MLS",
                                 "side": "front"})
    after = auditor.audit("shot_001")

    return {"ok": (not before.passed and repaired.ok and after.passed),
            "before_passed": before.passed,
            "repair_observation": repaired.content,
            "after_passed": after.passed, "after_score": after.score,
            "after_errors": [f.to_dict() for f in after.errors]}


# --------------------------------------------------------------------------- #
# 3. 移动角色会改变可见性（LLM 的手能改场景）
# --------------------------------------------------------------------------- #
def t_place_character_changes_visibility():
    _summary, _context, registry, _auditor = _built_with_tools()
    before = registry.execute("check_visibility", {"character_id": "char_002"})
    moved = registry.execute("place_character",
                             {"character_id": "char_002",
                              "position": [20.0, 0.0, 0.0]})
    after = registry.execute("check_visibility", {"character_id": "char_002"})
    return {"ok": (before.ok and "在画" in before.content and moved.ok
                   and after.ok and "不在画" in after.content),
            "before": before.content, "move": moved.content,
            "after": after.content}


# --------------------------------------------------------------------------- #
# 4. 加动作会真的写下关键帧
# --------------------------------------------------------------------------- #
def t_character_action_adds_keyframes():
    _summary, context, registry, _auditor = _built_with_tools()
    character = context.character("char_002")
    head = character.head_pivot
    before = character.root.animation_data is not None
    result = registry.execute("character_action",
                              {"character_id": "char_002",
                               "action_type": "shake_head",
                               "start_frame": 100, "end_frame": 140,
                               "params": {"cycles": 3}})
    animated = head.animation_data is not None
    return {"ok": result.ok and animated,
            "observation": result.content,
            "root_had_animation_before": before,
            "head_animated": animated}


# --------------------------------------------------------------------------- #
# 5. R007 引用缺失会被抓出来
# --------------------------------------------------------------------------- #
def t_rule_r007_missing_character():
    _summary, context, _registry, auditor = _built_with_tools()
    context.plan.shots[0].characters.append("ghost")
    result = auditor.audit("shot_001")
    rules = {f.rule for f in result.errors}
    return {"ok": not result.passed and "R007" in rules,
            "errors": [f.to_dict() for f in result.errors]}


# --------------------------------------------------------------------------- #
# 6. R008 地面约束
# --------------------------------------------------------------------------- #
def t_rule_r008_below_ground():
    _summary, context, _registry, auditor = _built_with_tools()
    context.character("char_001").root.location.z = -0.5
    bpy.context.view_layer.update()
    result = auditor.audit("shot_001")
    rules = {f.rule for f in result.warnings}
    return {"ok": "R008" in rules,
            "warnings": [f.to_dict() for f in result.warnings]}


# --------------------------------------------------------------------------- #
# 7. 工具参数错误仍是观察文本
# --------------------------------------------------------------------------- #
def t_tool_errors_are_observations():
    _summary, _context, registry, _auditor = _built_with_tools()
    unknown_shot = registry.execute("setup_camera", {"shot_id": "nope"})
    unknown_character = registry.execute("place_character",
                                         {"character_id": "nobody"})
    bad_action = registry.execute("character_action",
                                  {"character_id": "char_001",
                                   "action_type": "backflip",
                                   "start_frame": 1, "end_frame": 10})
    # 非法 action_type 会被 schema 枚举先拦下（"参数校验失败"），
    # 两者都是合格的可回灌观察；这里只要求"失败且说清了原因"。
    return {"ok": (not unknown_shot.ok and "找不到镜头" in unknown_shot.content
                   and not unknown_character.ok
                   and "找不到角色" in unknown_character.content
                   and not bad_action.ok
                   and ("未知动作类型" in bad_action.content
                        or "参数校验失败" in bad_action.content)),
            "unknown_shot": unknown_shot.content,
            "unknown_character": unknown_character.content,
            "bad_action": bad_action.content}


# --------------------------------------------------------------------------- #
# 8. R002 空间碰撞
# --------------------------------------------------------------------------- #
def t_rule_r002_collision():
    _summary, context, _registry, auditor = _built_with_tools()
    clean = auditor.audit("shot_001")
    # 在 char_002 所在位置塞一张桌子：角色应被判为穿模
    create_prop("table_01", (0.75, 0.0, 0.4), size=(1.5, 1.5, 0.8))
    bpy.context.view_layer.update()
    collided = auditor.audit("shot_001")
    rules = {f.rule for f in collided.errors}
    return {"ok": clean.passed and not collided.passed and "R002" in rules,
            "clean_passed": clean.passed,
            "errors": [f.to_dict() for f in collided.errors
                       if f.rule == "R002"]}


# --------------------------------------------------------------------------- #
# 9. R003 动作时间重叠
# --------------------------------------------------------------------------- #
def t_rule_r003_action_overlap():
    _summary, context, _registry, auditor = _built_with_tools()
    clean = auditor.audit("shot_002")
    shot = context.shot("shot_002")
    shot.actions.append({"character_id": "char_002", "action_type": "nod",
                         "start_frame": 10, "end_frame": 40,
                         "params": {"cycles": 2}})
    overlapped = auditor.audit("shot_002")
    rules = {f.rule for f in overlapped.errors}
    return {"ok": clean.passed and not overlapped.passed and "R003" in rules,
            "clean_passed": clean.passed,
            "errors": [f.to_dict() for f in overlapped.errors
                       if f.rule == "R003"]}


# --------------------------------------------------------------------------- #
# 10. R011 对白容纳
# --------------------------------------------------------------------------- #
def t_rule_r011_dialogue_overflow():
    _summary, context, _registry, auditor = _built_with_tools()
    shot = context.shot("shot_001")            # 时长 96 帧
    clean = auditor.audit("shot_001")

    # 先给一句排得下的对白：应当仍然通过
    shot.dialogues.append({"character_id": "char_001", "text": "你好。",
                           "start_frame": 1, "end_frame": 40})
    fitting = auditor.audit("shot_001")

    # 再把它推到超过时长（40 + 12 = 52 ≤ 96；改成 90 → 102 > 96）
    shot.dialogues[0]["end_frame"] = 90
    overflow = auditor.audit("shot_001")
    rules = {f.rule for f in overflow.errors}

    return {"ok": clean.passed and fitting.passed
            and not overflow.passed and "R011" in rules,
            "clean_passed": clean.passed, "fitting_passed": fitting.passed,
            "overflow_passed": overflow.passed,
            "errors": [f.to_dict() for f in overflow.errors if f.rule == "R011"]}


def main() -> int:
    capture_main_thread()
    check("auditor_reports_axis_violation", t_auditor_reports_axis_violation)
    check("setup_camera_fixes_the_violation", t_setup_camera_fixes_the_violation)
    check("place_character_changes_visibility", t_place_character_changes_visibility)
    check("character_action_adds_keyframes", t_character_action_adds_keyframes)
    check("rule_r007_missing_character", t_rule_r007_missing_character)
    check("rule_r008_below_ground", t_rule_r008_below_ground)
    check("tool_errors_are_observations", t_tool_errors_are_observations)
    check("rule_r002_collision", t_rule_r002_collision)
    check("rule_r003_action_overlap", t_rule_r003_action_overlap)
    check("rule_r011_dialogue_overflow", t_rule_r011_dialogue_overflow)

    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS}, ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
