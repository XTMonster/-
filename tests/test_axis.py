"""§10.3 轴线与 R001 / R010 的纯计算测试。"""

from __future__ import annotations

import pytest

from block_director.cinema.axis import (
    SIDE_NEGATIVE,
    SIDE_POSITIVE,
    SIDE_UNKNOWN,
    axis_for_speakers,
    axis_from_points,
    axis_violation,
    camera_angle_deg,
    establish_axis,
    shot_size_changed,
    shot_size_index,
    thirty_degree_violation,
)

# 两人沿 X 轴相邻而坐：小明在左(-1,0)，小红在右(1,0)
CHARACTERS = [((-1.0, 0.0, 0.0), "小明"), ((1.0, 0.0, 0.0), "小红")]


def base_axis():
    return axis_for_speakers(CHARACTERS)


def test_axis_is_built_from_the_two_speakers():
    axis = base_axis()
    assert axis is not None
    assert axis.start == (-1.0, 0.0) and axis.end == (1.0, 0.0)
    assert axis.left_label == "小明" and axis.right_label == "小红"


def test_axis_needs_two_speakers():
    assert axis_for_speakers(CHARACTERS[:1]) is None
    assert axis_for_speakers([]) is None


def test_side_of_uses_cross_product_sign():
    axis = base_axis()
    assert axis.side_of((0.0, 5.0)) == SIDE_POSITIVE     # 轴线 +Y 一侧
    assert axis.side_of((0.0, -5.0)) == SIDE_NEGATIVE    # 轴线 -Y 一侧
    assert axis.side_of((0.5, 0.0)) == SIDE_UNKNOWN      # 落在轴线上


def test_establish_axis_uses_first_camera():
    axis = establish_axis(base_axis(), (0.0, 5.0))
    assert axis.established_side == SIDE_POSITIVE
    assert axis.is_correct_side((2.0, 3.0))
    assert not axis.is_correct_side((2.0, -3.0))


def test_violation_is_reported_only_when_crossing():
    axis = establish_axis(base_axis(), (0.0, 5.0))
    assert axis_violation(axis, (1.0, 4.0)) is None
    message = axis_violation(axis, (1.0, -4.0))
    assert message and "180° 轴线" in message


def test_camera_on_the_axis_itself_is_flagged():
    axis = establish_axis(base_axis(), (0.0, 5.0))
    message = axis_violation(axis, (0.5, 0.0))
    assert message and "轴线上" in message


# --------------------------------------------------------------------------- #
# R010：30° 规则
# --------------------------------------------------------------------------- #
def test_shot_size_index_order():
    assert shot_size_index("ECU") < shot_size_index("MS") < shot_size_index("ELS")
    assert shot_size_index("???") == -1


def test_shot_size_changed():
    assert shot_size_changed("MS", "LS") is True
    assert shot_size_changed("MS", "MCU") is True
    assert shot_size_changed("MS", "MS") is False
    assert shot_size_changed("MS", "???") is False


def test_camera_angle_between_two_positions():
    assert camera_angle_deg((0, 5), (0, -5), (0, 0)) == pytest.approx(180.0)
    assert camera_angle_deg((5, 0), (0, 5), (0, 0)) == pytest.approx(90.0)
    assert camera_angle_deg((5, 0), (5, 0), (0, 0)) == pytest.approx(0.0)


def test_small_angle_change_without_shot_change_is_flagged():
    previous = (5.0, 0.0)
    current = (5.0, 0.6)          # 与前一机位夹角很小
    message = thirty_degree_violation(previous, current, (0, 0), "MS", "MS")
    assert message and "跳切" in message


def test_small_angle_with_shot_change_is_allowed():
    previous = (5.0, 0.0)
    current = (5.0, 0.6)
    assert thirty_degree_violation(previous, current, (0, 0), "MS", "CU") is None


def test_large_angle_is_allowed_even_with_same_shot():
    assert thirty_degree_violation((5, 0), (0, 5), (0, 0), "MS", "MS") is None
