"""§10.1 / §10.5 / §10.6 取景解算的纯计算测试。"""

from __future__ import annotations

import math

import pytest

from block_director.cinema.framing import (
    ASPECT_16_9,
    SHOT_FRAME,
    SENSOR_WIDTH,
    required_distance,
    side_vector,
    solve_framing,
    vertical_fov,
)


def test_shot_frame_table_is_monotonic():
    """景别越紧，画面高度越小——这是 §10.5 原表做不到的。"""
    order = ["ECU", "CU", "MCU", "MS", "MLS", "LS", "ELS"]
    heights = [SHOT_FRAME[key].frame_height for key in order]
    assert heights == sorted(heights), f"景别顺序不单调: {heights}"


def test_vertical_fov_shrinks_with_longer_lens():
    assert vertical_fov(85.0) < vertical_fov(50.0) < vertical_fov(24.0)


def test_vertical_fov_matches_hand_calculation():
    lens = 50.0
    expected = 2 * math.atan((SENSOR_WIDTH / ASPECT_16_9) / (2 * lens))
    assert vertical_fov(lens) == pytest.approx(expected)


def test_required_distance_grows_with_lens():
    """同一景别换长焦，必须站得更远才装得下。"""
    assert required_distance(1.6, 85.0) > required_distance(1.6, 50.0)


def test_required_distance_grows_with_frame_height():
    assert required_distance(3.0, 50.0) > required_distance(1.0, 50.0)


def test_closer_shot_puts_camera_nearer():
    cu = solve_framing((0, 0, 0), (0, 1, 0), "CU")
    ls = solve_framing((0, 0, 0), (0, 1, 0), "LS")
    assert cu.distance < ls.distance


# --------------------------------------------------------------------------- #
# 机位方向相对被摄主体朝向
# --------------------------------------------------------------------------- #
def test_front_side_sits_in_front_of_subject():
    result = solve_framing((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), "MS", side="front")
    assert result.position[1] > 0          # 角色朝 +Y，正面机位应在 +Y
    assert abs(result.position[0]) < 1e-6


def test_left_and_right_are_relative_to_facing():
    left = solve_framing((0, 0, 0), (0, 1, 0), "MS", side="left")
    right = solve_framing((0, 0, 0), (0, 1, 0), "MS", side="right")
    assert left.position[0] < 0 < right.position[0]


def test_rotating_subject_rotates_camera():
    """角色转 90° 后，"正面"机位也要跟着转 90°。"""
    front = solve_framing((0, 0, 0), (0, 1, 0), "MS", side="front")
    rotated = solve_framing((0, 0, 0), (1, 0, 0), "MS", side="front")
    assert rotated.position[0] > 0
    assert abs(rotated.position[1]) < 1e-6
    assert rotated.distance == pytest.approx(front.distance)


def test_degenerate_facing_falls_back_to_default():
    dx, dy = side_vector((0.0, 0.0, 0.0), "front")
    assert (dx, dy) == pytest.approx((0.0, 1.0))


def test_unknown_side_falls_back_to_front():
    assert side_vector((0, 1, 0), "sideways") == pytest.approx((0.0, 1.0))


# --------------------------------------------------------------------------- #
# 房间约束与特例
# --------------------------------------------------------------------------- #
def test_room_clamp_keeps_camera_inside():
    result = solve_framing((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), "ELS",
                           side="front", room=(-10.0, 10.0, -10.0, 0.0))
    assert result.clamped is True
    assert result.position[1] <= 0.0 - 0.5 + 1e-9
    assert result.warnings and "夹回" in result.warnings[0]


def test_no_room_no_clamp():
    result = solve_framing((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), "ELS", side="front")
    assert result.clamped is False and not result.warnings


def test_pov_sits_at_the_eyes():
    result = solve_framing((1.0, 2.0, 0.0), (0.0, 1.0, 0.0), "POV")
    assert result.position == pytest.approx((1.0, 2.0, 1.10))
    assert result.target[1] > result.position[1]     # 朝角色面朝方向看出去


def test_unknown_shot_type_warns_and_falls_back():
    result = solve_framing((0, 0, 0), (0, 1, 0), "XXXXL")
    assert result.shot_type == "MS"
    assert result.warnings


def test_explicit_lens_overrides_default():
    result = solve_framing((0, 0, 0), (0, 1, 0), "MS", lens=24.0)
    assert result.lens == 24.0
    assert result.distance == pytest.approx(required_distance(1.6, 24.0))
