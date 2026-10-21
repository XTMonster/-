"""v1.6 F2（D-09）：断点续跑——墙钟撞线保留已完成镜，resume 跳过终态镜（零 LLM）。

卡 F2 的纯层验收（TDD §4.6）：

* ``resume_state.json`` 带版本、能往返、坏文件与版本错配**如实报错、绝不猜**；
* 驱动器在 B1 每镜草案与每镜审核/修复终态之后都落 checkpoint；
* 跑到 shot_003 后"杀进程"（模拟墙钟撞线）⇒ resume 之后 ``llm_request``
  只对 shot_004+ 增长，终态镜零 LLM 调用；
* 墙钟撞线走的是**收尾**（CANCELLED + 落盘 resume_state），不是 ``run_failed``。
"""

from __future__ import annotations

import json

import pytest

from block_director.contracts.audit import AuditError, AuditResult
from block_director.contracts.enums import Purpose, Severity
from block_director.contracts.messages import ChatReply, FunctionCall, ToolCall
from block_director.contracts.plan import Plan
from block_director.layer5_orchestrator.driver import (
    RESUME_STATE_FILENAME,
    RESUME_STATE_VERSION,
    DriverLimits,
    PrevisDriver,
    ResumeState,
    ResumeStateError,
    load_resume_state,
    plan_for_shots,
    save_resume_state,
)
from block_director.layer5_orchestrator.planner import EMIT_PLAN_TOOL_PARAMETERS
from block_director.layer5_orchestrator.states import DriverState
from block_director.layer5_orchestrator.tool_registry import ToolRegistry
from block_director.layer6_audit.audit_logger import AuditLogger

from stage_helpers import is_understand, understand_reply
from test_driver import InlineThread

SCRIPT = "INT. 市场 - 日\n\n小明与小华在摊位前对峙。\n"

FOUR_SHOT_PLAN = {
    "scene_heading": "INT. 市场 - 日",
    "continuity_notes": ["断点续跑合成测试"],
    "shots": [
        {"shot_id": "shot_001", "order": 1, "intent": "建立场景与人物关系",
         "intent_type": "铺垫", "shot_type": "MLS", "duration_frames": 48,
         "characters": ["char_001", "char_002"], "dialogue_ids": [],
         "axis_note": "", "continuity_in": "", "prompt": ""},
        {"shot_id": "shot_002", "order": 2, "intent": "推进对话，给出反应",
         "intent_type": "推进", "shot_type": "MCU", "duration_frames": 48,
         "characters": ["char_002"], "dialogue_ids": [],
         "axis_note": "", "continuity_in": "", "prompt": ""},
        {"shot_id": "shot_003", "order": 3, "intent": "揭示人物立场",
         "intent_type": "揭示", "shot_type": "MS", "duration_frames": 48,
         "characters": ["char_001"], "dialogue_ids": [],
         "axis_note": "", "continuity_in": "", "prompt": ""},
        {"shot_id": "shot_004", "order": 4, "intent": "收束对峙",
         "intent_type": "收束", "shot_type": "MLS", "duration_frames": 48,
         "characters": ["char_001", "char_002"], "dialogue_ids": [],
         "axis_note": "", "continuity_in": "", "prompt": ""},
    ],
}


def _axis_finding(target: str) -> AuditError:
    return AuditError(rule="R001", code="E_AXIS_001", severity=Severity.ERROR,
                      target=target,
                      message="相机位置违反 180° 轴线规则。",
                      suggestion="将相机移到轴线另一侧。")


class FourShotTransport:
    """阶段替身：plan/editor 自动回放 4 镜计划；repair 回一个修复工具调用。"""

    def __init__(self):
        self.chat_calls = 0
        self.payloads = []
        self._editor = 0

    def chat(self, payload, timeout=120.0):
        if is_understand(payload):
            return understand_reply(payload.request_id)
        self.chat_calls += 1
        self.payloads.append(payload)
        if payload.purpose is Purpose.PLAN:
            call = ToolCall(id=f"plan_{self.chat_calls}",
                            function=FunctionCall(
                                name="emit_plan",
                                arguments=json.dumps(FOUR_SHOT_PLAN)))
            return ChatReply(tool_calls=[call], request_id=payload.request_id)
        if payload.purpose is Purpose.EDITOR:
            draft = {"shot_id": f"shot_{self._editor + 1:03d}",
                     "shot_type": "MS"}
            self._editor += 1
            call = ToolCall(id=f"draft_{self.chat_calls}",
                            function=FunctionCall(
                                name="emit_shot_draft",
                                arguments=json.dumps(draft, ensure_ascii=False)))
            return ChatReply(tool_calls=[call], request_id=payload.request_id)
        call = ToolCall(id=f"fix_{self.chat_calls}",
                        function=FunctionCall(name="setup_camera",
                                              arguments="{}"))
        return ChatReply(tool_calls=[call], content=None,
                         request_id=payload.request_id)

    def cancel(self, request_id):
        return None


class ScriptedAuditor:
    """按脚本回放审核结论；脚本用尽后一律通过。"""

    def __init__(self, results, shots):
        self._results = list(results)
        self._shots = list(shots)

    def shot_ids(self):
        return list(self._shots)

    def audit(self, shot_id):
        if self._results:
            return self._results.pop(0)
        return AuditResult(passed=True, target=shot_id)


class RecordingBuilder:
    def __init__(self):
        self.built = []

    def build(self, plan, brief=None):
        self.built.append(plan)
        return {"shots": len(plan.shots), "characters": 2, "cameras": 2,
                "motions": 0, "keyframes": 0,
                "total_frames": plan.total_frames, "warnings": [],
                "results": [{"shot_id": shot.shot_id, "start_frame": 1,
                             "end_frame": shot.duration_frames,
                             "camera": f"BD_Cam_{shot.shot_id}", "lens": 35}
                            for shot in plan.shots]}


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.add(name="emit_plan", description="plan",
                 parameters=EMIT_PLAN_TOOL_PARAMETERS,
                 handler=lambda **kwargs: "计划已接收")
    registry.add(name="setup_camera", description="fix",
                 parameters={"type": "object", "additionalProperties": False,
                             "properties": {}},
                 handler=lambda: "相机已重设")
    return registry


def _driver(transport, *, audit=None, auditor=None, resume_state=None,
            resume_state_path=None, script=SCRIPT, builder=None, **kwargs):
    limits = kwargs.pop("limits", None) or DriverLimits()
    return PrevisDriver(
        transport=transport, audit=audit or AuditLogger(), script=script,
        registry=_registry(), auditor=auditor,
        builder=builder or RecordingBuilder(), thread_factory=InlineThread,
        limits=limits, resume_state=resume_state,
        resume_state_path=resume_state_path, **kwargs)


def _passing_auditor():
    shots = [shot["shot_id"] for shot in FOUR_SHOT_PLAN["shots"]]
    return ScriptedAuditor([AuditResult(passed=True, target=s) for s in shots],
                           shots)


# --------------------------------------------------------------------------- #
# 1. resume_state.json：往返 / 版本 / 坏数据
# --------------------------------------------------------------------------- #
def test_resume_state_round_trip(tmp_path):
    state = ResumeState(run_id="abc123", plan={"scene_heading": "市场"},
                        terminal_shots={"shot_001": "passed"},
                        last_audit={"shot_001": {
                            "passed": True, "level": "rule",
                            "target": "shot_001", "score": 82.0,
                            "errors": [], "warnings": [], "suggestions": []}},
                        drafts={"shot_001": {"shot_id": "shot_001"}},
                        delivered_shots=["shot_001"], llm_calls=7,
                        tool_calls=3, reason="模拟墙钟")
    path = tmp_path / "sub" / RESUME_STATE_FILENAME
    save_resume_state(path, state)
    loaded = load_resume_state(path)
    assert loaded.version == RESUME_STATE_VERSION == 1
    assert loaded.to_dict() == state.to_dict()
    assert loaded.terminal_shots == {"shot_001": "passed"}
    assert loaded.delivered_shots == ["shot_001"]


def test_to_dict_does_not_restamp_saved_at(tmp_path, monkeypatch):
    """``to_dict()`` 必须原样透传 ``saved_at``，不随时钟现打。

    现打会让同一份状态的两次序列化跨秒时字节不同（构造性竞态）：
    ``test_resume_state_round_trip`` 在慢机器/高负载下偶发
    ``AssertionError: saved_at ... != ...``。
    """
    from block_director.layer5_orchestrator import driver as driver_module

    ticks = iter(["2026-10-10T20:00:00+08:00",
                  "2026-10-10T20:00:59+08:00"])
    monkeypatch.setattr(driver_module, "_now_iso", lambda: next(ticks))
    state = ResumeState(run_id="abc123")
    assert state.to_dict()["saved_at"] == ""
    assert state.to_dict() == state.to_dict()
    # 保存时打一次戳：此后状态与其序列化都与时钟推进无关。
    save_resume_state(tmp_path / RESUME_STATE_FILENAME, state)
    assert state.saved_at == "2026-10-10T20:00:00+08:00"
    assert state.to_dict() == state.to_dict()


def test_version_mismatch_is_reported_not_guessed(tmp_path):
    path = tmp_path / RESUME_STATE_FILENAME
    path.write_text(json.dumps({"schema_version": 2, "run_id": "x"}),
                    encoding="utf-8")
    with pytest.raises(ResumeStateError, match="版本"):
        load_resume_state(path)


def test_corrupted_resume_state_is_reported(tmp_path):
    path = tmp_path / RESUME_STATE_FILENAME
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ResumeStateError, match="JSON"):
        load_resume_state(path)


def test_missing_fields_are_reported_by_name(tmp_path):
    path = tmp_path / RESUME_STATE_FILENAME
    payload = ResumeState().to_dict()
    payload.pop("terminal_shots")
    payload.pop("plan")
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ResumeStateError, match="terminal_shots"):
        load_resume_state(path)


def test_unknown_terminal_status_is_reported(tmp_path):
    path = tmp_path / RESUME_STATE_FILENAME
    payload = ResumeState(terminal_shots={"shot_001": "mystery"}).to_dict()
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ResumeStateError, match="未知终态"):
        load_resume_state(path)


def test_unfinished_terminal_status_round_trips(tmp_path):
    """墙钟均摊写出的 ``unfinished`` 必须能恢复，不能成为未知终态。"""
    state = ResumeState(
        run_id="wall-share",
        plan=FOUR_SHOT_PLAN,
        terminal_shots={"shot_001": "unfinished"},
        reason="单镜均摊墙钟耗尽")
    path = tmp_path / RESUME_STATE_FILENAME

    save_resume_state(path, state)
    loaded = load_resume_state(path)

    assert loaded.terminal_shots == {"shot_001": "unfinished"}
    assert loaded.to_dict() == state.to_dict()


def test_missing_file_is_reported(tmp_path):
    with pytest.raises(ResumeStateError, match="找不到"):
        load_resume_state(tmp_path / "no_such_dir" / RESUME_STATE_FILENAME)


def test_plan_for_shots_keeps_environment_and_order():
    plan = Plan.from_dict(FOUR_SHOT_PLAN)
    keep = plan_for_shots(plan, ["shot_004", "shot_002"])
    assert [shot.shot_id for shot in keep.shots] == ["shot_002", "shot_004"]
    assert keep.environment == plan.environment
    assert keep.continuity_notes == plan.continuity_notes
    assert keep.scene_heading == plan.scene_heading


# --------------------------------------------------------------------------- #
# 2. 跑到 shot_003 杀进程 ⇒ resume 后 llm_request 只对 shot_004+ 增长
# --------------------------------------------------------------------------- #
def _llm_request_shots(driver):
    """从 llm_request 事件的消息里抽出镜头 id（plan/understand 没有镜头）。"""
    shots = set()
    for event in driver.audit.recent():
        if event.kind != "llm_request":
            continue
        for shot in [shot["shot_id"] for shot in FOUR_SHOT_PLAN["shots"]]:
            if shot in event.message:
                shots.add(shot)
    return shots


def test_kill_after_shot_003_then_resume_only_calls_remaining_shots(tmp_path):
    audit_a = AuditLogger(directory=tmp_path / "runs")
    resume_path = tmp_path / RESUME_STATE_FILENAME
    transport_a = FourShotTransport()
    auditor_a = ScriptedAuditor(
        [AuditResult(passed=True, target=s) for s in
         ("shot_001", "shot_002", "shot_003")]
        + [AuditResult.from_findings([_axis_finding("shot_004")],
                                     target="shot_004"),
           AuditResult(passed=True, target="shot_004")],
        [shot["shot_id"] for shot in FOUR_SHOT_PLAN["shots"]])
    driver_a = _driver(transport_a, audit=audit_a, auditor=auditor_a,
                       resume_state_path=resume_path)

    # 跑到恰好 3 个终态镜（= 模拟"杀进程"时刻）。
    while driver_a.step():
        if set(driver_a.snapshot()["terminal_shots"]) == {
                "shot_001", "shot_002", "shot_003"}:
            break
    assert set(driver_a.snapshot()["terminal_shots"]) == {
        "shot_001", "shot_002", "shot_003"}

    # 模拟墙钟撞线：下一步审到 shot_004（未终态）后立即收尾，而不是 run_failed。
    # 负数上限是**测试夹具**的确定性开关（任何一步之后立即判"已超时"），
    # 生产路径的墙钟来自 --wall / budget.max_wall_minutes。
    state = driver_a.run_to_completion(poll_interval=0.0, max_wall_s=-1.0)
    assert state is DriverState.CANCELLED
    assert driver_a.snapshot()["wall_clock_exhausted"] is True
    kinds = [event.kind for event in driver_a.audit.recent()]
    assert "wall_clock_exhausted" in kinds
    assert "run_failed" not in kinds
    assert resume_path.exists()

    saved = load_resume_state(resume_path)
    assert saved.version == RESUME_STATE_VERSION
    assert saved.terminal_shots == {"shot_001": "passed", "shot_002": "passed",
                                    "shot_003": "passed"}
    assert "shot_004" not in saved.terminal_shots
    assert [shot["shot_id"] for shot in saved.plan["shots"]] == [
        "shot_001", "shot_002", "shot_003", "shot_004"]
    assert set(saved.drafts) == {"shot_001", "shot_002", "shot_003", "shot_004"}

    # resume：终态镜零 LLM；非终态镜从 shot_004 继续。
    transport_b = FourShotTransport()
    auditor_b = ScriptedAuditor(
        [AuditResult.from_findings([_axis_finding("shot_004")],
                                   target="shot_004"),
         AuditResult(passed=True, target="shot_004")],
        [shot["shot_id"] for shot in FOUR_SHOT_PLAN["shots"]])
    driver_b = _driver(transport_b, audit=AuditLogger(), auditor=auditor_b,
                       resume_state=saved, resume_state_path=resume_path)

    assert driver_b.run_to_completion() is DriverState.DONE
    assert set(driver_b.snapshot()["terminal_shots"]) == {
        "shot_001", "shot_002", "shot_003", "shot_004"}
    # resume 之后没有 plan/understand/editor 调用：终态镜全部零 LLM。
    purposes = [payload.purpose for payload in transport_b.payloads]
    assert Purpose.UNDERSTAND not in purposes
    assert Purpose.PLAN not in purposes
    assert Purpose.EDITOR not in purposes
    assert _llm_request_shots(driver_b) == {"shot_004"}
    kinds_b = [event.kind for event in driver_b.audit.recent()]
    assert "run_resumed" in kinds_b
    assert "shot_resumed_skipped" in kinds_b


def test_kill_during_editing_resumes_remaining_drafts_only(tmp_path):
    """在 B1 起草到一半时杀进程：resume 只为没起草的镜发 editor 调用。"""
    audit_a = AuditLogger(directory=tmp_path / "runs")
    resume_path = tmp_path / RESUME_STATE_FILENAME
    driver_a = _driver(FourShotTransport(), audit=audit_a,
                       auditor=_passing_auditor(),
                       resume_state_path=resume_path)

    # 恰好两镜起草成功（shot_003 的回复已进队列但还没被消费）。
    while driver_a.step():
        if driver_a.snapshot()["drafts"] == 2:
            break
    assert driver_a.snapshot()["drafts"] == 2
    driver_a.run_to_completion(poll_interval=0.0, max_wall_s=-1.0)
    assert driver_a.state is DriverState.CANCELLED

    saved = load_resume_state(resume_path)
    assert set(saved.drafts) == {"shot_001", "shot_002"}
    assert saved.terminal_shots == {}

    transport_b = FourShotTransport()
    driver_b = _driver(transport_b, audit=AuditLogger(),
                       auditor=_passing_auditor(), resume_state=saved,
                       resume_state_path=resume_path)
    assert driver_b.run_to_completion() is DriverState.DONE
    purposes = [payload.purpose for payload in transport_b.payloads]
    assert Purpose.UNDERSTAND not in purposes
    assert Purpose.PLAN not in purposes
    assert Purpose.REPAIR not in purposes
    assert _llm_request_shots(driver_b) == {"shot_003", "shot_004"}


def test_resume_with_per_shot_builder_enters_prepare_then_resumes_per_shot():
    """方案 B 断点续跑：不回退整场 BUILDING，只重建未终态镜。"""

    class ResumablePerShotBuilder:
        def __init__(self):
            self.prepared = 0
            self.built = 0
            self.rebuilt = []

        def prepare_scene(self, plan, brief=None, spec=None):
            self.prepared += 1
            return {"characters": 2, "cameras": 0, "results": []}

        def rebuild_shot(self, shot_id, *, plan=None, brief=None,
                         preserve_camera_edits=False):
            self.rebuilt.append(str(shot_id))
            return {"shot_id": str(shot_id), "camera": f"BD_Cam_{shot_id}",
                    "keyframes": 1, "warnings": [], "protected": []}

        def build(self, plan, brief=None):
            self.built += 1
            raise AssertionError("方案 B resume 不应回退整场 build")

    state = ResumeState(
        plan=FOUR_SHOT_PLAN,
        terminal_shots={"shot_001": "passed"},
        drafts={shot["shot_id"]: {"shot_id": shot["shot_id"]}
                for shot in FOUR_SHOT_PLAN["shots"]},
        last_audit={"shot_001": {
            "passed": True, "level": "rule", "target": "shot_001",
            "score": 88.0, "errors": [], "warnings": [],
            "suggestions": []}},
    )
    builder = ResumablePerShotBuilder()
    auditor = ScriptedAuditor(
        [AuditResult(passed=True, target=shot)
         for shot in ("shot_002", "shot_003", "shot_004")],
        [shot["shot_id"] for shot in FOUR_SHOT_PLAN["shots"]])
    driver = _driver(FourShotTransport(), auditor=auditor,
                     resume_state=state, builder=builder)

    assert driver.run_to_completion() is DriverState.DONE
    assert builder.prepared == 1
    assert builder.built == 0
    assert builder.rebuilt == ["shot_002", "shot_003", "shot_004"]
    assert driver.snapshot()["terminal_shots"] == {
        "shot_001": "passed", "shot_002": "passed",
        "shot_003": "passed", "shot_004": "passed"}
    assert any(event.kind == "shot_resumed_skipped"
               and event.data.get("shot_id") == "shot_001"
               for event in driver.audit.recent())


def test_repeated_failed_shot_is_not_marked_degraded_terminal(tmp_path):
    """降级也是终态：resume 不得再为它调用一次模型。"""
    audit_a = AuditLogger(directory=tmp_path / "runs")
    resume_path = tmp_path / RESUME_STATE_FILENAME
    shots = [shot["shot_id"] for shot in FOUR_SHOT_PLAN["shots"]]
    # shot_001：修到上限降级；其余全过。
    results = [AuditResult.from_findings([_axis_finding("shot_001")],
                                         target="shot_001"),
               AuditResult.from_findings([_axis_finding("shot_001")],
                                         target="shot_001"),
               AuditResult.from_findings([_axis_finding("shot_001")],
                                         target="shot_001")]
    results += [AuditResult(passed=True, target=s) for s in
                ("shot_002", "shot_003", "shot_004")]
    auditor_a = ScriptedAuditor(results, shots)
    driver_a = _driver(transport=FourShotTransport(), audit=audit_a,
                       auditor=auditor_a, resume_state_path=resume_path,
                       limits=DriverLimits(max_repairs_per_shot=2))

    # shot_001 降级收尾、shot_002 终态后模拟杀进程。
    while driver_a.step():
        terminal = driver_a.snapshot()["terminal_shots"]
        if terminal.get("shot_001") == "passed":
            break
    assert driver_a.snapshot()["terminal_shots"]["shot_001"] == "passed"
    driver_a.run_to_completion(poll_interval=0.0, max_wall_s=-1.0)
    assert driver_a.state is DriverState.CANCELLED

    saved = load_resume_state(resume_path)
    assert saved.terminal_shots["shot_001"] == "passed"

    auditor_b = ScriptedAuditor([AuditResult(passed=True, target=s) for s in
                                 ("shot_003", "shot_004")], shots)
    driver_b = _driver(transport=FourShotTransport(), audit=AuditLogger(),
                       auditor=auditor_b, resume_state=saved,
                       resume_state_path=resume_path,
                       limits=DriverLimits(max_repairs_per_shot=2))
    assert driver_b.run_to_completion() is DriverState.DONE
    assert _llm_request_shots(driver_b) == set()
    assert all(event.data.get("status") == "passed"
               for event in driver_b.audit.recent()
               if event.kind == "shot_resumed_skipped"
               and event.data.get("shot_id") == "shot_001")


def test_resume_without_plan_starts_fresh():
    state = ResumeState(plan=None, terminal_shots={})
    driver = _driver(FourShotTransport(), resume_state=state)
    # 没有可续计划 ⇒ 从 IDLE 正常走完，不猜测任何东西。
    assert driver.run_to_completion() is DriverState.DONE
    assert len(driver.plan.shots) == 4


def test_broken_plan_inside_resume_state_is_reported(tmp_path):
    payload = ResumeState(plan={"shots": [{"shot_id": 42}]},
                          terminal_shots={}).to_dict()
    path = tmp_path / RESUME_STATE_FILENAME
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    saved = load_resume_state(path)          # 结构合法：能读出来
    with pytest.raises(ResumeStateError, match="plan"):
        _driver(FourShotTransport(), resume_state=saved)


def test_resume_seeds_terminal_audits_into_the_pass_rate():
    state = ResumeState(
        plan=FOUR_SHOT_PLAN,
        terminal_shots={"shot_001": "passed"},
        last_audit={"shot_001": {
            "passed": True, "level": "rule", "target": "shot_001",
            "score": 88.0, "errors": [], "warnings": [], "suggestions": []}},
    )
    auditor = ScriptedAuditor([AuditResult(passed=True, target=s) for s in
                               ("shot_002", "shot_003", "shot_004")],
                              [shot["shot_id"] for shot in
                               FOUR_SHOT_PLAN["shots"]])
    driver = _driver(FourShotTransport(), auditor=auditor, resume_state=state)
    assert driver.run_to_completion() is DriverState.DONE
    assert len(driver.audit_results) == 4      # 终态镜的旧结论 + 3 个新结论


# --------------------------------------------------------------------------- #
# 3. CLI：--resume 参数存在、且坏断点明确报错退出（纯层可测的部分）
# --------------------------------------------------------------------------- #
def test_cli_exposes_the_resume_flag():
    from tools.run_headless import parse_args

    # Blender 侧的参数约定：``--`` 之后才是 run_headless 自己的 argv。
    args = parse_args(["prog", "--", "--resume", "E:\\runs\\v15"])
    assert args.resume == "E:\\runs\\v15"
    assert parse_args(["prog", "--"]).resume == ""


def test_resume_path_accepts_directory_or_file(tmp_path):
    from tools.run_headless import _resume_state_path

    assert _resume_state_path(str(tmp_path)) == \
        tmp_path / RESUME_STATE_FILENAME
    direct = tmp_path / "custom.json"
    assert _resume_state_path(str(direct)) == direct
