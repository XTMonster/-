"""Ticket 06（纯层）：逐镜细排审核判定。

细排阶段不改变冻结空间：逐镜审核 = 无空间漂移 error + 无粗排硬伤 error +
构图可测（软指标记录不阻塞，按项目裁决 T07）；全镜 ok 才允许序列回放与
final gate。
"""

from __future__ import annotations

from block_director.cinema.detail_review import (
    detail_review_verdict,
)


def _baseline():
    return {"state": "frozen", "reference": {
        "characters": [
            {"name": "米迦尔", "position": {"x": -0.8, "y": 0.0, "z": 0.0}},
        ],
        "camera_intents": [{
            "shot_id": "shot_001", "position": [-0.5, 5.5, 2.0],
            "target": [-0.2, 0.0, 0.8], "lens": 35.0,
        }],
    }}


def _detail_shots():
    return [{
        "schema_version": "detail-shot-contract/v1",
        "shot_id": "shot_001", "order": 1,
        "start_frame": 1, "end_frame": 96,
        "characters": [{"name": "米迦尔",
                        "position": {"x": -0.8, "y": 0.0, "z": 0.0},
                        "source": "frozen_baseline"}],
        "props": [], "camera": {"position": [-0.5, 5.5, 2.0],
                                "target": [-0.2, 0.0, 0.8],
                                "lens_mm": 35.0, "movements": []},
        "beats": [], "audio_proxy": [],
    }]


def _report(findings=(), checks=()):
    return {"schema_version": "blockout-report/v1", "verdict": "fail",
            "findings": [dict(f) for f in findings],
            "checks": [dict(c) for c in checks]}


def test_detail_review_ok_when_no_drift_no_errors_and_composition_measured():
    report = _report(checks=[{
        "check_id": "composition", "shot_id": "shot_001",
        "actual": 81.5, "threshold": 80.0, "verdict": "pass",
    }])
    verdict = detail_review_verdict(detail_shots=_detail_shots(),
                                    blockout_report=report,
                                    baseline=_baseline())
    assert verdict["all_ok"] is True
    assert verdict["per_shot"]["shot_001"]["ok"] is True
    assert verdict["per_shot"]["shot_001"]["composition"] == 81.5


def test_detail_review_blocks_on_spatial_drift_error():
    shots = _detail_shots()
    shots[0]["characters"][0]["position"] = {"x": 9.9, "y": 9.9, "z": 9.9}
    report = _report()
    verdict = detail_review_verdict(detail_shots=shots,
                                    blockout_report=report,
                                    baseline=_baseline())
    assert verdict["all_ok"] is False
    assert verdict["per_shot"]["shot_001"]["drift"] >= 1


def test_detail_review_blocks_on_coarse_error_finding():
    report = _report(findings=[{
        "check_id": "E_BLOCKOUT_EMPTY_WALL", "shot_id": "shot_001",
        "severity": "error", "message": "空墙",
    }])
    verdict = detail_review_verdict(detail_shots=_detail_shots(),
                                    blockout_report=report,
                                    baseline=_baseline())
    assert verdict["all_ok"] is False
    assert verdict["per_shot"]["shot_001"]["errors"] >= 1


def test_composition_soft_fail_is_recorded_but_not_blocking():
    report = _report(checks=[{
        "check_id": "composition", "shot_id": "shot_001",
        "actual": 61.7, "threshold": 80.0, "verdict": "fail",
    }])
    verdict = detail_review_verdict(detail_shots=_detail_shots(),
                                    blockout_report=report,
                                    baseline=_baseline())
    assert verdict["all_ok"] is True  #: 软指标不阻塞（项目裁决 T07）
    assert verdict["per_shot"]["shot_001"]["composition_warning"] is True
