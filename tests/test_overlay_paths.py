"""G1：轨迹刻度与着色纯函数（v1.7 阶段 G，TDD §10）。"""

from __future__ import annotations

import pytest

from block_director.contracts.cast import DEFAULT_COLORS
from block_director.overlay.geometry import (
    ColoredPolyline,
    colored_paths,
    path_ticks,
)


def test_ticks_straight_line():
    """直线轨迹按帧间隔取刻度：x ∈ {0, 2.5, 5, 7.5, 10}（手算期望）。"""
    ticks = path_ticks([(0.0, 0.0, 0.0), (10.0, 0.0, 0.0)],
                       total_frames=48, interval_frames=12)
    xs = [point[0] for point in ticks]
    assert xs == pytest.approx([0.0, 2.5, 5.0, 7.5, 10.0])
    assert all(point[1:] == (0.0, 0.0) for point in ticks)


def test_ticks_empty_and_single():
    """空路径/单点不抛异常、原样返回。"""
    assert path_ticks([], total_frames=48) == []
    point = (3.0, 4.0, 5.0)
    assert path_ticks([point], total_frames=48) == [point]


def test_ticks_polyline():
    """L 形折线手算对拍：总弧长 20，5 个刻度等距落点。"""
    points = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 10.0, 0.0)]
    ticks = path_ticks(points, total_frames=48, interval_frames=12)
    assert ticks == pytest.approx([
        (0.0, 0.0, 0.0), (5.0, 0.0, 0.0), (10.0, 0.0, 0.0),
        (10.0, 5.0, 0.0), (10.0, 10.0, 0.0),
    ])


def test_ticks_appends_endpoint_when_not_on_interval():
    """total 不能被 interval 整除时，终点必须补进刻度。"""
    points = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0)]
    ticks = path_ticks(points, total_frames=50, interval_frames=12)
    # k=0..4 → t ∈ {0,12,24,36,48} → x ∈ {0,2.4,4.8,7.2,9.6}；终点 x=10 补进
    assert [t[0] for t in ticks] == pytest.approx(
        [0.0, 2.4, 4.8, 7.2, 9.6, 10.0])


def test_ticks_zero_frames_returns_start():
    """帧域退化为单点（total=0）时只取起点。"""
    assert path_ticks([(0.0, 0.0, 0.0), (10.0, 0.0, 0.0)],
                      total_frames=0) == [(0.0, 0.0, 0.0)]


def test_ticks_rejects_degenerate_frame_inputs():
    """负帧域 / 非正间隔属于调用方错误，显式报错而非静默出坏结果。"""
    points = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0)]
    with pytest.raises(ValueError):
        path_ticks(points, total_frames=-1)
    with pytest.raises(ValueError):
        path_ticks(points, total_frames=48, interval_frames=0)
    with pytest.raises(ValueError):
        path_ticks(points, total_frames=48, interval_frames=-12)


def test_colors_known_and_fallback():
    """已知角色用其 color；未知角色按出现顺序回落调色板且互不相同。"""
    paths = {
        "hero": [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)],
        "npc_a": [(0.0, 1.0, 0.0), (1.0, 1.0, 0.0)],
        "npc_b": [(0.0, 2.0, 0.0), (1.0, 2.0, 0.0)],
    }
    colors = {"hero": "#AABBCC"}
    result = colored_paths(paths, colors)
    assert len(result) == 3
    assert all(isinstance(polyline, ColoredPolyline) for polyline in result)
    hero, npc_a, npc_b = result
    assert hero.color == "#AABBCC"
    assert hero.points == paths["hero"]
    assert npc_a.color == DEFAULT_COLORS[0]
    assert npc_b.color == DEFAULT_COLORS[1]
    assert npc_a.color != npc_b.color
    assert npc_a.points == paths["npc_a"]
    assert npc_b.points == paths["npc_b"]
