"""排片器（执行文档 v1.2 §10.2）：**唯一**时间轴真源。

镜头只声明 ``duration_frames``，绝对帧号在这里统一生成。构建、单镜重生成、
SDL 回填都读同一份结果，避免"两个真源互相覆盖"。

纯计算，不依赖 bpy，因此可以在 pytest 里逐条断言。
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..contracts.plan import Plan
from ..utils.geometry import facing_to_rotation_z, rotation_z_to_facing


_MOTION_ACTIONS = frozenset({
    "walk_to", "run_to", "enter_from", "exit_frame",
})


def _plan_shots(plan: Any) -> List[Any]:
    if isinstance(plan, Mapping):
        shots = plan.get("shots")
        if isinstance(shots, list) and shots:
            return list(shots)
        if plan.get("shot_id"):
            return [plan]
        return []
    return list(getattr(plan, "shots", None) or [])


def _shot_value(shot: Any, key: str, default: Any = None) -> Any:
    if isinstance(shot, Mapping):
        return shot.get(key, default)
    return getattr(shot, key, default)


def _vec3(value: Any) -> Optional[Tuple[float, float, float]]:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    values = [float(value[index]) for index in range(min(len(value), 3))]
    while len(values) < 3:
        values.append(0.0)
    return (values[0], values[1], values[2])


def _motion_source(
    params: Mapping[str, Any],
    action: Mapping[str, Any],
    current: Tuple[float, float, float],
) -> Tuple[float, float, float]:
    source = params.get("from") or params.get("from_") or action.get("from")
    return _vec3(source) or current


def _motion_target(
    params: Mapping[str, Any],
    action: Mapping[str, Any],
) -> Optional[Tuple[float, float, float]]:
    target = (
        params.get("target_position")
        or params.get("to")
        or action.get("target_position")
        or action.get("to")
    )
    return _vec3(target)


def _turn_angle_radians(params: Mapping[str, Any]) -> float:
    raw = params.get("angle_deg")
    if raw is None:
        raw = params.get("angle")
    if raw is None:
        raw = params.get("degrees")
    return math.radians(float(90.0 if raw is None else raw))


def _travelled_state(
    plan: Any,
    initial_positions: Mapping[str, Sequence[float]],
    initial_facings: Optional[Mapping[str, Sequence[float]]],
) -> Tuple[
    Dict[str, Dict[str, Tuple[float, float, float]]],
    Dict[str, Dict[str, Tuple[float, float, float]]],
]:
    current_positions: Dict[str, Tuple[float, float, float]] = {}
    for character_id, location in initial_positions.items():
        value = _vec3(location)
        if value is not None:
            current_positions[str(character_id)] = value

    current_yaws: Dict[str, float] = {}
    for character_id, facing in (initial_facings or {}).items():
        value = _vec3(facing)
        if value is not None:
            current_yaws[str(character_id)] = facing_to_rotation_z(value)

    positions_by_shot: Dict[str, Dict[str, Tuple[float, float, float]]] = {}
    facings_by_shot: Dict[str, Dict[str, Tuple[float, float, float]]] = {}
    for shot in _plan_shots(plan):
        shot_id = str(_shot_value(shot, "shot_id", "") or "")
        positions_by_shot[shot_id] = dict(current_positions)
        facings_by_shot[shot_id] = {
            character_id: rotation_z_to_facing(yaw)
            for character_id, yaw in current_yaws.items()
        }
        for raw in _shot_value(shot, "actions", None) or []:
            if not isinstance(raw, dict):
                continue
            action_type = str(raw.get("action_type") or "")
            character_id = str(raw.get("character_id") or "")
            if not character_id:
                continue
            params = dict(raw.get("params") or {})
            if action_type == "turn_body":
                current_yaws[character_id] = (
                    current_yaws.get(character_id, 0.0)
                    + _turn_angle_radians(params)
                )
                continue
            if action_type not in _MOTION_ACTIONS:
                continue

            target = _motion_target(params, raw)
            if target is None:
                continue
            current = current_positions.get(
                character_id, (0.0, 0.0, 0.0))
            source = _motion_source(params, raw, current)
            dx, dy = target[0] - source[0], target[1] - source[1]
            if math.hypot(dx, dy) > 1e-9:
                current_yaws[character_id] = facing_to_rotation_z((dx, dy, 0.0))
            current_positions[character_id] = target
    return positions_by_shot, facings_by_shot


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


def out_of_bounds(target: Sequence[float], extent_m: float) -> bool:
    """走位目的地是否落在**场景可用范围**之外（只看 X/Y）。

    范围由 `config.scene.extent_m` 给（计划提示里也写着同一条），
    构建期用它把越界的走位**如实告警**——不夹取、不静默改写（夹取会把
    "模型把整场带出场地"这件事藏起来）。实测依据：`long9` 重建里角色被一串
    缺省 `from` 的行走带到 25 m 之外，而计划里每个目的地都在 9.5 m 以内
    （`docs/evidence/20261004-walk-handover/`）。
    """
    if len(target) < 2:
        return False
    limit = abs(float(extent_m))
    if limit <= 0.0:
        return False
    return abs(float(target[0])) > limit or abs(float(target[1])) > limit


def travelled_positions(plan: Any,
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
    positions, _facings = _travelled_state(plan, initial, None)
    return positions


def travelled_facings(
    plan: Any,
    initial_facings: Mapping[str, Sequence[float]],
    initial_positions: Optional[Mapping[str, Sequence[float]]] = None,
) -> Dict[str, Dict[str, Tuple[float, float, float]]]:
    """每一镜**开始时**各角色的根朝向。

    与 Blender 动作烘焙共用语义：``walk_to``/``run_to``/``enter_from``/
    ``exit_frame`` 的终点是运动方向的绝对朝向；``turn_body`` 按角度增量累积。
    设计快照用这份结果求解机位，避免“位置已接力、朝向仍停在初始 +Y”的镜像。
    """
    _positions, facings = _travelled_state(
        plan, initial_positions or {}, initial_facings)
    return facings


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


def action_ranges_from_plan(
    plan: Optional[Any],
    schedule: Optional[Mapping[str, Sequence[int]]] = None,
) -> Dict[str, List[Tuple[int, int, str]]]:
    """逐角色的全局动作区间：``{character_id: [(start, end, label)]}``。

    R003（同一角色动作不得重叠）判定的**单一真源**：与构建器问同一个
    ``action_frame_window``，并且**只信已构建镜的时间轴**。

    ``schedule``（shot_id → (起, 止)）是逐镜预演时**已构建镜**的实测区间；
    不在表里的镜头一律按计划级 ``shot_ranges(plan)`` 回退——否则未构建镜
    会被当成从第 1 帧开始，报出场景里并不存在的跨镜重叠（final6 实测：
    shot_002 的 turn_head 被折到 1..16，与 shot_001 的 look_at 1..32 假重叠，
    6 条 R003 淹没一张审计，修复回路被同一句话灌满）。

    纯计算、不依赖 bpy，可在 pytest 里逐条断言。
    """
    ranges: Dict[str, List[Tuple[int, int, str]]] = {}
    if plan is None:
        return ranges
    full = shot_ranges(plan)
    for shot in plan.shots:
        span = None
        if schedule is not None:
            span = schedule.get(shot.shot_id)
        if span is None:
            span = full.get(shot.shot_id)
        start = int(span[0]) if span else 1
        duration = max(int(shot.duration_frames), 1)
        for index, raw in enumerate(getattr(shot, "actions", None) or [],
                                   start=1):
            if not isinstance(raw, dict):
                continue
            character_id = str(raw.get("character_id") or "")
            if not character_id:
                continue
            absolute_start, absolute_end = action_frame_window(
                start, duration,
                int(raw.get("start_frame") or 1),
                int(raw.get("end_frame") or duration))
            label = f"{shot.shot_id}#{index} {raw.get('action_type')}"
            ranges.setdefault(character_id, []).append(
                (absolute_start, absolute_end, label))
    return ranges


def overlapping_action_pairs(
    items: Sequence[Tuple[int, int, str]],
) -> List[Tuple[str, str]]:
    """闭区间两两重叠对（R003 用）：``[(label_a, label_b), ...]``。"""
    ordered = sorted(items)
    pairs: List[Tuple[str, str]] = []
    for index, (start_a, end_a, label_a) in enumerate(ordered):
        for start_b, end_b, label_b in ordered[index + 1:]:
            if start_b < end_a and start_b <= end_b:
                pairs.append((label_a, label_b))
    return pairs
