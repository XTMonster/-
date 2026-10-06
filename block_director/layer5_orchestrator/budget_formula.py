"""每次场景的 LLM 调用额度公式（执行文档 v1.2 §21.5 的
``budget.max_llm_calls_per_scene_formula``）。

配置里写的是 ``"shots * 8 + 40"``（§2.4 的默认值；v1.3 是 ``"shots * 6"``）
这样的表达式：镜头越多允许的调用越多。它必须
在**拿到计划之后**才能算，因此由驱动器在计划落地时应用到预算账本上。

只支持三种形式（``<整数>``、``shots * <整数>``、``shots * <整数> + <整数>``）
——刻意不做通用表达式求值：配置是人手写的，语法越窄越不容易写出
"看起来对但算错"的东西。纯函数，可单测。

``+ <整数>`` 是 v1.3 新增的：理解阶段（Stage S）与逐镜复核是**每场固定开销**，
不随镜头数增长，用 ``shots * N`` 表达不了。不能识别的写法仍然返回 ``None``，
由调用方沿用静态上限——绝不静默按错误的额度放行。
"""

from __future__ import annotations

import re
from typing import Optional

_SHOTS_FORM = re.compile(
    r"^\s*shots\s*\*\s*(\d+)\s*(?:\+\s*(\d+)\s*)?$", re.IGNORECASE)
_PLAIN_FORM = re.compile(r"^\s*(\d+)\s*$")


def evaluate(formula: str, shots: int) -> Optional[int]:
    """按公式算出调用额度；无法识别时返回 ``None``（调用方保留静态上限）。"""
    text = str(formula or "")
    match = _SHOTS_FORM.match(text)
    if match:
        per_shot = max(int(match.group(1)), 1)
        fixed = int(match.group(2) or 0)
        return per_shot * max(int(shots), 1) + max(fixed, 0)
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
