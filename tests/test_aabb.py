"""§17.7 AABB 相交的纯计算测试（R002 的基础）。"""

from __future__ import annotations

import pytest

from block_director.utils.aabb import AABB, union


def test_from_center_size():
    box = AABB.from_center_size((1.0, 2.0, 3.0), (2.0, 4.0, 6.0))
    assert box.minimum == (0.0, 0.0, 0.0)
    assert box.maximum == (2.0, 4.0, 6.0)
    assert box.center == (1.0, 2.0, 3.0)
    assert box.size == (2.0, 4.0, 6.0)
    assert box.volume == pytest.approx(48.0)


def test_overlap_requires_all_three_axes():
    base = AABB.from_center_size((0, 0, 0), (2, 2, 2))
    same = AABB.from_center_size((1, 0, 0), (2, 2, 2))
    apart_in_z = AABB.from_center_size((0, 0, 5), (2, 2, 2))
    assert base.overlaps(same) is True
    assert base.overlaps(apart_in_z) is False


def test_touching_faces_do_not_overlap():
    left = AABB.from_center_size((0, 0, 0), (2, 2, 2))
    right = AABB.from_center_size((2, 0, 0), (2, 2, 2))
    assert left.overlaps(right) is False
    assert left.overlaps(right, margin=0.1) is True


def test_margin_expands_only_the_other_box():
    camera = AABB.from_center_size((0, 0, 0), (0.2, 0.2, 0.2))
    wall = AABB.from_center_size((0, 0.5, 0), (4.0, 0.2, 3.0))
    # 墙的 y 范围是 0.4–0.6，相机是 -0.1–0.1：留 0.2 还不够，0.5 才相交
    assert camera.overlaps(wall) is False
    assert camera.overlaps(wall, margin=0.2) is False
    assert camera.overlaps(wall, margin=0.5) is True


def test_expanded_keeps_center():
    box = AABB.from_center_size((1, 1, 1), (2, 2, 2)).expanded(0.5)
    assert box.center == (1.0, 1.0, 1.0)
    assert box.size == (3.0, 3.0, 3.0)


def test_union_covers_all_inputs():
    a = AABB.from_center_size((0, 0, 0), (2, 2, 2))
    b = AABB.from_center_size((10, 0, 0), (2, 2, 2))
    merged = union([a, b])
    assert merged.minimum == (-1.0, -1.0, -1.0)
    assert merged.maximum == (11.0, 1.0, 1.0)


def test_union_requires_input():
    with pytest.raises(ValueError):
        union([])
