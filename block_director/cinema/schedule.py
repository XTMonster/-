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
