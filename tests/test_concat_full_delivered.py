"""R2 ticket 03（D1）：全片拼接必须包含全部已交付 mp4。

根因：concat 用 ``_shot_ranges(plan, build_summary)`` 构造 clips，而 resume 时
传入的是子集 plan（``plan_for_shots(plan, remaining)``），于是每次导出都只拼
本次渲染的段，前段已过镜的 mp4 不进全片（实测 `blockout_full.mp4` 只剩
shot_006，而 shot_002/004 的 mp4 在盘不入片）。
"""

from __future__ import annotations

from pathlib import Path

from block_director.contracts.plan import Plan, ShotPlan
from block_director.delivery.concat_inputs import concat_inputs


def _full_plan():
    return Plan(shots=[
        ShotPlan(shot_id="shot_001", intent="a", shot_type="CU",
                 duration_frames=24),
        ShotPlan(shot_id="shot_002", intent="b", shot_type="MCU",
                 duration_frames=24),
        ShotPlan(shot_id="shot_003", intent="c", shot_type="MS",
                 duration_frames=24),
        ShotPlan(shot_id="shot_004", intent="d", shot_type="MLS",
                 duration_frames=24),
    ])


def _subset_plan(full):
    return Plan(shots=[shot for shot in full.shots
                       if shot.shot_id in {"shot_003", "shot_004"}])


def test_concat_inputs_use_full_plan_order_when_given():
    """传入 concat_plan 时，clips 按**完整计划顺序**（含已交付前段）。"""
    full = _full_plan()
    subset = _subset_plan(full)
    clips, clip_frames = concat_inputs(
        subset, concat_plan=full, export_dir=Path("E:/tmp/export"))
    assert [Path(c).name for c in clips] == [
        "blockout_shot_001.mp4", "blockout_shot_002.mp4",
        "blockout_shot_003.mp4", "blockout_shot_004.mp4"]
    assert clip_frames == [24, 24, 24, 24]


def test_concat_inputs_default_to_plan_when_no_concat_plan():
    """无 concat_plan 时保持既有行为：按传入 plan（子集）拼接。"""
    subset = _subset_plan(_full_plan())
    clips, clip_frames = concat_inputs(
        subset, concat_plan=None, export_dir=Path("E:/tmp/export"))
    assert [Path(c).name for c in clips] == [
        "blockout_shot_003.mp4", "blockout_shot_004.mp4"]
    assert clip_frames == [24, 24]


def test_concat_inputs_derive_frames_from_build_summary():
    """有 build_summary 时帧数取实际渲染区间（与既有 _shot_ranges 同口径）。"""
    subset = _subset_plan(_full_plan())
    build_summary = {"results": [
        {"shot_id": "shot_003", "start_frame": 49, "end_frame": 72},
        {"shot_id": "shot_004", "start_frame": 73, "end_frame": 96},
    ]}
    _, clip_frames = concat_inputs(
        subset, concat_plan=None, export_dir=Path("E:/tmp/export"),
        build_summary=build_summary)
    assert clip_frames == [24, 24]
