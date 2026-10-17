"""Ticket 05：处方应用接缝（纯层，无 bpy）。

``apply_plan_prescriptions`` 只自动执行计划级确定性处方，其余保持
``applied=False`` 且可见。本测试钉住：
* ``retime_shot``（scene 级）：按声明总秒数整场重排帧，记录 old/new；
* ``restore_cast``：从 responsibility.white_model ∩ brief 已知名恢复，
  不发明角色；已满足时是 no-op（applied=True）；
* 未知操作拒绝（ValueError）；
* ``review_transition`` 与相机类处方保持未应用但可见；
* 返回记录与输入处方一一对应。
"""

from __future__ import annotations

import pytest

from block_director.contracts.plan import Plan, Responsibility, ShotPlan
from block_director.layer5_orchestrator.ruler_observation import (
    apply_plan_prescriptions,
)


class _Brief:
    """只带空间尺消费的字段。"""

    speakers = [{"speaker": "米迦尔", "listener": "伊恩"}]
    gaze = [{"from": "米迦尔", "to": "偷盗者"}]
    space = [{"character": "偷盗者", "relative_to": "伊恩"}]


def _plan() -> Plan:
    plan = Plan(scene_heading="码头市场")
    plan.shots = [
        ShotPlan("shot_001", "建立", "ELS", 120, order=1, characters=[],
                 responsibility=Responsibility(
                     white_model=["米迦尔", "伊恩", "偷盗者"])),
        ShotPlan("shot_002", "推进", "MS", 96, order=2, characters=[],
                 responsibility=Responsibility(white_model=["神秘人"])),
        ShotPlan("shot_003", "对白", "MCU", 84, order=3, characters=["伊恩"],
                 responsibility=Responsibility(white_model=["伊恩"])),
        ShotPlan("shot_004", "反应", "MCU", 84, order=4, characters=["米迦尔"]),
    ]
    return plan


def _restore_cast(shot_id: str) -> dict:
    return {
        "prescription_id": "p_restore_cast",
        "shot_id": shot_id, "operation": "restore_cast",
        "parameters": {"source": "responsibility.white_model"},
        "precondition_measurement_ids": [],
        "postcondition_measurement_ids": [],
        "postcondition": "每个需要白模的镜头 characters 非空且只含已确认角色",
    }


def _retime(declared_total: float) -> dict:
    return {
        "prescription_id": "p_total_duration",
        "shot_id": "scene", "operation": "retime_shot",
        "parameters": {"declared_total_seconds": declared_total,
                       "actual_total_seconds": 16.0},
        "precondition_measurement_ids": ["m_scene_total_duration"],
        "postcondition_measurement_ids": ["m_scene_total_duration"],
        "postcondition": "全场时长回到声明总时长（±0.2s）",
    }


def _review_transition() -> dict:
    return {
        "prescription_id": "p_transition_shot_004",
        "shot_id": "shot_004", "operation": "review_transition",
        "parameters": {"from": "shot_003", "to": "shot_004",
                       "angle_degrees": 24.8, "required_degrees": 30.0,
                       "alternative": "change_shot_size"},
        "precondition_measurement_ids": ["m_shot_004_camera_angle_deg"],
        "postcondition_measurement_ids": ["m_shot_004_camera_angle_deg"],
        "postcondition": "角度 >= 30° 或景别至少变化一档",
    }


def test_retime_shot_records_old_and_new_frames():
    plan = _plan()
    plan, records = apply_plan_prescriptions(
        plan, [_retime(12.0)], brief=_Brief(), fps=24)
    record = records[0]
    assert record["operation"] == "retime_shot"
    assert record["applied"] is True
    assert record["old_frames"] == [120, 96, 84, 84]
    assert record["new_frames"] == [90, 72, 63, 63]
    assert plan.total_frames == 288
    assert "preserved" in record["dialogue_policy"]


def test_retime_keeps_minimum_one_frame():
    plan = _plan()
    plan, records = apply_plan_prescriptions(
        plan, [_retime(0.05)], brief=_Brief(), fps=24)
    assert records[0]["applied"] is True
    assert all(frame >= 1 for frame in records[0]["new_frames"])
    assert all(shot.duration_frames >= 1 for shot in plan.shots)


def test_restore_cast_only_reuses_known_brief_names():
    plan = _plan()
    plan, records = apply_plan_prescriptions(
        plan, [_restore_cast("shot_001")], brief=_Brief(), fps=24)
    assert plan.shots[0].characters == ["米迦尔", "伊恩", "偷盗者"]
    assert records[0]["applied"] is True


def test_restore_cast_does_not_invent_unknown_characters():
    plan = _plan()
    plan, records = apply_plan_prescriptions(
        plan, [_restore_cast("shot_002")], brief=_Brief(), fps=24)
    assert plan.shots[1].characters == []
    assert records[0]["applied"] is False


def test_restore_cast_already_satisfied_is_noop_applied():
    plan = _plan()
    plan, records = apply_plan_prescriptions(
        plan, [_restore_cast("shot_003")], brief=_Brief(), fps=24)
    assert plan.shots[2].characters == ["伊恩"]
    assert records[0]["applied"] is True


def test_unknown_operation_raises():
    plan = _plan()
    with pytest.raises(ValueError):
        apply_plan_prescriptions(
            plan, [{"prescription_id": "p_bad", "shot_id": "scene",
                    "operation": "delete_everything", "parameters": {}}],
            brief=_Brief(), fps=24)


def test_review_transition_stays_visible_and_unapplied():
    plan = _plan()
    plan, records = apply_plan_prescriptions(
        plan, [_review_transition()], brief=_Brief(), fps=24)
    assert len(records) == 1
    assert records[0]["operation"] == "review_transition"
    assert records[0]["applied"] is False


def test_record_for_every_prescription_in_order():
    plan = _plan()
    prescriptions = [_retime(12.0), _restore_cast("shot_001"),
                     _review_transition()]
    plan, records = apply_plan_prescriptions(
        plan, prescriptions, brief=_Brief(), fps=24)
    assert [r["prescription_id"] for r in records] == [
        "p_total_duration", "p_restore_cast", "p_transition_shot_004"]
    assert [r["operation"] for r in records] == [
        "retime_shot", "restore_cast", "review_transition"]


def test_retime_on_non_scene_shot_is_not_auto_applied():
    plan = _plan()
    prescription = _retime(12.0)
    prescription["shot_id"] = "shot_001"
    plan, records = apply_plan_prescriptions(
        plan, [prescription], brief=_Brief(), fps=24)
    assert records[0]["applied"] is False
    assert [s.duration_frames for s in plan.shots] == [120, 96, 84, 84]
