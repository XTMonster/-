"""§1.4 坐标约定相关的纯计算工具测试。"""

from __future__ import annotations

import math

import pytest

from block_director.utils.geometry import facing_to_rotation_z, hex_to_rgb


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
    assert facing_to_rotation_z((1.0, 0.0, 0.0)) == pytest.approx(math.pi / 2)


def test_facing_back_is_half_turn():
    assert abs(facing_to_rotation_z((0.0, -1.0, 0.0))) == pytest.approx(math.pi)


def test_degenerate_facing_is_safe():
    assert facing_to_rotation_z((0.0, 0.0, 0.0)) == 0.0
    assert facing_to_rotation_z((0.0,)) == 0.0
