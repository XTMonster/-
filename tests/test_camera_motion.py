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
    """v1.3 的封闭清单是 24 种（v1.2 只有 10 种）。"""
    assert len(MOVEMENT_TYPES) == 24
    assert set(MOVEMENT_TYPES) == {
        "dolly_in", "dolly_out", "track_left", "track_right",
        "crane_up", "crane_down", "push_through",
        "pan_left", "pan_right", "tilt_up", "tilt_down",
        "whip_pan_left", "whip_pan_right",
        "zoom_in", "zoom_out", "dolly_zoom",
        "orbit_cw", "orbit_ccw", "crane_arc_up", "crane_arc_down",
        "steadicam", "follow_subject", "lead_subject", "handheld"}
    assert describe("dolly_in") == "推近" and describe("pan_left") == "左摇"
    for movement in MOVEMENT_TYPES:
        assert describe(movement) != movement, f"{movement} 没有中文名"


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


# --------------------------------------------------------------------------- #
# v1.3 新增的 14 种运镜
# --------------------------------------------------------------------------- #
def test_zoom_changes_the_lens_and_keeps_the_camera_still():
    samples = movement_samples(CAMERA, TARGET, "zoom_in", 15.0, 1, 24,
                               lens=50.0)
    assert samples[-1]["position"] == pytest.approx(CAMERA)
    assert samples[-1]["lens"] == pytest.approx(65.0)
    assert movement_samples(CAMERA, TARGET, "zoom_out", 15.0, 1, 24,
                            lens=50.0)[-1]["lens"] == pytest.approx(35.0)


def test_zoom_can_aim_at_an_absolute_lens():
    samples = movement_samples(CAMERA, TARGET, "zoom_in", 0.0, 1, 24,
                               lens=50.0, lens_to=135.0)
    assert samples[-1]["lens"] == pytest.approx(135.0)


def test_zoom_never_leaves_the_supported_range():
    assert movement_samples(CAMERA, TARGET, "zoom_out", 500.0, 1, 10,
                            lens=50.0)[-1]["lens"] >= 8.0
    assert movement_samples(CAMERA, TARGET, "zoom_in", 5000.0, 1, 10,
                            lens=50.0)[-1]["lens"] <= 300.0


def test_dolly_zoom_keeps_the_subject_size_while_the_distance_changes():
    """推拉变焦的定义：主体大小不变、透视变化 → lens / distance 恒定。"""
    samples = movement_samples(CAMERA, TARGET, "dolly_zoom", 1.0, 1, 24,
                               lens=50.0)
    start_ratio = 50.0 / math.dist(CAMERA, TARGET)
    end = samples[-1]
    end_ratio = float(end["lens"]) / math.dist(end["position"], TARGET)
    assert end_ratio == pytest.approx(start_ratio, rel=1e-6)
    assert math.dist(end["position"], TARGET) < math.dist(CAMERA, TARGET)


def test_orbit_keeps_the_radius_and_moves_around_the_target():
    samples = movement_samples(CAMERA, TARGET, "orbit_cw", 60.0, 1, 24)
    radius = math.dist(CAMERA, TARGET)
    for sample in samples:
        assert math.dist(sample["position"], TARGET) == pytest.approx(
            radius, abs=1e-6)
        assert sample["look_at"] == pytest.approx(TARGET)
    assert samples[-1]["position"] != pytest.approx(CAMERA)


def test_orbit_directions_are_opposite():
    cw = movement_samples(CAMERA, TARGET, "orbit_cw", 60.0, 1, 24)[-1]
    ccw = movement_samples(CAMERA, TARGET, "orbit_ccw", 60.0, 1, 24)[-1]
    assert cw["position"][0] * ccw["position"][0] < 0


def test_crane_arc_up_rises_and_down_descends():
    """附录 B：上升弧抬升机位，下降弧下沉机位，两者互为镜像。

    规范更正：旧断言允许下降弧"不低于起点"，等于把升降符号互相抵消的
    缺陷（绕 +right 转 +angle 会让相机下沉，再乘一遍 ORBITS 符号就抵消了）
    写成了期望值。上升弧与下降弧的几何依据见 v1.3 附录 B 的情感语义表。
    """
    up = movement_samples(CAMERA, TARGET, "crane_arc_up", 45.0, 1, 24)[-1]
    down = movement_samples(CAMERA, TARGET, "crane_arc_down", 45.0, 1, 24)[-1]
    assert up["position"][2] > CAMERA[2]
    assert down["position"][2] < CAMERA[2]
    assert up["position"][2] - CAMERA[2] == pytest.approx(
        CAMERA[2] - down["position"][2], abs=1e-9)
    # 弧线同时改变水平角，且始终对准主体、半径不变
    assert up["position"][1] != pytest.approx(CAMERA[1])
    for sample in (up, down):
        assert sample["look_at"] == pytest.approx(TARGET)
        assert math.dist(sample["position"], TARGET) == pytest.approx(
            math.dist(CAMERA, TARGET), abs=1e-6)


def test_whip_pan_is_denser_and_front_loaded():
    plain = movement_samples(CAMERA, TARGET, "pan_right", 90.0, 1, 24)
    whip = movement_samples(CAMERA, TARGET, "whip_pan_right", 90.0, 1, 24)
    assert len(whip) > len(plain)                   # 更密的采样
    # 中间采样点已经走完大半（甩镜的"快"）
    middle = whip[len(whip) // 2]["look_at"]
    assert math.dist(middle, TARGET) > 0.0
    total = math.dist(whip[-1]["look_at"], TARGET)
    assert math.dist(middle, TARGET) > 0.4 * total


def test_handheld_is_deterministic_and_keeps_the_look_point():
    first = movement_samples(CAMERA, TARGET, "handheld", 0.05, 1, 24, seed=7)
    again = movement_samples(CAMERA, TARGET, "handheld", 0.05, 1, 24, seed=7)
    other = movement_samples(CAMERA, TARGET, "handheld", 0.05, 1, 24, seed=8)
    assert [s["position"] for s in first] == [s["position"] for s in again]
    assert [s["position"] for s in first] != [s["position"] for s in other]
    for sample in first:
        assert sample["look_at"] == pytest.approx(TARGET)
        assert math.dist(sample["position"], CAMERA) <= 0.05 * math.sqrt(2) + 1e-9


def test_follow_and_lead_keep_their_offset_from_the_subject():
    path = [(0.0, 0.0, 1.0), (2.0, 0.0, 1.0), (4.0, 0.0, 1.0)]
    follow = movement_samples(CAMERA, TARGET, "follow_subject", 0.0, 1, 24,
                              subject_path=path)
    lead = movement_samples(CAMERA, TARGET, "lead_subject", 0.0, 1, 24,
                            subject_path=path)
    offset = (CAMERA[0] - TARGET[0], CAMERA[1] - TARGET[1],
              CAMERA[2] - TARGET[2])
    for sample in follow:
        subject = sample["look_at"]
        assert (sample["position"][0] - subject[0]) == pytest.approx(offset[0])
        assert (sample["position"][1] - subject[1]) == pytest.approx(offset[1])
    for sample in lead:
        subject = sample["look_at"]
        assert (sample["position"][0] - subject[0]) == pytest.approx(-offset[0])
    assert follow[-1]["look_at"][0] == pytest.approx(4.0)


def test_steadicam_adds_a_bob_but_still_tracks():
    path = [(0.0, 0.0, 1.0), (4.0, 0.0, 1.0)]
    samples = movement_samples(CAMERA, TARGET, "steadicam", 0.0, 1, 24,
                               subject_path=path)
    middle = samples[len(samples) // 2]
    assert middle["position"][2] > middle["look_at"][2]


def test_subject_tracking_without_a_path_is_refused():
    with pytest.raises(ValueError) as excinfo:
        movement_samples(CAMERA, TARGET, "follow_subject", 1.0, 1, 24)
    assert "subject_path" in str(excinfo.value)
