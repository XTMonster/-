"""§17.1 Catmull-Rom 平滑 / §17.2 RDP 简化的纯计算测试。"""

from __future__ import annotations

import math

import pytest

from block_director.motion.path import (
    RDP_EPSILON,
    SAMPLES_PER_SEGMENT,
    catmull_rom,
    facing_along,
    path_length,
    rdp,
    simplify_and_smooth,
    tangents,
)


def straight(count: int = 20) -> list:
    return [(index * 0.1, 0.0, 0.0) for index in range(count)]


def test_documented_defaults():
    assert SAMPLES_PER_SEGMENT == 10
    assert RDP_EPSILON == 0.05


# --------------------------------------------------------------------------- #
# Catmull-Rom
# --------------------------------------------------------------------------- #
def test_curve_passes_through_the_first_and_last_sample():
    points = [(0.0, 0.0, 0.0), (1.0, 1.0, 0.0), (2.0, 0.0, 0.0)]
    curve = catmull_rom(points)
    assert curve[0] == pytest.approx(points[0])
    assert curve[-1] == pytest.approx(points[-1])


def test_curve_hits_the_original_vertices():
    points = [(0.0, 0.0, 0.0), (1.0, 1.0, 0.0), (2.0, 0.0, 0.0)]
    curve = catmull_rom(points, samples_per_segment=10)
    # 每段的第 0 个采样点就是原顶点
    assert curve[0] == pytest.approx(points[0])
    assert curve[10] == pytest.approx(points[1])
    assert curve[20] == pytest.approx(points[2])


def test_curve_has_the_documented_sample_count():
    curve = catmull_rom(straight(5), samples_per_segment=10)
    assert len(curve) == (5 - 1) * 10 + 1


def test_collinear_points_stay_on_the_line():
    curve = catmull_rom(straight(4))
    assert all(point[1] == pytest.approx(0.0, abs=1e-9) for point in curve)
    assert all(point[2] == pytest.approx(0.0, abs=1e-9) for point in curve)


def test_short_and_empty_inputs_are_returned_as_is():
    assert catmull_rom([]) == []
    assert catmull_rom([(1.0, 2.0, 0.0)]) == [(1.0, 2.0, 0.0)]


def test_zero_samples_per_segment_falls_back_to_the_input():
    points = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]
    assert catmull_rom(points, samples_per_segment=0) == points


# --------------------------------------------------------------------------- #
# RDP
# --------------------------------------------------------------------------- #
def test_collinear_points_collapse_to_the_endpoints():
    simplified = rdp(straight(30))
    assert len(simplified) == 2
    assert simplified[0] == pytest.approx((0.0, 0.0, 0.0))
    assert simplified[-1] == pytest.approx((2.9, 0.0, 0.0))


def test_a_spike_survives_simplification():
    points = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.6, 0.0),
              (3.0, 0.0, 0.0), (4.0, 0.0, 0.0)]
    simplified = rdp(points, epsilon=0.05)
    assert (2.0, 0.6, 0.0) in simplified
    assert simplified[0] == points[0] and simplified[-1] == points[-1]


def test_small_noise_is_removed():
    points = [(0.0, 0.0, 0.0), (1.0, 0.01, 0.0), (2.0, -0.01, 0.0),
              (3.0, 0.02, 0.0), (4.0, 0.0, 0.0)]
    assert len(rdp(points, epsilon=0.05)) == 2
    assert len(rdp(points, epsilon=0.001)) > 2


def test_rdp_keeps_short_inputs():
    two = [(0.0, 0.0, 0.0), (1.0, 1.0, 0.0)]
    assert rdp(two) == two
    assert rdp([]) == []


def test_rdp_is_dimension_agnostic():
    points = [(0.0, 0.0), (1.0, 0.4), (2.0, 0.0)]
    assert rdp(points, epsilon=0.05) == [(0.0, 0.0), (1.0, 0.4), (2.0, 0.0)]


# --------------------------------------------------------------------------- #
# 组合与派生量
# --------------------------------------------------------------------------- #
def test_simplify_then_smooth_is_shorter_than_smoothing_raw_input():
    noisy = [(index * 0.1, 0.01 * (-1) ** index, 0.0) for index in range(40)]
    combined = simplify_and_smooth(noisy)
    assert len(combined) < len(catmull_rom(noisy))
    assert combined[0] == pytest.approx(noisy[0])
    assert combined[-1] == pytest.approx(noisy[-1])


def test_tangents_are_unit_vectors_pointing_along_the_path():
    points = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)]
    for tangent in tangents(points):
        assert math.dist(tangent, (0.0, 0.0, 0.0)) == pytest.approx(1.0)
        assert tangent[0] == pytest.approx(1.0)


def test_facing_follows_the_tangent():
    points = [(0.0, 0.0, 0.0), (0.0, 1.0, 0.0)]      # 朝 +Y 走
    facings = facing_along(points)
    assert facings[0] == pytest.approx((0.0, 1.0))


def test_facing_on_a_diagonal_is_normalised():
    facings = facing_along([(0.0, 0.0, 0.0), (1.0, 1.0, 0.0)])
    assert math.hypot(*facings[0]) == pytest.approx(1.0)
    assert facings[0][0] == pytest.approx(facings[0][1])


def test_facing_of_a_degenerate_path_falls_back_to_forward():
    assert facing_along([(1.0, 1.0, 0.0), (1.0, 1.0, 0.0)])[0] == (0.0, 1.0)


def test_path_length_matches_a_known_distance():
    assert path_length([(0.0, 0.0, 0.0), (3.0, 4.0, 0.0)]) == pytest.approx(5.0)
    assert path_length([(0.0, 0.0, 0.0)]) == 0.0
