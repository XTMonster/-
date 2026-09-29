"""§7.6 / §12.6 驱动器护栏测试：循环检测与预算限流。"""

from __future__ import annotations

import json

from block_director.contracts.audit import AuditResult
from block_director.contracts.enums import Purpose
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
def test_waiting_for_a_slow_llm_does_not_trip_the_step_guard():
    """本地模型一次调用要几十秒，期间反复进 step()——那不是"死循环"。"""
    import queue as queue_module

    transport = RepairingTransport()
    driver = _driver(transport)
    driver._transition(DriverState.CALLING_LLM)
    before = driver.snapshot()["steps"]
    for _ in range(driver.limits.max_steps + 50):      # 远超上限的空转
        assert driver.step() is True
    assert driver.snapshot()["steps"] == before
    assert driver.error == ""


def test_budget_allows_the_normal_run_and_reports_usage():
    transport = RepairingTransport()
    auditor = FakeAuditor([AuditResult(passed=True, target="shot_001")])
    driver = _driver(transport, auditor=auditor)
    assert driver.run_to_completion() is DriverState.DONE
    summary = driver.snapshot()["budget"]
    # 剧本理解 1（阶段 S）+ 计划 1 + 单镜草案 2（§7.1 的 B1，逐镜一次）
    # + 自我审核 1
    assert summary["llm_calls"] == 5
    assert summary["exhausted"] is None


def test_budget_blocks_repair_but_keeps_the_built_scene():
    """理解 + 计划用掉仅有的两次调用后，修复被拦下——但场景已经建好了。"""
    transport = RepairingTransport()
    auditor = FakeAuditor([AuditResult(passed=False, target="shot_001",
                                       level="rule")])
    # 2 = 阶段 S 的理解 + 阶段 A 的计划；修复是第三次，必然被拦下
    budget = Budget(BudgetLimits(max_llm_calls=2, max_tokens=0,
                                 max_cost_usd=0, max_wall_seconds=0))
    driver = _driver(transport, auditor=auditor, budget=budget)

    assert driver.run_to_completion() is DriverState.DONE
    assert _purposes(transport) == [Purpose.UNDERSTAND, Purpose.PLAN]
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
    # 理解 + 计划 + 两镜草案 + 修复 + 自我审核，每次 150 token
    assert driver.snapshot()["budget"]["total_tokens"] == 6 * 150


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


# --------------------------------------------------------------------------- #
# v1.4 X7：叙事剧本下 R014 / R017 仍必须执行
# --------------------------------------------------------------------------- #
class EmptyShotTransport(RepairingTransport):
    """计划里放一个"无角色 + 有运镜 + 意图没写用途"的空镜。"""

    def chat(self, payload, timeout=120.0):
        reply = super().chat(payload, timeout)
        if payload.purpose is Purpose.PLAN:
            for call in reply.tool_calls or []:
                args = json.loads(call.function.arguments)
                args["shots"][0]["characters"] = []
                args["shots"][0]["intent"] = "x"
                call.function.arguments = json.dumps(args, ensure_ascii=False)
        return reply


def test_r014_and_r017_run_for_narrative_scripts():
    """没有分镜表声明的叙事剧本，R014/R017 也必须被判定（v1.4 X7）。"""
    driver = _driver(EmptyShotTransport())
    driver.run_to_completion()
    report = driver.snapshot()["compliance"]
    assert report is not None, "叙事剧本也要产出落实审核报告"
    rules = {item["rule"] for item in report["findings"]}
    assert "R017" in rules, "空镜没有说明用途时必须报 R017"
    assert "R014" not in rules, "X6 已删除 R014 的空镜分支，不得重复告警"


# --------------------------------------------------------------------------- #
# v1.4 §3.3：repair_applied 的条数 == 失败镜数
# --------------------------------------------------------------------------- #
def test_repair_applied_count_matches_failed_shots():
    """US-12②：每个失败镜各留一条 repair_applied，多或少都判失败。"""
    transport = RepairingTransport()
    # 第一镜先失败、修复后再审即通过；第二镜一次通过。
    auditor = FakeAuditor([
        AuditResult(passed=False, target="shot_001", level="rule"),
        AuditResult(passed=True, target="shot_001"),
        AuditResult(passed=True, target="shot_002"),
    ], shots=("shot_001", "shot_002"))
    driver = _driver(transport, auditor=auditor)
    driver.run_to_completion()

    events = [event for event in driver.audit.recent()
              if event.kind == "repair_applied"]
    failed = {result.target for result in driver.audit_results
              if not result.passed}
    assert len(events) == len(failed) == 1
    assert events[0].data.get("shot") == "shot_001"
    assert events[0].data.get("before_score") is None


def test_repair_applied_is_not_written_when_nothing_failed():
    """负例：从不失败的运行必须一条都不写（防止"空集通过"被写反）。"""
    transport = RepairingTransport()
    auditor = FakeAuditor([AuditResult(passed=True, target="shot_001")])
    driver = _driver(transport, auditor=auditor)
    driver.run_to_completion()
    kinds = [event.kind for event in driver.audit.recent()]
    assert "repair_applied" not in kinds
