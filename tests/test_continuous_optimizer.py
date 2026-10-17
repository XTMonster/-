"""阶段 5：连续变量数值层（无导数黑箱优化器）测试。

覆盖设计文档 ``work/per_shot_decision_tree_design.md`` §3.5 的硬性条款：
- 不用梯度下降（评分不可微）；``gradient`` 打在 ``score_kind="blackbox"``
  → ``method_inapplicable`` 回执，不自动降级换方法；
- 声明 ``"differentiable"`` 后运行期实测遇 ``-inf``/NaN → 同回执（带触发键
  证据），不静默跳过；
- 方法选择权在 agent：``method_choice``/``method_reason`` 必填，``auto`` 也
  要理由；
- 步长（学习率类比）由 agent 决定：``step_scale`` 缺键/非正/含未登记键 →
  登记期 ``OptDomainError``，不自动推导兜底；
- x0 含未登记键在登记期拒绝；运行期 x0 越盒 → 拒绝并保留原值，绝不静默
  clamp/改写（设计 §3.5.2 硬边界 2）；
- 预算计数含 x0 一次，``calls <= max_calls`` 恒成立（auto 合并也不超）；
- 确定性：同 seed 结果逐字节一致；``_random_restarts`` 各起点跑短 HJ
  refinement，取最优（设计 §3.5.3 算法要点）；
- 无提升时结果必须等于 x0。
"""

from __future__ import annotations

import math

import pytest

from block_director.layer5_orchestrator.continuous_optimizer import (
    OptDomainError,
    OptProblem,
    OptResult,
    OptVariable,
    _check_method_applicable,
    _random_restarts,
    default_step_scale,
    optimize,
)


def _var(key: str = "x", low: float = 0.0, high: float = 10.0,
         step: float | None = None, scale: float = 1.0) -> OptVariable:
    return OptVariable(key=key, low=low, high=high, unit="unit",
                       scale=scale, step=step)


def _problem(*, score=None, method_choice: str = "hooke_jeeves",
             x0=None, variables=None, step_scale=None,
             score_kind: str = "blackbox", max_calls: int = 40,
             seed: int | None = 7) -> OptProblem:
    variables = variables or (_var(),)
    score = score or (lambda x: -abs(x.get("x", 0.0) - 5.0))
    return OptProblem(
        variables=variables,
        score=score,
        x0=x0 if x0 is not None else {"x": 0.0},
        step_scale=step_scale if step_scale is not None
        else default_step_scale(variables),
        shot_id="s001",
        stage="draft",
        score_kind=score_kind,
        method_choice=method_choice,
        method_reason="agent 选择",
        max_calls=max_calls,
        seed=seed,
    )


def test_gradient_on_blackbox_returns_method_inapplicable() -> None:
    """agent 选了梯度法但声明 blackbox（不可微目标）→ 回执，不降级换方法。"""
    problem = _problem(method_choice="gradient", score_kind="blackbox")
    result = optimize(problem)
    assert result.method_inapplicable
    assert "blackbox" in result.method_inapplicable
    assert result.method == ""
    assert result.calls == 0
    assert result.x == problem.x0


def test_gradient_claim_differentiable_but_runtime_neg_inf_is_inapplicable() -> None:
    """声明 differentiable 但运行期 score(k) == -inf（硬违规）→ 回执。"""
    def score(x: dict) -> float:
        if x.get("x", 0.0) > 0.5:
            return -math.inf
        return -abs(x.get("x", 0.0) - 3.0)

    problem = _problem(score=score, method_choice="gradient",
                       score_kind="differentiable", x0={"x": 0.0},
                       max_calls=20)
    result = optimize(problem)
    assert result.method_inapplicable
    assert "-inf" in result.method_inapplicable or "inf" in result.method_inapplicable
    #: x0 自身不越界才继续跑到 -inf；x0 拒绝的语义由下面测试独立覆盖。
    assert result.method == ""
    #: 预算口径含初始评测：x0 已评测 1 次，触发候选又 1 次（设计 §3.5）。
    assert result.calls >= 1


def test_gradient_claim_differentiable_but_nan_score_is_inapplicable() -> None:
    """声明 differentiable 但 score 返回 NaN → 回执，不静默跳过。"""
    def score(x: dict) -> float:
        if x.get("x", 0.0) < 5.0:
            return float("nan")
        return 0.0

    problem = _problem(score=score, method_choice="gradient",
                       score_kind="differentiable", x0={"x": 5.0},
                       max_calls=20)
    result = optimize(problem)
    assert result.method_inapplicable
    assert "NaN" in result.method_inapplicable
    assert result.method == ""


def test_method_inapplicable_when_choice_is_missing_reason() -> None:
    """方法选择权在 agent：method_reason 必填，空理由登记期拒绝。"""
    with pytest.raises(OptDomainError):
        OptProblem(
            variables=(_var(),),
            score=lambda x: 0.0,
            x0={"x": 0.0},
            step_scale={"x": 1.0},
            shot_id="s001",
            stage="draft",
            method_choice="auto",
            method_reason="",
        )


def test_step_scale_missing_key_is_registration_error() -> None:
    with pytest.raises(OptDomainError):
        OptProblem(
            variables=(_var(),),
            score=lambda x: 0.0,
            x0={"x": 0.0},
            step_scale={},          # 缺键：不自动推导兜底
            shot_id="s001",
            stage="draft",
            method_choice="hooke_jeeves",
            method_reason="agent 选择",
        )


def test_step_scale_nonpositive_is_registration_error() -> None:
    with pytest.raises(OptDomainError):
        OptProblem(
            variables=(_var(),),
            score=lambda x: 0.0,
            x0={"x": 0.0},
            step_scale={"x": 0.0},
            shot_id="s001",
            stage="draft",
            method_choice="hooke_jeeves",
            method_reason="agent 选择",
        )


def test_step_scale_unknown_key_is_registration_error() -> None:
    with pytest.raises(OptDomainError):
        OptProblem(
            variables=(_var(),),
            score=lambda x: 0.0,
            x0={"x": 0.0},
            step_scale={"x": 1.0, "y": 1.0},   # y 未登记
            shot_id="s001",
            stage="draft",
            method_choice="hooke_jeeves",
            method_reason="agent 选择",
        )


def test_x0_unknown_key_is_registration_error() -> None:
    with pytest.raises(OptDomainError):
        OptProblem(
            variables=(_var(),),
            score=lambda x: 0.0,
            x0={"x": 0.0, "y": 2.0},          # y 未登记
            step_scale={"x": 1.0},
            shot_id="s001",
            stage="draft",
            method_choice="hooke_jeeves",
            method_reason="agent 选择",
        )


def test_x0_out_of_box_is_rejected_not_clamped() -> None:
    """运行期 x0 越盒 → 拒绝并保留原值，绝不静默 clamp/改写。"""
    problem = _problem(x0={"x": 999.0})
    result = optimize(problem)
    assert result.x == {"x": 999.0}
    assert result.value == -math.inf
    assert not result.improved
    assert any("硬违规" in str(r.get("reason", "")) for r in result.audit)


def test_calls_never_exceed_max_calls_and_includes_x0() -> None:
    """预算口径含 x0；auto 合并 HJ+RR 都不超。"""
    for method in ("hooke_jeeves", "random_restarts", "auto"):
        problem = _problem(method_choice=method, max_calls=11, seed=3)
        result = optimize(problem)
        assert result.calls >= 1
        assert result.calls <= problem.max_calls


def test_random_restarts_is_deterministic_given_seed() -> None:
    results = [_random_restarts(_problem(seed=42), _rng(42))
               for _ in range(2)]
    assert results[0].x == results[1].x
    assert results[0].value == results[1].value


def _rng(seed: int):
    import random
    return random.Random(seed)


def test_random_restarts_runs_short_hj_refinement_per_start() -> None:
    """各起点跑短 HJ refinement，取最优（不只是随机采样）。"""
    #: 目标：x=7 附近最高；只随机采样大概率碰不到，短 HJ 沿坡爬山能达到
    #: 或显著比纯随机好。用大步长提升出解（refinement 激活）。
    def score(x: dict) -> float:
        return -abs(x.get("x", 0.0) - 7.0)

    problem = _problem(score=score, variables=(_var(high=10.0),),
                       x0={"x": 1.0}, step_scale={"x": 2.0},
                       max_calls=80, seed=5)
    result = _random_restarts(problem, _rng(5))
    #: 短 HJ 后应显著贴近全局峰，纯随机 20 次内到 7±0.2 的概率极低。
    assert abs(result.x["x"] - 7.0) < 1.0


def test_no_improvement_returns_x0_unchanged() -> None:
    """无提升时结果必须等于 x0（auto 合并同守）。"""
    def score(x: dict) -> float:
        #: x0 已是唯一峰顶，任何移动都更差。
        return -abs(x.get("x", 0.0) - 0.0)

    problem = _problem(score=score, method_choice="auto", x0={"x": 0.0},
                       max_calls=30, seed=1)
    result = optimize(problem)
    assert not result.improved
    assert result.x == {"x": 0.0}


def test_default_step_scale_returns_per_key_span_over_20() -> None:
    vars_ = (_var(key="a", low=0.0, high=100.0, scale=1.0),
             _var(key="b", low=0.0, high=2.0, scale=0.1))
    scale = default_step_scale(vars_)
    assert scale == {"a": 5.0, "b": 0.1}
    #: 建议值只供 agent 显式取用：自己不写回 problem。
    problem = _problem(variables=vars_, x0={"a": 0.0, "b": 0.0},
                       step_scale={"a": 5.0, "b": 0.1})
    assert problem.step_scale == {"a": 5.0, "b": 0.1}
