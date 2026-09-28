"""每次场景的 LLM 调用额度公式（执行文档 v1.2 §21.5 的
``budget.max_llm_calls_per_scene_formula``）。

配置里写的是 ``"shots * 6"`` 这样的表达式：镜头越多允许的调用越多。它必须
在**拿到计划之后**才能算，因此由驱动器在计划落地时应用到预算账本上。

只支持两种形式（``<整数>``、``shots * <整数>``）——刻意不做通用表达式求值：
配置是人手写的，语法越窄越不容易写出"看起来对但算错"的东西。纯函数，可单测。
"""

from __future__ import annotations

import re
from typing import Optional

_SHOTS_FORM = re.compile(r"^\s*shots\s*\*\s*(\d+)\s*$", re.IGNORECASE)
_PLAIN_FORM = re.compile(r"^\s*(\d+)\s*$")


def evaluate(formula: str, shots: int) -> Optional[int]:
    """按公式算出调用额度；无法识别时返回 ``None``（调用方保留静态上限）。"""
    text = str(formula or "")
    match = _SHOTS_FORM.match(text)
    if match:
        return max(int(match.group(1)), 1) * max(int(shots), 1)
    match = _PLAIN_FORM.match(text)
    if match:
        return max(int(match.group(1)), 1)
    return None


def describe(formula: str, shots: int) -> str:
    """给日志/面板用的一句话。"""
    value = evaluate(formula, shots)
    if value is None:
        return f"无法识别的额度公式 {formula!r}，沿用静态上限"
    return f"{formula}（{shots} 镜）→ {value} 次调用"
