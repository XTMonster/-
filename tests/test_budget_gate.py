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


# --------------------------------------------------- token 上限随场景缩放（2026-10-07）
#
# 现场：v15 管线下 64 镜真跑**两次**都在只用了 59% 调用额度时就吃满写死的 2 M token
# （`docs/evidence/20261007-v15-long/`、`…-long-topped-out/`：2,000,574 / 2,004,960），
# 于是 `test_the_long_real_run_is_fresh_and_stayed_within_the_ceiling` 永久判红。
# 修法（用户 2026-10-07 "你看着来"）：token 上限＝`本场调用额度 × 每次调用额度`
# （7,000，来自那两次实测的 6,150 / 6,311 向上取整），再与静态帽、静态下限取大。
# 判据/门限一个字没动——这一格只决定"账本允不允许继续调用"。


def test_a_short_scene_keeps_the_static_token_floor():
    """小场景**一个字节都不变**：6 镜的公式值远低于 2 M ⇒ 仍是 2 M。"""
    driver = _driver_with(6, cli=0)
    assert driver.budget.limits.max_tokens == 2_000_000


def test_a_long_scene_raises_the_token_budget_with_the_call_budget():
    """64 镜：552 次调用 × 7,000 = 3,864,000 ⇒ token 上限必须够它烧完调用额度。"""
    driver = _driver_with(64, cli=0)
    assert driver.budget.limits.max_llm_calls == 552
    assert driver.budget.limits.max_tokens == 552 * 7_000


def test_the_static_token_ceiling_caps_a_monster_scene():
    """再长也不许无限增长：100 镜的公式值 5.88 M 被 4 M 的静态帽截住。"""
    driver = _driver_with(100, cli=0)
    assert driver.budget.limits.max_tokens == 4_000_000


def test_the_caller_hard_cap_shrinks_the_token_budget_but_never_below_the_floor():
    """`--max-llm-calls` 是**硬顶**：它压小调用额度时 token 上限跟着下来，但不低于 2 M。"""
    driver = _driver_with(64, cli=100)
    assert driver.budget.limits.max_llm_calls == 100
    assert driver.budget.limits.max_tokens == 2_000_000      # 100×7000 = 700 k < 下限


def test_the_scene_budget_step_is_idempotent_and_leaves_a_trace():
    """同一条公式重复应用结果不变（下限取自**静态**值），并把 token 额度写进审计。"""
    driver = _driver_with(64, cli=0)
    first = driver.budget.limits.max_tokens
    driver._apply_scene_budget(64)
    assert driver.budget.limits.max_tokens == first
    scoped = [entry for entry in driver.audit._recent
              if getattr(entry, "kind", "") == "budget_scoped"]
    assert scoped and scoped[-1].data.get("max_tokens_effective") == first


def test_zero_allowance_keeps_the_ledger_default():
    """配置里把额度关掉（0 = 不限）⇒ 沿用账本静态值，不引入新口径。"""
    driver = _driver_with(64, cli=0)
    driver.config.budget.tokens_per_call_allowance = 0
    driver.budget.limits.max_tokens = 2_000_000
    assert driver._scene_token_budget(552) == 2_000_000


def test_zero_never_enters_the_min():
    driver = _driver_with(2, cli=0)
    assert driver.budget.limits.max_llm_calls != 0


def test_describe_mentions_formula_and_result():
    text = describe("shots * 8 + 40", 61)
    assert "528" in text


@pytest.mark.parametrize("value", ["lots", "", None])
def test_unknown_formula_keeps_the_static_ceiling(value):
    assert evaluate(value, 3) is None
