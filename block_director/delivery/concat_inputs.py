"""全片拼接的纯输入构造（R2-D1，无 bpy）。

concat 的 clips 顺序必须来自**完整计划**，而不是 resume 时传入的子集 plan：
否则每次导出只拼本次渲染的段，前段已过镜的 mp4 不进全片（实测
`blockout_full.mp4` 只剩 shot_006，而 shot_002/004 的 mp4 在盘不入片）。
``concat_shot_clips`` 已负责过滤磁盘上缺失的 mp4（fail/skip 镜）并留 warning，
这里只决定"按哪个顺序、给哪些帧数"。
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from ..contracts.plan import Plan


def shot_ranges(
    plan: Plan,
    build_summary: Optional[Dict[str, object]] = None,
) -> List[Dict[str, object]]:
    """每镜 (start, end) 区间（与导出渲染循环同一口径，纯层可测）。"""
    results = {str(r.get("shot_id")): r for r in
               (build_summary or {}).get("results", [])}
    ranges: List[Dict[str, object]] = []
    cursor = 1
    for shot in plan.shots:
        result = results.get(str(shot.shot_id), {})
        start = int(result.get("start_frame", cursor))
        end = int(result.get("end_frame", start + shot.duration_frames - 1))
        ranges.append({"shot_id": str(shot.shot_id),
                       "start_frame": start, "end_frame": end})
        cursor = end + 1
    return ranges


def concat_inputs(
    plan: Plan,
    export_dir: Path,
    *,
    build_summary: Optional[Dict[str, object]] = None,
    concat_plan: Optional[Plan] = None,
) -> Tuple[List[str], List[int]]:
    """返回 (clips, clip_frames)：全片拼接的输入，按完整计划顺序。

    ``concat_plan`` 缺省时退回 ``plan``（既有行为）；传入完整计划时（resume
    的子集导出场景），clips 覆盖**全部**已交付 mp4，前段不再丢失。
    """
    source = concat_plan if concat_plan is not None else plan
    ranges = shot_ranges(source, build_summary)
    clips = [str(Path(export_dir) / f"blockout_{r['shot_id']}.mp4")
             for r in ranges]
    clip_frames = [int(r["end_frame"]) - int(r["start_frame"]) + 1
                   for r in ranges]
    return clips, clip_frames
