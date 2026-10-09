"""v1.6 G2：标签全帧自检的交付接线（README 段 + 审计事件字段）。"""

from __future__ import annotations

from block_director.contracts.audit import V16_EVENT_FIELDS
from block_director.contracts.plan import Plan, ShotPlan
from block_director.delivery.manifest import build_manifest
from block_director.delivery.readme import render_readme
from block_director.layer5_orchestrator.driver import (
    label_overlap_event_fields,
)


def _manifest():
    plan = Plan(shots=[
        ShotPlan(shot_id="shot_001", intent="开场", shot_type="MS",
                 duration_frames=48),
    ])
    return build_manifest(plan)


def test_readme_silent_without_report(tmp_path):
    text = render_readme(_manifest(), out_dir=tmp_path)
    assert "## 标签全帧自检" not in text


def test_readme_silent_for_empty_report(tmp_path):
    empty = {"max_overlap_ratio": 0.0, "overlap_frames": [],
             "frames_checked": 96, "limit": 0.05}
    text = render_readme(_manifest(), out_dir=tmp_path,
                         label_overlap_report=empty)
    assert "## 标签全帧自检" not in text


def test_readme_renders_overlap_summary(tmp_path):
    report = {"max_overlap_ratio": 0.083, "overlap_frames": [7, 11, 24],
              "frames_checked": 96, "limit": 0.05}
    text = render_readme(_manifest(), out_dir=tmp_path,
                         label_overlap_report=report)
    assert "## 标签全帧自检" in text
    assert "3 帧" in text
    assert "5%" in text
    assert "8.3%" in text
    assert "7, 11, 24" in text


def test_event_fields_match_the_contract_and_bake_output():
    summary = {"label_report": {"labels": 2, "frames": 96,
                                "label_overlap_report": {
                                    "max_overlap_ratio": 0.083,
                                    "overlap_frames": [7, 11, 24],
                                    "frames_checked": 96,
                                    "limit": 0.05}}}
    fields = label_overlap_event_fields(summary)
    assert set(fields) == set(V16_EVENT_FIELDS["label_overlap_report"])
    assert fields == {"max_overlap_ratio": 0.083,
                      "overlap_frames": [7, 11, 24],
                      "frames_checked": 96, "limit": 0.05}


def test_event_fields_cover_the_empty_report_too():
    summary = {"label_report": {"label_overlap_report": {
        "max_overlap_ratio": 0.0, "overlap_frames": [],
        "frames_checked": 0, "limit": 0.05}}}
    fields = label_overlap_event_fields(summary)
    assert set(fields) == set(V16_EVENT_FIELDS["label_overlap_report"])
    assert fields["overlap_frames"] == []
    assert fields["max_overlap_ratio"] == 0.0


def test_no_label_report_means_no_event():
    assert label_overlap_event_fields({"shots": 1}) is None
    assert label_overlap_event_fields({}) is None
