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
                "shots * -1", None):
        assert evaluate(bad, 3) is None


def test_zero_shots_or_zero_factor_still_allows_one_call():
    assert evaluate("shots * 6", 0) == 6
    # 因子被抬到至少 1：`shots * 0` 退化成"每镜一次调用"，而不是把预算锁死
    assert evaluate("shots * 0", 3) == 3
    assert evaluate("0", 3) == 1


def test_describe_reports_both_the_formula_and_the_result():
    assert "shots * 6" in describe("shots * 6", 2)
    assert "12" in describe("shots * 6", 2)
    assert "无法识别" in describe("???", 2)
