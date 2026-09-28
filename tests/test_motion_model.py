"""§9.6 / §9.7 动作库与混合的纯计算测试。"""

from __future__ import annotations

import math

import pytest

from block_director.motion.model import (
    BLEND_FRAMES,
    CH_BODY_ROT_X,
    CH_HEAD_ROT_X,
    CH_HEAD_ROT_Z,
    CH_LEG_L,
    CH_LEG_R,
    CH_ROOT_LOC,
    CH_ROOT_ROT_Z,
    LAYER_BASE,
    LAYER_BODY,
    LAYER_HEAD,
    LAYER_LEGS,
    LAYER_OF,
    ActionRequest,
    check_conflicts,
    compose,
    expand,
)


def walk(start=1, end=48, target=(2.0, 0.0, 0.0)):
    return ActionRequest("walk_to", start, end,
                         {"from": (0.0, 0.0, 0.0), "target_position": target,
                          "speed": "walk"})


def layers_of(request):
    return {spec.layer for spec in expand(request)}


def channels_of(request):
    return {ch for spec in expand(request) for ch in spec.channels}


# --------------------------------------------------------------------------- #
# 层归属与展开
# --------------------------------------------------------------------------- #
def test_layer_table_matches_document():
    assert LAYER_OF["walk_to"] == LAYER_BASE
    assert LAYER_OF["turn_head"] == LAYER_HEAD
    assert LAYER_OF["fall_down"] == LAYER_BODY
    assert LAYER_OF["sit"] == LAYER_BODY
    assert LAYER_OF["jump"] == LAYER_BASE


def test_walk_expands_to_base_and_legs():
    assert layers_of(walk()) == {LAYER_BASE, LAYER_LEGS}
    assert channels_of(walk()) == {CH_ROOT_LOC, CH_ROOT_ROT_Z, CH_LEG_L, CH_LEG_R}


def test_run_adds_body_lean():
    run = ActionRequest("run_to", 1, 24,
                        {"from": (0, 0, 0), "target_position": (3, 0, 0)})
    assert layers_of(run) == {LAYER_BASE, LAYER_LEGS, LAYER_BODY}
    assert CH_BODY_ROT_X in channels_of(run)


def test_unknown_action_raises():
    with pytest.raises(ValueError):
        expand(ActionRequest("backflip", 1, 10))


def test_layer_channel_ownership_is_disjoint():
    """分层之所以能并行，是因为各层写的通道互不重叠。"""
    owners = {}
    for kind in ("walk_to", "run_to", "turn_body", "jump", "body_tilt",
                 "fall_down", "sit", "stand", "turn_head", "look_at",
                 "nod", "shake_head"):
        for spec in expand(ActionRequest(kind, 1, 12)):
            for channel in spec.channels:
                assert channel not in owners or owners[channel] == spec.layer, (
                    f"{channel} 同时被 {owners.get(channel)} 和 {spec.layer} 写入")
                owners[channel] = spec.layer


# --------------------------------------------------------------------------- #
# 姿态数值
# --------------------------------------------------------------------------- #
def test_walk_moves_root_and_faces_target():
    trace = compose([walk(1, 48, (2.0, 0.0, 0.0))])
    assert trace[1][CH_ROOT_LOC][0] == pytest.approx(0.0)
    assert trace[48][CH_ROOT_LOC][0] == pytest.approx(2.0)
    # 朝 +X 走 → 绕 Z 旋转 +90°
    assert trace[48][CH_ROOT_ROT_Z] == pytest.approx(math.pi / 2)


def test_leg_swing_is_antisymmetric():
    trace = compose([walk(1, 48)])
    for frame in (12, 24, 36):
        assert trace[frame][CH_LEG_L] == pytest.approx(-trace[frame][CH_LEG_R])
    assert max(abs(trace[f][CH_LEG_L]) for f in range(1, 49)) > math.radians(15)


def test_head_yaw_is_clamped_to_90_degrees():
    """§9.3：头部水平旋转 ±90°。"""
    request = ActionRequest("turn_head", 1, 24, {"angle_deg": 200.0})
    trace = compose([request])
    assert trace[24][CH_HEAD_ROT_Z] == pytest.approx(math.radians(90.0))


def test_nod_only_touches_head_pitch():
    trace = compose([ActionRequest("nod", 1, 24, {"cycles": 2})])
    keys = set().union(*(pose.keys() for pose in trace.values()))
    assert keys == {CH_HEAD_ROT_X}
    assert max(abs(trace[f][CH_HEAD_ROT_X]) for f in trace) <= math.radians(10.5)


def test_shake_head_uses_yaw_channel():
    trace = compose([ActionRequest("shake_head", 1, 24)])
    keys = set().union(*(pose.keys() for pose in trace.values()))
    assert keys == {CH_HEAD_ROT_Z}


def test_fall_down_reaches_ninety_degrees():
    trace = compose([ActionRequest("fall_down", 1, 72)])
    assert trace[72][CH_BODY_ROT_X] == pytest.approx(math.pi / 2, abs=1e-6)
    # 三阶段：中途应小于终值
    assert trace[30][CH_BODY_ROT_X] < trace[72][CH_BODY_ROT_X]


def test_sit_then_stand_returns_to_ground():
    """先坐后站必须精确回到地面——这正是"接管冻结"语义要保证的。"""
    trace = compose([ActionRequest("sit", 1, 24, {"drop": 0.2}),
                     ActionRequest("stand", 25, 48, {"drop": 0.2})])
    assert trace[24][CH_ROOT_LOC][2] == pytest.approx(-0.2, abs=1e-6)
    assert trace[48][CH_ROOT_LOC][2] == pytest.approx(0.0, abs=1e-4)


def test_jump_is_a_parabola():
    trace = compose([ActionRequest("jump", 1, 24, {"height": 0.3})])
    heights = [trace[f][CH_ROOT_LOC][2] for f in range(1, 25)]
    assert min(heights) == pytest.approx(0.0, abs=1e-6)
    assert max(heights) == pytest.approx(0.3, abs=1e-2)
    assert heights.index(max(heights)) in range(10, 15)


# --------------------------------------------------------------------------- #
# 跨层合成
# --------------------------------------------------------------------------- #
def test_layers_compose_together():
    """走位（base+legs）与点头（head）可同时存在，互不覆盖。"""
    trace = compose([walk(1, 48), ActionRequest("nod", 1, 48)])
    frame = trace[24]
    assert CH_ROOT_LOC in frame and CH_LEG_L in frame and CH_HEAD_ROT_X in frame


def test_same_layer_actions_accumulate_without_resetting():
    """转身 90° 再接转身 90° 应得到 180°，且交接处连续。"""
    first = ActionRequest("turn_body", 1, 30, {"angle_deg": 90.0})
    second = ActionRequest("turn_body", 31, 60, {"angle_deg": 90.0})
    trace = compose([first, second])
    assert trace[30][CH_ROOT_ROT_Z] == pytest.approx(math.radians(90.0))
    assert trace[31][CH_ROOT_ROT_Z] == pytest.approx(math.radians(90.0), abs=1e-3)
    assert trace[60][CH_ROOT_ROT_Z] == pytest.approx(math.radians(180.0))
    values = [trace[f][CH_ROOT_ROT_Z] for f in range(1, 61)]
    assert all(b >= a - 1e-6 for a, b in zip(values, values[1:])), "转身过程不得回退"


# --------------------------------------------------------------------------- #
# 冲突仲裁（§9.7）
# --------------------------------------------------------------------------- #
def test_walk_plus_fall_is_rejected_when_overlapping():
    problems = check_conflicts([walk(1, 48), ActionRequest("fall_down", 20, 60)])
    assert problems and "语义冲突" in problems[0]


def test_walk_then_fall_is_allowed():
    """§9.7 的补救方式就是"先结束移动"——串行执行合法。"""
    assert check_conflicts([walk(1, 48),
                            ActionRequest("fall_down", 49, 90)]) == []


def test_walk_plus_jump_is_rejected_when_overlapping():
    assert check_conflicts([walk(1, 48), ActionRequest("jump", 10, 20)])


def test_walk_then_sit_is_allowed():
    assert check_conflicts([walk(1, 48), ActionRequest("sit", 49, 72)]) == []


def test_look_at_combines_with_walk():
    assert check_conflicts([walk(1, 48), ActionRequest("look_at", 1, 48)]) == []


def test_overlapping_same_layer_actions_are_reported():
    problems = check_conflicts([walk(1, 48), ActionRequest("turn_body", 20, 60)])
    assert any("同层动作必须串行" in p for p in problems)


def test_sequential_same_layer_actions_are_allowed():
    assert check_conflicts([ActionRequest("turn_body", 1, 30),
                            ActionRequest("turn_body", 31, 60)]) == []


def test_tail_blend_window_keeps_pose_after_end():
    """动作结束后仍有 BLEND_FRAMES 帧保持姿态，供下一个动作平滑接管。"""
    trace = compose([ActionRequest("turn_body", 1, 24, {"angle_deg": 90.0})])
    assert max(trace) == 24 + BLEND_FRAMES
    assert trace[24 + BLEND_FRAMES][CH_ROOT_ROT_Z] == pytest.approx(math.radians(90.0))
