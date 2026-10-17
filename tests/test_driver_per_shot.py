"""方案 B 逐镜预演（§3.6.3）——纯层状态机测试。

覆盖：
- ``EDITING → PREPARE_SCENE → PER_SHOT → FINISHING`` 主路径；
- ``prepare_scene`` 只调一次、``build`` 调用数为 0（迭代是增量 rebuild_shot，
  不是整场重建）；
- 每镜先 ``rebuild_shot`` 再审核；通过 → ``shot_advanced`` → 下一镜；
- 失败 → REPAIRING 回到 PER_SHOT 同一镜，``_per_shot_iterations`` 递增；
- 兼容回退：假 builder 无 ``prepare_scene``/``rebuild_shot`` 时走旧
  ``BUILDING → CHECKING``；
- 回滚走 ``rebuild_shot`` 增量、不整场 ``build``。
"""

from __future__ import annotations

import json

from block_director.contracts.audit import AuditError, AuditResult
from block_director.contracts.enums import Purpose, Severity
from block_director.contracts.messages import ChatReply, FunctionCall, ToolCall
from block_director.layer5_orchestrator.driver import PrevisDriver
from block_director.layer5_orchestrator.offline import (
    OfflineTransport,
    demo_draft_dict,
    demo_plan_dict,
)
from block_director.layer5_orchestrator.planner import EMIT_PLAN_TOOL_PARAMETERS
from block_director.layer5_orchestrator.states import DriverState
from block_director.layer5_orchestrator.tool_registry import ToolRegistry
from block_director.layer6_audit.audit_logger import AuditLogger

from test_driver import InlineThread
from stage_helpers import is_understand, understand_reply

SCRIPT = "INT. 咖啡馆 - 日\n\n小明坐下。\n"


def axis_finding() -> AuditError:
    return AuditError(rule="R001", code="E_AXIS_001", severity=Severity.ERROR,
                      target="shot_001",
                      message="相机位置违反 180° 轴线规则。",
                      suggestion="将相机移到轴线另一侧。")


class PerShotBuilder:
    """支持 prepare_scene + rebuild_shot 的假 builder（方案 B 主路径）。"""

    def __init__(self):
        self.prepared = 0
        self.rebuilt: list = []
        self.built = 0

    def prepare_scene(self, plan, brief=None, spec=None):
        self.prepared += 1
        return {"characters": 2, "cameras": 0, "props": 0,
                "crowd": 0, "prepared_at": "2026-10-11T00:00:00+00:00"}

    def rebuild_shot(self, shot_id, *, plan=None, brief=None):
        self.rebuilt.append({"shot_id": shot_id, "plan": plan})
        return {"shot_id": shot_id, "warnings": [], "protected": [],
                "camera": f"BD_Cam_{shot_id}", "keyframes": 1,
                "characters": list(plan.shots[0].characters)
                if plan and plan.shots else []}

    def build(self, plan, brief=None):
        self.built += 1
        return {"shots": len(plan.shots)}


class FakeAuditor:
    def __init__(self, results, shots=("shot_001", "shot_002")):
        self._results = list(results)
        self._shots = list(shots)
        self.calls = []

    def shot_ids(self):
        return list(self._shots)

    def audit(self, shot_id):
        self.calls.append(shot_id)
        if self._results:
            return self._results.pop(0)
        return AuditResult(passed=True, target=shot_id)


class PerShotTransport:
    """按阶段回放：理解 → 计划 → 每镜草案（B1）。"""

    def __init__(self):
        self.chat_calls = 0
        self._editor_index = 0

    def chat(self, payload, timeout=120.0):
        self.chat_calls += 1
        if is_understand(payload):
            self.chat_calls -= 1
            return understand_reply(payload.request_id)
        if payload.purpose is Purpose.PLAN:
            call = ToolCall(id=f"plan_{self.chat_calls}",
                            function=FunctionCall(
                                name="emit_plan",
                                arguments=json.dumps(demo_plan_dict(SCRIPT))))
            return ChatReply(tool_calls=[call])
        if payload.purpose is Purpose.EDITOR:
            draft = demo_draft_dict(self._editor_index)
            self._editor_index += 1
            call = ToolCall(id=f"draft_{self.chat_calls}",
                            function=FunctionCall(
                                name="emit_shot_draft",
                                arguments=json.dumps(draft, ensure_ascii=False)))
            return ChatReply(tool_calls=[call])
        return ChatReply(tool_calls=[], content=None)

    def cancel(self, request_id):
        return None


class RepairingTransport(PerShotTransport):
    """在草案后追加一个修复工具调用（setup_camera）。"""

    def chat(self, payload, timeout=120.0):
        reply = super().chat(payload, timeout)
        if reply.tool_calls:
            return reply
        call = ToolCall(id=f"fix_{self.chat_calls}",
                        function=FunctionCall(name="setup_camera",
                                              arguments="{}"))
        return ChatReply(tool_calls=[call], content=None)


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.add(
        name="emit_plan", description="plan",
        parameters=EMIT_PLAN_TOOL_PARAMETERS,
        handler=lambda **kwargs: "计划已接收")
    registry.add(
        name="emit_shot_draft", description="draft",
        parameters={"type": "object", "properties": {}},
        handler=lambda **kwargs: "草案已接收")
    registry.add(name="setup_camera", description="fix",
                 parameters={"type": "object", "additionalProperties": False,
                             "properties": {}},
                 handler=lambda: "相机已重设")
    return registry


def _driver(transport, auditor, builder, **kwargs):
    return PrevisDriver(transport=transport, audit=AuditLogger(), script=SCRIPT,
                        registry=_registry(), auditor=auditor, builder=builder,
                        thread_factory=InlineThread, **kwargs)


def test_per_shot_path_reaches_done():
    """方案 B 主路径：EDITING → PREPARE_SCENE → PER_SHOT → FINISHING。"""
    builder = PerShotBuilder()
    driver = _driver(PerShotTransport(), FakeAuditor([]), builder)
    assert driver.run_to_completion() is DriverState.DONE
    assert builder.prepared == 1
    assert builder.built == 0
    assert len(builder.rebuilt) == 2  # 两镜各重建一次
    assert [item["shot_id"] for item in builder.rebuilt] == ["shot_001",
                                                             "shot_002"]
    assert driver.state is DriverState.DONE


def test_per_shot_without_auditor_still_builds_every_shot():
    """无 auditor 时逐镜路径也必须逐镜重建摆相机（旧 BUILDING 语义）。

    phase6 探针 `review_requests_survive_real_driver_build_and_export`
    （tools/blender_tests/test_phase6_delivery.py:448）用不带 auditor 的
    PrevisDriver 跑真实驱动后直接导出；若 `_step_per_shot` 因 auditor=None
    直接收尾，场景里没有任何相机，导出渲染报 `Cannot render, no camera`。
    旧整场路径（`_step_building`）无论有无 auditor 都会摆相机——逐镜路径
    必须保持同一语义：无审核器只跳过审计/修复，不跳过摆相机。
    """
    builder = PerShotBuilder()
    driver = _driver(PerShotTransport(), auditor=None, builder=builder)
    assert driver.run_to_completion() is DriverState.DONE
    assert builder.prepared == 1
    assert builder.built == 0
    assert [item["shot_id"] for item in builder.rebuilt] == ["shot_001",
                                                             "shot_002"]
    assert len(driver.build_summary.get("results") or []) == 2
    assert driver.build_summary.get("cameras") == 2


def test_prepare_scene_called_exactly_once():
    """迭代是增量调整：prepare_scene 只调一次，build 永不调用。"""
    builder = PerShotBuilder()
    auditor = FakeAuditor([
        AuditResult.from_findings([axis_finding()], target="shot_001"),
    ])  # 第一镜失败一次，第二镜起全过
    driver = _driver(RepairingTransport(), auditor, builder)
    assert driver.run_to_completion() is DriverState.DONE
    assert builder.prepared == 1
    assert builder.built == 0
    assert len(builder.rebuilt) >= 2  # 第一镜修复后重做一次


def test_failed_shot_stays_in_per_shot_and_iterations_grow():
    """失败镜：REPAIRING → 回 PER_SHOT 同一镜，迭代计数递增。"""
    builder = PerShotBuilder()
    auditor = FakeAuditor([
        AuditResult.from_findings([axis_finding()], target="shot_001"),
        AuditResult(passed=True, target="shot_001"),  # 修复后过
    ])
    driver = _driver(RepairingTransport(), auditor, builder)
    assert driver.run_to_completion() is DriverState.DONE
    assert driver._per_shot_iterations["shot_001"] >= 2
    # 修复回到同一镜：shots 内只重做过 shot_001 两次
    shot_001_rebuilds = [item for item in builder.rebuilt
                         if item["shot_id"] == "shot_001"]
    assert len(shot_001_rebuilds) >= 2


def test_fallback_builder_without_prepare_scene_uses_old_path():
    """兼容回退：没有 prepare_scene/rebuild_shot 的假 builder 走旧 BUILDING。"""
    import types

    class OldBuilder:
        def __init__(self):
            self.built = 0

        def build(self, plan, brief=None):
            self.built += 1
            return {"shots": len(plan.shots), "characters": 2, "cameras": 2,
                    "motions": 0, "keyframes": 0,
                    "total_frames": plan.total_frames, "warnings": [],
                    "results": []}

    builder = OldBuilder()
    driver = _driver(PerShotTransport(), FakeAuditor([]), builder)
    assert driver.run_to_completion() is DriverState.DONE
    assert builder.built >= 1
    assert not hasattr(builder, "prepare_scene")


def test_rollback_uses_rebuild_shot_not_full_build():
    """修复引入新违规 → 回滚：恢复基线计划快照 + rebuild_shot，不整场 build。"""
    builder = PerShotBuilder()
    # 第一次审计失败 → 修复（改坏）→ 第二次审计多一条新规则 → 回滚
    # 回滚后转 PER_SHOT 再审当前镜（passed）→ 前进。
    fixes = [
        AuditResult.from_findings([axis_finding()], target="shot_001"),
        AuditResult.from_findings([axis_finding(),
                                   AuditError(rule="R009",
                                              code="E_FRAMING_001",
                                              severity=Severity.ERROR,
                                              target="shot_001",
                                              message="取景偏差",
                                              suggestion="调整焦段")],
                                  target="shot_001"),
        AuditResult(passed=True, target="shot_001"),
    ]
    auditor = FakeAuditor(fixes)
    driver = _driver(RepairingTransport(), auditor, builder)
    assert driver.run_to_completion() is DriverState.DONE
    assert builder.built == 0
    assert len(builder.rebuilt) >= 3
    rollbacks = [item for item in driver.rollback_events
                 if item["shot_id"] == "shot_001"]
    assert len(rollbacks) >= 1


def test_rebuild_result_replaces_shot_entry_and_preserves_audit_keys():
    """同镜第二轮 rebuild 后 results 条目被整体替换，非 rebuild 键保留。"""

    class ReplacingBuilder(PerShotBuilder):
        def __init__(self):
            super().__init__()
            self._calls = 0

        def rebuild_shot(self, shot_id, *, plan=None, brief=None):
            base = super().rebuild_shot(shot_id, plan=plan, brief=brief)
            self._calls += 1
            if self._calls == 2:
                base["camera_position"] = [9.9, 9.9, 9.9]
                base["lens"] = 85.0
            return base

    builder = ReplacingBuilder()
    # 第一镜失败一次再通过 → 同镜第二轮 rebuild
    auditor = FakeAuditor([
        AuditResult.from_findings([axis_finding()], target="shot_001"),
        AuditResult(passed=True, target="shot_001"),
    ])
    driver = _driver(RepairingTransport(), auditor, builder)
    assert driver.run_to_completion() is DriverState.DONE
    entry = next(item for item in driver.build_summary["results"]
                 if item.get("shot_id") == "shot_001")
    assert entry["lens"] == 85.0
    assert entry["camera_position"] == [9.9, 9.9, 9.9]


def test_empty_shot_in_per_shot_path_rebuilds_and_passes():
    """空镜逐镜路径：无角色镜仍 rebuild 摆相机，特殊镜序照常前进。

    六视角评审建议补的缺口（`work/reviews/six_view_tests_20261012.md` §4）：
    D1 交接 §3b 自述"空镜（无角色）在逐镜路径建相机无动作 → audit 空镜豁免"
    未用测试钉住。这里显式断言：

    * 计划里含一个无角色镜（``characters == []``）时逐镜路径照常走到 DONE；
    * 该镜也经过 ``rebuild_shot``（空镜不是"跳过构建"，是"建相机无动作"）；
    * audit 空镜豁免——不带 auditor 的嵌入用法（与
      ``test_per_shot_without_auditor_still_builds_every_shot`` 同口径）下
      build_summary 里空镜条目存在，不被当成失败吞掉。
    """
    from block_director.contracts.plan import Plan, ShotPlan

    plan = Plan(shots=[
        ShotPlan("shot_001", "建立", "MLS", 96,
                 characters=["char_001", "char_002"]),
        ShotPlan("shot_002", "空镜", "ELS", 48, characters=[]),
    ], scene_heading="码头")

    class EmptyShotBuilder(PerShotBuilder):
        def rebuild_shot(self, shot_id, *, plan=None, brief=None):
            self.rebuilt.append({"shot_id": shot_id, "plan": plan})
            return {"shot_id": shot_id, "warnings": [], "protected": [],
                    "camera": f"BD_Cam_{shot_id}", "keyframes": 1,
                    "characters": []}

    builder = EmptyShotBuilder()

    class EmptyShotTransport(PerShotTransport):
        def chat(self, payload, timeout=120.0):
            if is_understand(payload):
                return understand_reply(payload.request_id)
            if payload.purpose is Purpose.PLAN:
                plan_dict = demo_plan_dict(SCRIPT)
                #: 第二镜改为空镜：逐镜路径必须容纳"建相机无动作"的镜。
                plan_dict["shots"][1]["characters"] = []
                call = ToolCall(
                    id=f"plan_{self.chat_calls}",
                    function=FunctionCall(
                        name="emit_plan",
                        arguments=json.dumps(plan_dict, ensure_ascii=False)))
                return ChatReply(tool_calls=[call])
            if payload.purpose is Purpose.EDITOR:
                draft = demo_draft_dict(self._editor_index)
                if draft.get("shot_id") == "shot_002":
                    draft.pop("actions", None)
                self._editor_index += 1
                call = ToolCall(
                    id=f"draft_{self.chat_calls}",
                    function=FunctionCall(
                        name="emit_shot_draft",
                        arguments=json.dumps(draft, ensure_ascii=False)))
                return ChatReply(tool_calls=[call])
            return ChatReply(tool_calls=[], content=None)

    driver = _driver(EmptyShotTransport(), auditor=None, builder=builder)
    driver.plan = plan
    driver._transition(DriverState.PREPARE_SCENE)
    #: 跳过 LLM 起草：空镜测试聚焦逐镜构建，不引入 editor 调用。
    driver._editing_queue = []
    driver._editing_index = 0
    assert driver.run_to_completion() is DriverState.DONE
    assert [item["shot_id"] for item in builder.rebuilt] == [
        "shot_001", "shot_002"]
    shot_ids = {entry.get("shot_id") for entry in
                (driver.build_summary.get("results") or [])}
    assert "shot_002" in shot_ids


def test_repair_replanning_a_shot_falls_back_to_full_building():
    """per-shot 修复改了计划 ⇒ 整场 BUILDING 重建，而不是留在 PER_SHOT。

    六视角评审 §4 缺口 4（SPEC_d1_merge_pre_tests_20261017 任务 A 第 3 条）：
    修复回合重提草案（``emit_shot_draft`` ⇒ ``_needs_rebuild=True``）时，
    driver 必须经 ``_rebuild_in_place`` 回 BUILDING 整场重建，重建后回
    CHECKING 续审当前镜——不能假装"单镜 rebuild 已把改好的计划落进场景"。

    这里用显式断言钉住：

    * ``build()`` 被调（整场重建发生），``prepare_scene`` 仍只调一次；
    * 事件里出现 ``scene_built`` 且带 ``rebuild_in_place`` 语义；
    * 终态两镜均为 passed，没有停留在 PER_SHOT 假装改好。
    """
    from block_director.layer5_orchestrator.driver import scene_built_reason

    class ReplanningTransport(PerShotTransport):
        """修复回合提一份新草案：往 shot_001 塞一个动作（计划真的被改了）。"""

        def chat(self, payload, timeout=120.0):
            if payload.purpose is not Purpose.REPAIR:
                return super().chat(payload, timeout)
            draft = demo_draft_dict(0)
            draft["shot_id"] = "shot_001"
            actions = [dict(item) for item in (draft.get("actions") or [])]
            actions.append({"character_id": "char_001", "action_type": "nod",
                            "start_frame": 1, "end_frame": 12, "params": {}})
            draft["actions"] = actions
            call = ToolCall(id="draft_fix",
                            function=FunctionCall(
                                name="emit_shot_draft",
                                arguments=json.dumps(draft, ensure_ascii=False)))
            return ChatReply(tool_calls=[call], content=None)

    builder = PerShotBuilder()
    auditor = FakeAuditor([
        AuditResult.from_findings([axis_finding()], target="shot_001"),
        AuditResult(passed=True, target="shot_001"),
        AuditResult(passed=True, target="shot_002"),
    ])
    driver = _driver(ReplanningTransport(), auditor, builder)
    assert driver.run_to_completion() is DriverState.DONE
    #: 修复改了计划：整场重建必须真的发生（build 调用 > 0）。
    assert builder.built >= 1
    assert builder.prepared == 1
    kinds = [entry.kind for entry in driver.audit.recent()]
    assert "scene_built" in kinds
    assert "repair_rolled_back" not in kinds
    #: 重建后回 CHECKING 续审：两镜都真正走到终态，而不是停在 PER_SHOT。
    assert driver.snapshot()["terminal_shots"] == {
        "shot_001": "passed", "shot_002": "passed"}
    #: scene_built 的 reason 是"重建"分支（同一真源函数），不是首次构建。
    #: prepare 阶段先发一条 initial，修复重建后发第二条 rebuild。
    rebuilt = [entry for entry in driver.audit.recent()
               if entry.kind == "scene_built"
               and entry.data.get("reason") == "repair_rebuild"]
    assert rebuilt, "修复重建必须发出 repair_rebuild 语义的 scene_built"
    assert rebuilt[0].data.get("reason") == scene_built_reason(
        rebuild_in_place=True, just_rolled_back=False)
