"""完整白模流程 UI 接线的纯层验收（不 import bpy）。

钉住三件事：

1. ``assemble_pipeline_inputs`` 优先取 driver 的 plan/brief，回退场景上下文，
   且 ``cast_positions`` 与 ``SceneSpec.from_plan`` 同源（站位不另摆一套）；
2. gate 判定（``coarse_is_ready`` / ``detail_is_ready``）与 operator 的阻塞
   语义一致：粗排 gate 或基准未通过不进细排，细排/序列/final 未通过不导
   final 视频；
3. ``pipeline_summary`` 只从真实报告折一页纸摘要，不伪造产物路径。
"""

from __future__ import annotations

from block_director.contracts.plan import Plan, ShotPlan
from block_director.layer5_orchestrator.pipeline_ui_inputs import (
    assemble_pipeline_inputs,
    coarse_is_ready,
    detail_is_ready,
    gate_value,
    pipeline_summary,
)


def _plan(scene_heading: str = "dock_fly_bomb") -> Plan:
    return Plan(
        scene_heading=scene_heading,
        shots=[
            ShotPlan(
                shot_id="shot_001",
                intent="飞扑建立空间",
                shot_type="MS",
                duration_frames=72,
                order=1,
                characters=["米迦尔", "偷盗者"],
                actions=[{"action": "飞扑", "target": "偷盗者"}],
                camera={"side": "front", "lens": 35},
            )
        ],
    )


class _Driver:
    def __init__(self, plan=None, brief=None):
        self.plan = plan
        self.brief = brief


class _SceneContext:
    def __init__(self, plan=None):
        self.plan = plan


def test_prefers_driver_plan_and_brief():
    plan = _plan()
    brief = object()
    inputs = assemble_pipeline_inputs(_Driver(plan=plan, brief=brief), None)
    assert inputs is not None
    assert inputs["plan"] is plan
    assert inputs["brief"] is brief
    assert inputs["scene_id"] == "dock_fly_bomb"


def test_falls_back_to_scene_context_plan():
    plan = _plan("market")
    inputs = assemble_pipeline_inputs(None, _SceneContext(plan=plan))
    assert inputs is not None
    assert inputs["plan"] is plan
    #: driver 缺失时 brief 为 None：粗排用确定性理解兜底（不伪造 Stage S）。
    assert inputs["brief"] is None
    assert inputs["scene_id"] == "market"


def test_cast_positions_same_source_as_scene_spec():
    from block_director.contracts.cast import SceneSpec

    plan = _plan()
    inputs = assemble_pipeline_inputs(_Driver(plan=plan), None)
    spec = SceneSpec.from_plan(plan)
    expected = {str(m.name): list(m.initial_location)
                for m in spec.cast}
    assert inputs is not None
    assert inputs["cast_positions"] == expected


def test_no_plan_returns_none():
    assert assemble_pipeline_inputs(_Driver(plan=None), None) is None
    assert assemble_pipeline_inputs(None, _SceneContext(plan=None)) is None


def test_gate_value_missing_returns_empty():
    assert gate_value(None, "coarse") == ""
    assert gate_value({"gates": {"coarse": "pass"}}, "baseline") == ""


def test_coarse_is_ready_requires_pass_and_frozen():
    ready = {"gates": {"coarse": "pass", "baseline": "frozen"}}
    not_frozen = {"gates": {"coarse": "pass", "baseline": "missing"}}
    blocked = {"gates": {"coarse": "blocked", "baseline": "missing"}}
    assert coarse_is_ready(ready)
    assert not coarse_is_ready(not_frozen)
    assert not coarse_is_ready(blocked)
    assert not coarse_is_ready(None)


def test_detail_is_ready_requires_final_flag_and_gate():
    ready = {"final": True, "gates": {"final": "pass", "sequence": "pass"}}
    no_video = {"final": False, "gates": {"final": "pass", "sequence": "pass"}}
    blocked = {"final": False, "gates": {"final": "blocked", "sequence": "pass"}}
    assert detail_is_ready(ready)
    assert not detail_is_ready(no_video)
    assert not detail_is_ready(blocked)
    assert not detail_is_ready(None)


def test_pipeline_summary_merges_both_reports():
    coarse = {
        "gates": {"coarse": "pass", "baseline": "frozen"},
        "rounds": [{"round_no": 1}],
        "artifacts": {"baseline": "coarse_world_baseline.json"},
    }
    detail = {
        "final": True,
        "gates": {"detail": "pass", "sequence": "pass", "final": "pass"},
        "artifacts": {"final_video": "final_video.mp4"},
    }
    summary = pipeline_summary(coarse, detail)
    assert summary["gates"] == {
        "coarse": "pass", "baseline": "frozen",
        "detail": "pass", "sequence": "pass", "final": "pass",
    }
    assert summary["coarse_rounds"] == 1
    assert summary["final_video"] == "final_video.mp4"


def test_pipeline_summary_without_reports_does_not_fabricate():
    summary = pipeline_summary(None, None)
    assert summary["gates"] == {
        "coarse": "", "baseline": "",
        "detail": "", "sequence": "", "final": "",
    }
    assert summary["final_video"] is None
