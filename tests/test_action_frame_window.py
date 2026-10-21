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

from block_director.cinema.schedule import (  # noqa: E402
    action_frame_window,
    action_ranges_from_plan,
    overlapping_action_pairs,
)


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
    schedule = (ROOT / "block_director" / "cinema"
                / "schedule.py").read_text(encoding="utf-8")
    assert "action_frame_window(" in builder
    #: v1.8：R003 的动作区间纯逻辑收进 schedule.action_ranges_from_plan，
    #: rule_checker 只引用该纯函数（单一真源），夹法仍只有 schedule 一份。
    assert "action_ranges_from_plan(" in rules
    assert "action_frame_window(" in schedule
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


class _Shot:
    """最小计划镜头桩：只带 R003 需要的字段。"""

    def __init__(self, shot_id, duration_frames, actions):
        self.shot_id = shot_id
        self.duration_frames = duration_frames
        self.actions = actions


class _Plan:
    def __init__(self, shots):
        self.shots = shots


def _two_shot_plan():
    """shot_001 与 shot_002 各 96 帧，米迦尔在两镜里都有动作。"""
    return _Plan([
        _Shot("shot_001", 96, [
            {"character_id": "米迦尔", "action_type": "look_at",
             "start_frame": 1, "end_frame": 32}]),
        _Shot("shot_002", 96, [
            {"character_id": "米迦尔", "action_type": "turn_head",
             "start_frame": 1, "end_frame": 16}]),
    ])


def test_per_shot_previz_missing_schedule_falls_back_to_plan_global_frames():
    """逐镜预演时 schedule 只含当前镜：未构建镜按计划级绝对帧回退。

    final6 实测（2026-10-20，run f018ac273f35）：shot_001 审计被 6 条跨镜
    R003 淹没，根因就是 shot_002 的动作被 ``(1, duration)`` 缺省折到
    1..16，与 shot_001 的 1..32 假重叠。这里是回归不变量。
    """
    plan = _two_shot_plan()
    #: 逐镜预演：只构建了 shot_001，schedule 只有它。
    ranges = action_ranges_from_plan(plan, {"shot_001": (1, 96)})
    items = ranges["米迦尔"]
    assert (1, 32, "shot_001#1 look_at") in items
    #: shot_002 回退到计划级全局区间 97–192，动作落在 97–112。
    assert (97, 112, "shot_002#1 turn_head") in items
    #: 相邻两镜的动作不再假重叠。
    assert list(overlapping_action_pairs(items)) == []


def test_explicit_schedule_entry_wins_over_plan_fallback():
    """已构建镜用 schedule 实测区间，未构建镜仍回退计划级区间。"""
    plan = _two_shot_plan()
    ranges = action_ranges_from_plan(
        plan, {"shot_001": (10, 105), "shot_002": (200, 295)})
    items = ranges["米迦尔"]
    assert (10, 41, "shot_001#1 look_at") in items
    assert (200, 215, "shot_002#1 turn_head") in items


def test_real_overlap_inside_one_shot_is_still_detected():
    """修复只去掉跨镜假重叠，不放过同镜真重叠。"""
    plan = _two_shot_plan()
    ranges = action_ranges_from_plan(plan, {"shot_001": (1, 96)})
    items = list(ranges["米迦尔"])
    items.append((20, 40, "shot_001#2 body_tilt"))
    pairs = list(overlapping_action_pairs(items))
    assert ("shot_001#1 look_at", "shot_001#2 body_tilt") in pairs
    #: shot_002 的动作（97–112）不与任何 shot_001 动作成对。
    assert not any(
        "shot_002" in label_a or "shot_002" in label_b
        for label_a, label_b in pairs)
