"""v1.4 P9.5 / US-1 / RK-9：operator（GUI）路径必须真的出片。

``--background`` 下跑不了模态（``event_timer_add`` 需要 ``context.window``），
所以探针驱动的是从 ``invoke()`` 抽出来的 ``build_run_context`` —— 这是
P9.5 把"建运行"抽成可测函数的**唯一理由**。

判据（RK-9，全部外生）：
  ① 负对照：不注入 ``builder`` → 必须失败（不是"仅规划"的 DONE）；
  ② 正向：``audit_log.jsonl`` 出现 ``run_started`` / ``scene_built`` /
     ``shot_audit`` / ``export_started``（``export_started`` 是 P9.5 新增），
     且 ``bpy.data.objects`` 里有 ``BD_Char_*`` / ``BD_Cam_*`` /
     ``BD_CamTarget_*``；
  ③ 产物集合与 CLI 路径一致：``shots.json`` / ``prompts.md`` / 逐镜 ``*.mp4``
     / 首帧 ``*.png``。

运行：blender --background --factory-startup --python tools/blender_tests/test_operator_end_to_end.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy  # noqa: E402

import block_director  # noqa: E402

from block_director.layer3_engine.collection_router import ensure_collections  # noqa: E402
from block_director.layer5_orchestrator import modal_operator  # noqa: E402
from block_director.layer5_orchestrator.offline import OfflineTransport  # noqa: E402
from block_director.layer5_orchestrator.runtime import clear_active, get_active  # noqa: E402
from block_director.layer5_orchestrator.states import DriverState  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

RESULTS: dict = {}


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                         "trace": traceback.format_exc(limit=3)}


class InlineThread:
    """同步执行器：LLM 调用在 start() 时立刻完成，探针无需 sleep。"""

    def __init__(self, target, name=""):
        self._target = target

    def start(self):
        self._target()


class _Context:
    """最小 context：``build_run_context`` 只用到 ``context.scene``。"""

    def __init__(self, scene):
        self.scene = scene


def fresh_scene():
    # 面板字段（bd_offline / bd_script_path …）由插件注册时挂到 Scene 上；
    # ``--factory-startup`` 下插件未启用，必须先走一次真实的注册路径。
    block_director.register()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    ensure_collections(scene)
    scene.bd_offline = True
    scene.bd_script_path = ""
    return scene


def _run(run, tmp_dir):
    """同步把状态机推到终止（代替 modal 的 timer 循环）。"""
    driver = run.driver
    driver.thread_factory = InlineThread
    for _ in range(5000):
        if not driver.step():
            break
    return driver.state


# --------------------------------------------------------------------------- #
# 1. 负对照：不注入 builder 必须失败
# --------------------------------------------------------------------------- #
def t_missing_builder_is_refused():
    fresh_scene()
    run = modal_operator.build_run_context(_Context(bpy.context.scene),
                                           builder=None,
                                           transport=OfflineTransport())
    return {"ok": (not run.ok) and run.driver is None and run.problems,
            "problems": list(run.problems)}


# --------------------------------------------------------------------------- #
# 2. 正向：operator 路径建场景、出片、写全四类事件
# --------------------------------------------------------------------------- #
def t_operator_path_builds_and_exports():
    scene = fresh_scene()
    tmp_dir = Path(tempfile.mkdtemp(prefix="bd_operator_"))
    modal_operator.default_project_root = staticmethod(lambda: tmp_dir)

    clear_active()
    run = modal_operator.build_run_context(
        _Context(scene), transport=OfflineTransport(),
        parsed_script=None)
    if not run.ok:
        return {"ok": False, "problems": list(run.problems)}

    state = _run(run, tmp_dir)
    payload = None
    if state is DriverState.DONE:
        payload = modal_operator.export_finished_run(run)
    clear_active()

    driver = run.driver
    kinds = [event.kind for event in driver.audit.recent(400)]
    names = [obj.name for obj in bpy.data.objects]
    characters = [n for n in names if n.startswith("BD_Char_")]
    cameras = [n for n in names if n.startswith("BD_Cam_")
               and not n.startswith("BD_CamTarget_")]
    targets = [n for n in names if n.startswith("BD_CamTarget_")]

    out_dir = Path(payload["out_dir"]) if payload else None
    products = sorted(p.name for p in out_dir.iterdir()) if (
        out_dir and out_dir.exists()) else []
    clips = [name for name in products if name.endswith(".mp4")]
    stills_dir = out_dir / "first_frames" if out_dir else None
    stills = sorted(p.name for p in stills_dir.iterdir()) if (
        stills_dir and stills_dir.exists()) else []

    ok = (state is DriverState.DONE
          and payload is not None and payload.get("ok") is True
          and "run_started" in kinds and "scene_built" in kinds
          and "shot_audit" in kinds and "export_started" in kinds
          and characters and cameras and targets
          and "shots.json" in products and "prompts.md" in products
          and len(clips) >= len(driver.plan.shots)
          and len(stills) == len(driver.plan.shots))
    return {"ok": ok, "state": state.value, "kinds": kinds,
            "characters": len(characters), "cameras": len(cameras),
            "targets": len(targets), "products": products,
            "clips": len(clips), "stills": len(stills),
            "shots": len(driver.plan.shots) if driver.plan else 0}


def main() -> int:
    capture_main_thread()
    check("operator_refuses_without_a_builder", t_missing_builder_is_refused)
    check("operator_path_builds_and_exports", t_operator_path_builds_and_exports)

    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS},
        ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
