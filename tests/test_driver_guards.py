"""§7.6 / §12.6 驱动器护栏测试：循环检测与预算限流。"""

from __future__ import annotations

from block_director.contracts.audit import AuditResult
from block_director.contracts.messages import ChatReply, FunctionCall, ToolCall, Usage
from block_director.layer5_orchestrator.budget import Budget, BudgetLimits
from block_director.layer5_orchestrator.driver import DriverLimits, PrevisDriver
from block_director.layer5_orchestrator.loop_detector import LoopDetector
from block_director.layer5_orchestrator.states import DriverState
from block_director.layer5_orchestrator.tool_registry import ToolRegistry
from block_director.layer6_audit.audit_logger import AuditLogger

from test_driver import InlineThread
from test_driver_builder import RecordingBuilder, SCRIPT
from test_driver_repair import FakeAuditor, RepairingTransport, _registry


def axis_config():
    from block_director.contracts.config import AppConfig

    config = AppConfig()
    config.llm.temperature_repair = 0.1
    return config


def _driver(transport, **kwargs):
    return PrevisDriver(transport=transport, audit=AuditLogger(), script=SCRIPT,
                        registry=_registry(), builder=RecordingBuilder(),
                        thread_factory=InlineThread, config=axis_config(),
                        **kwargs)


def _purposes(transport):
    return [p.purpose for p in transport.payloads]


# --------------------------------------------------------------------------- #
# 预算
# --------------------------------------------------------------------------- #
def test_budget_allows_the_normal_run_and_reports_usage():
    transport = RepairingTransport()
    auditor = FakeAuditor([AuditResult(passed=True, target="shot_001")])
    driver = _driver(transport, auditor=auditor)
    assert driver.run_to_completion() is DriverState.DONE
    summary = driver.snapshot()["budget"]
    # 计划 1 + 单镜草案 2（§7.1 的 B1，逐镜一次）+ 自我审核 1
    assert summary["llm_calls"] == 4
    assert summary["exhausted"] is None


def test_budget_blocks_repair_but_keeps_the_built_scene():
    """计划用掉唯一一次调用后，修复被拦下——但场景已经建好了。"""
    transport = RepairingTransport()
    auditor = FakeAuditor([AuditResult(passed=False, target="shot_001",
                                       level="rule")])
    budget = Budget(BudgetLimits(max_llm_calls=1, max_tokens=0,
                                 max_cost_usd=0, max_wall_seconds=0))
    driver = _driver(transport, auditor=auditor, budget=budget)

    assert driver.run_to_completion() is DriverState.DONE
    assert _purposes(transport) == [p for p in _purposes(transport)
                                    if p.value == "plan"]
    assert driver.degraded_reason and "调用次数" in driver.degraded_reason
    assert driver.snapshot()["built"] is True          # 场景没被丢掉
    kinds = [e.kind for e in driver.audit.recent()]
    assert "budget_exhausted" in kinds


def test_budget_exhausted_before_planning_degrades_immediately():
    transport = RepairingTransport()
    budget = Budget(BudgetLimits(max_llm_calls=0, max_tokens=0,
                                 max_cost_usd=0.0001, max_wall_seconds=0))
    budget.record_cost(1.0)              # 先花掉，模拟"一开局就超预算"
    driver = _driver(transport, budget=budget)
    assert driver.run_to_completion() is DriverState.DONE
    assert "费用" in driver.degraded_reason
    assert transport.chat_calls == 0     # 一次都没打出去


def test_token_usage_is_accounted_from_replies():
    class UsageTransport(RepairingTransport):
        def chat(self, payload, timeout=120.0):
            reply = super().chat(payload, timeout)
            reply.usage = Usage(100, 50, 150)
            return reply

    transport = UsageTransport()
    auditor = FakeAuditor([
        AuditResult(passed=False, target="shot_001"),
        AuditResult(passed=True, target="shot_001")])
    driver = _driver(transport, auditor=auditor)
    driver.run_to_completion()
    # 计划 + 两镜草案 + 修复 + 自我审核，每次 150 token
    assert driver.snapshot()["budget"]["total_tokens"] == 5 * 150


# --------------------------------------------------------------------------- #
# 循环检测
# --------------------------------------------------------------------------- #
class LoopingTransport(RepairingTransport):
    """修复阶段永远只调同一个工具、同一组参数。"""

    def chat(self, payload, timeout=120.0):
        if payload.purpose.value == "plan":
            return super().chat(payload, timeout)
        self.chat_calls += 1
        self.payloads.append(payload)
        call = ToolCall(id=f"loop_{self.chat_calls}",
                        function=FunctionCall(name="fix_camera",
                                              arguments="{}"))
        return ChatReply(tool_calls=[call])


def test_repeated_identical_tool_calls_raise_a_loop_warning():
    transport = LoopingTransport()
    failing = AuditResult(passed=False, target="shot_001")
    auditor = FakeAuditor([failing] * 10)
    driver = _driver(transport, auditor=auditor,
                     limits=DriverLimits(max_repairs_per_shot=4))
    driver.run_to_completion()
    warnings = [e for e in driver.audit.recent() if e.kind == "loop_warning"]
    assert warnings, "反复调同一工具应当触发循环警告"
    assert warnings[0].data.get("loop_kind") in ("repeat", "query_only")
    assert driver.snapshot()["loops"]["calls"] > 0


def test_loop_warning_is_injected_into_the_conversation():
    """警告要真的进到对话里，模型下一轮才看得见。"""
    detector = LoopDetector(repeat_threshold=1)
    detector.record("fix_camera", {})
    report = detector.detect()
    assert report is not None and report.kind == "repeat"

    transport = LoopingTransport()
    failing = AuditResult(passed=False, target="shot_001")
    driver = _driver(transport, auditor=FakeAuditor([failing] * 10),
                     loop_detector=detector,
                     limits=DriverLimits(max_repairs_per_shot=3))

    # 修复对话在每个镜头结束时会清空（每镜独立），所以要在注入瞬间抓取
    snapshots = []

    def observe(event):
        if event.kind == "loop_warning":
            snapshots.append(list(driver.repair_messages))

    driver.add_observer(observe)
    driver.run_to_completion()
    assert snapshots, "应当触发循环警告"
    injected = [m for snapshot in snapshots for m in snapshot
                if m.role.value == "system" and "重复调用" in (m.content or "")]
    assert injected, "警告必须真的进到修复对话里"
