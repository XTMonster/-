"""G2 判据 #8：无歧义看门狗（``normalize_draft_watchdog``）的纯函数回归。

r6 真跑（run 12dadce87acc）暴露：模型写 ``look_at.params.angle_deg``
（``angle_deg ≡ yaw_deg`` 的等价键），看门狗只弹规范键 ``yaw_deg``/
``pitch_deg``，随后 ``normalize_action_params`` 把 ``angle_deg`` 翻回
``yaw_deg``，``target`` 与角度再次同框被判域拒绝。这里钉住：
target 优先要连同等价键一起丢，且等价键表从 ``ACTION_PARAM_ALIASES``
单一真源推导、不手抄。
"""

from __future__ import annotations

from block_director.layer5_orchestrator.editor import normalize_draft_watchdog
from block_director.motion.model import (
    action_param_problems,
    normalize_action_params,
)


def test_look_at_target_drops_alias_angle_deg():
    args = {"actions": [{"action_type": "look_at",
                         "params": {"target": {"character": "char_001"},
                                    "angle_deg": -20}}]}
    params = normalize_draft_watchdog(args)["actions"][0]["params"]
    assert "angle_deg" not in params
    assert "yaw_deg" not in params
    assert params == {"target": {"character": "char_001"}}


def test_look_at_target_drops_canonical_angle_keys():
    args = {"actions": [{"action_type": "look_at",
                         "params": {"target": "char_001",
                                    "yaw_deg": 12, "pitch_deg": -4}}]}
    params = normalize_draft_watchdog(args)["actions"][0]["params"]
    assert params == {"target": "char_001"}


def test_watchdog_then_normalize_leaves_no_look_at_problems():
    for raw in (
        {"target": {"point": [6, 0, 0.8]}, "angle_deg": -20},
        {"target": "char_001", "yaw_deg": 5, "pitch_deg": 0},
    ):
        args = {"actions": [{"action_type": "look_at",
                             "params": dict(raw)}]}
        item = normalize_draft_watchdog(args)["actions"][0]
        norm = normalize_action_params("look_at", item["params"])
        assert action_param_problems("look_at", norm) == []


def test_look_at_without_target_keeps_angle():
    args = {"actions": [{"action_type": "look_at",
                         "params": {"angle_deg": 12}}]}
    params = normalize_draft_watchdog(args)["actions"][0]["params"]
    assert params == {"angle_deg": 12}


def test_other_actions_keep_angle_keys():
    args = {"actions": [{"action_type": "turn_head",
                         "params": {"angle_deg": 16, "angle": 16,
                                    "degrees": 16}}]}
    params = normalize_draft_watchdog(args)["actions"][0]["params"]
    assert params["angle_deg"] == 16
    assert params["angle"] == 16 and params["degrees"] == 16


def test_watchdog_does_not_mutate_input():
    args = {"actions": [{"action_type": "look_at",
                         "params": {"target": "char_001", "angle_deg": 3}}],
            "camera": {"side": "neutral"}}
    normalize_draft_watchdog(args)
    assert args["actions"][0]["params"] == {"target": "char_001",
                                            "angle_deg": 3}
    assert args["camera"]["side"] == "neutral"


def test_start_frame_zero_and_neutral_side_normalised():
    out = normalize_draft_watchdog({
        "actions": [{"action_type": "walk_to",
                     "start_frame": 0, "end_frame": 0,
                     "params": {"target_position": [0, 0, 1]}}],
        "camera": {"side": "neutral"}})
    action = out["actions"][0]
    assert action["start_frame"] == 1
    assert action["end_frame"] == 1
    assert out["camera"]["side"] == ""
