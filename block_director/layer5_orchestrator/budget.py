"""预算与限流（执行文档 v1.2 §12.6）。

四条上限：LLM 调用次数、总 token、预估费用、墙上时间。任一触顶都要**如实
上报**并按降级策略收尾，而不是悄悄继续烧钱。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional

from ..contracts.messages import Usage


@dataclass
class BudgetLimits:
    max_llm_calls: int = 60             # 0 表示不限
    max_tokens: int = 2_000_000         # 0 表示不限
    max_cost_usd: float = 5.0           # 0 表示不限
    max_wall_seconds: float = 1800.0    # 0 表示不限
    cost_per_1k_prompt_usd: float = 0.0
    cost_per_1k_completion_usd: float = 0.0


@dataclass
class BudgetState:
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    elapsed_seconds: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def to_dict(self) -> Dict[str, object]:
        return {"llm_calls": self.llm_calls,
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "total_tokens": self.total_tokens,
                "cost_usd": round(self.cost_usd, 4),
                "elapsed_seconds": round(self.elapsed_seconds, 1)}


class Budget:
    """运行级预算账本。所有判断都是"以上限为准"，0 表示该项不限。"""

    def __init__(self, limits: Optional[BudgetLimits] = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.limits = limits or BudgetLimits()
        self.clock = clock
        self.state = BudgetState()
        self._started = self.clock()

    @property
    def elapsed(self) -> float:
        return self.clock() - self._started

    def refresh(self) -> None:
        self.state.elapsed_seconds = self.elapsed

    def exhausted_reason(self) -> Optional[str]:
        """返回触顶原因；未触顶返回 None。"""
        self.refresh()
        limits = self.limits
        if limits.max_llm_calls and self.state.llm_calls >= limits.max_llm_calls:
            return f"LLM 调用次数已达上限（{limits.max_llm_calls}）"
        if limits.max_tokens and self.state.total_tokens >= limits.max_tokens:
            return f"token 用量已达上限（{limits.max_tokens}）"
        if limits.max_cost_usd and self.state.cost_usd >= limits.max_cost_usd:
            return f"预估费用已达上限（${limits.max_cost_usd:.2f}）"
        if limits.max_wall_seconds and self.elapsed >= limits.max_wall_seconds:
            return f"运行时间已达上限（{limits.max_wall_seconds:.0f}s）"
        return None

    def allow_llm_call(self, purpose: str = "") -> bool:
        return self.exhausted_reason() is None

    def record_llm(self, usage: Optional[Usage], *, calls: int = 1) -> None:
        """记一次（或多次）LLM 调用。``usage`` 允许缺失——部分端点不返回。"""
        self.state.llm_calls += int(calls)
        if usage is not None:
            self.state.prompt_tokens += int(usage.prompt_tokens)
            self.state.completion_tokens += int(usage.completion_tokens)
            self.state.cost_usd += (
                usage.prompt_tokens / 1000.0
                * self.limits.cost_per_1k_prompt_usd
                + usage.completion_tokens / 1000.0
                * self.limits.cost_per_1k_completion_usd)
        self.refresh()

    def record_cost(self, usd: float) -> None:
        self.state.cost_usd += float(usd)
        self.refresh()

    @property
    def summary(self) -> Dict[str, object]:
        self.refresh()
        return {**self.state.to_dict(), "exhausted": self.exhausted_reason()}
