"""§21.5 额度公式的纯计算测试。"""

from __future__ import annotations

import pytest

from block_director.layer5_orchestrator.budget_formula import describe, evaluate


def test_documented_default_formula():
    assert evaluate("shots * 6", 1) == 6
    assert evaluate("shots * 6", 5) == 30


def test_whitespace_and_case_are_tolerated():
    assert evaluate("  SHOTS*4  ", 3) == 12
    assert evaluate("shots*4", 3) == 12


def test_plain_integer_formula():
    assert evaluate("8", 99) == 8
    assert evaluate(" 12 ", 1) == 12


def test_unknown_formula_returns_none_so_the_static_cap_stays():
    for bad in ("", "shots ** 6", "shots / 2", "6 * shots", "按镜头算",
                "shots * -1", None, "shots * 6 +", "shots * 6 - 1",
                "+ 2", "shots * 6 + 2 + 3"):
        assert evaluate(bad, 3) is None


def test_fixed_overhead_formula():
    """v1.3：Stage S 与逐镜复核是每场固定开销，不随镜头数增长。"""
    assert evaluate("shots * 6 + 2", 1) == 8
    assert evaluate("shots * 6 + 2", 6) == 38
    assert evaluate("shots*8+0", 5) == 40
    assert evaluate("  SHOTS * 3 + 1  ", 4) == 13


def test_fixed_overhead_is_per_scene_not_per_shot():
    """固定项只加一次——否则镜头越多越离谱，等于悄悄放开预算。"""
    one = evaluate("shots * 2 + 10", 1)
    ten = evaluate("shots * 2 + 10", 10)
    assert ten - one == 9 * 2


def test_zero_shots_or_zero_factor_still_allows_one_call():
    assert evaluate("shots * 6", 0) == 6
    # 因子被抬到至少 1：`shots * 0` 退化成"每镜一次调用"，而不是把预算锁死
    assert evaluate("shots * 0", 3) == 3
    assert evaluate("0", 3) == 1


def test_describe_reports_both_the_formula_and_the_result():
    assert "shots * 6" in describe("shots * 6", 2)
    assert "12" in describe("shots * 6", 2)
    assert "无法识别" in describe("???", 2)
