"""小助手状态映射（v1.7 TDD §3，R-UI-3 的单一真源）。

键用**字符串**（``DriverState.value``），不用枚举本体：``DriverState``
定义在 ``layer5_orchestrator/states.py``，而 contracts 不许反向 import
layer5。``DriverState`` 是 ``StrEnum``，字符串键与枚举成员**相等且同 hash**。
"""

from __future__ import annotations

from typing import Dict

CLIP_BY_STATE: Dict[str, str] = {
    "IDLE": "sleep",
    "UNDERSTANDING": "read",
    "PLANNING": "think",
    "CALLING_LLM": "think_wait",
    "EXECUTING_TOOL": "build",
    "BUILDING": "build",
    "EDITING": "think",
    "AWAIT_HUMAN": "ask",
    "REVIEWING": "inspect",
    "CHECKING": "inspect",
    "REPAIRING": "fix",
    "FINISHING": "pack",
    "DONE": "celebrate",
    "ERROR": "dizzy",
    "CANCELLED": "sit",
    #: v1.7 §9（卡 E1）：剧本优化态 → 小助手"阅读"动画。
    "POLISHING": "read",
}


def clip_for_state(state: str) -> str:
    """未知态回落 "sit"，永不抛异常（UI 是附属品）。"""
    return CLIP_BY_STATE.get(str(state), "sit")
