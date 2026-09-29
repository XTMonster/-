"""控制类工具（执行文档 v1.2 §7.4 的最后一行）。

它们**不改场景**，只操纵这次运行：登记一次自我审核、声明当前镜头完成、或者
放弃整场。因此：

- 工具本身只做参数校验并回一句人话（§16.2：工具永不抛异常）；
- 真正的状态迁移由驱动器在派发工具调用时完成——只有它知道运行到哪一步了。

放在这里（而不是 ``layer3_engine``）是因为它们与 bpy 无关。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..contracts.tools import (
    ABORT,
    CONTROL_TOOL_NAMES,
    FINISH_SHOT,
    REQUEST_SELF_REVIEW,
)

REQUEST_SELF_REVIEW_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "shot_id": {"type": "string"},
        "shot_intent": {"type": "string"},
    },
}

FINISH_SHOT_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"summary": {"type": "string"}},
}

ABORT_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["reason"],
    "properties": {"reason": {"type": "string"}},
}


def _request_self_review(**kwargs) -> str:
    shot = str(kwargs.get("shot_id") or "")
    intent = str(kwargs.get("shot_intent") or "")
    target = shot or "当前镜头"
    return (f"已登记对 {target} 的自我审核请求"
            + (f"（意图：{intent}）" if intent else "")
            + "；由驱动器在下一轮执行，不额外发起调用。")


def _finish_shot(**kwargs) -> str:
    summary = str(kwargs.get("summary") or "")
    return ("已声明当前镜头完成" + (f"：{summary}" if summary else "")
            + "；驱动器会记录该结论并继续下一个镜头。")


def _abort(**kwargs) -> str:
    return f"已请求放弃本次生成：{kwargs.get('reason', '')}"


def register_control_tools(registry) -> Optional[Any]:
    """把三个控制工具注册进注册表（重复调用安全）。"""
    registry.add(name=REQUEST_SELF_REVIEW,
                 description="登记一次对该镜头的自我审核请求（不发起额外调用，"
                             "由驱动器在下一轮执行）。",
                 parameters=REQUEST_SELF_REVIEW_PARAMETERS,
                 handler=_request_self_review)
    registry.add(name=FINISH_SHOT,
                 description="声明当前镜头已完成，返回状态供下一个镜头使用。",
                 parameters=FINISH_SHOT_PARAMETERS, handler=_finish_shot)
    registry.add(name=ABORT,
                 description="放弃本次生成（场景保留，运行以 CANCELLED 结束）。",
                 parameters=ABORT_PARAMETERS, handler=_abort)
    return registry.get(ABORT)
