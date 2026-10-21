"""缺陷 C（T1）Blender 探针：agent 工具改动与用户手动改动分离。

判据四条：

1. 模拟 agent 工具写入（suppress_sync + mark_agent_edited + 挪角色）后，
   ``dirty_ids()`` 不含该角色，``sync_from_blender`` 不回读 → 角色
   ``initial_location`` 保持计划原值；
2. 用户直接挪角色（无 agent 标记）后，``dirty_ids()`` 含该角色且 sync
   照旧回读保留；
3. 真实工具 ``_tool_place_character`` 调用后，对象带 ``bd_agent_edited``
   标记，``dirty_ids()`` 不含该角色；
4. ``regenerate_shot`` 重建后清掉 agent 标记并重记基线，后续用户改动仍可
   被识别为 dirty（可回读）。

运行：
  blender --background --factory-startup --python tools/blender_tests/test_agent_edit_probe.py
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
from block_director.layer3_engine.scene_sync import (  # noqa: E402
    get_synchronizer,
    is_agent_edited,
    mark_agent_edited,
    note_build,
    reset_synchronizer,
    suppress_sync,
)
from block_director.layer3_engine.shot_builder import build_scene  # noqa: E402
from block_director.layer3_engine.scene_context import get_context  # noqa: E402
from block_director.layer3_engine.shot_regenerator import regenerate_shot  # noqa: E402
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


def _build_with_singleton_sync():
    """reset → 单例同步器 → 构建（build_scene 内部会 note_build 记基线）。"""
    reset_synchronizer()
    sync = get_synchronizer()
    fresh_scene()
    plan = two_shot_plan()
    spec = SceneSpec.from_plan(plan)
    build_scene(plan, spec, clear_scene=True)
    return sync, plan, spec


def _plan_location(spec, character_id):
    return tuple(next(m.initial_location for m in spec.cast
                      if m.id == character_id))


def t_agent_write_not_readback_keeps_plan_value():
    sync, plan, spec = _build_with_singleton_sync()
    try:
        character = get_context().characters["char_001"]
        original = _plan_location(spec, "char_001")
        with suppress_sync(sync):
            character.root.location = (original[0] + 3.0,
                                       original[1] - 1.0, 0.0)
            bpy.context.view_layer.update()
            mark_agent_edited(character.root)
        dirty = sync.dirty_ids()
        _plan2, spec2 = sync.sync_from_blender(plan, spec)
        readback = _plan_location(spec2, "char_001")
        return {"ok": dirty == [] and readback == original,
                "dirty": dirty, "original": original, "readback": readback,
                "marked": is_agent_edited(character.root)}
    finally:
        reset_synchronizer()


def t_user_move_still_readback():
    sync, plan, spec = _build_with_singleton_sync()
    try:
        character = get_context().characters["char_001"]
        original = _plan_location(spec, "char_001")
        moved = (original[0] + 1.5, original[1] + 0.5, 0.0)
        character.root.location = moved
        bpy.context.view_layer.update()
        dirty = sync.dirty_ids()
        _plan2, spec2 = sync.sync_from_blender(plan, spec)
        readback = _plan_location(spec2, "char_001")
        return {"ok": dirty == ["char_001"] and readback == moved,
                "dirty": dirty, "moved": moved, "readback": readback}
    finally:
        reset_synchronizer()


def t_tool_place_character_marks_agent_and_stays_clean():
    sync, _plan, _spec = _build_with_singleton_sync()
    try:
        from block_director.layer3_engine.tool_bindings import (
            _tool_place_character,
        )
        character = get_context().characters["char_001"]
        result = _tool_place_character("char_001",
                                       position=[2.0, -2.0, 0.0])
        dirty = sync.dirty_ids()
        position = tuple(round(v, 3)
                         for v in character.root.matrix_world.translation)
        return {"ok": is_agent_edited(character.root)
                and dirty == [] and position == (2.0, -2.0, 0.0)
                and str(result).startswith("角色 char_001 已就位"),
                "dirty": dirty, "position": position,
                "marked": is_agent_edited(character.root),
                "result": str(result)}
    finally:
        reset_synchronizer()


def t_rebuild_clears_agent_marks_and_rebaselines():
    sync, plan, _spec = _build_with_singleton_sync()
    try:
        context = get_context()
        character = context.characters["char_001"]
        original = _plan_location(SceneSpec.from_plan(plan), "char_001")
        with suppress_sync(sync):
            character.root.location = (9.0, 9.0, 0.0)
            bpy.context.view_layer.update()
            mark_agent_edited(character.root)
        dirty_before = sync.dirty_ids()
        report = regenerate_shot("shot_001", sync=sync, plan=plan,
                                 context=context)
        still_marked = is_agent_edited(character.root)
        # 单镜重建不重置角色摆位（只换相机/重烘动作），但 agent 挪过的位置
        # 不得被回读进计划基线：这里直接验证 sync 不把 (9,9,0) 写回计划。
        _plan2, spec2 = sync.sync_from_blender(plan, SceneSpec.from_plan(plan))
        readback = _plan_location(spec2, "char_001")
        # 重建后基线已重记：再挪一次（用户改动）必须能被识别
        user_dirty = sync.dirty_ids()
        character.root.location = (4.0, 4.0, 0.0)
        bpy.context.view_layer.update()
        after_user = sync.dirty_ids()
        return {"ok": report["ok"] and not still_marked
                and dirty_before == [] and user_dirty == []
                and after_user == ["char_001"]
                and readback == original,
                "report_ok": report["ok"], "still_marked": still_marked,
                "dirty_before": dirty_before, "readback": readback,
                "original": original, "user_dirty": user_dirty,
                "after_user": after_user}
    finally:
        reset_synchronizer()


def main() -> int:
    capture_main_thread()
    check("agent_write_not_readback_keeps_plan_value",
          t_agent_write_not_readback_keeps_plan_value)
    check("user_move_still_readback", t_user_move_still_readback)
    check("tool_place_character_marks_agent_and_stays_clean",
          t_tool_place_character_marks_agent_and_stays_clean)
    check("rebuild_clears_agent_marks_and_rebaselines",
          t_rebuild_clears_agent_marks_and_rebaselines)

    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS},
        ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
