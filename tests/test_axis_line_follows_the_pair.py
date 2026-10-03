"""轴线跟着走位走：线取两人**此刻**的连线，侧别继承（v1.8）。

现场（2026-10-04，`work/_r001_classify_probe.py`）：`long12` 的 27 条 R001 里
**26 条**是同一形状——伊恩走到 (6.9,−6.5)、米迦尔走到 (−1.8,−2.4) 之后就再没动，
而轴线还是首镜那条 ⇒ 后面每一镜都被判越轴。工艺上 180° 约束的是**覆盖**
（机位怎么摆）而不是**调度**（人怎么走）：人走到哪线跟到哪，真正要继承的是
**屏幕上左右关系**（侧别）。GLM 5.3 会诊的 F1/F4 与这条一致。

本文件钉纯函数 `cinema/axis.current_line` 的四件事：平移不改侧别、保持标签顺序
时"两人互换左右"会把侧别翻过来（真正的越轴仍判得出）、缺一个标签就原样返回、
两人重合（退化线）也原样返回。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.cinema.axis import (  # noqa: E402
    Axis,
    current_line,
)

AXIS = Axis(start=(-0.9, 0.0), end=(0.9, 0.0),
            established_side=-1, left_label="甲", right_label="乙")


def test_translating_the_pair_keeps_both_the_line_and_the_side():
    moved = current_line(AXIS, {"甲": (-0.9, -6.0), "乙": (0.9, -6.0)})
    assert moved.start == (-0.9, -6.0) and moved.end == (0.9, -6.0)
    assert moved.established_side == AXIS.established_side
    #: 同侧的一点（原来在 −y 侧）平移后仍在 −y 侧。
    assert moved.side_of((0.0, -9.0)) == -1


def test_the_line_follows_a_rotation():
    rotated = current_line(AXIS, {"甲": (-0.9, 0.0), "乙": (0.9, -4.0)})
    assert rotated.end == (0.9, -4.0)
    assert rotated.direction != AXIS.direction
    assert rotated.established_side == AXIS.established_side


def test_swapping_the_two_people_flips_the_side_so_a_real_crossing_still_reads():
    """保持**标签顺序**：乙走到甲另一侧时 `side_of` 翻号——真正的越轴不被洗掉。"""
    swapped = current_line(AXIS, {"甲": (-0.9, 0.0), "乙": (-4.0, 0.0)})
    probe = (0.0, -3.0)
    assert AXIS.side_of(probe) == -1
    assert swapped.side_of(probe) == 1        # 线反向 ⇒ 同一点到了另一侧
    assert swapped.established_side == AXIS.established_side


def test_a_missing_label_or_a_degenerate_line_returns_the_original():
    assert current_line(AXIS, {"甲": (-0.9, 0.0)}) is AXIS
    assert current_line(AXIS, {"甲": (1.0, 1.0), "乙": (1.0, 1.0)}) is AXIS
