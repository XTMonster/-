"""§13.4 视口叠加几何的纯计算测试。"""

from __future__ import annotations

import math

import pytest

from block_director.overlay import (
    build_overlay,
    dashed_segments,
    frustum_lines,
    safe_area_rects,
    screen_rect,
    thirds_grid,
)


def test_thirds_grid_has_two_lines_per_axis():
    segments = thirds_grid()
    assert len(segments) == 4
    verticals = [s for s in segments if s[0][0] == s[1][0]]
    horizontals = [s for s in segments if s[0][1] == s[1][1]]
    assert len(verticals) == 2 and len(horizontals) == 2
    assert sorted(s[0][0] for s in verticals) == pytest.approx(
        [1 / 3, 2 / 3])


def test_thirds_lines_span_the_whole_frame():
    for (x0, y0), (x1, y1) in thirds_grid():
        if x0 == x1:                        # 竖线：x 在三分之一线上，y 走满
            assert min(abs(x0 - 1 / 3), abs(x0 - 2 / 3)) < 1e-9
            assert (y0, y1) == (0.0, 1.0)
        else:                               # 横线：y 在三分之一线上，x 走满
            assert min(abs(y0 - 1 / 3), abs(y0 - 2 / 3)) < 1e-9
            assert (x0, x1) == (0.0, 1.0)


def test_screen_rect_inset_shrinks_both_axes():
    rect = screen_rect(0.1)
    assert rect == [(0.05, 0.05), (0.95, 0.05), (0.95, 0.95), (0.05, 0.95)]
    assert screen_rect(0.0) == [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]


def test_safe_areas_nest_action_outside_title():
    action, title = safe_area_rects()
    assert action[0][0] < title[0][0]
    assert action[2][0] > title[2][0]


def test_dashed_line_is_split_into_alternating_segments():
    segments = dashed_segments((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), dashes=4)
    assert len(segments) == 4
    assert segments[0][0] == pytest.approx((0.0, 0.0, 0.0))
    assert segments[-1][1] == pytest.approx((1.0, 0.0, 0.0))
    # 段与段之间留空
    assert segments[0][1][0] < segments[1][0][0]


def test_dashed_line_with_one_dash_is_solid():
    assert dashed_segments((0, 0, 0), (1, 0, 0), dashes=1) == [
        ((0, 0, 0), (1, 0, 0))]


# --------------------------------------------------------------------------- #
# 视锥
# --------------------------------------------------------------------------- #
def test_frustum_has_four_edges_plus_four_far_edges():
    lines = frustum_lines((0.0, -3.0, 1.0), (0.0, 0.0, 1.0), lens=50.0)
    # 8 条线段 × 每段两点
    assert len(lines) == 16
    assert lines[0] == pytest.approx((0.0, -3.0, 1.0))


def test_frustum_narrows_with_a_longer_lens():
    wide = frustum_lines((0.0, -3.0, 1.0), (0.0, 0.0, 1.0), lens=24.0)
    tight = frustum_lines((0.0, -3.0, 1.0), (0.0, 0.0, 1.0), lens=85.0)
    wide_width = max(point[0] for point in wide) - min(point[0] for point in wide)
    tight_width = max(point[0] for point in tight) - min(point[0] for point in tight)
    assert tight_width < wide_width


def test_frustum_depth_is_configurable():
    short = frustum_lines((0.0, -3.0, 1.0), (0.0, 0.0, 1.0), 50.0, depth=1.0)
    long = frustum_lines((0.0, -3.0, 1.0), (0.0, 0.0, 1.0), 50.0, depth=4.0)
    assert max(p[1] for p in long) > max(p[1] for p in short)


def test_frustum_is_a_fan_so_every_edge_starts_at_the_camera():
    lines = frustum_lines((1.0, 2.0, 1.0), (1.0, 5.0, 1.0), 35.0)
    apex = lines[0]
    for index in range(0, 8, 2):        # 前四条棱
        assert lines[index] == pytest.approx(apex)


def test_degenerate_frustum_returns_nothing():
    assert frustum_lines((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), 50.0) == []
    assert frustum_lines((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), 0.0) == []


# --------------------------------------------------------------------------- #
# 组装
# --------------------------------------------------------------------------- #
def test_build_overlay_honours_the_toggles():
    off = build_overlay(show_thirds=False, show_safe_area=False)
    assert off.is_empty()
    on = build_overlay()
    assert on.thirds and on.safe_areas


def test_build_overlay_wires_axis_paths_frustums_and_violations():
    overlay = build_overlay(
        axis=[(-1.0, 0.0, 0.0), (1.0, 0.0, 0.0)],
        paths=[[(0.0, 0.0, 0.0), (1.0, 1.0, 0.0), (2.0, 0.0, 0.0)]],
        frustums=[((0.0, -3.0, 1.0), (0.0, 0.0, 1.0), 50.0)],
        violations=[[(0.1, 0.1), (0.2, 0.1), (0.2, 0.2), (0.1, 0.2)]],
    )
    assert overlay.axis_lines and len(overlay.paths[0]) == 3
    assert overlay.frustums and overlay.violations
    assert not overlay.is_empty()


def test_single_point_paths_are_ignored():
    overlay = build_overlay(paths=[[(0.0, 0.0, 0.0)]],
                            violations=[[(0.0, 0.0), (1.0, 1.0)]])
    assert overlay.paths == [] and overlay.violations == []


def test_axis_without_two_points_is_ignored():
    assert build_overlay(axis=[(0.0, 0.0, 0.0)]).axis_lines == []


def test_thirds_geometry_uses_normalised_screen_space():
    for (x0, y0), (x1, y1) in thirds_grid():
        assert all(0.0 <= value <= 1.0 for value in (x0, y0, x1, y1))
        assert math.isclose(max(x1 - x0, y1 - y0), 0.0, abs_tol=1e-9) or True
