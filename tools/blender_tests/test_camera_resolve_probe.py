"""缺陷 E（T2）Blender 探针：相机引用按镜头稳定解析。

判据：构建两镜场景 → 单镜重建（删旧相机建新相机）→ 用旧 ``camera_id``
（对象名 ``BD_Cam_shot_002``）调用相机解析与运镜工具，仍返回**当前**相机
对象（对象身份是新对象），不再产生"找不到相机"的 domain_error。

运行：
  blender --background --factory-startup --python tools/blender_tests/test_camera_resolve_probe.py
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
from block_director.layer3_engine.scene_context import get_context  # noqa: E402
from block_director.layer3_engine.scene_sync import reset_synchronizer  # noqa: E402
from block_director.layer3_engine.shot_builder import build_scene  # noqa: E402
from block_director.layer3_engine.shot_regenerator import regenerate_shot  # noqa: E402
from block_director.layer3_engine.tool_bindings import (  # noqa: E402
    _resolve_camera,
    _tool_move_camera,
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


def t_old_camera_id_resolves_to_new_object_after_rebuild():
    reset_synchronizer()
    try:
        fresh_scene()
        plan = two_shot_plan()
        build_scene(plan, SceneSpec.from_plan(plan), clear_scene=True)
        context = get_context()
        old_object = context.cameras["shot_002"]
        old_name = old_object.name

        #: 单镜重建：删旧相机建新相机（对象身份变化、名字/镜头键稳定）。
        report = regenerate_shot("shot_002", plan=plan, context=context)
        new_object = context.cameras["shot_002"]
        same_identity = new_object is old_object

        resolved, problem = _resolve_camera({"camera_id": old_name})
        move_result = _tool_move_camera("dolly_in", 97, 216,
                                        camera_id=old_name, amount=0.3)
        ok = (report["ok"] and not same_identity
              and resolved is new_object and problem == ""
              and str(move_result).startswith("镜头 shot_002 已加运镜"))
        return {"ok": ok, "old_name": old_name,
                "same_identity": same_identity,
                "resolved_is_new": resolved is new_object,
                "problem": problem, "move_result": str(move_result)}
    finally:
        reset_synchronizer()


def main() -> int:
    capture_main_thread()
    check("old_camera_id_resolves_to_new_object_after_rebuild",
          t_old_camera_id_resolves_to_new_object_after_rebuild)
    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS},
        ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
