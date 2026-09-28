"""§12.6 预算与限流测试。"""

from __future__ import annotations

import pytest

from block_director.contracts.messages import Usage
from block_director.layer5_orchestrator.budget import Budget, BudgetLimits


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_defaults_do_not_exhaust_immediately():
    budget = Budget()
    assert budget.exhausted_reason() is None
    assert budget.allow_llm_call()


def test_call_limit_is_enforced():
    budget = Budget(BudgetLimits(max_llm_calls=2, max_tokens=0,
                                 max_cost_usd=0, max_wall_seconds=0))
    budget.record_llm(None)
    assert budget.allow_llm_call()
    budget.record_llm(None)
    assert not budget.allow_llm_call()
    assert "调用次数" in budget.exhausted_reason()


def test_token_limit_uses_prompt_plus_completion():
    budget = Budget(BudgetLimits(max_llm_calls=0, max_tokens=100,
                                 max_cost_usd=0, max_wall_seconds=0))
    budget.record_llm(Usage(60, 39, 99))
    assert budget.exhausted_reason() is None
    budget.record_llm(Usage(1, 0, 1))
    assert "token" in budget.exhausted_reason()


def test_cost_limit_is_computed_from_usage():
    limits = BudgetLimits(max_llm_calls=0, max_tokens=0, max_cost_usd=0.10,
                          max_wall_seconds=0,
                          cost_per_1k_prompt_usd=1.0,
                          cost_per_1k_completion_usd=2.0)
    budget = Budget(limits)
    budget.record_llm(Usage(50, 10, 60))
    assert budget.state.cost_usd == pytest.approx(0.05 + 0.02)
    assert budget.exhausted_reason() is None
    budget.record_llm(Usage(40, 0, 40))
    assert "费用" in budget.exhausted_reason()


def test_wall_clock_limit():
    clock = FakeClock()
    budget = Budget(BudgetLimits(max_llm_calls=0, max_tokens=0,
                                 max_cost_usd=0, max_wall_seconds=10.0),
                    clock=clock)
    assert budget.exhausted_reason() is None
    clock.advance(11.0)
    assert "运行时间" in budget.exhausted_reason()


def test_zero_means_unlimited():
    budget = Budget(BudgetLimits(max_llm_calls=0, max_tokens=0,
                                 max_cost_usd=0, max_wall_seconds=0))
    for _ in range(50):
        budget.record_llm(Usage(1000, 1000, 2000))
    assert budget.exhausted_reason() is None
    assert budget.state.total_tokens == 50 * 2000


def test_summary_reports_state_and_reason():
    budget = Budget(BudgetLimits(max_llm_calls=1, max_tokens=0,
                                 max_cost_usd=0, max_wall_seconds=0))
    budget.record_llm(Usage(10, 5, 15))
    summary = budget.summary
    assert summary["llm_calls"] == 1
    assert summary["total_tokens"] == 15
    assert "调用次数" in str(summary["exhausted"])
