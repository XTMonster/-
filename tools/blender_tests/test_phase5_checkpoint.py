"""Phase 5 集成测试：检查点与回滚（执行文档 v1.2 §11.2）。

运行：
  blender --background --factory-startup --python tools/blender_tests/test_phase5_checkpoint.py
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
from block_director.layer3_engine.checkpoint_manager import (  # noqa: E402
    CheckpointManager,
)
from block_director.layer3_engine.collection_router import ensure_collections  # noqa: E402
from block_director.layer3_engine.scene_context import get_context  # noqa: E402
from block_director.layer3_engine.shot_builder import build_scene  # noqa: E402
from block_director.layer3_engine.tool_bindings import register_all_scene_tools  # noqa: E402
from block_director.layer5_orchestrator.tool_registry import ToolRegistry  # noqa: E402
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


def _built():
    fresh_scene()
    build_scene(two_shot_plan())
    registry = ToolRegistry()
    register_all_scene_tools(registry)
    return get_context(), registry, CheckpointManager()


def _character_x(character) -> float:
    bpy.context.view_layer.update()
    return round(character.root.matrix_world.translation.x, 3)


def _live_keys(obj) -> int:
    """对象当前实际拥有的关键帧数（跨 4.x/5.x）。"""
    animation = obj.animation_data
    if animation is None:
        return 0
    return sum(len(curve.keyframe_points) for curve in action_fcurves(animation.action))


def _checkpoint_keys(checkpoint, obj_name: str) -> int:
    return sum(len(record.keys) for record in checkpoint.curves.get(obj_name, []))


# --------------------------------------------------------------------------- #
# 1. 变换回滚
# --------------------------------------------------------------------------- #
def t_rollback_restores_transforms():
    context, registry, manager = _built()
    character = context.character("char_002")
    before = _character_x(character)
    checkpoint = manager.capture("before-move")

    registry.execute("place_character",
                     {"character_id": "char_002", "position": [20.0, 0.0, 0.0]})
    moved = _character_x(character)
    manager.restore("before-move")
    restored = _character_x(character)

    return {"ok": abs(moved - 20.0) < 0.01 and abs(restored - before) < 0.01,
            "before": before, "moved": moved, "restored": restored,
            "summary": checkpoint.summary()}


# --------------------------------------------------------------------------- #
# 2. 关键帧回滚（新增的动画要被撤掉）
# --------------------------------------------------------------------------- #
def t_rollback_restores_animation():
    context, registry, manager = _built()
    character = context.character("char_001")
    head = character.head_pivot
    checkpoint = manager.capture("before-action")
    keys_before = _live_keys(head)
    assert keys_before == _checkpoint_keys(checkpoint, head.name)

    registry.execute("character_action",
                     {"character_id": "char_001", "action_type": "shake_head",
                      "start_frame": 120, "end_frame": 180, "params": {"cycles": 3}})
    keys_after_edit = _live_keys(head)

    manager.restore("before-action")
    bpy.context.view_layer.update()
    keys_restored = _live_keys(head)
    return {"ok": keys_before > 0 and keys_after_edit > keys_before
            and keys_restored == keys_before,
            "keys_before": keys_before,
            "keys_after_edit": keys_after_edit,
            "keys_restored": keys_restored}


# --------------------------------------------------------------------------- #
# 3. 帧范围与剪切标记回滚
# --------------------------------------------------------------------------- #
def t_rollback_restores_timeline():
    scene = fresh_scene()
    build_scene(two_shot_plan())
    manager = CheckpointManager()
    checkpoint = manager.capture("before-retime")
    original_range = (scene.frame_start, scene.frame_end)

    scene.frame_start, scene.frame_end = 5, 42
    for marker in list(scene.timeline_markers):
        scene.timeline_markers.remove(marker)

    manager.restore("before-retime")
    restored_range = (scene.frame_start, scene.frame_end)
    markers = sorted(m.name for m in scene.timeline_markers)
    return {"ok": restored_range == original_range and len(markers) == 2
            and all(m.camera is not None for m in scene.timeline_markers),
            "original": list(original_range), "restored": list(restored_range),
            "markers": markers}


# --------------------------------------------------------------------------- #
# 4. 未知检查点会报错，不会静默成功
# --------------------------------------------------------------------------- #
def t_unknown_checkpoint_raises():
    _context, _registry, manager = _built()
    manager.capture("kept")
    raised = False
    try:
        manager.restore("nope")
    except KeyError:
        raised = True
    return {"ok": raised and manager.names() == ["kept"],
            "names": manager.names()}


# --------------------------------------------------------------------------- #
# 5. 数量上限会淘汰最旧的检查点
# --------------------------------------------------------------------------- #
def t_checkpoint_limit_drops_oldest():
    _context, _registry, manager = _built()
    manager.limit = 2
    for index in range(4):
        manager.capture(f"cp{index}")
    return {"ok": manager.names() == ["cp2", "cp3"],
            "names": manager.names()}


def main() -> int:
    capture_main_thread()
    check("rollback_restores_transforms", t_rollback_restores_transforms)
    check("rollback_restores_animation", t_rollback_restores_animation)
    check("rollback_restores_timeline", t_rollback_restores_timeline)
    check("unknown_checkpoint_raises", t_unknown_checkpoint_raises)
    check("checkpoint_limit_drops_oldest", t_checkpoint_limit_drops_oldest)

    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS}, ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
