"""默认站位（v1.3 诉求 2）。

v1.2 把所有角色沿 X 轴排开、一律面朝 +Y——两个正在对话的人并排朝前、
谁也不看谁，与"互相看向对方"的剧本语义正好相反。
"""

from __future__ import annotations

import math

import pytest

from block_director.contracts.cast import (
    DEFAULT_SPACING,
    OPPOSITE_SPACING,
    CastMember,
    default_station,
)
from block_director.contracts.plan import Plan


def _facing_of(member: CastMember):
    return tuple(round(float(v), 3) for v in member.initial_facing)


def test_single_character_stands_at_the_origin_facing_forward():
    (location, facing), = default_station(1)
    assert location == (0.0, 0.0, 0.0)
    assert facing == (0.0, 1.0, 0.0)


def test_two_characters_face_each_other():
    """核心断言：两人默认相对而立。"""
    left, right = default_station(2)
    assert left[0][0] == pytest.approx(-OPPOSITE_SPACING / 2.0)
    assert right[0][0] == pytest.approx(OPPOSITE_SPACING / 2.0)
    assert left[1] == (1.0, 0.0, 0.0)       # 左边的人朝 +X（朝右）
    assert right[1] == (-1.0, 0.0, 0.0)     # 右边的人朝 -X（朝左）

    # 两人之间的连线（轴线）与双方朝向共线——这是对峙的定义
    axis = (right[0][0] - left[0][0], right[0][1] - left[0][1])
    for _location, facing in (left, right):
        cross = axis[0] * facing[1] - axis[1] * facing[0]
        assert abs(cross) == pytest.approx(0.0)


def test_more_than_two_face_the_group_centre():
    stations = default_station(4)
    assert len(stations) == 4
    assert stations[0][0][0] == pytest.approx(-1.5 * DEFAULT_SPACING)
    assert stations[0][1][0] > 0            # 最左边的人朝 +X
    assert stations[-1][1][0] < 0           # 最右边的人朝 -X


def test_no_characters_is_empty():
    assert default_station(0) == []
    assert default_station(-3) == []


def test_from_plan_uses_the_default_station():
    plan = Plan.from_dict({
        "scene_heading": "INT. 码头 - 午后",
        "shots": [{"shot_id": "shot_001", "order": 1, "intent": "对峙",
                   "shot_type": "MLS", "duration_frames": 72,
                   "characters": ["char_001", "char_002"]}]})
    from block_director.contracts.cast import SceneSpec

    spec = SceneSpec.from_plan(plan)
    first, second = spec.cast
    assert _facing_of(first) == (1.0, 0.0, 0.0)
    assert _facing_of(second) == (-1.0, 0.0, 0.0)
    # 距离落在"社交距离"区间，镜头里读得出对峙
    gap = abs(second.initial_location[0] - first.initial_location[0])
    assert gap == pytest.approx(OPPOSITE_SPACING)


def test_from_plan_reverses_the_facing_direction_on_the_x_axis():
    """朝向必须与 ``facing_to_rotation_z`` 的约定一致（P0-1 的镜像修复）。"""
    from block_director.utils.geometry import facing_to_rotation_z

    plan = Plan.from_dict({
        "scene_heading": "INT. 房间 - 日",
        "shots": [{"shot_id": "shot_001", "order": 1, "intent": "x",
                   "shot_type": "MS", "duration_frames": 48,
                   "characters": ["a", "b"]}]})
    from block_director.contracts.cast import SceneSpec

    left = SceneSpec.from_plan(plan).cast[0]
    theta = facing_to_rotation_z(left.initial_facing)
    # 世界朝向 = (-sin θ, cos θ)：左边的人必须真的朝 +X
    assert -math.sin(theta) == pytest.approx(1.0)
    assert math.cos(theta) == pytest.approx(0.0, abs=1e-9)
