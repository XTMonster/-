from __future__ import annotations

from types import SimpleNamespace

from block_director.layer5_orchestrator.driver import (
    ResumeState, save_resume_state, load_resume_state,
)
from tools.run_headless import (
    _delivered_shots_from_report,
    _passed_shots_from_report,
    _write_delivered_state,
)


def _report():
    return SimpleNamespace(shots=[
        {"shot_id": "shot_002", "video": "blockout_shot_002.mp4"},
        {"shot_id": "shot_003", "video": None, "failed": True},
        {"shot_id": "shot_004", "video": "blockout_shot_004.mp4"},
    ])


def test_only_rendered_mp4_shots_are_delivered():
    assert _delivered_shots_from_report(_report()) == ["shot_002", "shot_004"]


def test_passed_shots_are_the_non_failed_delivered_subset():
    report = SimpleNamespace(shots=[
        {"shot_id": "shot_001", "video": "blockout_shot_001.mp4"},
        {"shot_id": "shot_002", "video": "blockout_shot_002.mp4",
         "failed": True},
        {"shot_id": "shot_003", "video": None, "failed": True},
    ])
    assert _passed_shots_from_report(report) == ["shot_001"]


def test_success_export_writes_back_delivered(tmp_path):
    path = tmp_path / "resume_state.json"
    save_resume_state(path, ResumeState(delivered_shots=["shot_001"]))
    updated = _write_delivered_state(path, _report())
    assert updated == ["shot_001", "shot_002", "shot_004"]
    assert load_resume_state(path).delivered_shots == updated
