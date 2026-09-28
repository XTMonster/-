"""§7.4 `estimate_shot_duration` 工具的纯计算测试。"""

from __future__ import annotations

from block_director.layer1_input.dialogue_timing import DIALOGUE_TAIL_FRAMES
from block_director.layer5_orchestrator.timing_tool import (
    ESTIMATE_DURATION,
    ESTIMATE_DURATION_PARAMETERS,
    estimate_shot_duration,
    register_timing_tools,
)
from block_director.layer5_orchestrator.tool_registry import ToolRegistry


def test_no_content_still_returns_a_minimum_shot():
    result = estimate_shot_duration()
    assert result["frames"] == 1 and result["dialogue_end"] == 0
    assert "最短" in result["reason"]


def test_dialogue_length_includes_the_tail():
    result = estimate_shot_duration([{"text": "你还在听吗。"}])
    assert result["dialogue_end"] > 0
    assert result["frames"] == result["dialogue_end"] + DIALOGUE_TAIL_FRAMES
    assert "余量" in result["reason"]


def test_longer_text_needs_more_frames():
    short = estimate_shot_duration([{"text": "好。"}])
    long = estimate_shot_duration([{"text": "我真的不知道该怎么跟你说这件事。"}])
    assert long["frames"] > short["frames"]


def test_emotion_changes_the_estimate_like_the_timing_rules():
    """生气更快 → 更短；悲伤更慢 → 更长（§4.4 的方向性断言）。"""
    angry = estimate_shot_duration([{"text": "你到底想怎么样", "emotion": "angry"}])
    sad = estimate_shot_duration([{"text": "你到底想怎么样", "emotion": "sad"}])
    assert angry["frames"] < sad["frames"]


def test_parenthetical_is_used_when_emotion_is_missing():
    plain = estimate_shot_duration([{"text": "我明天就走"}])
    sad = estimate_shot_duration([{"text": "我明天就走", "parenthetical": "（停顿）"}])
    assert sad["frames"] >= plain["frames"]


def test_actions_can_dominate_the_duration():
    result = estimate_shot_duration([{"text": "好。"}],
                                    [{"character_id": "char_001",
                                      "end_frame": 200}])
    assert result["frames"] == 200
    assert "动作到第 200 帧" in result["reason"]


def test_custom_fps_scales_the_seconds_but_not_the_frames():
    at_24 = estimate_shot_duration([{"text": "你还在听吗。"}], fps=24)
    at_12 = estimate_shot_duration([{"text": "你还在听吗。"}], fps=12)
    assert at_12["seconds"] > at_24["seconds"]
    assert at_12["fps"] == 12


def test_bad_action_entries_are_ignored():
    result = estimate_shot_duration([], [{"end_frame": "十二"},
                                         {"no_end_frame": True}])
    assert result["action_end"] == 0 and result["frames"] == 1


# --------------------------------------------------------------------------- #
# 工具注册
# --------------------------------------------------------------------------- #
def test_tool_is_registered_with_a_schema():
    registry = ToolRegistry()
    register_timing_tools(registry, fps=24)
    assert ESTIMATE_DURATION in registry.names()
    spec = registry.get(ESTIMATE_DURATION)
    assert spec.parameters == ESTIMATE_DURATION_PARAMETERS


def test_tool_handler_answers_through_the_registry():
    registry = ToolRegistry()
    register_timing_tools(registry, fps=24)
    result = registry.execute(ESTIMATE_DURATION,
                              {"dialogues": [{"text": "你还在听吗。"}]})
    assert result.ok and "建议镜头时长" in result.content


def test_tool_rejects_bad_argument_types():
    registry = ToolRegistry()
    register_timing_tools(registry)
    bad = registry.execute(ESTIMATE_DURATION, {"fps": "快"})
    assert not bad.ok and "参数校验失败" in bad.content
