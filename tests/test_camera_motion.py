"""§10.2 运镜解算的纯计算测试。"""

from __future__ import annotations

import math

import pytest

from block_director.cinema.camera_motion import (
    DEFAULT_SAMPLES,
    MOVEMENT_TYPES,
    describe,
    movement_samples,
)

CAMERA = (0.0, -4.0, 1.0)
TARGET = (0.0, 0.0, 1.0)


def test_documented_movement_vocabulary():
    assert set(MOVEMENT_TYPES) == {
        "dolly_in", "dolly_out", "track_left", "track_right",
        "crane_up", "crane_down",
        "pan_left", "pan_right", "tilt_up", "tilt_down"}
    assert describe("dolly_in") == "推近" and describe("pan_left") == "左摇"


def test_samples_span_the_frame_range():
    samples = movement_samples(CAMERA, TARGET, "dolly_in", 1.0, 10, 20)
    assert len(samples) == DEFAULT_SAMPLES
    assert [s["frame"] for s in samples] == [10, 15, 20]


def test_first_sample_is_the_starting_state():
    samples = movement_samples(CAMERA, TARGET, "track_right", 2.0, 1, 24)
    assert samples[0]["position"] == pytest.approx(CAMERA)
    assert samples[0]["look_at"] == pytest.approx(TARGET)


# --------------------------------------------------------------------------- #
# 平移类
# --------------------------------------------------------------------------- #
def test_dolly_in_moves_toward_the_target_by_the_requested_distance():
    samples = movement_samples(CAMERA, TARGET, "dolly_in", 1.5, 1, 24)
    end = samples[-1]["position"]
    start_distance = math.dist(CAMERA, TARGET)
    assert math.dist(end, TARGET) == pytest.approx(start_distance - 1.5, abs=1e-6)
    assert samples[-1]["look_at"] == pytest.approx(TARGET)


def test_dolly_out_moves_away():
    samples = movement_samples(CAMERA, TARGET, "dolly_out", 1.0, 1, 24)
    assert math.dist(samples[-1]["position"], TARGET) == pytest.approx(
        math.dist(CAMERA, TARGET) + 1.0, abs=1e-6)


def test_track_moves_sideways_without_changing_the_look_point():
    samples = movement_samples(CAMERA, TARGET, "track_right", 2.0, 1, 24)
    end = samples[-1]["position"]
    # 相机在 -Y 看向 +Y，右手边是 +X（右手系、Z 向上）
    assert end[0] == pytest.approx(2.0, abs=1e-6)
    assert end[1] == pytest.approx(CAMERA[1])
    assert samples[-1]["look_at"] == pytest.approx(TARGET)


def test_crane_raises_the_camera():
    samples = movement_samples(CAMERA, TARGET, "crane_up", 0.8, 1, 24)
    assert samples[-1]["position"][2] == pytest.approx(CAMERA[2] + 0.8)
    assert samples[-1]["position"][0] == pytest.approx(CAMERA[0])


# --------------------------------------------------------------------------- #
# 旋转类
# --------------------------------------------------------------------------- #
def test_pan_keeps_the_camera_and_swings_the_look_point():
    samples = movement_samples(CAMERA, TARGET, "pan_right", 30.0, 1, 24)
    assert samples[-1]["position"] == pytest.approx(CAMERA)
    swung = samples[-1]["look_at"]
    assert swung != pytest.approx(TARGET)
    # 仍落在以相机为心、半径 = 原距离的球面上
    assert math.dist(swung, CAMERA) == pytest.approx(
        math.dist(TARGET, CAMERA), abs=1e-6)


def test_pan_direction_is_opposite_for_left_and_right():
    left = movement_samples(CAMERA, TARGET, "pan_left", 30.0, 1, 24)[-1]
    right = movement_samples(CAMERA, TARGET, "pan_right", 30.0, 1, 24)[-1]
    assert left["look_at"][0] * right["look_at"][0] <= 0 or (
        left["look_at"] != right["look_at"])


def test_tilt_changes_height_of_the_look_point():
    up = movement_samples(CAMERA, TARGET, "tilt_up", 20.0, 1, 24)[-1]["look_at"]
    down = movement_samples(CAMERA, TARGET, "tilt_down", 20.0, 1, 24)[-1]["look_at"]
    assert up[2] > TARGET[2] > down[2]


def test_zero_amount_is_a_no_op():
    samples = movement_samples(CAMERA, TARGET, "pan_left", 0.0, 1, 24)
    assert samples[-1]["look_at"] == pytest.approx(TARGET)


# --------------------------------------------------------------------------- #
# 边界
# --------------------------------------------------------------------------- #
def test_unknown_movement_is_refused_with_the_vocabulary():
    with pytest.raises(ValueError) as excinfo:
        movement_samples(CAMERA, TARGET, "zoom", 1.0, 1, 10)
    assert "zoom" in str(excinfo.value) and "dolly_in" in str(excinfo.value)


def test_non_positive_frame_range_is_refused():
    with pytest.raises(ValueError):
        movement_samples(CAMERA, TARGET, "dolly_in", 1.0, 10, 10)


def test_two_samples_is_still_a_valid_motion():
    samples = movement_samples(CAMERA, TARGET, "dolly_in", 1.0, 1, 10, samples=2)
    assert [s["frame"] for s in samples] == [1, 10]
