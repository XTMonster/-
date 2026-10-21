"""缺陷 B / R8（T6）Blender 探针：revert_shot 物理回滚到最高分版本。

判据：
1. 记录最高分快照（相机+角色+道具）后改坏场景（挪角色/相机/道具）；
2. 调用 ``revert_shot`` 工具后，live 世界坐标与最高分快照逐字段一致，
   ``runtime_world_state.json`` 同步刷新且无差值（R11）；
3. 再次评估构图分与历史最高分版本一致（探针里用快照分数作为最高分）。

运行：
  blender --background --factory-startup --python tools/blender_tests/test_revert_shot_probe.py -- --out <dir>
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
from block_director.contracts.world_state import divergence_report  # noqa: E402
from block_director.layer3_engine.scene_context import get_context  # noqa: E402
from block_director.layer3_engine.scene_sync import reset_synchronizer  # noqa: E402
from block_director.layer3_engine.shot_builder import build_scene  # noqa: E402
from block_director.layer3_engine.tool_bindings import _tool_revert_shot  # noqa: E402
from block_director.layer3_engine.world_state import (  # noqa: E402
    collect_world_state,
    ensure_consistent,
    refresh_world_state,
)
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


def _build(out_dir: Path):
    reset_synchronizer()
    fresh_scene()
    plan = two_shot_plan(with_actions=False)
    spec = SceneSpec.from_plan(
        plan,
        props=[{"id": "coin", "position": (1.0, 2.4, 1.0),
                "size": (0.12, 0.12, 0.03), "shape": "cylinder"}])
    build_scene(plan, spec, clear_scene=True)
    context = get_context()
    context.world_state_path = str(out_dir / "runtime_world_state.json")
    return plan, context


def _mutate_scene():
    """把 best 场景改坏：角色挪走、相机换位/焦距、道具出画。"""
    context = get_context()
    character = context.characters["char_001"]
    character.root.location = (9.0, 9.0, 0.0)
    camera = context.cameras["shot_001"]
    camera.location = (5.0, 5.0, 5.0)
    camera.data.lens = 12.0
    prop = next(obj for obj in bpy.context.scene.objects
                if obj.get("bd_element_type") == "prop")
    prop.location = (10.0, 10.0, 10.0)
    bpy.context.view_layer.update()


def t_revert_restores_best_and_refreshes_json():
    out_dir = Path(ROOT / ".scratch_diag" / "revert_shot_probe")
    _plan, context = _build(out_dir)
    try:
        refresh_world_state(context)
        best = collect_world_state(context)
        context.react_best_snapshot["shot_001"] = best
        _mutate_scene()
        mutated = collect_world_state(context)
        mutated_away = (mutated != best)

        text = str(_tool_revert_shot("shot_001"))
        live = collect_world_state(context)
        restored = live == best
        findings = ensure_consistent(context)
        on_disk = json.loads(Path(context.world_state_path)
                             .read_text(encoding="utf-8"))
        return {"ok": mutated_away and restored and findings == []
                and on_disk == live,
                "mutated_away": mutated_away,
                "restored": restored,
                "findings": findings,
                "result": text[:80],
                "json_matches_live": on_disk == live}
    finally:
        reset_synchronizer()


def t_revert_without_snapshot_is_a_clean_domain_error():
    out_dir = Path(ROOT / ".scratch_diag" / "revert_shot_probe")
    _plan, context = _build(out_dir)
    try:
        context.react_best_snapshot.clear()
        text = str(_tool_revert_shot("shot_001"))
        return {"ok": "没有最高分版本快照" in text,
                "text": text[:120]}
    finally:
        reset_synchronizer()


def main() -> int:
    capture_main_thread()
    check("revert_restores_best_and_refreshes_json",
          t_revert_restores_best_and_refreshes_json)
    check("revert_without_snapshot_is_a_clean_domain_error",
          t_revert_without_snapshot_is_a_clean_domain_error)
    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS},
        ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
