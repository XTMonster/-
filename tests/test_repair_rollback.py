"""一次**把片子改坏**的修复必须回滚（v1.4 §7.1 B4；2026-10-04 实测）。

现场（真跑复算）：long16 有 **12** 镜、long15 有 **4** 镜在修复之后**多出**了原本
没有的违规——典型形状是"为了让构图合格去挪机位，顺手把 R001 轴线踩了"；long18 里
"构图触底（≤20.0）"的镜头由 8 涨到 16。系统此前对这种退化**没有任何动作**：
`repair_applied` 照写，改坏的那一版留在交付里。

判据刻意取**严格变多**（`new - baseline` 非空）：

* 清掉一条规则 ⇒ 改善，留（不回滚）；
* 规则集不变 ⇒ 修没修成是另一回事（`shot_degraded` 记账），不回滚；
* **多出一条** ⇒ 这次修复引入了观众看得见的新毛病 ⇒ 回滚到修复前的基线。
"""

from __future__ import annotations

import json

from block_director.contracts.audit import AuditError, AuditResult
from block_director.contracts.enums import Purpose, Severity
from block_director.contracts.messages import ChatReply, FunctionCall, ToolCall
from block_director.layer5_orchestrator.driver import DriverLimits, PrevisDriver
from block_director.layer5_orchestrator.offline import demo_draft_dict
from block_director.layer5_orchestrator.planner import EMIT_PLAN_TOOL_PARAMETERS
from block_director.layer5_orchestrator.states import DriverState
from block_director.layer5_orchestrator.tool_registry import ToolRegistry
from block_director.layer6_audit.audit_logger import AuditLogger

from stage_helpers import is_understand, understand_reply
from test_driver import InlineThread
from test_driver_repair import SCRIPT, FakeAuditor, RepairingTransport, TrivialBuilder


def failing(rules, *, score=60.0):
    errors = [AuditError(rule=rule, code=f"E_{rule}", severity=Severity.ERROR,
                         target="shot_001", message=f"{rule} 红", suggestion="改")
              for rule in rules]
    return AuditResult(passed=False, level="rule", errors=errors, score=score)


def _registry():
    registry = ToolRegistry()
    registry.add(name="emit_plan", description="plan",
                 parameters=EMIT_PLAN_TOOL_PARAMETERS,
                 handler=lambda **kwargs: "计划已接收")
    registry.add(name="emit_shot_draft", description="draft",
                 parameters={"type": "object", "properties": {}},
                 handler=lambda **kwargs: "草案已接收")
    registry.add(name="setup_camera", description="fix",
                 parameters={"type": "object", "properties": {}},
                 handler=lambda: "相机已重设")
    return registry


class DraftRepairTransport(RepairingTransport):
    """修复回合**提一份新草案**（往这一镜塞一个动作）——计划真的被改了。"""

    def chat(self, payload, timeout=120.0):
        if payload.purpose is not Purpose.REPAIR:
            return super().chat(payload, timeout)
        self.payloads.append(payload)
        self.chat_calls += 1
        draft = dict(demo_draft_dict(0))
        draft["shot_id"] = "shot_001"
        actions = [dict(item) for item in (draft.get("actions") or [])]
        actions.append({"character_id": "char_001", "action_type": "nod",
                        "start_frame": 1, "end_frame": 12, "params": {}})
        draft["actions"] = actions
        call = ToolCall(id="draft_fix", function=FunctionCall(
            name="emit_shot_draft",
            arguments=json.dumps(draft, ensure_ascii=False)))
        return ChatReply(tool_calls=[call], content=None)


def _driver(transport, results, builder=None):
    return PrevisDriver(
        transport=transport, audit=AuditLogger(), script=SCRIPT,
        registry=_registry(), auditor=FakeAuditor(results),
        builder=builder or TrivialBuilder(), thread_factory=InlineThread)


def _kinds(driver):
    return [entry.kind for entry in driver.audit.recent()]


def test_a_repair_that_introduces_a_new_violation_is_rolled_back():
    """`{R003}` → `{R003, R001}`：多出来的 R001 是这次修复带来的 ⇒ 回滚。"""
    transport = RepairingTransport()          # 修复回合调 setup_camera（改场景）
    builder = TrivialBuilder()
    driver = _driver(transport, [
        failing(["R003"]),                    # 首次审计
        failing(["R003", "R001"]),            # 修复之后：多了一条 R001
        failing(["R003"]),                    # 回滚之后（重建完再审）
    ], builder=builder)

    assert driver.run_to_completion() is DriverState.DONE

    kinds = _kinds(driver)
    assert "repair_rolled_back" in kinds, f"改坏了却什么都没做：{kinds}"
    assert driver.rollback_events == [{"shot_id": "shot_001",
                                       "before": ["R003"],
                                       "after": ["R001", "R003"],
                                       "introduced": ["R001"]}]
    #: 回滚靠"计划变了 ⇒ 重建"那条现成通路：构建器被调了**两次**
    #: （首次建场景 ＋ 回滚后的重建），而且第二次拿到的计划就是修复前那份。
    assert len(builder.built) == 2, "回滚必须重建场景，否则改坏的机位留在工程里"
    assert builder.built[0].to_dict() == builder.built[1].to_dict()


def test_the_plan_snapshot_is_restored_too():
    """修复改了**计划**（重提草案）⇒ 回滚要把那份改动一起退掉。"""
    transport = DraftRepairTransport()
    builder = TrivialBuilder()
    driver = _driver(transport, [
        failing(["R003"]),
        failing(["R003", "R001"]),
        failing(["R003"]),
    ], builder=builder)

    assert driver.run_to_completion() is DriverState.DONE
    assert driver.rollback_events, "提了草案又改坏了，必须回滚"
    baseline, rebuilt = builder.built[0], builder.built[-1]
    shot_a = next(s for s in baseline.shots if s.shot_id == "shot_001")
    shot_b = next(s for s in rebuilt.shots if s.shot_id == "shot_001")
    assert len(shot_b.actions) == len(shot_a.actions), (
        "草案里多塞的那个动作必须随回滚消失（计划快照要一起退）")


def test_the_audit_after_a_rollback_is_marked_as_such():
    """回滚后的那次审核要带 `restored: true`——账上分得清"审的是哪一版"。"""
    transport = RepairingTransport()
    driver = _driver(transport, [
        failing(["R003"]), failing(["R003", "R001"]), failing(["R003"]),
    ])
    assert driver.run_to_completion() is DriverState.DONE
    audits = [entry for entry in driver.audit.recent()
              if getattr(entry, "kind", "") == "shot_audit"
              and entry.data.get("shot") == "shot_001"]
    assert audits[0].data.get("restored") is None       # 首次审计不带
    restored = [entry for entry in audits
                if entry.data.get("restored") is True]
    assert len(restored) == 1, f"回滚后的那次审核必须带标记 —— {audits}"
    #: 带标记的那一次审的正是**修复前那一版**：规则集回到基线的 {R003}。
    assert restored[0].data.get("rule_ids") == ["R003"]
    assert restored[0].data.get("composition_score") == 60.0


def test_a_repair_that_clears_a_rule_is_kept():
    """反面对照：**修好了**不许回滚（否则回滚就成了"一有风吹草动就退"）。"""
    transport = RepairingTransport()
    driver = _driver(transport, [failing(["R003"]),
                                 AuditResult(passed=True, level="rule", score=88.0)])
    assert driver.run_to_completion() is DriverState.DONE
    assert driver.rollback_events == []
    assert "repair_rolled_back" not in _kinds(driver)


def test_a_repair_that_changes_nothing_is_not_rolled_back():
    """反面对照：规则集**不变**不算"改坏"——那是没修好，由 `shot_degraded` 记账。"""
    transport = RepairingTransport()
    driver = _driver(transport, [failing(["R003"]), failing(["R003"]),
                                 failing(["R003"])])
    assert driver.run_to_completion() is DriverState.DONE
    assert driver.rollback_events == []
    assert "shot_degraded" in _kinds(driver)
