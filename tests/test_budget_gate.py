"""v1.4 §2.4 / RK-18：预算门禁的唯一口径。

``ceiling_effective = max(budget.max_llm_calls_ceiling, formula(N))``
（``ceiling`` 是**额度下限保障**），CLI 的 ``--max-llm-calls`` 才是真硬顶；
``0`` 表示不限，**不得**写成 ``min(..., 0)``。
"""

from __future__ import annotations

import pytest

from block_director.contracts.config import AppConfig
from block_director.layer5_orchestrator.budget_formula import describe, evaluate
from block_director.layer5_orchestrator.driver import DriverLimits, _limits_from


def test_documented_default_formula():
    assert evaluate("shots * 8 + 40", 1) == 48
    assert evaluate("shots * 8 + 40", 61) == 528


def test_config_defaults_carry_the_new_formula_and_wall_clock():
    config = AppConfig()
    assert config.budget.max_llm_calls_per_scene_formula == "shots * 8 + 40"
    assert config.budget.max_llm_calls_ceiling == 200
    assert config.budget.max_wall_minutes == 120.0


def test_driver_limits_cap_defaults_to_zero_meaning_unlimited():
    assert DriverLimits().max_llm_calls == 0


def test_initial_budget_comes_from_the_ceiling_when_the_cli_is_silent():
    limits = _limits_from(AppConfig(), DriverLimits())
    assert limits.max_llm_calls == 200


def test_cli_value_overrides_the_ceiling():
    limits = _limits_from(AppConfig(), DriverLimits(max_llm_calls=1))
    assert limits.max_llm_calls == 1


def _driver_with(shots: int, *, cli: int):
    from test_driver import InlineThread
    from test_driver_builder import RecordingBuilder, SCRIPT
    from test_driver_repair import RepairingTransport, _registry

    from block_director.layer5_orchestrator.driver import PrevisDriver
    from block_director.layer6_audit.audit_logger import AuditLogger

    config = AppConfig()
    driver = PrevisDriver(
        transport=RepairingTransport(), audit=AuditLogger(), script=SCRIPT,
        registry=_registry(), builder=RecordingBuilder(),
        thread_factory=InlineThread, config=config,
        limits=DriverLimits(max_llm_calls=cli))
    driver._apply_scene_budget(shots)
    return driver


def test_long_script_ceiling_is_the_max_not_the_min():
    """61 镜：formula = 528 > ceiling 200 → 门禁 528（不是被 200 卡死）。"""
    driver = _driver_with(61, cli=0)
    assert driver.budget.limits.max_llm_calls == 528


def test_short_script_uses_the_ceiling_floor():
    driver = _driver_with(2, cli=0)
    assert driver.budget.limits.max_llm_calls == 200


def test_cli_hard_cap_still_wins():
    driver = _driver_with(61, cli=1)
    assert driver.budget.limits.max_llm_calls == 1


def test_zero_never_enters_the_min():
    driver = _driver_with(2, cli=0)
    assert driver.budget.limits.max_llm_calls != 0


def test_describe_mentions_formula_and_result():
    text = describe("shots * 8 + 40", 61)
    assert "528" in text


@pytest.mark.parametrize("value", ["lots", "", None])
def test_unknown_formula_keeps_the_static_ceiling(value):
    assert evaluate(value, 3) is None
