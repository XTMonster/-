"""v1.6 F2（D-09）Blender 探针：真实构建器上的断点续跑。

场景与纯层测试同构：跑到 shot_003 终态后模拟墙钟撞线（收尾 → CANCELLED →
落盘 resume_state.json），再 resume：shot_001–003 零 LLM 调用跳过，
只对 shot_004+ 发请求（这里把 shot_004 的相机拆到轴线另一侧，逼出一轮
定向修复，证明"resume 后 LLM 只花在未完成镜上"这条判据不是空集成立的）。

运行：
  blender --background --factory-startup --python tools/blender_tests/test_checkpoint_resume.py

输出：一行 ``BD_TEST_RESULT {json}``（递归消毒过，绝无 NaN/Inf 字面量）。
"""

from __future__ import annotations

import json
import math
import re
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy  # noqa: E402

from block_director.contracts.enums import Purpose  # noqa: E402
from block_director.contracts.messages import (  # noqa: E402
    ChatReply,
    FunctionCall,
    ToolCall,
)
from block_director.contracts.plan import Plan  # noqa: E402
from block_director.layer3_engine.cinema_engine import create_camera  # noqa: E402
from block_director.layer3_engine.collection_router import (  # noqa: E402
    ensure_collections,
)
from block_director.layer3_engine.scene_context import get_context  # noqa: E402
from block_director.layer3_engine.shot_auditor import BpyShotAuditor  # noqa: E402
from block_director.layer3_engine.shot_builder import BpySceneBuilder  # noqa: E402
from block_director.layer3_engine.tool_bindings import (  # noqa: E402
    register_all_scene_tools,
)
from block_director.layer5_orchestrator.driver import (  # noqa: E402
    RESUME_STATE_FILENAME,
    DriverLimits,
    PrevisDriver,
    default_registry,
    load_resume_state,
)
from block_director.layer5_orchestrator.human_gate import AutoGate  # noqa: E402
from block_director.layer5_orchestrator.offline import (  # noqa: E402
    OfflineTransport,
)
from block_director.layer5_orchestrator.states import DriverState  # noqa: E402
from block_director.layer6_audit.audit_logger import AuditLogger  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

RESULTS: dict = {}
SCRIPT = "INT. 市场 - 日\n\n小明与小华在摊位前对峙。\n"

SCHEMA_PLAN_DICT = {
    "scene_heading": "INT. 市场 - 日",
    "continuity_notes": ["断点续跑 Blender 探针"],
    "shots": [
        {"shot_id": "shot_001", "order": 1, "intent": "建立场景与人物关系",
         "intent_type": "铺垫", "shot_type": "MLS", "duration_frames": 96,
         "characters": ["char_001", "char_002"], "dialogue_ids": [],
         "axis_note": "以两人连线建立轴线", "continuity_in": "开场",
         "prompt": ""},
        {"shot_id": "shot_002", "order": 2, "intent": "推进对话，给出反应",
         "intent_type": "推进", "shot_type": "MCU", "duration_frames": 120,
         "characters": ["char_002"], "dialogue_ids": [],
         "axis_note": "保持轴线同侧", "continuity_in": "承接 shot_001",
         "prompt": ""},
        {"shot_id": "shot_003", "order": 3, "intent": "揭示人物立场",
         "intent_type": "揭示", "shot_type": "MS", "duration_frames": 96,
         "characters": ["char_001"], "dialogue_ids": [],
         "axis_note": "保持轴线同侧", "continuity_in": "承接 shot_002",
         "prompt": ""},
        {"shot_id": "shot_004", "order": 4, "intent": "收束对峙",
         "intent_type": "收束", "shot_type": "MLS", "duration_frames": 96,
         "characters": ["char_001", "char_002"], "dialogue_ids": [],
         "axis_note": "保持轴线同侧", "continuity_in": "承接 shot_003",
         "prompt": ""},
    ],
}
#: 传给离线替身的必须是 **emit_plan schema 形状**（逐键对照 planner._SHOT_ITEM_SCHEMA），
#: 完整 Plan 的 to_dict 会带 actions/camera 等 schema 外的字段，会被工具校验退回。
FOUR_SHOT_PLAN = Plan.from_dict(SCHEMA_PLAN_DICT)

#: B1 草案与修复回合共用的机位参数（与构建器同解 ⇒ 复核应通过）。
SHOT_CAMERA = {"shot_001": ("MLS", "front_right", 35),
               "shot_002": ("MCU", "front_left", 50),
               "shot_003": ("MS", "front", 40),
               "shot_004": ("MLS", "front", 35)}


def _repair_shot_id(payload) -> str:
    """修复提示写死"本次要修的镜头：`shot_00X`"——从它取镜号，不猜。"""
    for message in getattr(payload, "messages", []) or []:
        content = getattr(message, "content", None) or ""
        if not isinstance(content, str):
            continue
        match = re.search(r"shot_\d{3}", content)
        if match:
            return match.group(0)
    return ""


class ProbeTransport(OfflineTransport):
    """离线替身 + 修复回合：按计划参数重设这一镜的机位。"""

    def __init__(self):
        drafts = []
        for shot in FOUR_SHOT_PLAN.shots:
            shot_type, side, lens = SHOT_CAMERA[shot.shot_id]
            drafts.append({"shot_id": shot.shot_id, "shot_type": shot_type,
                           "camera": {"side": side, "lens": lens}})
        super().__init__(
            plan=SCHEMA_PLAN_DICT,
            drafts=drafts)
        self.repair_shots = []

    def chat(self, payload, timeout=120.0):
        if payload.purpose is Purpose.REPAIR:
            shot_id = _repair_shot_id(payload)
            self.repair_shots.append(shot_id)
            shot_type, side, _lens = SHOT_CAMERA.get(shot_id,
                                                     ("MS", "front", 35))
            call = ToolCall(id=f"fix_{len(self.repair_shots)}",
                            function=FunctionCall(
                                name="setup_camera",
                                arguments=json.dumps(
                                    {"shot_id": shot_id,
                                     "shot_type": shot_type, "side": side},
                                    ensure_ascii=False)))
            return ChatReply(tool_calls=[call], content=None,
                             request_id=payload.request_id, model="probe",
                             finish_reason="tool_calls")
        return super().chat(payload, timeout)


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


def _break_axis(shot_id):
    """把这一镜的相机换到轴线另一侧，制造一次可修的 R001。"""
    context = get_context()
    axis = context.axis
    opposite = -1.0 if (axis is None or axis.established_side > 0) else 1.0
    bundle = create_camera(f"broken_{shot_id}", (0.0, opposite * 6.0, 1.2),
                           look_at=(0.0, 0.0, 1.0), make_scene_camera=False)
    context.cameras[str(shot_id)] = bundle.camera
    bpy.context.view_layer.update()


def _make_driver(audit, resume_state=None, resume_path=None):
    fresh_scene()
    from block_director.settings import get_config

    config = get_config()
    registry = default_registry(max_shots=int(config.orchestration.max_shots))
    register_all_scene_tools(registry)
    from block_director.observation.state import format_scene_state
    from block_director.layer3_engine.scene_state import collect_scene_state

    return PrevisDriver(
        transport=ProbeTransport(), audit=audit, script=SCRIPT,
        config=config, registry=registry,
        builder=BpySceneBuilder(clear_scene=True),
        auditor=BpyShotAuditor(audit_level=config.audit.level,
                               vlm_review=config.vlm_review),
        scene_state_provider=lambda: format_scene_state(
            collect_scene_state(detailed=False)),
        human_gate=AutoGate(), limits=DriverLimits(),
        resume_state=resume_state, resume_state_path=resume_path)


def _llm_request_shots(driver):
    shots = set()
    for event in driver.audit.recent():
        if event.kind != "llm_request":
            continue
        for match in re.findall(r"shot_\d{3}", event.message):
            shots.add(match)
    return shots


def t_kill_after_shot_003_then_resume():
    resume_dir = Path(tempfile.mkdtemp(prefix="bd_resume_"))
    resume_path = resume_dir / RESUME_STATE_FILENAME
    audit_a = AuditLogger(directory=resume_dir / "runs")
    driver_a = _make_driver(audit_a, resume_path=resume_path)

    # 跑到恰好 3 个终态镜（= 模拟"杀进程"时刻），随后把 shot_004 拆坏。
    while driver_a.step():
        terminal = set(driver_a.snapshot()["terminal_shots"])
        if terminal == {"shot_001", "shot_002", "shot_003"}:
            break
        if driver_a.state in (DriverState.DONE, DriverState.ERROR,
                              DriverState.CANCELLED):
            break
    terminal_a = set(driver_a.snapshot()["terminal_shots"])
    _break_axis("shot_004")
    state_a = driver_a.run_to_completion(poll_interval=0.0, max_wall_s=-1.0)
    kinds_a = [event.kind for event in driver_a.audit.recent()]
    if state_a is not DriverState.CANCELLED:
        return {"ok": False, "state": state_a.value, "kinds": kinds_a,
                "terminal_a": sorted(terminal_a)}

    saved = load_resume_state(resume_path)
    audit_b = AuditLogger()
    transport_b = ProbeTransport()
    from block_director.settings import get_config

    config = get_config()
    registry = default_registry(max_shots=int(config.orchestration.max_shots))
    register_all_scene_tools(registry)
    from block_director.observation.state import format_scene_state
    from block_director.layer3_engine.scene_state import collect_scene_state

    fresh_scene()
    driver_b = PrevisDriver(
        transport=transport_b, audit=audit_b,
        script=saved.script or SCRIPT, config=config, registry=registry,
        builder=BpySceneBuilder(clear_scene=True),
        auditor=BpyShotAuditor(audit_level=config.audit.level,
                               vlm_review=config.vlm_review),
        scene_state_provider=lambda: format_scene_state(
            collect_scene_state(detailed=False)),
        human_gate=AutoGate(), limits=DriverLimits(),
        resume_state=saved, resume_state_path=resume_path)

    # resume：D1 方案 B 下逐镜路径是 PREPARE_SCENE → PER_SHOT（该镜
    # rebuild 与审核在同一 step 内完成），不再经过 CHECKING——旧的
    # "state is CHECKING 时拆坏"钩子永远不触发。把"拆坏 shot_004"的
    # 时机挂到与旧语义等价的接缝：audit 即将审 shot_004 的前一刻（包一层
    # auditor.audit，只触发一次）。断言一字未动：resume 后 LLM 只花在
    # shot_004+，且定向修复仍会命中。
    tampered = False
    original_audit = driver_b.auditor.audit

    def tampering_audit(shot_id):
        nonlocal tampered
        if str(shot_id) == "shot_004" and not tampered:
            _break_axis("shot_004")
            tampered = True
        return original_audit(shot_id)

    driver_b.auditor.audit = tampering_audit
    while driver_b.step():
        if driver_b.state in (DriverState.DONE, DriverState.ERROR,
                              DriverState.CANCELLED):
            break

    terminal_b = set(driver_b.snapshot()["terminal_shots"])
    llm_shots = _llm_request_shots(driver_b)
    skipped = [event.data for event in driver_b.audit.recent()
               if event.kind == "shot_resumed_skipped"]
    ok = (
        terminal_a == {"shot_001", "shot_002", "shot_003"}
        and driver_a.snapshot()["wall_clock_exhausted"] is True
        and "wall_clock_exhausted" in kinds_a and "run_failed" not in kinds_a
        and resume_path.exists()
        and saved.terminal_shots.keys() == terminal_a
        and driver_b.state is DriverState.DONE
        and terminal_b == {"shot_001", "shot_002", "shot_003", "shot_004"}
        and transport_b.repair_shots == ["shot_004"]
        and llm_shots == {"shot_004"}
        and {item.get("shot_id") for item in skipped} == terminal_a
    )
    return {"ok": ok, "terminal_a": sorted(terminal_a),
            "state_a": state_a.value, "wall_clock_exhausted":
            driver_a.snapshot()["wall_clock_exhausted"],
            "state_b": driver_b.state.value,
            "terminal_b": sorted(terminal_b),
            "repair_shots": transport_b.repair_shots,
            "llm_request_shots": sorted(llm_shots),
            "skipped": skipped,
            "resume_path": str(resume_path),
            "version": saved.version}


def _sanitize(value):
    """递归消毒：NaN/Inf 不能作为 JSON 字面量出现在 BD_TEST_RESULT 里。"""
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, dict):
        return {str(key): _sanitize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    return value


def main() -> int:
    capture_main_thread()
    check("kill_after_shot_003_then_resume", t_kill_after_shot_003_then_resume)

    passed = [key for key, value in RESULTS.items() if value.get("ok")]
    failed = [key for key, value in RESULTS.items() if not value.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed,
         "checks": _sanitize(RESULTS)},
        ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
