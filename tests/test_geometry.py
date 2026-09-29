"""§1.4 坐标约定相关的纯计算工具测试。"""

from __future__ import annotations

import math

import pytest

from block_director.utils.geometry import (
    facing_to_rotation_z,
    hex_to_rgb,
    rotation_z_to_facing,
)


def _rotate_z(theta: float, vector):
    """绕 Z 旋转 theta（右手系），返回 (x, y, z)。"""
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    x, y, z = vector
    return (x * cos_t - y * sin_t, x * sin_t + y * cos_t, z)


def test_hex_to_rgb_full_form():
    r, g, b = hex_to_rgb("#FF6B6B")
    assert r == pytest.approx(1.0)
    assert g == pytest.approx(0.4196, abs=1e-4)
    assert b == pytest.approx(0.4196, abs=1e-4)


def test_hex_to_rgb_short_form_expands():
    assert hex_to_rgb("#fff") == (1.0, 1.0, 1.0)
    assert hex_to_rgb("#000") == (0.0, 0.0, 0.0)


@pytest.mark.parametrize("bad", ["", "#12", "not-a-color", "#GGGGGG", "#12345"])
def test_hex_to_rgb_falls_back_to_white(bad):
    assert hex_to_rgb(bad) == (1.0, 1.0, 1.0)


def test_facing_default_is_zero():
    """§1.4：角色默认面朝 +Y，对应绕 Z 旋转 0。"""
    assert facing_to_rotation_z((0.0, 1.0, 0.0)) == pytest.approx(0.0)


def test_facing_right_is_quarter_turn():
    """面朝 +X（画右）需要绕 Z 转 **-π/2**，不是 +π/2。

    角色正面是局部 +Y；绕 Z 旋转 θ 后世界朝向为 ``(-sin θ, cos θ)``。
    取 θ = +π/2 会得到 ``(-1, 0)``（面朝画左），这正是 v1.2 的镜像缺陷。
    """
    assert facing_to_rotation_z((1.0, 0.0, 0.0)) == pytest.approx(-math.pi / 2)


def test_world_facing_matches_the_requested_vector():
    """回归护栏：把旋转角代回世界坐标，必须还原成请求的朝向向量。

    这是本缺陷的真实判据——只断言 `atan2` 的返回值形式没有意义，
    必须证明"旋转之后角色的正面确实指向请求方向"。
    """
    for facing in ((0.0, 1.0, 0.0), (1.0, 0.0, 0.0), (-1.0, 0.0, 0.0),
                   (0.0, -1.0, 0.0), (0.5, 0.86, 0.0), (-0.6, 0.8, 0.0)):
        theta = facing_to_rotation_z(facing)
        world = _rotate_z(theta, (0.0, 1.0, 0.0))
        norm = math.hypot(facing[0], facing[1])
        assert world[0] == pytest.approx(facing[0] / norm, abs=1e-9)
        assert world[1] == pytest.approx(facing[1] / norm, abs=1e-9)


def test_rotation_z_to_facing_is_the_inverse():
    """写入与回读必须互为逆运算；只修一侧会让朝向被读成镜像。"""
    for facing in ((0.0, 1.0, 0.0), (1.0, 0.0, 0.0), (0.0, -1.0, 0.0),
                   (0.5, 0.86, 0.0)):
        theta = facing_to_rotation_z(facing)
        back = rotation_z_to_facing(theta)
        norm = math.hypot(facing[0], facing[1])
        assert back[0] == pytest.approx(facing[0] / norm, abs=1e-6)
        assert back[1] == pytest.approx(facing[1] / norm, abs=1e-6)
        assert back[2] == 0.0


def test_rotation_z_to_quarter_turn_faces_minus_x():
    """绕 Z 转 +π/2 的正面朝向是 **-X**——这条钉死读写两侧的符号约定。"""
    x, y, z = rotation_z_to_facing(math.pi / 2)
    assert x == pytest.approx(-1.0)
    assert y == pytest.approx(0.0)
    assert z == 0.0


def test_facing_back_is_half_turn():
    assert abs(facing_to_rotation_z((0.0, -1.0, 0.0))) == pytest.approx(math.pi)


def test_degenerate_facing_is_safe():
    assert facing_to_rotation_z((0.0, 0.0, 0.0)) == 0.0
    assert facing_to_rotation_z((0.0,)) == 0.0
