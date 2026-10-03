"""排片器（执行文档 v1.2 §10.2）：**唯一**时间轴真源。

镜头只声明 ``duration_frames``，绝对帧号在这里统一生成。构建、单镜重生成、
SDL 回填都读同一份结果，避免"两个真源互相覆盖"。

纯计算，不依赖 bpy，因此可以在 pytest 里逐条断言。
"""

from __future__ import annotations

from typing import Dict, Mapping, Sequence, Tuple

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


def travelled_positions(plan: Plan,
                        initial: Mapping[str, Sequence[float]]
                        ) -> Dict[str, Dict[str, Tuple[float, float, float]]]:
    """每一镜**开始时**各角色站在哪——把计划里的行走终点接力起来。

    为什么需要它（2026-10-04 实测，`work/_walk_once_probe.py` +
    `work/_drift_probe.py`）：`motion/model.py` 的 `walk_to`/`run_to` 在
    **没有 `from`** 时把 `target_position` 当成**相对位移**（`base + target`）。
    规划器几乎从不写 `from`，于是构建器一直拿 `CastMember.initial_location`
    当缺省起点 ⇒ 同一角色的一串行走**累加**：`long9` 重建里伊恩从起始站位
    一路加到了 (13.0, −12.6)，而计划里每一个目的地都在 9.5 m 以内。

    这里按**计划顺序**推算"到这一镜开始时人在哪"：上一次行走的终点就是下一次
    的起点（`target_position` 是**绝对**目的地），没有行走过的角色就是剧本的
    起始站位。纯计算，可单测；构建器把它当作 `walk_to` 的缺省 `from`。

    注意：只跟踪**位置**。`sit`/`stand`/`turn_*` 这类动作不改平面位置，
    所以不必参与接力（也不该参与，否则一次"坐下"会把坐标带到错误的地方）。
    """
    current: Dict[str, Tuple[float, float, float]] = {}
    for character_id, location in initial.items():
        values = [float(value) for value in location][:3]
        while len(values) < 3:
            values.append(0.0)
        current[str(character_id)] = (values[0], values[1], values[2])

    per_shot: Dict[str, Dict[str, Tuple[float, float, float]]] = {}
    for shot in plan.shots:
        per_shot[str(shot.shot_id)] = dict(current)
        for raw in getattr(shot, "actions", None) or []:
            if not isinstance(raw, dict):
                continue
            action_type = str(raw.get("action_type") or "")
            if action_type not in ("walk_to", "run_to"):
                continue
            character_id = str(raw.get("character_id") or "")
            params = dict(raw.get("params") or {})
            target = params.get("target_position") or raw.get("target_position")
            if not character_id or not isinstance(target, (list, tuple)):
                continue
            if len(target) < 2:
                continue
            values = [float(value) for value in target][:3]
            while len(values) < 3:
                values.append(0.0)
            current[character_id] = (values[0], values[1], values[2])
    return per_shot


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
