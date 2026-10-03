"""单人镜头也必须待在**已确立的轴侧**（v1.6）。

现场（`docs/evidence/20261003_chunked_long9/`，64 镜真跑，DeepSeek sidecar）：
审计里 **61 条 R001（180° 轴线）错误、命中 21/64 镜，全部是单人镜头**，同一跑
里两人镜头一条都没有。可复算的取证命令是 `work/_axis_audit.py`（逐镜打印
`camera.side` 与 R001 文案）。

翻实现：`camera.side` 是**相对被摄主体朝向**的（§10.1/§10.5 的
`framing.side_vector`），而"两人相对而立"时两个角色的朝向相反——同一个
`front_right` 落在**世界轴线的两侧**。R001 的判据却是世界轴侧
（`Axis.established_side`）。两人镜头在 v1.5 已经改成按轴线法线解算
（`test_axis_side_wins_over_facing.py`），单人镜头这条路当时没接上，
于是模型写"同侧机位、不越轴"、引擎却把一半的单人镜头摆到另一侧。

本文件钉三件事：轴侧在单人镜头里被遵守（两种符号）、**镜像保持与轴线的夹角**
（不是把机位夹回轴线上）、以及"镜像会把正面变背面"时**不静默改拍法**。
"""

from __future__ import annotations

import math
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.cinema.axis import Axis  # noqa: E402
from block_director.cinema.station import camera_direction, subject_frame  # noqa: E402

ALL_SIDES = ("front", "front_left", "front_right", "left", "right",
             "back", "back_left", "back_right")


def _single_facing_along_the_axis():
    """乙站在 +X、面朝 −X（正对搭档米迦尔），整场轴线沿 +X。"""
    return subject_frame([("char_002", (0.9, 0.0, 0.0), (-1.0, 0.0, 0.0))],
                         shot_type="MCU")


def _side_of(frame, direction):
    """机位方向落在轴线的哪一侧（与 `Axis.side_of` 同一判据）。"""
    axis = Axis(start=(-0.9, 0.0), end=(0.9, 0.0))
    probe = (frame.anchor[0] + direction[0] * 3.0,
             frame.anchor[1] + direction[1] * 3.0,
             frame.anchor[2])
    return axis.side_of(probe)


@pytest.mark.parametrize("wanted", (-1, 1))
@pytest.mark.parametrize("side", ALL_SIDES)
def test_a_single_shot_lands_on_the_established_side(side, wanted):
    frame = _single_facing_along_the_axis()
    direction = camera_direction(frame, side, axis_dir=(1.0, 0.0),
                                 axis_side=wanted)
    assert _side_of(frame, direction) == wanted, (
        f"side={side} axis_side={wanted} 时机位落在 "
        f"{_side_of(frame, direction)} 侧（方向 {direction}）")


def test_the_mirror_keeps_the_angle_to_the_axis():
    """修正必须是**关于轴线镜像**，不是把机位夹回轴线上（那会变成中性镜头）。"""
    frame = _single_facing_along_the_axis()
    cos_before = abs(camera_direction(frame, "front_left", axis_dir=(1.0, 0.0),
                                      axis_side=-1)[0])
    direction = camera_direction(frame, "front_left", axis_dir=(1.0, 0.0),
                                 axis_side=1)
    cos_after = abs(direction[0])
    assert cos_after == pytest.approx(cos_before, abs=1e-9)
    assert cos_after == pytest.approx(math.cos(math.radians(45.0)), abs=1e-6)
    assert _side_of(frame, direction) == 1


def test_the_mirror_is_reported_rather_than_silent():
    frame = _single_facing_along_the_axis()
    notes: list = []
    camera_direction(frame, "front_left", axis_dir=(1.0, 0.0), axis_side=1,
                     notes=notes)
    assert notes and "镜像" in notes[0]


def test_a_request_that_would_flip_front_to_back_is_not_silently_rewritten():
    """主体朝 +Y、轴线沿 X、已确立轴侧是 −Y：正面机位不可能同时满足。

    镜像会把"正面"变成"背面"——那等于把这一镜换掉。此时必须原样返回并留一条
    说明，让 R001 如实报错（而不是在解算器里把冲突吞掉）。
    """
    frame = subject_frame([("char_001", (0.0, 0.0, 0.0), (0.0, 1.0, 0.0))],
                          shot_type="CU")
    notes: list = []
    direction = camera_direction(frame, "front", axis_dir=(1.0, 0.0),
                                 axis_side=-1, notes=notes)
    assert direction == pytest.approx((0.0, 1.0))
    assert notes and "背拍" in notes[0]


def test_without_an_established_side_nothing_is_mirrored():
    """对照：`axis_side == 0`（还没有轴线基准）时**不做镜像**。

    （"front" 落在轴线上时被 `_off_axis` 扭开 30° 是 v1.3 就有的既存行为，
    与本次改动无关：它保证相机不站在搭档的位置上。）
    """
    frame = _single_facing_along_the_axis()
    notes: list = []
    for side in ("front_left", "front_right", "left", "right",
                 "back_left", "back_right"):
        assert camera_direction(frame, side, axis_dir=(1.0, 0.0), axis_side=0,
                                notes=notes) == \
            camera_direction(frame, side), side
    assert notes == []


def test_without_an_axis_at_all_nothing_changes():
    """没有整场轴线时保持 v1.2 语义（单人镜头的行为不变保证）。"""
    frame = _single_facing_along_the_axis()
    for side in ALL_SIDES:
        assert camera_direction(frame, side) == \
            camera_direction(frame, side, axis_dir=None, axis_side=0)
