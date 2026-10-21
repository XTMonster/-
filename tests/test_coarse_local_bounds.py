"""粗排局部主体框（coarse_local_bounds）与细排几何同源契约。

粗排 preview 只有纯体块，细排/ruler 用真实角色网格。两把尺子必须共享
同一份冻结几何（``anchor.profile`` / ``hand_offset`` / ``HAND_BOX_SIZE``），
否则特写镜在粗排被整身框压到 55-58 分、细排 gate（>80）永远过不了。
本测试钉住粗排局部框的数值推导，防止粗排侧另起炉灶写一套数字。
"""

from __future__ import annotations

from block_director.cinema.anchor import (
    DEFAULT_PROFILE,
    HAND_BOX_SIZE,
    HAND_PROXY_FORWARD,
    HAND_PROXY_SIDE,
    coarse_local_bounds,
    hand_offset,
)


def test_hand_box_uses_same_offset_and_window_as_detail():
    """手部框中心 = 体块水平中心 + facing 旋转的 hand_offset（same side=1.0）。

    细排 ``_anchored_hand_box`` 取 ``body_pivot.matrix_world @
    hand_offset(side=1.0)``；粗排没有 body_pivot，用体块中心 + 同一偏移。
    """
    low = (1.0, 2.0, 0.0)
    high = (1.5, 2.5, 1.7)
    facing = (0.0, 1.0, 0.0)
    bounds = coarse_local_bounds(
        kind="character", part="hand", low=low, high=high, facing=facing)
    assert bounds is not None
    center = ((bounds[0][0] + bounds[1][0]) / 2.0,
              (bounds[0][1] + bounds[1][1]) / 2.0,
              (bounds[0][2] + bounds[1][2]) / 2.0)
    off = hand_offset(DEFAULT_PROFILE, side=1.0)
    body_center = ((low[0] + high[0]) / 2.0,
                   (low[1] + high[1]) / 2.0,
                   (low[2] + high[2]) / 2.0)
    #: facing=(0,1,0)：右手在局部 +X 侧 = 世界 +X 侧（x 偏移 +HAND_PROXY_SIDE）
    assert abs(center[0] - (body_center[0] + HAND_PROXY_SIDE)) < 1e-9
    assert abs(center[1] - (body_center[1] + HAND_PROXY_FORWARD)) < 1e-9
    assert abs(center[2] - (low[2] + DEFAULT_PROFILE.chest_z)) < 1e-9
    assert abs(abs(bounds[1][0] - bounds[0][0]) - HAND_BOX_SIZE) < 1e-9


def test_hand_box_rotates_with_facing():
    """facing=(-1,0,0) 时手部在世界 -X 前方、+Y 侧（逆时针旋转）。"""
    low = (0.0, 0.0, 0.0)
    high = (0.5, 0.5, 1.7)
    bounds = coarse_local_bounds(
        kind="character", part="hand", low=low, high=high,
        facing=(-1.0, 0.0, 0.0))
    assert bounds is not None
    center = ((bounds[0][0] + bounds[1][0]) / 2.0,
              (bounds[0][1] + bounds[1][1]) / 2.0,
              (bounds[0][2] + bounds[1][2]) / 2.0)
    off = hand_offset(DEFAULT_PROFILE, side=1.0)
    body_center = (0.25, 0.25, 0.85)
    #: facing=(-1,0,0)：前方 = -X，右手侧 = +Y（facing 顺时针 90 度）
    assert abs(center[0] - (body_center[0] - off[1])) < 1e-9
    assert abs(center[1] - (body_center[1] + off[0])) < 1e-9


def test_face_box_uses_frozen_head_center():
    """脸框中心 z = leg_h + torso_h + head_r（冻结几何，与细排同源）。"""
    low = (0.0, 0.0, 0.0)
    high = (0.5, 0.5, 1.7)
    bounds = coarse_local_bounds(
        kind="character", part="face", low=low, high=high)
    assert bounds is not None
    center_z = (bounds[0][2] + bounds[1][2]) / 2.0
    expected_z = (DEFAULT_PROFILE.leg_h + DEFAULT_PROFILE.torso_h
                  + DEFAULT_PROFILE.head_r)
    assert abs(center_z - expected_z) < 1e-9
    assert abs(bounds[1][2] - bounds[0][2]) == DEFAULT_PROFILE.head_d


def test_flat_prop_uses_dominant_cube():
    """扁平道具（银币）投影框取支配维度立方（细排同款口径）。"""
    low = (0.0, 0.0, 0.9)
    high = (0.2, 0.2, 0.93)
    bounds = coarse_local_bounds(
        kind="prop", part="none", low=low, high=high)
    assert bounds is not None
    extent = (bounds[1][0] - bounds[0][0],
              bounds[1][1] - bounds[0][1],
              bounds[1][2] - bounds[0][2])
    assert abs(extent[0] - 0.2) < 1e-9
    assert abs(extent[1] - 0.2) < 1e-9
    assert abs(extent[2] - 0.2) < 1e-9


def test_missing_or_invalid_inputs_return_none():
    """缺体块/不可推导时返回 None（退回整身框，不脑补）。"""
    assert coarse_local_bounds(
        kind="character", part="none", low=(0, 0, 0), high=(1, 1, 1)) is None
    assert coarse_local_bounds(
        kind="character", part="hand", low=None, high=None) is None
    assert coarse_local_bounds(
        kind="prop", part="none", low=(0, 0), high=(1, 1)) is None
