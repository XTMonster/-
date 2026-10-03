"""求解器必须遵守 §10.4 的构图模型：单主体镜头的**视线留白**（v1.6）。

现场（2026-10-04，`docs/evidence/20261003_chunked_long10/`）：终审 49 个未过镜头里
**27 个**带 `COMPOSITION`，分项判据是 `lead_room`（朝向侧空白 ≥64.5% 满分）
与 `rule_of_thirds`（主体靠近 1/3 交点）。而 `solve_framing` 一直把目标点
放在主体上 ⇒ 主体恒在画面正中 ⇒ `lead_room` 只拿 ~0.29、`rule_of_thirds` ~0.05。
**求解器从来没读自己的评分模型。**

本文件钉的是那一处"看哪"的偏移：把对准点朝视线方向推 1/6 幅宽 ⇒ 主体落在
背向视线的那条三分线上；机位与焦距**不动**；主体正对镜头时不该偏移。
"""

from __future__ import annotations

import math
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.cinema.framing import SENSOR_WIDTH, solve_framing  # noqa: E402
from block_director.cinema.station import (  # noqa: E402
    LEAD_ROOM_OFFSET,
    aim_offset_for_lead_room,
    subject_frame,
)


def _single(facing=(1.0, 0.0, 0.0)):
    return subject_frame([("char_001", (0.0, 0.0, 0.0), facing)], shot_type="MCU")


def test_a_subject_facing_screen_right_gets_its_aim_pushed_right():
    """主体朝画面右 ⇒ 对准点朝右推 ⇒ 主体落到**左**三分线、右侧留出空白。

    几何（与 `right_of` 的定义一致）：机位在主体 +Y（`direction` 是"主体 → 机位"
    的单位向量），相机朝 −Y 看 ⇒ **屏幕右 = 世界 −X**。所以"朝画面右"的朝向是
    `(−1, 0, 0)`，对准点应朝屏幕右推（世界 −X 方向）＝正的 `aim_offset_x`。
    """
    offset = aim_offset_for_lead_room((0.0, 1.0), (-1.0, 0.0, 0.0))
    assert offset == pytest.approx(LEAD_ROOM_OFFSET)


def test_the_offset_flips_with_the_gaze():
    """同一个机位，朝向换成朝画面左（世界 +X）⇒ 对准点必须朝屏幕左推。"""
    left = aim_offset_for_lead_room((0.0, 1.0), (1.0, 0.0, 0.0))
    assert left == pytest.approx(-LEAD_ROOM_OFFSET)


def test_a_subject_looking_into_the_lens_is_not_offset():
    """正对镜头没有"视线留白"可言：偏移必须是 0，不许凭空造一个三分法。"""
    #: 机位在 +Y ⇒ 主体朝 +Y 就是正对镜头。
    assert aim_offset_for_lead_room((0.0, 1.0), (0.0, 1.0, 0.0)) == 0.0


def test_no_facing_means_no_offset():
    assert aim_offset_for_lead_room((0.0, 1.0), (0.0, 0.0, 0.0)) == 0.0
    assert aim_offset_for_lead_room((0.0, 0.0), (1.0, 0.0, 0.0)) == 0.0


def test_the_offset_is_one_sixth_of_the_frame_width():
    """偏移的量纲是**幅宽**：目标点的位移 = 该距离上的画面宽度 × 1/6。"""
    result = solve_framing(subject_pos=(0.0, 0.0, 0.0), facing=(-1.0, 0.0, 0.0),
                           shot_type="MCU", lens=50.0, direction=(0.0, 1.0),
                           aim_offset_x=LEAD_ROOM_OFFSET)
    width = result.distance * SENSOR_WIDTH / result.lens
    #: 机位在 +Y、看回原点 ⇒ 屏幕右 = 世界 −X，于是目标点朝 −X 偏 1/6 幅宽。
    assert result.target[0] == pytest.approx(-LEAD_ROOM_OFFSET * width)
    assert result.target[1] == pytest.approx(0.0)


def test_the_offset_moves_the_aim_only():
    """机位、焦距、距离、景别都不许因为"看哪"而变。"""
    base = solve_framing(subject_pos=(0.0, 0.0, 0.0), facing=(1.0, 0.0, 0.0),
                         shot_type="MCU", lens=50.0, direction=(0.0, 1.0))
    moved = solve_framing(subject_pos=(0.0, 0.0, 0.0), facing=(1.0, 0.0, 0.0),
                          shot_type="MCU", lens=50.0, direction=(0.0, 1.0),
                          aim_offset_x=LEAD_ROOM_OFFSET)
    assert moved.position == pytest.approx(base.position)
    assert moved.lens == base.lens
    assert moved.distance == base.distance
    assert moved.shot_type == base.shot_type
    assert math.hypot(moved.target[0] - base.target[0],
                      moved.target[1] - base.target[1]) > 0.0


def test_without_an_offset_the_target_stays_on_the_subject():
    """对照：`aim_offset_x=0`（双人镜头那条路）行为不变。"""
    result = solve_framing(subject_pos=(0.3, -0.2, 0.0), facing=(1.0, 0.0, 0.0),
                           shot_type="MS", lens=35.0, direction=(0.0, 1.0))
    assert result.target[0] == pytest.approx(0.3)
    assert result.target[1] == pytest.approx(-0.2)


# --------------------------------------------------------------------------- #
# v1.8：竖直方向——单主体镜头把**对准点抬高**（`HEAD_ROOM_AIM_M`）。
#
# 实测依据：`work/_box_center_probe.py` 量到三份冻结工程里主体盒中心的**中位纵向
# 偏差**是 0.13（≈ 停在画面正中），于是 `_thirds` 在 61–63/64 镜里都是弱项；
# `work/_aim_sweep_probe.py` 把对准点按 −0.4…+0.4 m 扫了一遍（long12 的 40 个
# 单主体镜），抬高 +0.1 / +0.2 m 的合计增益是 **+130 / +214 分**，压低只有
# +34 / +38 ⇒ 取 +0.15 m。`SHOT_FRAME.target_z`（§2.2 D2 的冻结常量）一个字没动。
# --------------------------------------------------------------------------- #
def test_the_vertical_aim_can_be_raised_without_moving_the_camera():
    base = solve_framing(subject_pos=(0.0, 0.0, 0.0), facing=(1.0, 0.0, 0.0),
                         shot_type="MCU", lens=50.0, direction=(0.0, 1.0))
    raised = solve_framing(subject_pos=(0.0, 0.0, 0.0), facing=(1.0, 0.0, 0.0),
                           shot_type="MCU", lens=50.0, direction=(0.0, 1.0),
                           aim_offset_y=0.15)
    assert raised.target[2] == pytest.approx(base.target[2] + 0.15, abs=1e-9)
    assert raised.target[0] == pytest.approx(base.target[0])
    assert raised.position == pytest.approx(base.position)
    assert raised.lens == base.lens
