"""对抗性审查接进 driver 的公开行为测试（SPEC_adversarial_review_driver_integration_20261012.md）。

只通过 ``PrevisDriver.step()`` / ``run_to_completion()`` 的公开行为断言：

- 每镜每次审核都产生一条版本化 ``adversarial_review`` 记录（事件 + 交付结果）；
- 安全区 / 九宫格偏差只是软参考，绝不单独进 REPAIRING、不阻塞前进；
- 硬 finding 保持在修复/ReAct 路径，修复提示词里能看到对抗审查的解释与建议；
- 越轴经既有人工 gate 升级，不被静默放行；
- 同镜重建替换结果条目后，review 记录仍然保留（回溯留痕）。
"""

from __future__ import annotations

import json

from block_director.contracts.audit import AuditError, AuditResult
from block_director.contracts.config import AppConfig
from block_director.contracts.enums import Purpose, Severity
from block_director.contracts.messages import ChatReply, FunctionCall, ToolCall
from block_director.layer5_orchestrator.driver import DriverLimits, PrevisDriver
from block_director.layer5_orchestrator.human_gate import AutoGate, GateDecision
from block_director.layer5_orchestrator.offline import (
    demo_draft_dict,
    demo_plan_dict,
)
from block_director.layer5_orchestrator.planner import EMIT_PLAN_TOOL_PARAMETERS
from block_director.layer5_orchestrator.states import DriverState
from block_director.layer5_orchestrator.tool_registry import ToolRegistry
from block_director.layer6_audit.audit_logger import AuditLogger

from test_driver import InlineThread
from test_driver_per_shot import PerShotBuilder, PerShotTransport
from stage_helpers import is_understand, understand_reply


SCRIPT = "INT. 咖啡馆 - 日\n\n小明坐下。\n"


def axis_finding() -> AuditError:
    return AuditError(rule="R001", code="E_AXIS_001", severity=Severity.ERROR,
                      target="shot_001",
                      message="相机位置违反 180° 轴线规则。",
                      suggestion="将相机移到轴线另一侧。")


def soft_digest() -> dict:
    """画面摘要：主体略偏离安全区与九宫格，但完全可见（软参考，非硬门）。"""
    return {
        "framing": {
            "subjects": {
                "小明": [{
                    "frame": 1,
                    "ndc_box": {"left": -0.1, "right": 0.95,
                                "top": 0.6, "bottom": -0.2},
                    "head_box": {"left": -0.1, "right": 0.95,
                                 "top": 0.6, "bottom": 0.35},
                    "center": [0.425, 0.2],
                    "thirds": "bottom",
                    "screen_height_ratio": 0.8,
                    "visible_ratio": 0.86,
                    "behind_camera": False,
                    "in_frame": True,
                    "in_action_safe": False,
                    "in_title_safe": False,
                }],
            },
        },
        "spatial": {},
    }


class DigestAuditor:
    """假审核器：每个结果都带 ``scene_digest``（与真实审核器同一形状）。"""

    def __init__(self, results, shots=("shot_001", "shot_002")):
        self._results = list(results)
        self._shots = list(shots)
        self.calls = []

    def shot_ids(self):
        return list(self._shots)

    def audit(self, shot_id):
        self.calls.append(shot_id)
        if self._results:
            result = self._results.pop(0)
        else:
            result = AuditResult(passed=True, target=shot_id)
        if getattr(result, "scene_digest", None) is None:
            result.scene_digest = soft_digest()
        return result


class CapturingTransport(PerShotTransport):
    """记录修复请求的 system 文本，供"解释进入修复上下文"断言。"""

    def __init__(self):
        super().__init__()
        self.repair_system_texts: list = []

    def chat(self, payload, timeout=120.0):
        if payload.purpose is Purpose.REPAIR:
            self.repair_system_texts.append(
                str(payload.messages[0].content))
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
    registry.add(name="setup_camera", description="fix",
                 parameters={"type": "object", "additionalProperties": False,
                             "properties": {}},
                 handler=lambda: "相机已重设")
    return registry


def _driver(transport, auditor, builder, **kwargs):
    return PrevisDriver(transport=transport, audit=AuditLogger(),
                        script=SCRIPT, registry=_registry(), auditor=auditor,
                        builder=builder, thread_factory=InlineThread, **kwargs)


def _review_events(driver):
    return [event for event in driver.audit.recent()
            if event.kind == "adversarial_review"]


def _shot_entry(driver, shot_id):
    return next(item for item in driver.build_summary["results"]
                if item.get("shot_id") == shot_id)


def test_soft_ruler_deviations_never_enter_repair_and_do_not_block():
    """安全区/九宫格偏差：pass + 全 soft，镜头照常前进，不进 REPAIRING。"""
    builder = PerShotBuilder()
    driver = _driver(PerShotTransport(), DigestAuditor([]), builder)
    assert driver.run_to_completion() is DriverState.DONE

    events = _review_events(driver)
    assert len(events) == 2                      # 两镜各一条
    for event in events:
        assert event.data["disposition"] == "pass"
        assert event.data["version"] >= 1
        assert isinstance(event.data["issues"], list) and event.data["issues"]
        severities = {issue["severity"] for issue in event.data["issues"]}
        assert severities <= {"soft"}
        assert event.data["rationale"]
    # 两镜都重建并前进，没有人被拖进修复
    assert len(builder.rebuilt) == 2
    assert driver.state is DriverState.DONE
    # 交付结果里每个镜头都有对抗审查记录
    for shot_id in ("shot_001", "shot_002"):
        entry = _shot_entry(driver, shot_id)
        assert entry["adversarial_review"]["disposition"] == "pass"


def test_hard_finding_stays_on_repair_path_with_explanation():
    """硬失败：revise 记录 + 修复提示词里带对抗审查的解释（证据/建议）。"""
    failing = AuditResult.from_findings([
        AuditError(rule="COMPOSITION", message="构图评分 40 低于阈值",
                   severity=Severity.ERROR, target="shot_001"),
    ], target="shot_001")
    transport = CapturingTransport()
    builder = PerShotBuilder()
    driver = _driver(transport, DigestAuditor([failing]), builder)
    assert driver.run_to_completion() is DriverState.DONE

    events = _review_events(driver)
    shot_001_events = [e for e in events
                       if e.data.get("shot_id") == "shot_001"]
    first = shot_001_events[0]
    assert first.data["disposition"] == "revise"
    assert any(issue["severity"] == "hard"
               for issue in first.data["issues"])
    # 修复提示词把对抗审查的解释带给了模型（梯度下降的"信号"）。
    assert transport.repair_system_texts
    joined = "\n".join(transport.repair_system_texts)
    assert "对抗性审查" in joined
    assert "revise" in joined
    assert "建议" in joined
    # 修完通过后，交付结果里保留对抗审查记录（最新一轮判定随状态更新）。
    entry = _shot_entry(driver, "shot_001")
    assert "adversarial_review" in entry
    assert entry["adversarial_review"]["disposition"] in ("pass", "revise")


def test_axis_violation_escalates_to_human_gate_not_silent_pass():
    """越轴：对抗审查记 escalate，且走既有人工 gate（不静默放行）。"""
    failing = AuditResult.from_findings([axis_finding()], target="shot_001")
    gate = AutoGate(default=GateDecision.APPROVED)
    config = AppConfig()
    config.audit.human_gate_on_plan = False
    config.audit.human_gate_on_axis_violation = True
    driver = _driver(
        CapturingTransport(), DigestAuditor([failing] * 10), PerShotBuilder(),
        human_gate=gate,
        config=config,
        limits=DriverLimits(max_repairs_per_shot=1))
    assert driver.run_to_completion() is DriverState.DONE

    kinds = [item["kind"] for item in driver.gate_history]
    assert "axis_violation" in kinds
    events = _review_events(driver)
    assert any(e.data["disposition"] == "escalate" for e in events
               if e.data.get("shot_id") == "shot_001")
    entry = _shot_entry(driver, "shot_001")
    assert entry["adversarial_review"]["disposition"] == "escalate"


def test_review_survives_result_replacement_on_rebuild():
    """同镜第二轮 rebuild 整体替换结果条目时，对抗审查记录仍然保留。"""

    class ReplacingBuilder(PerShotBuilder):
        def __init__(self):
            super().__init__()
            self._calls = 0

        def rebuild_shot(self, shot_id, *, plan=None, brief=None,
                         preserve_camera_edits=False):
            base = super().rebuild_shot(shot_id, plan=plan, brief=brief)
            self._calls += 1
            if self._calls == 2:
                base["camera_position"] = [9.9, 9.9, 9.9]
                base["lens"] = 85.0
            return base

    failing = AuditResult.from_findings([
        AuditError(rule="COMPOSITION", message="构图评分 40 低于阈值",
                   severity=Severity.ERROR, target="shot_001"),
    ], target="shot_001")
    builder = ReplacingBuilder()
    driver = _driver(CapturingTransport(),
                     DigestAuditor([failing]), builder)
    assert driver.run_to_completion() is DriverState.DONE
    entry = _shot_entry(driver, "shot_001")
    assert entry["lens"] == 85.0
    assert "adversarial_review" in entry
    assert entry["adversarial_review"]["disposition"] in ("pass", "revise")


def test_adversarial_review_event_has_all_contract_fields():
    """事件契约：shot_id/version/disposition/issues/rationale 五字段齐备。"""
    builder = PerShotBuilder()
    driver = _driver(PerShotTransport(), DigestAuditor([]), builder)
    assert driver.run_to_completion() is DriverState.DONE
    events = _review_events(driver)
    assert events
    for event in events:
        assert event.data["shot_id"] in ("shot_001", "shot_002")
        assert isinstance(event.data["version"], int)
        assert event.data["version"] >= 1
        assert event.data["disposition"] in ("pass", "revise", "escalate")
        assert isinstance(event.data["issues"], list)
        assert event.data["rationale"]
    from block_director.contracts.audit import missing_event_fields
    assert missing_event_fields("adversarial_review", {
        "shot_id": events[0].data["shot_id"],
        "version": events[0].data["version"],
        "disposition": events[0].data["disposition"],
        "issues": list(events[0].data["issues"]),
        "rationale": events[0].data["rationale"],
    }) == []
