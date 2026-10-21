"""R10（Ticket 07）：粗排 gate 必须有效验证分镜序列/时长（shot_sequence）。

对抗 fixture（spec §2.2 R10）：粗排参考 JSON 的 ``shots[]`` 顺序被颠倒、
或 ``manifest.shot_table`` 被改错（顺序/时长/镜数）时，
``build_blockout_report`` 必须给出 ``E_BLOCKOUT_SHOT_SEQUENCE_MISMATCH``
error finding，``coarse_gate`` 必须 fail；一致时 gate 通过。
偏差要求为 0（spec：``actual == expected``，一字不改）。
"""

from __future__ import annotations

from block_director.cinema.blockout import build_blockout_manifest
from block_director.cinema.blockout_report import (
    E_BLOCKOUT_SHOT_SEQUENCE_MISMATCH,
    build_blockout_report,
)
from block_director.cinema.pipeline_gates import coarse_gate


def _reference(**overrides):
    """粗排参考世界坐标 JSON（单一真源；含 shots[] 语义层）。"""
    doc = {
        "schema_version": "coarse-world-reference/v1",
        "scene_id": "dock_market",
        "characters": [
            {"name": "米迦尔", "position": {"x": -0.9, "y": 0.0, "z": 0.0},
             "facing": [0.0, 1.0, 0.0], "rotation": None, "gaze": None,
             "motion_by_shot": []},
        ],
        "props": [],
        "anchors": [],
        "camera_intents": [
            {"shot_id": "shot_001", "position": [-0.9, 4.66, 0.62],
             "target": [-0.9, 0.0, 1.0], "lens": 35.0, "fov_deg": 54.4,
             "movement": None, "provenance": "algorithmic_measurement",
             "resolved": True},
            {"shot_id": "shot_002", "position": [0.0, 5.0, 1.6],
             "target": [0.0, 0.0, 1.0], "lens": 35.0, "fov_deg": 54.4,
             "movement": None, "provenance": "algorithmic_measurement",
             "resolved": True},
        ],
        "shots": [
            {"shot_id": "shot_001", "order": 1, "duration_frames": 24,
             "intent": "开场", "characters": ["米迦尔"], "actions": []},
            {"shot_id": "shot_002", "order": 2, "duration_frames": 12,
             "intent": "空镜：市场通道", "characters": [], "actions": []},
        ],
        "revisions": [],
        "notes": [],
    }
    doc.update(overrides)
    return doc


def _plan():
    """原始计划（expected 侧；粗排世界 JSON 应逐项与它一致）。"""
    return {
        "scene_heading": "第十四街区码头市场",
        "shots": [
            {"shot_id": "shot_001", "order": 1, "intent": "开场",
             "shot_type": "MS", "duration_frames": 24,
             "characters": ["米迦尔"], "actions": []},
            {"shot_id": "shot_002", "order": 2, "intent": "空镜：市场通道",
             "shot_type": "MS", "duration_frames": 12,
             "characters": [], "actions": []},
        ],
    }


def _manifest(reference, plan):
    return build_blockout_manifest(design=reference, plan=plan)


def _report(manifest, expected):
    #: R2 空计划漏洞：expected 声明了主体的镜不得再以 empty=True 占位
    #: （否则新判据会把它当"声明拍对象但场景空"拦下）。声明角色的镜给
    #: 真实渲染数值，计划空镜才允许 empty 豁免——per_shot 与 expected
    #: 语义一致，测试仍然只考察 shot_sequence check。
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


def _shot_sequence_check(report):
    return next(c for c in report["checks"]
                if c["check_id"] == "shot_sequence")


def _sequence_findings(report):
    return [f for f in report["findings"]
            if f["check_id"] == E_BLOCKOUT_SHOT_SEQUENCE_MISMATCH]


def test_consistent_shot_sequence_passes_gate():
    reference = _reference()
    manifest = _manifest(reference, _plan())
    report = _report(manifest, _plan())
    check = _shot_sequence_check(report)
    assert check["verdict"] == "pass"
    assert check["actual"] == check["expected"]
    assert _sequence_findings(report) == []
    assert coarse_gate(report)["passed"] is True


def test_swapped_order_in_reference_fails_gate():
    """对抗：粗排参考 JSON 的 shots[] 顺序被颠倒 -> manifest 跟随 -> fail。"""
    reference = _reference()
    #: order 是规范序列：shot_001 变为第 2 镜、shot_002 变为第 1 镜
    reference["shots"][0]["order"], reference["shots"][1]["order"] = 2, 1
    manifest = _manifest(reference, _plan())
    report = _report(manifest, _plan())
    check = _shot_sequence_check(report)
    assert check["verdict"] == "fail"
    findings = _sequence_findings(report)
    assert findings and findings[0]["severity"] == "error"
    assert coarse_gate(report)["passed"] is False


def test_swapped_shot_table_order_fails_gate():
    """对抗：manifest.shot_table 的镜号顺序被颠倒 -> fail（偏差 0）。"""
    manifest = _manifest(_reference(), _plan())
    rows = manifest["shot_table"]
    rows[0], rows[1] = rows[1], rows[0]
    rows[0]["order"], rows[1]["order"] = 1, 2  #: 交换时 order 一起换
    report = _report(manifest, _plan())
    assert _shot_sequence_check(report)["verdict"] == "fail"
    assert _sequence_findings(report)
    assert coarse_gate(report)["passed"] is False


def test_duration_mismatch_fails_gate():
    """对抗：分镜时长被改（end_frame 与 plan duration_frames 偏差非 0）。"""
    manifest = _manifest(_reference(), _plan())
    manifest["shot_table"][0]["end_frame"] = 48  # 计划 24 -> 时长翻倍
    report = _report(manifest, _plan())
    check = _shot_sequence_check(report)
    assert check["verdict"] == "fail"
    assert _sequence_findings(report)
    assert coarse_gate(report)["passed"] is False


def test_shot_count_mismatch_fails_gate():
    """对抗：manifest 少一镜 -> 数量不符 -> fail。"""
    manifest = _manifest(_reference(), _plan())
    manifest["shot_table"] = [manifest["shot_table"][0]]
    report = _report(manifest, _plan())
    assert _shot_sequence_check(report)["verdict"] == "fail"
    assert _sequence_findings(report)
    assert coarse_gate(report)["passed"] is False


def test_without_expected_no_new_checks_old_callers_unchanged():
    """回归守卫：未提供 expected（旧调用方）不追加新 check，行为不变。"""
    manifest = _manifest(_reference(), _plan())
    report = build_blockout_report(
        manifest=manifest, per_shot=[], manifest_fingerprint="fp1")
    assert "shot_sequence" not in [c["check_id"] for c in report["checks"]]
