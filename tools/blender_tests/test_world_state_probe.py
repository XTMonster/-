"""R11（T4）Blender 探针：runtime_world_state.json 实时刷新与一致性。

判据：
1. 场景构建后 JSON 存在且与现场一致（无差值）；
2. agent 工具（place_character）改动后 JSON 立即反映新坐标；
3. 人为写旧 JSON 后调用查询工具，检出 ``E_WORLD_STATE_DIVERGED`` 并刷新
   重读——后续查询一致（不再报差）。

运行：
  blender --background --factory-startup --python tools/blender_tests/test_world_state_probe.py -- --out <dir>
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
from block_director.contracts.world_state import E_WORLD_STATE_DIVERGED  # noqa: E402
from block_director.layer3_engine.scene_context import get_context  # noqa: E402
from block_director.layer3_engine.scene_sync import reset_synchronizer  # noqa: E402
from block_director.layer3_engine.shot_builder import build_scene  # noqa: E402
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
    plan = two_shot_plan()
    build_scene(plan, SceneSpec.from_plan(plan), clear_scene=True)
    context = get_context()
    context.world_state_path = str(out_dir / "runtime_world_state.json")
    return plan, context


def t_build_refreshes_json_and_is_consistent():
    out_dir = Path(ROOT / ".scratch_diag" / "world_state_probe")
    _plan, context = _build(out_dir)
    try:
        payload = refresh_world_state(context)
        path = context.world_state_path
        on_disk = json.loads(Path(path).read_text(encoding="utf-8"))
        findings = ensure_consistent(context)
        return {"ok": Path(path).exists() and findings == []
                and payload["schema_version"] == "runtime-world/v1"
                and len(payload["characters"]) == 2
                and len(payload["cameras"]) == 2,
                "characters": list(payload["characters"]),
                "cameras": list(payload["cameras"]),
                "findings": findings,
                "on_disk_characters": list(on_disk["characters"])}
    finally:
        reset_synchronizer()


def t_agent_tool_write_refreshes_json():
    out_dir = Path(ROOT / ".scratch_diag" / "world_state_probe")
    _plan, context = _build(out_dir)
    try:
        from block_director.layer3_engine.tool_bindings import (
            _tool_place_character,
        )
        result = _tool_place_character("char_001", position=[2.0, -2.0, 0.0])
        payload = json.loads(Path(context.world_state_path)
                             .read_text(encoding="utf-8"))
        position = payload["characters"]["char_001"]["position"]
        findings = ensure_consistent(context)
        return {"ok": position == [2.0, -2.0, 0.0] and findings == []
                and str(result).startswith("角色 char_001 已就位"),
                "position": position, "findings": findings,
                "result": str(result)}
    finally:
        reset_synchronizer()


def t_tampered_json_is_detected_refreshed_and_recovered():
    out_dir = Path(ROOT / ".scratch_diag" / "world_state_probe")
    _plan, context = _build(out_dir)
    try:
        path = Path(context.world_state_path)
        refresh_world_state(context)
        live = collect_world_state(context)
        #: 人为写旧坐标（模拟 JSON 与场景脱节）
        live["characters"]["char_001"]["position"] = [-9.0, -9.0, -9.0]
        path.write_text(json.dumps(live, ensure_ascii=False), encoding="utf-8")

        from block_director.layer3_engine.tool_bindings import (
            _tool_get_scene_state,
        )
        text = _tool_get_scene_state()
        detected = E_WORLD_STATE_DIVERGED in text or any(
            E_WORLD_STATE_DIVERGED in note for note in context.notes)
        refreshed = json.loads(path.read_text(encoding="utf-8"))
        refreshed_position = refreshed["characters"]["char_001"]["position"]
        findings_after = ensure_consistent(context)
        return {"ok": detected and refreshed_position != [-9.0, -9.0, -9.0]
                and findings_after == [],
                "detected": detected, "notes": list(context.notes),
                "refreshed_position": refreshed_position,
                "findings_after": findings_after}
    finally:
        reset_synchronizer()


def t_driver_wiring_registers_path_and_writes_json():
    out_dir = Path(ROOT / ".scratch_diag" / "world_state_probe")
    _plan, context = _build(out_dir)
    try:
        #: 真实时序是“构建器先建 context、驱动器构建成功后补登记路径并刷新”：
        #: 清掉 _build 手工登记的路径，改走 PrevisDriver._wire_world_state。
        context.world_state_path = None
        target = out_dir / "runtime_world_state.json"
        if target.exists():
            target.unlink()
        from types import MethodType, SimpleNamespace

        from block_director.layer5_orchestrator.driver import PrevisDriver

        stub = SimpleNamespace(
            audit=SimpleNamespace(directory=out_dir / "runs"))
        MethodType(PrevisDriver._wire_world_state, stub)()
        return {"ok": context.world_state_path == str(target)
                and target.exists(),
                "path": context.world_state_path,
                "exists": target.exists()}
    finally:
        reset_synchronizer()


def main() -> int:
    capture_main_thread()
    check("build_refreshes_json_and_is_consistent",
          t_build_refreshes_json_and_is_consistent)
    check("agent_tool_write_refreshes_json",
          t_agent_tool_write_refreshes_json)
    check("tampered_json_is_detected_refreshed_and_recovered",
          t_tampered_json_is_detected_refreshed_and_recovered)
    check("driver_wiring_registers_path_and_writes_json",
          t_driver_wiring_registers_path_and_writes_json)
    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS},
        ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
