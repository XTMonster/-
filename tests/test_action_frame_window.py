"""动作帧折算是**单一真源**：规则与构建器必须问同一个函数（v1.5）。

现场（2026-10-03 的真跑对比，`docs/evidence/20261003_chunked_long6|long8/`）：

* 构建器一直把动作窗口**夹进它自己那一镜**（`shot_builder.action_requests` 里
  `min(max(local_end, local_start), shot.duration_frames)`）；
* 而 R003 的动作区间映射（`rule_checker._action_ranges`）**没夹**，直接
  `start + local_end - 1`。

于是模型把 `end_frame` 写到镜头时长之外时，规则会报出**场景里并不存在**的
跨镜重叠：run8 里 **64/64 镜、487 条 R003**，样例是
"`shot_055#3 nod` 与 `shot_056#1 turn_head` 重叠"——而构建器早把 055 的动作
夹回它自己的窗口了（run6 只有 38 条，因为那一次的草案大多没越界；同一份规则、
同一个引擎，差别只在"草案有没有越界"）。

本文件钉三件事：折算函数的边界、两个调用点**引用同一函数**、以及"越界不产生
跨镜重叠"这条不变量。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.cinema.schedule import action_frame_window  # noqa: E402


def test_the_window_is_clamped_into_its_own_shot():
    #: 镜头从第 100 帧开始、长 48 帧；动作写 1–96（越界）⇒ 夹到 100–147。
    assert action_frame_window(100, 48, 1, 96) == (100, 147)
    #: 正常范围内的原样通过。
    assert action_frame_window(100, 48, 10, 30) == (109, 129)
    #: `start` 至少 1（0 或负数当 1），`end` 至少等于 `start`。
    assert action_frame_window(1, 48, 0, 0) == (1, 1)
    assert action_frame_window(1, 48, 30, 10) == (30, 30)


def test_both_call_sites_share_the_one_function():
    """构建器与规则都必须**引用**它，不许各写一份夹法。"""
    builder = (ROOT / "block_director" / "layer3_engine"
               / "shot_builder.py").read_text(encoding="utf-8")
    rules = (ROOT / "block_director" / "layer3_engine"
             / "rule_checker.py").read_text(encoding="utf-8")
    assert "action_frame_window(" in builder
    assert "action_frame_window(" in rules
    #: 反面对照：旧的手写夹法不该再出现（那是这次修复的对象）。
    assert "min(max(local_end, local_start), shot.duration_frames)" not in builder
    assert "start + local_end - 1" not in rules


def test_an_overrun_action_cannot_fake_a_cross_shot_overlap():
    """不变量：相邻两镜的动作，只要各自在自己的窗口里，就永远不重叠。"""
    #: shot_055 从第 2629 帧开始长 72 帧；它的动作被写成 1–96（越界）。
    a = action_frame_window(2629, 72, 1, 96)
    #: shot_056 紧接着开始，动作 1–20。
    b = action_frame_window(2629 + 72, 72, 1, 20)
    assert a[1] < b[0], f"越界动作溢到了下一镜：{a} vs {b}"
