"""`estimate_shot_duration` 工具（执行文档 v1.2 §7.4 / §4.4）。

纯计算：给几句对白与几个动作，按 §4.4 的语速公式算出"这个镜头至少要多长"。
不碰 bpy，因此注册逻辑与实现都放在这里，pytest 可以直接调用 handler。

为什么值得单独做成工具：R011（对白容纳）是**硬门槛**，而模型在写计划时对
"这句话要几秒"的直觉经常偏短。让它先问一次，比事后再修便宜得多。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..layer1_input.dialogue_timing import (
    DIALOGUE_TAIL_FRAMES,
    FPS,
    schedule_dialogues,
)

ESTIMATE_DURATION = "estimate_shot_duration"

ESTIMATE_DURATION_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "dialogues": {
            "type": "array",
            "maxItems": 40,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text"],
                "properties": {
                    "text": {"type": "string"},
                    "parenthetical": {"type": "string"},
                    "emotion": {"type": "string"},
                },
            },
        },
        "actions": {
            "type": "array",
            "maxItems": 40,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["end_frame"],
                "properties": {
                    "character_id": {"type": "string"},
                    "end_frame": {"type": "integer", "minimum": 1},
                },
            },
        },
        "fps": {"type": "integer", "minimum": 1, "maximum": 120},
    },
}

ESTIMATE_DURATION_DESCRIPTION = (
    "按 §4.4 的语速公式估算这个镜头需要多少帧（含收尾余量）；"
    "不确定时长时先问它，别凭感觉写。")


class _DialogueLike:
    """把工具入参包装成 §4.4 需要的对象形状。"""

    __slots__ = ("text", "parenthetical", "emotion", "start_frame", "end_frame")

    def __init__(self, text: str = "", parenthetical: str = "",
                 emotion: str = "") -> None:
        self.text = text
        self.parenthetical = parenthetical
        self.emotion = emotion or "normal"
        self.start_frame = 0
        self.end_frame = 0


def estimate_shot_duration(dialogues: Sequence[Dict[str, Any]] = (),
                           actions: Sequence[Dict[str, Any]] = (),
                           fps: int = FPS) -> Dict[str, Any]:
    """返回建议时长与推导依据。"""
    items = [_DialogueLike(str(item.get("text", "")),
                           str(item.get("parenthetical", "")),
                           str(item.get("emotion", "")))
             for item in (dialogues or ())]
    spans: List[Tuple[int, int]] = schedule_dialogues(items, start_frame=1,
                                                      fps=int(fps))
    dialogue_end = max((end for _start, end in spans), default=0)
    with_tail = dialogue_end + DIALOGUE_TAIL_FRAMES if dialogue_end else 0

    action_end = 0
    for action in (actions or ()):
        try:
            action_end = max(action_end, int(action.get("end_frame", 0)))
        except (TypeError, ValueError, AttributeError):
            continue

    frames = max(with_tail, action_end, 1)
    reasons = []
    if dialogue_end:
        reasons.append(f"对白到第 {dialogue_end} 帧 + {DIALOGUE_TAIL_FRAMES} 帧余量")
    if action_end:
        reasons.append(f"动作到第 {action_end} 帧")
    if not reasons:
        reasons.append("既无对白也无动作：按最短镜头 1 帧计")
    return {"frames": frames, "seconds": round(frames / float(fps), 2),
            "dialogue_end": dialogue_end, "action_end": action_end,
            "tail_frames": DIALOGUE_TAIL_FRAMES,
            "spans": [list(span) for span in spans],
            "reason": "；".join(reasons), "fps": int(fps)}


def render_estimate(result: Dict[str, Any]) -> str:
    """工具返回给 LLM 的观察文本。"""
    return (f"建议镜头时长 {result['frames']} 帧"
            f"（{result['seconds']} 秒 @ {result['fps']}fps）：{result['reason']}")


def register_timing_tools(registry, fps: Optional[int] = None):
    """把 ``estimate_shot_duration`` 注册进工具表（重复调用安全）。"""

    def handler(**kwargs) -> str:
        return render_estimate(estimate_shot_duration(
            kwargs.get("dialogues") or (), kwargs.get("actions") or (),
            int(kwargs.get("fps") or fps or FPS)))

    registry.add(name=ESTIMATE_DURATION,
                 description=ESTIMATE_DURATION_DESCRIPTION,
                 parameters=ESTIMATE_DURATION_PARAMETERS, handler=handler)
    return registry.get(ESTIMATE_DURATION)
