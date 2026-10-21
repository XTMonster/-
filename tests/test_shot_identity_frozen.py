"""R2 Ticket 07（S2）：精修不得改写镜头主体集合与景别。

验收：
1. 精修试图改 ``characters`` ⇒ 拒绝 + E 类错误 + 计划声明原样保留；
2. ``framing_target`` / ``shot_type`` 同规则；
3. 正常的相机/走位/道具精修不受影响。
"""

from __future__ import annotations

from block_director.cinema.detail_blocking import (
    E_IDENTITY_DRIFT,
    derive_detail_shots,
    identity_freeze_review,
)


def _baseline():
    return {"schema_version": "coarse-baseline/v1", "state": "frozen",
            "reference": {
                "schema_version": "coarse-world-reference/v1",
                "scene_id": "dock_market",
                "characters": [
                    {"name": "米迦尔", "position": {"x": -0.8, "y": 0.0, "z": 0.0},
                     "facing": [0.0, 1.0, 0.0],
                     "gaze": None, "rotation": None, "motion_by_shot": []},
                    {"name": "伊恩", "position": {"x": 0.8, "y": 0.0, "z": 0.0},
                     "facing": [0.0, 1.0, 0.0],
                     "gaze": None, "rotation": None, "motion_by_shot": []},
                ],
                "camera_intents": [{
                    "shot_id": "shot_004", "position": [-0.5, 5.5, 2.0],
                    "target": [-0.2, 0.0, 0.8], "lens": 35.0,
                }],
                "shots": [],
            },
            "manifest": {}, "report": {}, "approval": {"state": "frozen"},
            "reference_fingerprint": "fp", "manifest_fingerprint": "fp2",
            "cameras_fingerprint": "fp3", "report_fingerprint": "fp4",
            "produced_at": "t0", "approved_by": "test",
            "checkpoint_id": "c.blend"}


def _plan(characters=("米迦尔", "伊恩"), shot_type="MS",
          framing_target="米迦尔"):
    return {"shots": [{
        "shot_id": "shot_004", "order": 4, "duration_frames": 96,
        "intent": "米迦尔瞪向伊恩", "characters": list(characters),
        "shot_type": shot_type, "framing_target": framing_target,
        "actions": [], "camera": {"side": "front", "lens": 35},
    }]}


def test_derive_carries_declared_identity_fields():
    """derive 出的 DetailShotContract 必须携带计划声明的身份字段。"""
    shots = derive_detail_shots(baseline=_baseline(), plan=_plan())
    shot = shots[0]
    assert shot["shot_type"] == "MS"
    assert shot["framing_target"] == "米迦尔"
    assert [c["name"] for c in shot["characters"]] == ["米迦尔", "伊恩"]


def test_identity_review_ok_when_matching_plan():
    shots = derive_detail_shots(baseline=_baseline(), plan=_plan())
    findings = identity_freeze_review(detail_shots=shots, plan=_plan())
    assert findings == []


def test_characters_drift_is_rejected_with_e_error_and_plan_kept():
    """验收 1：精修试图把 [米迦尔,伊恩] 改成 [伊恩] ⇒ E 类错误 + 计划保留。"""
    plan = _plan()
    shots = derive_detail_shots(baseline=_baseline(), plan=plan)
    # 模拟精修/构建结果把主体漂移成只剩伊恩（真实缺陷场景）。
    shots[0]["characters"] = [c for c in shots[0]["characters"]
                              if c["name"] == "伊恩"]
    findings = identity_freeze_review(detail_shots=shots, plan=plan)
    assert len(findings) == 1
    assert findings[0]["check_id"] == E_IDENTITY_DRIFT
    assert findings[0]["severity"] == "error"
    assert findings[0]["path"] == "shot_004.characters"
    # 计划声明原样保留。
    assert plan["shots"][0]["characters"] == ["米迦尔", "伊恩"]


def test_shot_type_drift_is_rejected():
    """验收 2：shot_type 被改成 CU ⇒ E 类错误。"""
    plan = _plan(shot_type="MS")
    shots = derive_detail_shots(baseline=_baseline(), plan=plan)
    shots[0]["shot_type"] = "CU"
    findings = identity_freeze_review(detail_shots=shots, plan=plan)
    assert len(findings) == 1
    assert findings[0]["check_id"] == E_IDENTITY_DRIFT
    assert findings[0]["path"] == "shot_004.shot_type"


def test_framing_target_drift_is_rejected():
    """验收 2：framing_target 被改成伊恩 ⇒ E 类错误。"""
    plan = _plan(framing_target="米迦尔")
    shots = derive_detail_shots(baseline=_baseline(), plan=plan)
    shots[0]["framing_target"] = "伊恩"
    findings = identity_freeze_review(detail_shots=shots, plan=plan)
    assert len(findings) == 1
    assert findings[0]["check_id"] == E_IDENTITY_DRIFT
    assert findings[0]["path"] == "shot_004.framing_target"


def test_camera_movement_and_prop_refinement_are_not_blocked():
    """验收 3：正常相机/走位/道具精修不触发身份漂移。"""
    plan = _plan()
    shots = derive_detail_shots(baseline=_baseline(), plan=plan)
    # 相机位置、镜头、道具、动作节拍的精修都不属于身份字段。
    shots[0]["camera"]["position"] = {"x": -1.0, "y": 4.0, "z": 2.0}
    shots[0]["camera"]["lens_mm"] = 50.0
    shots[0]["beats"] = [{
        "frame": 1, "kind": "start", "note": "动作精修",
        "actions": [{"frame": 1, "action": "抬手", "parameter": None,
                     "target": None}]}]
    findings = identity_freeze_review(detail_shots=shots, plan=plan)
    assert findings == []


def test_identity_drift_blocks_detail_review_verdict():
    """身份漂移必须让细排审核判定 all_ok=False。"""
    from block_director.cinema.detail_review import detail_review_verdict
    plan = _plan()
    shots = derive_detail_shots(baseline=_baseline(), plan=plan)
    shots[0]["characters"] = [c for c in shots[0]["characters"]
                              if c["name"] == "伊恩"]
    blockout_report = {"schema_version": "blockout-report/v1",
                       "verdict": "pass",
                       "findings": [], "checks": [{
                           "check_id": "composition", "shot_id": "shot_004",
                           "actual": 82.0, "threshold": 80.0,
                           "verdict": "pass"}]}
    verdict = detail_review_verdict(detail_shots=shots,
                                    blockout_report=blockout_report,
                                    baseline=_baseline(),
                                    plan=plan)
    assert verdict["all_ok"] is False
    assert verdict["per_shot"]["shot_004"]["identity"] >= 1


def test_detail_review_without_plan_keeps_zero_shape_difference():
    """plan 缺省（None）时身份校验不启用，既有行为不变。"""
    from block_director.cinema.detail_review import detail_review_verdict
    plan = _plan()
    shots = derive_detail_shots(baseline=_baseline(), plan=plan)
    blockout_report = {"schema_version": "blockout-report/v1",
                       "verdict": "pass",
                       "findings": [], "checks": [{
                           "check_id": "composition", "shot_id": "shot_004",
                           "actual": 82.0, "threshold": 80.0,
                           "verdict": "pass"}]}
    verdict = detail_review_verdict(detail_shots=shots,
                                    blockout_report=blockout_report,
                                    baseline=_baseline())
    assert verdict["all_ok"] is True
