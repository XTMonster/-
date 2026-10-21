"""粗排回溯分数必须纳入构图通过率（2026-10-21 真跑：
4 镜 composition 20/20/77/77 全 fail，分数若只看 error 则回溯永远放弃）。
"""

from __future__ import annotations

import json

from block_director.layer5_orchestrator.driver import _coarse_plan_score


def _report_path(tmp_path, scores):
    report = {
        "schema_version": "blockout-report/v1",
        "verdict": "fail",
        "checks": [
            {"check_id": "composition", "shot_id": f"shot_{i+1:03d}",
             "actual": score, "threshold": 80.0,
             "verdict": "pass" if score and score > 80.0 else "fail"}
            for i, score in enumerate(scores)
        ],
        "findings": [],
    }
    p = tmp_path / "blockout_report.json"
    p.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    return p


def test_score_reflects_composition_pass_rate(tmp_path):
    p = _report_path(tmp_path, [85.0, 90.0, 95.0, 80.0])
    payload = {"rounds": [], "findings": [],
               "artifacts": {"blockout_report": str(p)}}
    score = _coarse_plan_score(payload)
    # 3/4 通过 -> 75 分；无 error -> 75
    assert score == 75.0


def test_all_fail_scores_zero(tmp_path):
    p = _report_path(tmp_path, [20.0, 20.0, 77.0, 77.0])
    payload = {"rounds": [], "findings": [],
               "artifacts": {"blockout_report": str(p)}}
    score = _coarse_plan_score(payload)
    assert score == 0.0


def test_all_pass_scores_hundred(tmp_path):
    p = _report_path(tmp_path, [81.0, 90.0, 95.0, 88.0])
    payload = {"rounds": [], "findings": [],
               "artifacts": {"blockout_report": str(p)}}
    score = _coarse_plan_score(payload)
    assert score == 100.0


def test_errors_penalize_score(tmp_path):
    p = _report_path(tmp_path, [85.0, 90.0])
    payload = {"rounds": [{"findings": 2}], "findings": [],
               "artifacts": {"blockout_report": str(p)}}
    score = _coarse_plan_score(payload)
    assert score == 98.0      # 100 - 2 error


def test_missing_report_scores_zero():
    assert _coarse_plan_score({}) == 0.0
