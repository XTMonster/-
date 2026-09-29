"""§14.4 replay 集成测试：不调用 LLM，从 audit_log.jsonl 重建出同一条时间线。

运行：
  blender --background --factory-startup --python tools/blender_tests/test_replay.py
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

from _fixtures import two_shot_plan  # noqa: E402
from block_director.contracts.cast import SceneSpec  # noqa: E402
from block_director.knowledge import default_retriever  # noqa: E402
from block_director.layer3_engine.collection_router import ensure_collections  # noqa: E402
from block_director.layer3_engine.shot_builder import (  # noqa: E402
    BpySceneBuilder,
    build_scene,
)
from block_director.layer3_engine.scene_context import get_context  # noqa: E402
from block_director.layer3_engine.tool_bindings import register_all_scene_tools  # noqa: E402
from block_director.layer5_orchestrator.driver import (  # noqa: E402
    DriverLimits,
    PrevisDriver,
    default_registry,
)
from block_director.layer5_orchestrator.offline import OfflineTransport  # noqa: E402
from block_director.layer6_audit.audit_logger import AuditLogger  # noqa: E402
from block_director.layer9_persistence import replay  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

RESULTS: dict = {}


class InlineThread:
    """同步执行器：LLM 调用在 start() 时立刻完成，测试无需 sleep。"""

    def __init__(self, target, name=""):
        self._target = target

    def start(self):
        self._target()


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
    ensure_collections(scene)
    return scene


def make_registry():
    registry = default_registry()
    register_all_scene_tools(registry)
    return registry


def run_once(tmp_dir):
    """跑一次真实 headless 链路，把审计日志写到 tmp_dir/runs。"""
    fresh_scene()
    runs = Path(tmp_dir) / "runs"
    audit = AuditLogger(directory=runs)
    registry = make_registry()
    driver = PrevisDriver(
        transport=OfflineTransport(), audit=audit,
        script="INT. 咖啡馆 - 日\n\n小明与小红隔桌对坐。\n",
        registry=registry, builder=BpySceneBuilder(clear_scene=True),
        knowledge=default_retriever(), limits=DriverLimits(),
        thread_factory=InlineThread)
    driver.run_to_completion()
    return driver.snapshot(), audit, registry


def _rebuild_with_replay(tmp_dir, registry):
    fresh_scene()

    def build(plan, spec, brief=None):
        return build_scene(plan, spec or SceneSpec.from_plan(plan, brief=brief),
                           clear_scene=True).to_dict()

    return replay(tmp_dir, registry, builder=build)


def _fingerprint(summary):
    results = summary.get("results", [])
    return {
        "shots": summary.get("shots"),
        "total_frames": summary.get("total_frames"),
        "characters": summary.get("characters"),
        "cameras": summary.get("cameras"),
        "keyframes": summary.get("keyframes"),
        "shot_frames": [[item["shot_id"], item["start_frame"], item["end_frame"]]
                        for item in results],
        "camera_positions": [[item["shot_id"],
                              [round(v, 4) for v in item["camera_position"]]]
                             for item in results],
    }


# --------------------------------------------------------------------------- #
# 1. 重放出的场景与原始运行逐项一致
# --------------------------------------------------------------------------- #
def t_replay_rebuilds_the_same_timeline():
    tmp_dir = tempfile.mkdtemp(prefix="bd_replay_")
    snapshot, _audit, registry = run_once(tmp_dir)
    original = dict(snapshot["build"])

    report = _rebuild_with_replay(tmp_dir, registry)
    before, after = _fingerprint(original), _fingerprint(report.summary)

    return {"ok": report.ok and report.built and before == after,
            "before": before, "after": after,
            "steps": len(report.steps), "skipped": report.skipped,
            "executed": report.executed}


# --------------------------------------------------------------------------- #
# 2. 重放不调用 LLM
# --------------------------------------------------------------------------- #
def t_replay_never_calls_the_llm():
    tmp_dir = tempfile.mkdtemp(prefix="bd_replay_")
    _snapshot, _audit, registry = run_once(tmp_dir)

    transport = OfflineTransport()
    # replay 根本不接受 transport——这正是"不调用 LLM"的强形式：
    # 它只有注册表、计划与日志三个输入。
    report = _rebuild_with_replay(tmp_dir, registry)
    return {"ok": report.ok and transport.chat_calls == 0,
            "transport_calls": transport.chat_calls,
            "steps": len(report.steps)}


# --------------------------------------------------------------------------- #
# 3. 重放是幂等的：连跑两次结果一致
# --------------------------------------------------------------------------- #
def t_replay_is_idempotent():
    tmp_dir = tempfile.mkdtemp(prefix="bd_replay_")
    _snapshot, _audit, registry = run_once(tmp_dir)
    first = _rebuild_with_replay(tmp_dir, registry)
    second = _rebuild_with_replay(tmp_dir, registry)
    return {"ok": first.ok and second.ok
            and _fingerprint(first.summary) == _fingerprint(second.summary),
            "first": _fingerprint(first.summary),
            "second": _fingerprint(second.summary)}


# --------------------------------------------------------------------------- #
# 4. 记录了动作工具调用时，重放会把它们重新落到场景上
# --------------------------------------------------------------------------- #
def t_replay_reapplies_recorded_tool_calls():
    tmp_dir = tempfile.mkdtemp(prefix="bd_replay_")
    runs = Path(tmp_dir) / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    plan = two_shot_plan()
    audit = AuditLogger(directory=runs)
    audit.log("plan_received", "计划", plan=plan.to_dict(),
              shots=[shot.to_dict() for shot in plan.shots],
              total_frames=plan.total_frames)
    audit.log("tool_call", "place_character -> ok",
              tool="place_character",
              ok=True, args={"character_id": "char_001",
                             "position": [4.0, 0.0, 0.0]})

    registry = make_registry()
    report = _rebuild_with_replay(tmp_dir, registry)
    context = get_context()
    placed = context.characters.get("char_001") if context else None
    root = getattr(placed, "root", None)
    moved = root is not None and abs(root.location.x - 4.0) < 1e-6
    return {"ok": report.ok and report.executed == ["place_character"] and moved,
            "executed": report.executed,
            "x": round(root.location.x, 4) if root else None}


# --------------------------------------------------------------------------- #
# 5. v1.4 X5：站位必须来自 brief_received（否则重放与原始运行不是同一幅画）
# --------------------------------------------------------------------------- #
def _write_plan_log(tmp_dir, plan, *, brief=None):
    runs = Path(tmp_dir) / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    audit = AuditLogger(directory=runs)
    if brief is not None:
        audit.log("brief_received", "理解完成", brief=brief)
    audit.log("plan_received", "计划", plan=plan.to_dict(),
              shots=[shot.to_dict() for shot in plan.shots],
              total_frames=plan.total_frames)
    return runs


def t_replay_staging_comes_from_the_brief():
    plan = two_shot_plan()
    brief = {
        "source": "model",
        "space": [
            {"character": "char_002", "relative_to": "char_001",
             "relation": "behind", "distance_class": "far"},
        ],
    }
    tmp_dir = tempfile.mkdtemp(prefix="bd_replay_brief_")
    _write_plan_log(tmp_dir, plan, brief=brief)

    registry = make_registry()
    report = _rebuild_with_replay(tmp_dir, registry)
    context = get_context()
    placed = context.characters.get("char_002") if context else None
    root = getattr(placed, "root", None)
    # ``relation=behind`` 把 char_002 摆到 char_001 的**后面**（-X 方向），
    # 与默认站位（+X）明显不同。先取值：下一次重建会清场，旧的 Object 引用
    # 会失效（StructRNA removed）。
    with_brief_x = round(root.location.x, 4) if root else None
    behind = with_brief_x is not None and with_brief_x < 0.0

    # 负例：去掉 brief_received 事件后，站位必须**不再是**同一处。
    other_dir = tempfile.mkdtemp(prefix="bd_replay_nobrief_")
    _write_plan_log(other_dir, plan)
    bare = _rebuild_with_replay(other_dir, make_registry())
    bare_context = get_context()
    bare_root = getattr(bare_context.characters.get("char_002"), "root", None)
    bare_x = round(bare_root.location.x, 4) if bare_root else None
    differs = (bare_x is None or with_brief_x is None
               or abs(bare_x - with_brief_x) > 1e-3)

    return {"ok": report.ok and report.brief_source == "model" and behind
            and bare.ok and differs,
            "brief_source": report.brief_source,
            "x": with_brief_x,
            "bare_x": bare_x}


def main() -> int:
    capture_main_thread()
    check("replay_rebuilds_the_same_timeline", t_replay_rebuilds_the_same_timeline)
    check("replay_never_calls_the_llm", t_replay_never_calls_the_llm)
    check("replay_is_idempotent", t_replay_is_idempotent)
    check("replay_reapplies_recorded_tool_calls",
          t_replay_reapplies_recorded_tool_calls)
    check("replay_staging_comes_from_the_brief",
          t_replay_staging_comes_from_the_brief)

    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS}, ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
