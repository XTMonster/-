"""连续变量数值层：无导数（黑箱）优化器（无 bpy、无第三方）。

设计文档 ``work/per_shot_decision_tree_design.md`` §3.5：
- 评分函数处处不可微（阶梯/硬闸/离散 ray_cast），**不用梯度下降**；
  用 Hooke-Jeeves 坐标模式搜索 + 确定性随机重启（非凸目标）；
- **方法选择权在 agent**：``method_choice``/``method_reason``/``score_kind``
  由 agent 显式声明，优化器不自动降级换方法；agent 选了梯度法但声明
  blackbox，或运行期实测遇 ``-inf``/NaN，都回执 ``method_inapplicable``；
- **步长（学习率类比）由 agent 决定**：``step_scale`` 逐键必填，缺键/
  非正/含未登记键 → 登记期 ``OptDomainError``，不自动推导兜底；
- 预算计数含 x0；x0 自身硬违规立即返回（不自动找可行点）；
- 带 ``step`` 的键：``clamp -> round_to_step -> clamp``；grid 键终止基准
  ``max(tolerance, step/2)``；
- 随机重启起点在盒内均匀采样，``seed`` 确定性可复现。
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Any, Callable, Dict, Optional, Tuple


class OptDomainError(ValueError):
    """登记期错误：把离散键/剧本硬值/未登记键登记为 OptVariable，
    或 step_scale 缺键/非正。

    构建期即抛，不留 ``opt_rejected`` 审计（还没到运行期，没有可拒绝的
    调用）。调用方负责把该异常记入运行日志/失败原因——它是构建期配置
    错误，不是"提议被拒"事件，避免与 ``opt_rejected`` 语义混淆。
    """


@dataclass(frozen=True)
class OptVariable:
    """一个可微调连续键（盒内）。"""

    key: str
    low: float
    high: float
    unit: str
    scale: float = 1.0          # 步长建议基准（只供 agent 显式取用）
    step: Optional[float] = None  # 有则对候选取整（如 1 度 / 0.01 米）

    def __post_init__(self) -> None:
        if self.low > self.high:
            raise OptDomainError(f"{self.key}: low > high")
        if self.scale <= 0:
            raise OptDomainError(f"{self.key}: scale 必须为正")
        if self.step is not None and self.step <= 0:
            raise OptDomainError(f"{self.key}: step 必须为正")


@dataclass(frozen=True)
class OptProblem:
    """一次逐镜数值优化请求（由 agent 组装）。"""

    variables: Tuple[OptVariable, ...]
    score: Callable[[Dict[str, float]], float]
    x0: Dict[str, float]
    step_scale: Dict[str, float]
    shot_id: str
    stage: str                    # "draft" / "react" / "repair" / "review"
    score_kind: str = "blackbox"
    method_choice: str = "auto"
    method_reason: str = ""
    max_calls: int = 40
    seed: Optional[int] = None
    tolerance: float = 1e-3

    def __post_init__(self) -> None:
        if not self.variables:
            raise OptDomainError("variables 不得为空")
        if self.max_calls <= 0:
            raise OptDomainError("max_calls 必须为正")
        if self.tolerance <= 0:
            raise OptDomainError("tolerance 必须为正")
        if self.score_kind not in ("blackbox", "differentiable"):
            raise OptDomainError(
                f"score_kind 必须是 blackbox/differentiable，"
                f"收到 {self.score_kind!r}")
        if self.method_choice not in (
                "hooke_jeeves", "random_restarts", "auto", "gradient"):
            raise OptDomainError(
                f"method_choice 必须是 hooke_jeeves/random_restarts/"
                f"auto/gradient，收到 {self.method_choice!r}")
        #: 方法由 agent 决定：选了 auto 也必须给理由（不自动推导兜底）。
        if not self.method_reason:
            raise OptDomainError("method_reason 必填（方法选择权在 agent）")
        registered = {v.key for v in self.variables}
        unknown_x0 = set(self.x0) - registered
        if unknown_x0:
            raise OptDomainError(
                f"x0 含未登记键: {sorted(unknown_x0)}")
        missing_scale = registered - set(self.step_scale)
        if missing_scale:
            raise OptDomainError(
                f"step_scale 缺键（不自动推导兜底）: {sorted(missing_scale)}")
        unknown_scale = set(self.step_scale) - registered
        if unknown_scale:
            raise OptDomainError(
                f"step_scale 含未登记键: {sorted(unknown_scale)}")
        for key, step in self.step_scale.items():
            if step <= 0:
                raise OptDomainError(f"step_scale[{key}] 必须为正，收到 {step!r}")


@dataclass(frozen=True)
class OptResult:
    """一次优化结果（审计进 ``opt_result`` 事件）。"""

    x: Dict[str, float]
    value: float
    x0: Dict[str, float]
    value0: float
    calls: int
    method: str
    improved: bool
    method_inapplicable: Optional[str] = None
    audit: Tuple[Dict[str, Any], ...] = ()
    warnings: Tuple[str, ...] = ()


def _clamp_value(v: OptVariable, x: float) -> float:
    """与树 ``project()`` 同一口径：先 clamp 到盒内。"""
    return min(v.high, max(v.low, float(x)))


def _round_to_step(v: OptVariable, x: float) -> float:
    """带 ``step`` 的键：按步长取整（用于 grid 键的候选生成）。"""
    if v.step is None:
        return x
    return round(x / v.step) * v.step


def _candidate(v: OptVariable, x: float) -> float:
    """候选值次序：clamp -> round -> clamp（取整可能顶出盒外）。"""
    clamped = _clamp_value(v, x)
    if v.step is not None:
        return _clamp_value(v, _round_to_step(v, clamped))
    return clamped


def _grid_stop(problem: OptProblem, v: OptVariable) -> float:
    """grid 键的步长终止基准：不低于 max(tolerance, step/2)。"""
    if v.step is not None:
        return max(problem.tolerance, v.step / 2.0)
    return problem.tolerance


def _evaluate(problem: OptProblem, x: Dict[str, float]
              ) -> Tuple[float, Dict[str, Any]]:
    """对候选评分：先 clamp，再调 score；-inf 硬违规原因写进审计。"""
    clamped = {v.key: _clamp_value(v, float(x.get(v.key, v.low)))
               for v in problem.variables}
    try:
        value = float(problem.score(clamped))
    except Exception as exc:  # noqa: BLE001
        return -math.inf, {"x": dict(x), "clamped": clamped,
                           "value": -math.inf,
                           "reason": f"score 抛异常: {type(exc).__name__}: {exc}"}
    if math.isnan(value):
        return -math.inf, {"x": dict(x), "clamped": clamped,
                           "value": -math.inf, "reason": "score 返回 NaN"}
    reason = "hard_violation_at_x0" if (value == -math.inf
                                        and dict(x) == problem.x0) else ""
    return value, {"x": dict(x), "clamped": clamped,
                   "value": value, "reason": reason}


def default_step_scale(variables) -> Dict[str, float]:
    """步长建议值（区间典型跨度 / 20），只供 agent 显式取用后自行决定。"""
    out: Dict[str, float] = {}
    for v in variables:
        span = v.high - v.low
        out[v.key] = max(v.scale, span / 20.0) if span > 0 else v.scale
    return out


def _check_method_applicable(problem: OptProblem) -> Tuple[bool, str]:
    """第一判据 = agent 声明的 score_kind；不靠优化器事后猜。"""
    if problem.method_choice == "gradient":
        if problem.score_kind == "blackbox":
            return False, (
                "agent 声明 blackbox（评分含阶梯/硬闸/离散 ray_cast），"
                "gradient 不适用；请改用 hooke_jeeves/random_restarts "
                "或换可微目标（不自动降级换方法）")
        return True, ""
    return True, ""


def _x0_box_violations(problem: OptProblem) -> str:
    """x0 越盒检查：任一登记键值越出 [low, high] 即拒绝，绝不静默 clamp。"""
    out = []
    for v in problem.variables:
        x = problem.x0.get(v.key)
        if x is None:
            out.append(f"{v.key} 缺 x0 值（缺失也是运行期拒绝，不猜默认）")
            continue
        try:
            value = float(x)
        except (TypeError, ValueError):
            out.append(f"{v.key}=<{type(x).__name__}:{x!r}> 不可转 float")
            continue
        if value < v.low or value > v.high:
            out.append(f"{v.key}={value!r} 越出盒 [{v.low}, {v.high}]")
    return "; ".join(out)


def _make_inapplicable(problem: OptProblem, rec: Dict[str, Any],
                       calls: int, audit: Tuple[Dict[str, Any], ...],
                       warnings: Tuple[str, ...] = (),
                       reason: Optional[str] = None) -> OptResult:
    """gradient + 声明 differentiable + 运行期实测 -inf/NaN → method_inapplicable
    回执（method 为空，不降级换方法、不静默跳过）。
    """
    evidence = reason or rec.get("reason") or "运行期实测不可应用（-inf/NaN）"
    evidence = (f"运行期实测不可应用（-inf/NaN）: {evidence}; "
                f"x={rec.get('x')!r}, clamped={rec.get('clamped')!r}")
    return OptResult(
        x=dict(problem.x0), value=math.nan,
        x0=dict(problem.x0), value0=math.nan,
        calls=calls, method="", improved=False,
        method_inapplicable=evidence,
        audit=audit, warnings=warnings)


def _reject_x0(problem: OptProblem, method: str, reason: str) -> OptResult:
    """x0 越盒/缺值 → 直接拒绝（结果保持原 x0，绝不改写为 clamp 后的值）。"""
    rec = {"x": dict(problem.x0), "clamped": None, "value": -math.inf,
           "reason": f"x0 运行期拒绝（硬违规）: {reason}"}
    return OptResult(
        x=dict(problem.x0), value=-math.inf,
        x0=dict(problem.x0), value0=-math.inf,
        calls=0, method=method, improved=False,
        audit=(rec,), warnings=("x0 越盒/缺值，不自动 clamp，问题退回 agent",))


def _hooke_jeeves(problem: OptProblem, rng: random.Random) -> OptResult:
    """坐标方向模式搜索（无导数）。"""
    bad = _x0_box_violations(problem)
    if bad:
        return _reject_x0(problem, "hooke_jeeves", bad)
    value0, rec0 = _evaluate(problem, problem.x0)
    if value0 == -math.inf:
        if problem.method_choice == "gradient" and problem.score_kind == "differentiable":
            return _make_inapplicable(problem, rec0, 1, (rec0,))
        #: x0 自身硬违规：立即返回，把问题退回 agent 调整意图。
        return OptResult(
            x=dict(problem.x0), value=value0,
            x0=dict(problem.x0), value0=value0,
            calls=1, method="hooke_jeeves", improved=False,
            audit=(rec0,),
            warnings=("x0 自身硬违规，不自动找可行点",))

    best = {v.key: _clamp_value(v, float(problem.x0.get(v.key, v.low)))
            for v in problem.variables}
    best_value = value0
    audit = [rec0]
    calls = 1
    step = dict(problem.step_scale)
    #: 模式搜索：base 是上一轮净增益起点；probe 沿坐标试探。
    base = dict(best)
    base_value = best_value

    while calls < problem.max_calls:
        improved_this_pass = False
        new_base = dict(base)
        new_base_value = base_value
        for v in problem.variables:
            remaining = problem.max_calls - calls
            if remaining <= 0:
                break
            key = v.key
            if step[key] < _grid_stop(problem, v):
                continue
            for direction in (1.0, -1.0):
                if remaining <= 0:
                    break
                candidate = _candidate(v, base[key] + direction * step[key])
                if candidate == base[key]:
                    continue
                remaining -= 1
                calls += 1
                cand_value, rec = _evaluate(
                    problem, {**base, key: candidate})
                audit.append(rec)
                if (cand_value == -math.inf
                        and problem.method_choice == "gradient"
                        and problem.score_kind == "differentiable"):
                    #: 声明可微但搜索路径上撞到硬违规/NaN → 回执，不降级。
                    return _make_inapplicable(problem, rec, calls,
                                              tuple(audit))
                if cand_value > new_base_value:
                    new_base_value = cand_value
                    new_base[key] = candidate
                    improved_this_pass = True
                    break
            if calls >= problem.max_calls:
                break
        if not improved_this_pass:
            #: 全轴都无净增益：缩小步长（grid 键不低于 step/2 基准）。
            any_active = False
            for v in problem.variables:
                key = v.key
                if step[key] > _grid_stop(problem, v):
                    step[key] = max(_grid_stop(problem, v), step[key] / 2.0)
                    any_active = True
            if not any_active:
                break
        else:
            #: 有净增益：模式移动加速（base 移动到新点）。
            base = dict(new_base)
            base_value = new_base_value
            best = dict(base)
            best_value = base_value

    improved = best_value > value0
    if not improved:
        best = dict(problem.x0)
        best_value = value0
    return OptResult(
        x=best, value=best_value,
        x0=dict(problem.x0), value0=value0,
        calls=calls, method="hooke_jeeves", improved=improved,
        audit=tuple(audit), warnings=())


def _short_hj_from(problem: OptProblem, start: Dict[str, float],
                   budget: int) -> Tuple[Dict[str, float], float,
                                         int, Tuple[Dict[str, Any], ...]]:
    """从给定起点跑短 HJ refinement（不重新计 x0，budget = 本轮可探次数）。

    与主 HJ 同一候选口径（``_candidate`` clamp→round→clamp），只做有限几轮
    坐标探索（每轮每变量 ±step 一次），预算到了即停；用于随机重启补位。
    """
    if budget <= 0:
        return dict(start), -math.inf, 0, ()
    best = dict(start)
    step = dict(problem.step_scale)
    best_value, rec = _evaluate(problem, best)
    audit = (rec,)
    #: 起点评测也计 1 次（预算口径「每次评测都进 calls」）
    calls = 1
    while calls < budget:
        improved = False
        new_best = dict(best)
        new_value = best_value
        for v in problem.variables:
            remaining = budget - calls
            if remaining <= 0:
                break
            key = v.key
            if step[key] < _grid_stop(problem, v):
                continue
            for direction in (1.0, -1.0):
                if remaining <= 0:
                    break
                candidate = _candidate(v, new_best[key]
                                       + direction * step[key])
                if candidate == new_best[key]:
                    continue
                remaining -= 1
                calls += 1
                cand_value, rec = _evaluate(
                    problem, {**new_best, key: candidate})
                audit = audit + (rec,)
                if cand_value > new_value and cand_value != -math.inf:
                    new_best[key] = candidate
                    new_value = cand_value
                    improved = True
                    break
            if calls >= budget:
                break
        if not improved:
            break
        best, best_value = new_best, new_value
    return best, best_value, calls, audit


def _random_restarts(problem: OptProblem, rng: random.Random,
                     budget: Optional[int] = None) -> OptResult:
    """非凸目标补充起点：盒内均匀采样，各跑短 HJ，取最优。

    ``budget`` 供 ``auto`` 共享预算（HJ 已花后只给剩余次数），缺省 = 全预算；
    预算口径含 x0 一次，恒不超过传入 budget。
    """
    budget = problem.max_calls if budget is None else budget
    if budget <= 0:
        return OptResult(x=dict(problem.x0), value=math.nan,
                         x0=dict(problem.x0), value0=math.nan,
                         calls=0, method="random_restarts",
                         improved=False, audit=(), warnings=())
    bad = _x0_box_violations(problem)
    if bad:
        return _reject_x0(problem, "random_restarts", bad)
    value0, rec0 = _evaluate(problem, problem.x0)
    if value0 == -math.inf:
        if problem.method_choice == "gradient" and problem.score_kind == "differentiable":
            return _make_inapplicable(problem, rec0, 1, (rec0,))
        return OptResult(
            x=dict(problem.x0), value=value0,
            x0=dict(problem.x0), value0=value0,
            calls=1, method="random_restarts", improved=False,
            audit=(rec0,),
            warnings=("x0 自身硬违规，不自动找可行点",))

    best = dict(problem.x0)
    best_value = value0
    audit = [rec0]
    calls = 1
    n_starts = 8
    if budget > 40:
        n_starts = 16
    elif budget > 20:
        n_starts = 12
    for start_index in range(n_starts):
        if calls >= budget:
            break
        start = {}
        for v in problem.variables:
            start[v.key] = v.low + rng.random() * (v.high - v.low)
        starts_left = n_starts - start_index
        per_budget = max(2, (budget - calls) // starts_left)
        refined_x, refined_value, used, recs = _short_hj_from(
            problem, start, per_budget)
        calls += used
        audit.extend(recs)
        if refined_value > best_value:
            best = dict(refined_x)
            best_value = refined_value

    improved = best_value > value0
    if not improved:
        best = dict(problem.x0)
        best_value = value0
    return OptResult(
        x=best, value=best_value,
        x0=dict(problem.x0), value0=value0,
        calls=calls, method="random_restarts", improved=improved,
        audit=tuple(audit), warnings=())


def optimize(problem: OptProblem) -> OptResult:
    """执行优化；方法取自 problem.method_choice，不替 agent 换方法。"""
    ok, evidence = _check_method_applicable(problem)
    if not ok:
        return OptResult(
            x=dict(problem.x0), value=math.nan,
            x0=dict(problem.x0), value0=math.nan,
            calls=0, method="", improved=False,
            method_inapplicable=evidence, warnings=())

    rng = random.Random(problem.seed)
    if problem.method_choice == "random_restarts":
        return _random_restarts(problem, rng, budget=problem.max_calls)
    if problem.method_choice == "hooke_jeeves":
        return _hooke_jeeves(problem, rng)
    #: auto：先 HJ，若预算剩余 >=10 次再随机重启补位；RR 只拿剩余预算，
    #: 总 calls 恒 <= max_calls（预算共享，不重复记 x0）。
    result = _hooke_jeeves(problem, rng)
    remaining = problem.max_calls - result.calls
    if remaining >= 10 and result.method_inapplicable is None:
        rr = _random_restarts(problem, rng, budget=remaining)
        result = OptResult(
            x=rr.x if rr.improved and rr.value > result.value else result.x,
            value=max(rr.value, result.value),  # x0 无提升时两路都 == value0
            x0=result.x0, value0=result.value0,
            calls=result.calls + rr.calls, method="auto",
            improved=result.improved or rr.improved,
            method_inapplicable=rr.method_inapplicable,
            audit=result.audit + rr.audit,
            warnings=result.warnings + rr.warnings)
    return result
