"""缺陷 B / U10（T6）：回溯三态——高分保留、低分回溯、过分数采用。

纯函数层测试（``contracts.backtrack.backtrack_three_state``）。判据来自
spec：版本序列 ``[55, 62, 55]`` 时 62 更新 best、第 3 版 55≤best 自动回滚；
序列 ``[81, 70]`` 时 81 被采用收尾；门槛 80 一字不动。
"""

from __future__ import annotations

from block_director.contracts.backtrack import backtrack_three_state
from block_director.cinema.composition import PASS_SCORE


def test_sequence_55_62_55_updates_best_and_rolls_back():
    first = backtrack_three_state(55.0)          # 首版：成为 best 基线
    second = backtrack_three_state(62.0, best_score=first.best_score,
                                   no_gain=first.no_gain)
    third = backtrack_three_state(55.0, best_score=second.best_score,
                                  no_gain=second.no_gain)
    assert first.disposition == "new_high" and first.best_score == 55.0
    assert second.disposition == "new_high" and second.best_score == 62.0
    assert second.no_gain == 0
    assert third.disposition == "revert"
    assert third.should_revert is True
    assert third.best_score == 62.0
    assert third.no_gain == 1


def test_score_above_threshold_adopts_even_on_first_version():
    adopted = backtrack_three_state(81.0)
    assert adopted.disposition == "adopt"
    assert adopted.adopted is True
    assert adopted.should_revert is False


def test_score_above_threshold_is_not_downgraded_by_best():
    """过分数采用：即使历史有更高分（例如另一条路线 90），81 已合格也收。"""
    adopted = backtrack_three_state(81.0, best_score=90.0, no_gain=2)
    assert adopted.disposition == "adopt"
    assert adopted.adopted is True


def test_below_best_counts_no_gain_and_requires_revert():
    decision = backtrack_three_state(40.0, best_score=62.0, no_gain=0)
    assert decision.disposition == "revert"
    assert decision.no_gain == 1
    assert decision.should_revert is True
    assert decision.best_score == 62.0


def test_tie_to_best_counts_no_gain_without_revert():
    decision = backtrack_three_state(62.0, best_score=62.0, no_gain=1)
    assert decision.disposition == "tie"
    assert decision.no_gain == 2
    assert decision.should_revert is False


def test_three_consecutive_no_gain_is_terminal_fail_condition():
    decision = None
    best = 62.0
    no_gain = 0
    for score in (55.0, 55.0, 55.0):
        decision = backtrack_three_state(score, best_score=best,
                                         no_gain=no_gain)
        no_gain = decision.no_gain
    assert no_gain == 3
    assert decision.disposition == "revert"


def test_threshold_is_exact_80_no_relaxation():
    assert PASS_SCORE == 80.0
    boundary = backtrack_three_state(80.0)
    #: 恰好 80 不算过：按 U6/U7"门槛不下放"，它只能成为 best 基线。
    assert boundary.disposition == "new_high"
    assert boundary.adopted is False
