"""空间尺处方应用测试（Ticket 05 计划级）。

``apply_plan_prescriptions`` 是计划级空间尺的「应用」接缝：在 bpy 构建前把
已有处方应用到可执行计划上（retime_shot / restore_cast），并返回处方记录
（契约 prescription 形状）＋ 计划级测量（契约 measurement 形状），供审计
与交付证据引用。

要点：
* retime 只按声明时长重设 ``duration_frames``，并显式记录 old/new 帧与
  对白收尾策略；对白装不下时 applied=false 且不改帧（不猜、不硬缩）；
* restore_cast 只从 ``responsibility.white_model`` 与 SceneBrief 已知角色
  交集恢复，不发明未声明角色；
* 每条处方都有 pre/postcondition 测量引用，整包经 validate_bundle 闭合。
"""

from __future__ import annotations

from block_director.contracts.plan import Plan, ShotPlan, Responsibility
from block_director.contracts.spatial_ruler import validate_bundle
from block_director.layer5_orchestrator.spatial_ruler import (
    apply_plan_prescriptions,
)


class Brief:
    speakers = [{"speaker": "米迦尔", "listener": "伊恩"}]
    gaze = [{"from": "米迦尔", "to": "偷盗者"}]
    space = [{"character": "偷盗者", "relative_to": "伊恩"}]


def _plan(shot_001_frames: int = 168) -> Plan:
    plan = Plan(scene_heading="码头")
    plan.shots = [
        ShotPlan("shot_001", "建立", "ELS", shot_001_frames,
                 responsibility=Responsibility(white_model=["米迦尔", "伊恩"])),
        ShotPlan("shot_002", "推进", "MS", 96,
                 responsibility=Responsibility(white_model=["偷盗者"])),
    ]
    return plan


def test_retime_prescription_applies_declared_duration() -> None:
    plan = _plan(shot_001_frames=168)          # 7s @ 24fps，声明 3.5s
    plan, findings, prescriptions, measurements = apply_plan_prescriptions(
        plan, brief=Brief(), declared_total_seconds=16.0,
        declared_seconds_by_shot={"shot_001": 3.5, "shot_002": 4.0},
        fps=24)
    assert plan.shots[0].duration_frames == 84  # 3.5s * 24
    retimes = [p for p in prescriptions if p["operation"] == "retime_shot"]
    assert len(retimes) == 1
    retime = retimes[0]
    assert retime["shot_id"] == "shot_001"
    assert retime["applied"] is True
    assert retime["parameters"]["old_frames"] == 168
    assert retime["parameters"]["new_frames"] == 84
    assert "dialogue_policy" in retime["parameters"]
    assert retime["postcondition_measurement_ids"]
    #: 应用后可执行计划的帧数与声明测量一致
    assert plan.shots[0].declared_duration_frames == 0  # 声明帧只作对拍参考


def test_retime_blocked_when_dialogue_does_not_fit() -> None:
    plan = _plan(shot_001_frames=168)
    plan.shots[0].dialogues = [
        {"speaker": "米迦尔", "text": "这里是长台词。", "start_frame": 1,
         "end_frame": 80},
    ]
    _, findings, prescriptions, measurements = apply_plan_prescriptions(
        plan, brief=Brief(), declared_total_seconds=16.0,
        declared_seconds_by_shot={"shot_001": 3.5},
        fps=24)
    retimes = [p for p in prescriptions if p["operation"] == "retime_shot"]
    assert retimes and retimes[0]["applied"] is False
    assert plan.shots[0].duration_frames == 168   # 不改帧
    assert retimes[0]["waive_reason"]


def test_restore_cast_records_prescription() -> None:
    plan = _plan()
    plan, findings, prescriptions, measurements = apply_plan_prescriptions(
        plan, brief=Brief(), declared_total_seconds=16.0,
        declared_seconds_by_shot={"shot_001": 3.5, "shot_002": 4.0},
        fps=24)
    assert plan.shots[0].characters == ["米迦尔", "伊恩"]
    assert plan.shots[1].characters == ["偷盗者"]
    restores = [p for p in prescriptions if p["operation"] == "restore_cast"]
    assert len(restores) == 2
    assert all(p["applied"] is True for p in restores)
    assert [(p["shot_id"], p["parameters"]["characters"]) for p in restores] == [
        ("shot_001", ["米迦尔", "伊恩"]),
        ("shot_002", ["偷盗者"]),
    ]


def test_undeclared_environment_element_not_invented_as_cast() -> None:
    plan = Plan(scene_heading="码头")
    plan.shots = [
        ShotPlan("shot_001", "建立", "ELS", 120,
                 responsibility=Responsibility(
                     white_model=["摊位", "海面"])),
    ]
    plan, findings, prescriptions, measurements = apply_plan_prescriptions(
        plan, brief=Brief(), declared_total_seconds=None,
        declared_seconds_by_shot=None, fps=24)
    assert plan.shots[0].characters == []
    assert not any(p["operation"] == "restore_cast" and p["applied"]
                   for p in prescriptions)
    assert any(f.rule == "SR001" and f.severity.value == "error"
               for f in findings)


def test_total_rhythm_drift_is_reported_not_silently_retimed() -> None:
    plan = _plan(shot_001_frames=168)          # 7s + 4s = 11s vs 声明 16s
    plan, findings, prescriptions, measurements = apply_plan_prescriptions(
        plan, brief=Brief(), declared_total_seconds=16.0,
        declared_seconds_by_shot=None, fps=24)
    assert plan.shots[0].duration_frames == 168  # 无逐镜声明 → 不自动缩时
    #: 全场漂移只有一份声明数据时记 finding，不擅自重排整场（缺 provider）。
    assert any(f.rule == "SR002" and f.severity.value == "error"
               for f in findings)


def test_prescriptions_close_inside_bundle() -> None:
    plan = _plan(shot_001_frames=168)
    plan, findings, prescriptions, measurements = apply_plan_prescriptions(
        plan, brief=Brief(), declared_total_seconds=16.0,
        declared_seconds_by_shot={"shot_001": 3.5, "shot_002": 4.0},
        fps=24)
    bundle = {
        "schema_version": "spatial-ruler-observation/v2",
        "observation_id": "o_plan_ruler",
        "run_context": {"source_run": "", "model": "test", "status": "offline"},
        "plugin_adapter": {
            "consumer": "BlockDirector.audit",
            "phase": ["pre_build"],
            "blocking_policy": {"error": "blocks", "warning": "persists"},
            "integration_status": "partial_plan_level_only",
        },
        "observation_request": {
            "targets": [{"shot_id": s.shot_id} for s in plan.shots],
            "coordinate_system": "normalized_screen_0_1",
            "fps": 24,
        },
        "registry": {"rules": {}, "guard": {}, "composition": {}},
        "shot_specs": [], "camera_specs": [],
        "measurements": list(measurements),
        "verdicts": [], "prescriptions": list(prescriptions),
    }
    assert validate_bundle(bundle) == []
