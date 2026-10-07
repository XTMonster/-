"""道具交互事件的纯逻辑（执行文档 v1.5 TDD §4.4）。**不 import bpy**（红线 R-1）。

分工：动作动词表（``place_prop`` / ``pick_up`` / ``hand_to``）与角色**那一侧**的
关键帧在 ``motion/model.py`` ＋ ``motion_library``；**道具对象**那一侧的关键帧
由构建器写（``layer3_engine/scene_executor.py``），因为那条路要真的碰对象。
本模块只负责"从动作表算出：哪个道具、在哪几段帧窗里需要跟随"——纯函数，
可以脱离 Blender 逐条验算。

**帧号口径**：计划里的动作帧是**镜内局部帧**，跟随窗必须是**场景绝对帧**；
折算走单一真源 ``cinema/schedule.action_frame_window``（与 R003 的动作区间、
构建器其余部分同一把尺子），不在这里另写一份折帧公式。

**跟随窗语义**（TDD §4.4 的原话："起止区间内的 Child Of 跟随"）：一个动词只在
它声明的 ``[start_frame, end_frame]`` 区间内跟随；区间外道具停在原地。
同一道具的多个交互窗**并集**成一条 0/1 曲线（重叠不叠加，避免两条约束互相
拉扯）。没被任何动词点名的道具**不打关键帧**。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence, Tuple

from ..motion.model import PROP_ACTIONS
from .schedule import action_frame_window

Window = Tuple[int, int]

#: 道具交互动词（单一真源 = ``motion/model.py``，红线 R-7）。
PROP_INTERACTION_ACTIONS: Tuple[str, ...] = tuple(PROP_ACTIONS)


def merge_windows(windows: Sequence[Window]) -> List[Window]:
    """把任意顺序的帧窗并成互不重叠、按起点升序的区间表。"""
    ordered = sorted((min(int(a), int(b)), max(int(a), int(b)))
                     for a, b in windows if int(a) or int(b))
    merged: List[Window] = []
    for start, end in ordered:
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def influence_keys(windows: Sequence[Window]) -> List[Tuple[int, float]]:
    """跟随窗 → Child Of 的 ``influence`` 关键帧表（0 = 不跟随，1 = 跟随）。

    每个区间给出四个点：``start-1 → 0``、``start → 1``、``end → 1``、
    ``end+1 → 0``。``start == 1`` 时省掉首点（第 1 帧之前没有可写的帧），
    ``end == scene_end`` 时省掉尾点（由调用方按实际帧数追加闭合点）。
    """
    keys: List[Tuple[int, float]] = []
    for start, end in merge_windows(windows):
        if start > 1:
            keys.append((start - 1, 0.0))
        keys.append((start, 1.0))
        keys.append((end, 1.0))
        keys.append((end + 1, 0.0))
    # 同一帧出现两次（相邻区间合并后不会发生，但输入可能带重复窗）时留最后一次。
    deduped: Dict[int, float] = {}
    for frame, value in keys:
        deduped[int(frame)] = float(value)
    return sorted(deduped.items())


def prop_interaction_windows(
        actions: Sequence[Any], *, shot_id: str, shot_start: int,
        duration_frames: int) -> Tuple[Dict[str, List[Window]], List[str]]:
    """从一镜的动作表算出 ``{道具名: [绝对帧窗…]}`` ＋ 结构问题清单。

    没有具名道具的交互动作（``params.prop`` 为空）是**合法的哑剧**：角色那一侧
    的动作照旧烘焙，只是没有对象需要跟随——按"未交互道具不打关键帧"的纪律，
    这里不产出窗口。它不写进问题清单（否则每次真跑都会被刷屏），只在调用方
    ``log.info`` 留痕。
    """
    windows: Dict[str, List[Window]] = {}
    problems: List[str] = []
    span = max(int(duration_frames), 1)
    for index, raw in enumerate(actions or [], start=1):
        if not isinstance(raw, Mapping):
            problems.append(f"{shot_id}: 第 {index} 个动作不是对象，已跳过")
            continue
        kind = str(raw.get("action_type") or "")
        if kind not in PROP_INTERACTION_ACTIONS:
            continue
        params = raw.get("params") or {}
        prop_name = str((params or {}).get("prop") or "").strip()
        if not prop_name:
            continue                     # 哑剧：无具名道具
        start, end = action_frame_window(
            int(shot_start), span,
            int(raw.get("start_frame") or 1),
            int(raw.get("end_frame") or span))
        windows.setdefault(prop_name, []).append((start, end))
    return windows, problems


__all__ = [
    "PROP_INTERACTION_ACTIONS", "Window", "merge_windows", "influence_keys",
    "prop_interaction_windows",
]
