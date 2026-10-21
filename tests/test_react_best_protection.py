"""F14/F15/F16（2026-10-20 final10 实测）：高分版本必须在所有路径被保护。

final10 实锤缺陷链：

1. 空间尺自动 reframe 把 shot_001 从 53 分（50mm）推到 79.5 分（36mm，
   subject_not_visible 消失），但该版本在普通 CHECKING/REPAIRING 路径下
   从未进入 ``_react_best``（best 只在 B5 React 精修建立）；
2. 下一轮 repair 里模型 ``setup_camera(MCU, front, 50mm)`` 把 36mm 覆盖
   回 50mm，79.5 版本丢失；
3. ``_rollback_repair_if_worse`` 回滚只恢复计划（deepcopy）、不恢复场景级
   状态（lens 36mm），重建后仍是 53 分——回滚形同虚设。

本文件钉住修复后的三条不变量：
- reframe 后的重审自动登记 best（79.5 成为最高分基线）；
- 低分审核走回溯三态 revert，best 保持不变且触发物理回滚；
- 回滚重建传 ``preserve_camera_edits=True``（场景状态不再被计划原值覆盖）；
- repair 提示注入"高分保留"，防止模型整位重摆覆盖 best。
"""

from __future__ import annotations

import json

from block_director.contracts.audit import AuditError, AuditResult
from block_director.contracts.config import AppConfig
from block_director.contracts.enums import Purpose, Severity
from block_director.contracts.messages import ChatReply, FunctionCall, ToolCall
from block_director.layer5_orchestrator.driver import DriverLimits, PrevisDriver
from block_director.layer5_orchestrator.planner import PLAN_TOOL_NAME
from block_director.layer5_orchestrator.states import DriverState
from block_director.layer5_orchestrator.tool_registry import ToolRegistry
from block_director.layer6_audit.audit_logger import AuditLogger

from test_backtrack_no_stop_on_fail import (
    InlineThread,
    ScriptedTransport,
    StubBuilder,
)
from test_driver_repair import FakeAuditor

SCRIPT = "INT. 咖啡馆 - 日\n\n小明坐下。\n"
PLAN_REPLY = (PLAN_TOOL_NAME, {"shots": [
    {"shot_id": "shot_001", "order": 1, "intent": "x", "shot_type": "MS",
     "duration_frames": 24},
    {"shot_id": "shot_002", "order": 2, "intent": "y", "shot_type": "CU",
     "duration_frames": 24}]})


def _registry() -> ToolRegistry:
    """最小工具表：计划/草案 + 修改工具 setup_camera（repair 回合用）。"""
    registry = ToolRegistry()
    registry.add(
        name=PLAN_TOOL_NAME, description="plan",
        parameters={"type": "object", "additionalProperties": True,
                    "properties": {"shots": {"type": "array"}}},
        handler=lambda **kwargs: "计划已接收")
    registry.add(
        name="emit_shot_draft", description="draft",
        parameters={"type": "object", "properties": {}},
        handler=lambda **kwargs: "草案已接收")
    registry.add(
        name="setup_camera", description="重设相机",
        parameters={"type": "object", "additionalProperties": False,
                    "properties": {"shot_id": {"type": "string"},
                                   "shot_type": {"type": "string"}}},
        handler=lambda **kwargs: "相机已重设")
    return registry


def _fail(rule, *, score):
    return AuditResult(
        passed=False, target="shot_001", score=score,
        errors=[AuditError(rule=rule, code=f"E_{rule}",
                           severity=Severity.ERROR, target="shot_001",
                           message=f"{rule} 红", suggestion="改")])


class PrepareSceneBuilder:
    """方案 B 构建器：记录 rebuild_shot 收到的 kwargs（F15 验证）。"""

    def __init__(self):
        self.rebuild_kwargs = []

    def prepare_scene(self, plan, brief=None):
        return {"shots": len(plan.shots)}

    def rebuild_shot(self, shot_id, *, plan=None, preserve_camera_edits=False):
        self.rebuild_kwargs.append({
            "shot_id": str(shot_id),
            "preserve_camera_edits": bool(preserve_camera_edits),
        })
        return {"shot_id": str(shot_id), "ok": True}

    def build(self, plan, brief=None):
        return {"shots": len(plan.shots)}


def _make_driver(transport, auditor, builder=None):
    config = AppConfig()
    config.orchestration.react_max_steps = 6
    config.orchestration.react_max_rounds = 4
    config.orchestration.context_window_tokens = 32000
    registry = None
    return PrevisDriver(
        transport=transport, audit=AuditLogger(), script=SCRIPT,
        config=config, builder=builder or StubBuilder(), auditor=auditor,
        registry=registry or _registry(),
        limits=DriverLimits(max_repairs_per_shot=1),
        thread_factory=InlineThread)


def test_reframe_version_registers_as_best_and_low_score_reverts():
    """F14：reframe 后的重审自动登记 best；低分审核走 revert 且 best 不降。"""
    #: 首审 79.5（fail）——reframe 已发生（_ruler_reframed_shots 已含该镜）；
    #: 修复后 53（fail）——比 best 低，必须 revert 而不是覆盖 best。
    auditor = FakeAuditor([
        _fail("COMPOSITION", score=79.5),
        _fail("COMPOSITION", score=53.0),
        _fail("COMPOSITION", score=53.0),
        AuditResult(passed=True, target="shot_001", score=88.0),
    ], shots=("shot_001", "shot_002"))
    transport = ScriptedTransport([
        PLAN_REPLY,
        ("setup_camera", {"shot_id": "shot_001", "shot_type": "MCU"}),
        ("setup_camera", {"shot_id": "shot_001", "shot_type": "MCU"}),
    ])
    driver = _make_driver(transport, auditor, builder=None)
    driver._ruler_reframed_shots = {"shot_001"}
    state = driver.run_to_completion()
    assert state is DriverState.DONE, f"不应整体停止：{state}"
    best = driver._react_best.get("shot_001")
    assert best is not None, "reframe 后的重审必须登记 best"
    trail = driver._react_scores.get("shot_001", [])
    dispositions = [item["disposition"] for item in trail]
    assert dispositions[0] == "new_high", dispositions
    #: 79.5（v1）之后第一次低分 53 必须走 revert——不得覆盖 best。
    v2 = trail[1]
    assert v2["disposition"] == "revert", trail
    assert v2["summary"] == "best=79.5", trail
    #: 最终 88 分过线，best 收敛到 88（adopt，收尾版），低分从未污染它。
    assert best["score"] == 88.0, best
    assert "revert" in dispositions, (
        f"低分审核必须走回溯三态 revert：{dispositions}")
    kinds = [entry.kind for entry in driver.audit.recent()]
    assert any(k == "react_score" for k in kinds), kinds


def test_rollback_rebuild_preserves_camera_edits():
    """F15：回滚重建必须带 preserve_camera_edits=True（场景状态不被覆盖）。"""
    builder = PrepareSceneBuilder()
    auditor = FakeAuditor([
        _fail("R003", score=60.0),              # 首次审计（基线）
        _fail("R003", score=60.0),              # 修复（未动，同分）
        _fail("R003", score=60.0),              # 规则集不变，无回滚
        AuditResult(passed=True, target="shot_001", score=88.0),
    ], shots=("shot_001",))
    transport = ScriptedTransport([
        PLAN_REPLY,
        ("setup_camera", {"shot_id": "shot_001", "shot_type": "MCU"}),
        None,
    ])
    driver = _make_driver(transport, auditor, builder=builder)
    driver._react_best["shot_001"] = {
        "score": 60.0, "version": 1, "world_state": None}
    state = driver.run_to_completion()
    assert state is DriverState.DONE, f"不应停止：{state}"
    #: 方案 B 路径下回滚只发生在"修复引入新规则"时；这里的场景不触发回滚，
    #: 但每一步重建都必须带 preserve_camera_edits=True（逐镜迭代语义）。
    assert builder.rebuild_kwargs, "方案 B 路径必须走 rebuild_shot"
    assert all(item["preserve_camera_edits"] for item in builder.rebuild_kwargs)


def test_rollback_restores_best_world_state_then_preserves_it():
    """F15：回滚先物理恢复 best，再带保留标记重建（恢复的相机不被冲掉）。"""
    builder = PrepareSceneBuilder()
    auditor = FakeAuditor([
        _fail("R003", score=60.0),              # 首次审计（基线，含 R003）
        _fail("R001", score=60.0),              # 修复后多出 R001（改坏→回滚）
        _fail("R003", score=60.0),              # 回滚后重建，规则回到基线
        AuditResult(passed=True, target="shot_001", score=88.0),
    ], shots=("shot_001",))
    transport = ScriptedTransport([
        PLAN_REPLY,
        ("setup_camera", {"shot_id": "shot_001", "shot_type": "MCU"}),
        None,
    ])
    driver = _make_driver(transport, auditor, builder=builder)
    #: 用有世界快照的 best：回滚应调用 _revert_to_best（纯层无 bpy 时记
    #: revert_skipped；有快照记录时走 restore_world_snapshot 分支）。
    driver._react_best["shot_001"] = {
        "score": 60.0, "version": 1,
        "world_state": {"schema_version": "runtime-world/v1",
                        "characters": {}, "cameras": {}, "props": {}},
    }
    state = driver.run_to_completion()
    assert state is DriverState.DONE, f"不应停止：{state}"
    #: _revert_to_best 的物理恢复在无 bpy 时如实记录失败（revert_failed），
    #: 但事件必须可见——"回滚有没有尝试恢复高分版本"要可审计。
    kinds = [entry.kind for entry in driver.audit.recent()]
    assert any(k in kinds for k in
               ("revert_skipped", "revert_applied", "revert_failed")), kinds
    assert "repair_rolled_back" in kinds, kinds
    assert builder.rebuild_kwargs, "回滚必须重建当前镜"
    assert builder.rebuild_kwargs[-1]["preserve_camera_edits"] is True, (
        "回滚重建必须保留恢复后的相机（preserve_camera_edits=True）")


def test_repair_prompt_carries_best_score_guard():
    """F16：repair 提示注入"高分保留"，防止整位重摆覆盖 best。"""
    auditor = FakeAuditor([
        _fail("COMPOSITION", score=53.0),
        _fail("COMPOSITION", score=53.0),
        AuditResult(passed=True, target="shot_001", score=88.0),
    ], shots=("shot_001",))
    transport = ScriptedTransport([
        PLAN_REPLY,
        ("setup_camera", {"shot_id": "shot_001", "shot_type": "MCU"}),
        None,
    ])
    driver = _make_driver(transport, auditor, builder=None)
    driver._react_best["shot_001"] = {
        "score": 79.5, "version": 1, "world_state": None}
    driver.run_to_completion()
    repair_payloads = [p for p in transport.payloads
                       if getattr(p, "purpose", None) is Purpose.REPAIR]
    assert repair_payloads, "必须产生一次修复请求"
    system = str(repair_payloads[0].messages[0].content)
    assert "高分保留" in system, system
    assert "best=79.5" in system, system
    assert "不要用 setup_camera" in system, system


def test_no_best_no_extra_prompt_shape_change():
    """F16 反面对照：无 best 时 repair 提示零形状差（不注入额外块）。"""
    auditor = FakeAuditor([
        _fail("COMPOSITION", score=53.0),
        AuditResult(passed=True, target="shot_001", score=88.0),
    ], shots=("shot_001",))
    transport = ScriptedTransport([
        PLAN_REPLY,
        ("setup_camera", {"shot_id": "shot_001", "shot_type": "MCU"}),
    ])
    driver = _make_driver(transport, auditor, builder=None)
    driver.run_to_completion()
    repair_payloads = [p for p in transport.payloads
                       if getattr(p, "purpose", None) is Purpose.REPAIR]
    assert repair_payloads
    system = str(repair_payloads[0].messages[0].content)
    assert "高分保留" not in system, system
