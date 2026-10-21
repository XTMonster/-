"""R10（Ticket 07）：粗排 gate 必须有效验证走位路线（walk_path）。

对抗 fixture（spec §2.2 R10）：粗排参考 JSON 的角色路线终点被改错、
路线缺失、或同镜两角色路线交叉（碰撞容差 = 体块半径和 × 0.5，裁决 D5=B）
时，``build_blockout_report`` 必须给出 error finding，``coarse_gate`` 必须
fail；逐段一致时 gate 通过。
"""

from __future__ import annotations

from block_director.cinema.blockout import build_blockout_manifest
from block_director.cinema.blockout_report import (
    E_BLOCKOUT_WALK_PATH_COLLISION,
    E_BLOCKOUT_WALK_PATH_MISMATCH,
    build_blockout_report,
)
from block_director.cinema.pipeline_gates import coarse_gate


def _reference(**overrides):
    doc = {
        "schema_version": "coarse-world-reference/v1",
        "scene_id": "dock_market",
        "characters": [
            {"name": "米迦尔", "position": {"x": -3.0, "y": 0.0, "z": 0.0},
             "facing": [0.0, 1.0, 0.0], "rotation": None, "gaze": None,
             "motion_by_shot": [{
                 "shot_id": "shot_001", "start": [-3.0, 0.0, 0.0],
                 "end": [1.0, 0.0, 0.0], "speed_m_s": 1.0,
             }]},
        ],
        "props": [],
        "anchors": [],
        "camera_intents": [
            {"shot_id": "shot_001", "position": [-0.5, 5.5, 2.0],
             "target": [-0.5, 0.0, 1.0], "lens": 35.0, "fov_deg": 54.4,
             "movement": None, "provenance": "algorithmic_measurement",
             "resolved": True},
        ],
        "shots": [
            {"shot_id": "shot_001", "order": 1, "duration_frames": 72,
             "intent": "米迦尔走向市场", "characters": ["米迦尔"],
             "actions": [{
                 "action_type": "walk_to", "character_id": "米迦尔",
                 "params": {"target_position": [1.0, 0.0, 0.0]},
             }]},
        ],
        "revisions": [],
        "notes": [],
    }
    doc.update(overrides)
    return doc


def _plan():
    return {
        "scene_heading": "第十四街区码头市场",
        "shots": [
            {"shot_id": "shot_001", "order": 1, "intent": "米迦尔走向市场",
             "shot_type": "MS", "duration_frames": 72,
             "characters": ["米迦尔"],
             "actions": [{
                 "action_type": "walk_to", "character_id": "米迦尔",
                 "params": {"target_position": [1.0, 0.0, 0.0]},
             }]},
        ],
    }


def _manifest(reference, plan):
    return build_blockout_manifest(design=reference, plan=plan)


def _report(manifest, expected):
    #: R2 空计划漏洞：expected 声明了主体的镜不得再以 empty=True 占位
    #: （否则新判据会把它当"声明拍对象但场景空"拦下）。声明角色的镜给
    #: 真实渲染数值，计划空镜才允许 empty 豁免。
    per_shot = []
    for row in manifest.get("shot_table") or []:
        shot_id = str(row.get("shot_id") or "")
        exp = next((s for s in expected["shots"]
                    if s["shot_id"] == shot_id), {})
        if exp.get("characters") or exp.get("framing_target"):
            per_shot.append({
                "shot_id": shot_id,
                "composition_score": 92.0,
                "visible_ratio": 1.0,
                "foreground_occlusion_ratio": 0.0,
                "max_subject_area_ratio": 0.4,
                "on_screen_ratio": 0.4,
                "off_screen": False,
                "design_diff": {"max_deviation_m": 0.05},
                "frames": [],
            })
        else:
            per_shot.append({"shot_id": shot_id, "empty": True,
                             "frames": []})
    return build_blockout_report(
        manifest=manifest, per_shot=per_shot,
        manifest_fingerprint="fp1", expected=expected)


def _walk_path_check(report):
    return next(c for c in report["checks"]
                if c["check_id"] == "walk_path")


def _findings(report, check_id):
    return [f for f in report["findings"] if f["check_id"] == check_id]


def test_consistent_walk_path_passes_gate():
    report = _report(_manifest(_reference(), _plan()), _plan())
    assert _walk_path_check(report)["verdict"] == "pass"
    assert _findings(report, E_BLOCKOUT_WALK_PATH_MISMATCH) == []
    assert coarse_gate(report)["passed"] is True


def test_route_end_rewritten_in_reference_fails_gate():
    """对抗：粗排参考 JSON 路线终点被改错 -> manifest.routes 跟随 -> fail。"""
    reference = _reference()
    reference["characters"][0]["motion_by_shot"][0]["end"] = [1.0, 2.0, 0.0]
    report = _report(_manifest(reference, _plan()), _plan())
    assert _walk_path_check(report)["verdict"] == "fail"
    findings = _findings(report, E_BLOCKOUT_WALK_PATH_MISMATCH)
    assert findings and findings[0]["severity"] == "error"
    assert coarse_gate(report)["passed"] is False


def test_missing_route_fails_gate():
    """对抗：计划声明走位但参考 JSON 无该路线 -> fail（不猜）。"""
    reference = _reference()
    reference["characters"][0]["motion_by_shot"] = []
    report = _report(_manifest(reference, _plan()), _plan())
    assert _walk_path_check(report)["verdict"] == "fail"
    assert _findings(report, E_BLOCKOUT_WALK_PATH_MISMATCH)
    assert coarse_gate(report)["passed"] is False


def test_extra_route_not_in_plan_fails_gate():
    """对抗：参考 JSON 多出一条计划未声明的路线 -> fail（逐段一致是双向的）。"""
    reference = _reference()
    reference["characters"][0]["motion_by_shot"].append({
        "shot_id": "shot_001", "start": [1.0, 0.0, 0.0],
        "end": [4.0, 0.0, 0.0], "speed_m_s": 1.0,
    })
    report = _report(_manifest(reference, _plan()), _plan())
    assert _walk_path_check(report)["verdict"] == "fail"
    assert _findings(report, E_BLOCKOUT_WALK_PATH_MISMATCH)
    assert coarse_gate(report)["passed"] is False


def test_crossing_routes_fail_gate_with_d5_tolerance():
    """对抗：同镜两角色路线交叉 -> 碰撞 finding（容差=体块半径和×0.5）。"""
    reference = _reference()
    reference["characters"].append({
        "name": "伊恩", "position": {"x": 0.0, "y": -3.0, "z": 0.0},
        "facing": [0.0, 1.0, 0.0], "rotation": None, "gaze": None,
        "motion_by_shot": [{
            "shot_id": "shot_001", "start": [0.0, -3.0, 0.0],
            "end": [0.0, 3.0, 0.0], "speed_m_s": 1.0,
        }],
    })
    reference["shots"][0]["characters"] = ["米迦尔", "伊恩"]
    plan = _plan()
    plan["shots"][0]["characters"] = ["米迦尔", "伊恩"]
    plan["shots"][0]["actions"].append({
        "action_type": "walk_to", "character_id": "伊恩",
        "params": {"target_position": [0.0, 3.0, 0.0]},
    })
    report = _report(_manifest(reference, plan), plan)
    assert _walk_path_check(report)["verdict"] == "fail"
    collisions = _findings(report, E_BLOCKOUT_WALK_PATH_COLLISION)
    assert collisions and collisions[0]["severity"] == "error"
    assert coarse_gate(report)["passed"] is False


def test_parallel_routes_do_not_collide():
    """同镜并行路线相距 2 m（远大于容差 0.25 m）-> 不判碰撞。"""
    reference = _reference()
    reference["characters"].append({
        "name": "伊恩", "position": {"x": 2.0, "y": -3.0, "z": 0.0},
        "facing": [0.0, 1.0, 0.0], "rotation": None, "gaze": None,
        "motion_by_shot": [{
            "shot_id": "shot_001", "start": [2.0, -3.0, 0.0],
            "end": [2.0, 3.0, 0.0], "speed_m_s": 1.0,
        }],
    })
    reference["shots"][0]["characters"] = ["米迦尔", "伊恩"]
    plan = _plan()
    plan["shots"][0]["characters"] = ["米迦尔", "伊恩"]
    plan["shots"][0]["actions"].append({
        "action_type": "walk_to", "character_id": "伊恩",
        "params": {"target_position": [2.0, 3.0, 0.0]},
    })
    report = _report(_manifest(reference, plan), plan)
    assert _walk_path_check(report)["verdict"] == "pass"
    assert _findings(report, E_BLOCKOUT_WALK_PATH_COLLISION) == []
    assert coarse_gate(report)["passed"] is True
