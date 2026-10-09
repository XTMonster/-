"""§10.1 / P0-2 站位与取景参考系的纯计算测试。

这些断言锁的是**行为**，不是写法：只检查 "atan2 返回什么" 没有意义，
必须证明"镜头最终从哪里拍、角色最终朝哪边看"。
"""

from __future__ import annotations

import math

import pytest

from block_director.cinema.framing import side_vector
from block_director.cinema.station import (
    camera_direction,
    right_of,
    subject_frame,
)

ALL_SIDES = ("front", "back", "left", "right", "front_left", "front_right",
             "back_left", "back_right", "over_shoulder")

#: 米迦尔在左、伊恩在右，两人**相对而立**（这正是"互相看向对方"的语义）。
FACING_EACH_OTHER = [
    ("char_001", (-0.9, 0.0, 0.0), (1.0, 0.0, 0.0)),
    ("char_002", (0.9, 0.0, 0.0), (-1.0, 0.0, 0.0)),
]

#: 两人并排同向（v1.2 的默认站位）。
PARALLEL = [
    ("char_001", (-0.75, 0.0, 0.0), (0.0, 1.0, 0.0)),
    ("char_002", (0.75, 0.0, 0.0), (0.0, 1.0, 0.0)),
]


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


# --------------------------------------------------------------------------- #
# 单人镜头：语义必须与 v1.2 完全一致（这是行为不变的保证）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("side", ALL_SIDES)
def test_single_subject_keeps_v12_semantics(side):
    frame = subject_frame([("char_001", (0.0, 0.0, 0.0), (0.0, 1.0, 0.0))],
                          shot_type="CU")
    assert not frame.has_axis
    assert camera_direction(frame, side) == \
        pytest.approx(side_vector((0.0, 1.0, 0.0), side))


def test_single_subject_anchor_is_the_character_itself():
    frame = subject_frame([("char_001", (-0.75, 0.4, 0.0), (0.0, 1.0, 0.0))],
                          shot_type="MS")
    assert frame.anchor == (-0.75, 0.4, 0.0)
    assert frame.focus_id == "char_001"
    assert not frame.group


def test_no_characters_falls_back_to_origin():
    frame = subject_frame([], shot_type="LS")
    assert frame.anchor == (0.0, 0.0, 0.0)
    assert frame.facing == (0.0, 1.0, 0.0)
    assert not frame.has_axis


# --------------------------------------------------------------------------- #
# 双人镜头：P0-2 的核心——机位必须离开轴线
# --------------------------------------------------------------------------- #
def test_two_subjects_build_an_axis():
    frame = subject_frame(FACING_EACH_OTHER, shot_type="MLS")
    assert frame.has_axis
    assert frame.axis_start == (-0.9, 0.0)
    assert frame.axis_end == (0.9, 0.0)
    assert frame.axis_start_id == "char_001"
    assert frame.axis_end_id == "char_002"


def test_front_of_a_two_shot_is_perpendicular_to_the_axis():
    """front 必须是轴线**法线**，否则相机落在轴线上、R001 必报。"""
    frame = subject_frame(FACING_EACH_OTHER, shot_type="MLS")
    axis = frame.axis_direction()
    direction = camera_direction(frame, "front")
    assert _dot(direction, axis) == pytest.approx(0.0, abs=1e-9)
    assert abs(_dot(right_of(axis), direction)) == pytest.approx(1.0)


def test_old_semantics_would_have_put_the_camera_on_the_axis():
    """回归护栏：证明旧写法确实会把机位放到轴线上。

    旧写法 = 锚点取两人中点 + 方向取**第一个角色的朝向** + ``side="front"``。
    两人相对而立时它的方向与轴线平行 —— 相机因此落在轴线上。
    这条断言存在的意义是：谁把锚点语义改回去，这里立刻红。
    """
    frame = subject_frame(FACING_EACH_OTHER, shot_type="MLS")
    axis = frame.axis_direction()
    old_direction = side_vector(FACING_EACH_OTHER[0][2], "front")
    assert abs(_dot(old_direction, axis)) == pytest.approx(1.0)

    new_direction = camera_direction(frame, "front")
    assert _dot(new_direction, axis) == pytest.approx(0.0, abs=1e-9)


def test_two_shot_sides_rotate_around_the_axis():
    frame = subject_frame(FACING_EACH_OTHER, shot_type="MLS")
    axis = frame.axis_direction()
    front = camera_direction(frame, "front")
    left = camera_direction(frame, "left")
    right = camera_direction(frame, "right")
    # left / right 朝轴线两端偏，且互不相同
    assert _dot(left, axis) < 0.0
    assert _dot(right, axis) > 0.0
    # 三个方向都在"正面半平面"里（与 front 同号）
    for direction in (left, right):
        assert _dot(direction, front) > 0.0


def test_two_shot_over_shoulder_stays_near_the_axis():
    frame = subject_frame(FACING_EACH_OTHER, shot_type="OTS")
    axis = frame.axis_direction()
    direction = camera_direction(frame, "over_shoulder")
    # 过肩是"近轴"的：主轴分量远大于法线分量，但又不是正好落在轴上
    assert abs(_dot(direction, axis)) > abs(_dot(direction, right_of(axis)))


def test_group_shot_anchors_on_the_group_center():
    frame = subject_frame(PARALLEL, shot_type="MLS")
    assert frame.group
    assert frame.anchor == pytest.approx((0.0, 0.0, 0.0))


def test_tight_shot_anchors_on_the_focus_subject():
    """特写对准说话人，而不是两人重心——否则特写会框到两个人中间。"""
    frame = subject_frame(PARALLEL, shot_type="CU", speaker_id="char_002")
    assert not frame.group
    assert frame.focus_id == "char_002"
    assert frame.anchor == pytest.approx((0.75, 0.0, 0.0))


def test_two_person_mcu_anchors_on_the_pair_center():
    """2026-10-09 用户裁决：双人 MCU 锚点改取两人质心（v1.6 G2 #3/#4）。

    两人沿视线前后站时，对准说话人会让近者把远者挡掉、framing 实测/预期≈1.75；
    组中心锚点让两人同深、左右对称。单人 MCU 与 CU/ECU 仍对准说话人。
    """
    frame = subject_frame(FACING_EACH_OTHER, shot_type="MCU",
                          speaker_id="char_001")
    assert frame.group
    assert frame.focus_id == "char_001"
    assert frame.anchor == pytest.approx((0.0, 0.0, 0.0))
    assert frame.facing == pytest.approx((1.0, 0.0, 0.0))


def test_two_shot_normal_points_to_the_focus_subject_front():
    """两人并排同向时，法线要选"朝焦点主体正面"的那一侧。

    这正是 Golden 夹具的情形（两人都朝 +Y）：front 应当保持 +Y，
    与 v1.2 的结果一致，历史产物不会因此漂移。
    """
    frame = subject_frame(PARALLEL, shot_type="MLS")
    assert camera_direction(frame, "front") == pytest.approx((0.0, 1.0))


def test_coincident_characters_do_not_produce_nan():
    frame = subject_frame([("a", (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)),
                           ("b", (1.0, 1.0, 0.0), (0.0, 1.0, 0.0))],
                          shot_type="MLS")
    direction = camera_direction(frame, "front")
    assert math.isfinite(direction[0]) and math.isfinite(direction[1])
    assert math.hypot(*direction) == pytest.approx(1.0)


def test_unknown_side_falls_back_to_front():
    frame = subject_frame(FACING_EACH_OTHER, shot_type="MLS")
    assert camera_direction(frame, "no_such_side") == \
        pytest.approx(camera_direction(frame, "front"))


def test_direction_is_always_a_unit_vector():
    for entries in (FACING_EACH_OTHER, PARALLEL):
        frame = subject_frame(entries, shot_type="MS")
        for side in ALL_SIDES:
            dx, dy = camera_direction(frame, side)
            assert math.hypot(dx, dy) == pytest.approx(1.0, abs=1e-9)


# --------------------------------------------------------------------------- #
# 单主体镜头落在整场轴线上：必须扭开，否则相机站在搭档的位置上
# --------------------------------------------------------------------------- #
def _single_subject_facing_along_the_axis():
    """乙站在 +X、面朝 -X（正对搭档），轴线沿 X。"""
    return subject_frame([("char_002", (0.9, 0.0, 0.0), (-1.0, 0.0, 0.0))],
                         shot_type="MCU")


def test_single_subject_on_the_axis_is_turned_off_axis():
    frame = _single_subject_facing_along_the_axis()
    direction = camera_direction(frame, "front", axis_dir=(1.0, 0.0),
                                 axis_side=-1)
    cos = abs(direction[0] * 1.0 + direction[1] * 0.0)
    assert cos == pytest.approx(math.cos(math.radians(30.0)), abs=1e-6)


def test_the_off_axis_turn_follows_the_established_side():
    """扭开的方向必须落在已确立的一侧，否则修好遮挡却换来越轴。"""
    frame = _single_subject_facing_along_the_axis()
    for axis_side in (1, -1):
        direction = camera_direction(frame, "front", axis_dir=(1.0, 0.0),
                                     axis_side=axis_side)
        cross = 1.0 * direction[1] - 0.0 * direction[0]
        assert (cross > 0) == (axis_side > 0)


def test_single_subject_perpendicular_to_the_axis_is_left_alone():
    """主体朝 +Y、轴线沿 X 时，正面机位本来就垂直于轴线，不该被动。"""
    frame = subject_frame([("char_001", (0.0, 0.0, 0.0), (0.0, 1.0, 0.0))],
                          shot_type="CU")
    assert camera_direction(frame, "front", axis_dir=(1.0, 0.0),
                            axis_side=1) == pytest.approx((0.0, 1.0))


def test_without_an_axis_nothing_changes():
    """没有整场轴线时保持 v1.2 语义（这是行为不变的保证）。"""
    frame = _single_subject_facing_along_the_axis()
    assert camera_direction(frame, "front") == \
        pytest.approx(side_vector((-1.0, 0.0, 0.0), "front"))
