"""排片器（执行文档 v1.2 §10.2）：**唯一**时间轴真源。

镜头只声明 ``duration_frames``，绝对帧号在这里统一生成。构建、单镜重生成、
SDL 回填都读同一份结果，避免"两个真源互相覆盖"。

纯计算，不依赖 bpy，因此可以在 pytest 里逐条断言。
"""

from __future__ import annotations

from typing import Dict, Tuple

from ..contracts.plan import Plan


def shot_ranges(plan: Plan) -> Dict[str, Tuple[int, int]]:
    """按计划顺序算出每个镜头的绝对帧范围（闭区间，从第 1 帧开始）。"""
    ranges: Dict[str, Tuple[int, int]] = {}
    cursor = 1
    for shot in plan.shots:
        end = cursor + max(int(shot.duration_frames), 1) - 1
        ranges[shot.shot_id] = (cursor, end)
        cursor = end + 1
    return ranges


def total_frames(plan: Plan) -> int:
    """整条时间轴的帧数（= 最后一个镜头的结束帧）。"""
    ranges = shot_ranges(plan)
    if not ranges:
        return 0
    return max(end for _start, end in ranges.values())


def action_frame_window(shot_start: int, duration_frames: int,
                        local_start: int, local_end: int) -> Tuple[int, int]:
    """把**镜头内局部**的动作帧区间折成**绝对**帧区间（闭区间）。

    夹法是**单一真源**：动作必须发生在它自己那一镜里。``start`` 至少是 1，
    ``end`` 至少等于 ``start``、至多是镜头时长——写到时长之外的 `end_frame`
    被夹回镜头边界（与取景求解器的 `_clamp_to_room` 同一个口径：越界的输入
    夹回合法域，而不是让它溢到下一镜）。

    为什么必须是**同一份**（2026-10-03 的真跑实测）：构建器一直这么夹
    （`shot_builder.action_requests`），而 R003 的动作区间映射**没夹**——
    模型把 `end_frame` 写到时长之外时，规则会报出一堆**场景里并不存在**的
    跨镜重叠：run8 里 64/64 镜、**487 条 R003**，其中样例是
    "`shot_055#3 nod` 与 `shot_056#1 turn_head` 重叠"——而构建器早把 055 的
    动作夹回它自己的窗口了（run6 同一份规则只有 38 条，因为那一次的草案
    大多没越界）。**规则与实现必须问同一个函数**。
    """
    span = max(int(duration_frames), 1)
    first = max(int(local_start), 1)
    last = min(max(int(local_end), first), span)
    base = int(shot_start)
    return (base + first - 1, base + last - 1)
