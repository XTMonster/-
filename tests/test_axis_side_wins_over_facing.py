"""两人镜头里，**已确立的轴侧**必须压过"焦点主体朝向"（v1.5）。

现场（2026-10-03 的 64 镜真跑，`docs/evidence/20261003_chunked_long6/`）：
R001（180° 轴线）从 **0 涨到 79**——`camera.side` 收成闭集之后机位第一次真的按
模型要的角度摆，于是"摆错一侧"这件事真的发生了。翻实现发现：
`station.camera_direction` **收了 `axis_side` 却只在单人镜头的 `_off_axis` 分支用**；
两人镜头一律按"焦点主体朝向"挑那一条法线，于是模型的角度与已确立轴侧打架时
**必然越轴**——而 R001 的判据恰恰就是 `Axis.established_side`。

本文件钉：`axis_side` 非零时就按它挑法线（`side_of` 与它一致）；没有轴线基准
（`axis_side == 0`）时保持旧口径（按焦点朝向）——两种情况都给反面对照。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.cinema.axis import Axis  # noqa: E402
from block_director.cinema.station import camera_direction, subject_frame  # noqa: E402


def _frame():
    """两人相对而立：米迦尔在 −0.9 面向 +X，伊恩在 +0.9 面向 −X。"""
    entries = [("char_001", (-0.9, 0.0, 0.0), (1.0, 0.0, 0.0)),
               ("char_002", (0.9, 0.0, 0.0), (-1.0, 0.0, 0.0))]
    return subject_frame(entries, shot_type="MS", speaker_id="char_001")


def _side_of(frame, direction):
    """机位方向落在轴线的哪一侧（与 `Axis.side_of` 同一判据）。"""
    axis = Axis(start=(-0.9, 0.0), end=(0.9, 0.0))
    probe = (frame.anchor[0] + direction[0] * 3.0,
             frame.anchor[1] + direction[1] * 3.0, frame.anchor[2])
    return axis.side_of(probe)


def test_the_established_side_is_honoured_for_both_signs():
    frame = _frame()
    for wanted in (-1, 1):
        direction = camera_direction(frame, "front", axis_dir=(1.0, 0.0),
                                     axis_side=wanted)
        assert _side_of(frame, direction) == wanted, (
            f"axis_side={wanted} 时机位落在 {_side_of(frame, direction)} 侧"
            f"（方向 {direction}）")


def test_without_an_established_side_the_old_facing_rule_still_applies():
    """反面对照：`axis_side=0`（还没有轴线基准）时不许改行为。"""
    frame = _frame()
    with_axis = camera_direction(frame, "front", axis_dir=(1.0, 0.0), axis_side=0)
    without = camera_direction(frame, "front")
    assert with_axis == without


def test_the_side_also_survives_back_and_over_shoulder():
    """`back*`/`over_shoulder` 是从法线派生的，也必须跟着轴侧走。

    可判定的形式：把 `axis_side` 从 +1 翻到 −1，这些方向**必须改变**
    （它们都从法线派生）。若哪天有人把这条逻辑改回"只看焦点朝向"，
    两个符号会给出同一个方向，这条立刻红。
    """
    frame = _frame()
    for key in ("back", "back_left", "back_right", "front_left", "over_shoulder"):
        positive = camera_direction(frame, key, axis_dir=(1.0, 0.0), axis_side=1)
        negative = camera_direction(frame, key, axis_dir=(1.0, 0.0), axis_side=-1)
        assert positive != negative, (
            f"{key} 对轴侧符号不敏感：两边都是 {positive}")
        assert camera_direction(frame, key, axis_dir=(1.0, 0.0),
                                axis_side=1) == positive
