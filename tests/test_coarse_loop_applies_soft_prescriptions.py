"""粗排修正循环必须应用构图软处方（2026-10-21 真跑：
only_hard=True 导致构图 20/77 不放行也不收敛，直接 approved）。
"""

from __future__ import annotations

from block_director.cinema.coarse_loop import run_coarse_revision_loop
from block_director.cinema.coarse_revision import effective_shot_reference
from block_director.layer5_orchestrator.coarse_agent import (
    OfflineFixtureCoarseProposalProvider,
)


def _overlapped_reference():
    return {
        "characters": [
            {"name": "米迦尔", "position": {"x": -0.3, "y": 0.0, "z": 0.0},
             "facing": [1.0, 0.0, 0.0]},
            {"name": "伊恩", "position": {"x": -0.3, "y": 0.0, "z": 0.0},
             "facing": [0.0, 1.0, 0.0]},
        ],
        "camera_intents": [
            {"shot_id": "shot_001", "position": [-0.3, 3.0, 1.2],
             "target": [-0.3, 0.0, 1.4], "lens": 50.0},
        ],
        "shots": [
            {"shot_id": "shot_001", "characters": ["米迦尔", "伊恩"]},
        ],
        "revisions": [],
    }


def test_loop_applies_character_separation_when_composition_fails():
    ref = _overlapped_reference()

    def report_loader(current):
        # 第一次观察：composition fail；第二次观察：仍在循环中（这里让
        # 它在应用站位后返回 composition pass，模拟收敛）。
        effective = effective_shot_reference(current, "shot_001")
        chars = {
            c["name"]: c for c in effective.get("characters") or []}
        a = chars["米迦尔"]["position"]
        b = chars["伊恩"]["position"]
        gap = ((a["x"] - b["x"]) ** 2 + (a["z"] - b["z"]) ** 2) ** 0.5
        score = 90.0 if gap > 0.8 else 20.0
        return {
            "verdict": "fail" if score <= 80 else "pass",
            "checks": [
                {"check_id": "composition", "shot_id": "shot_001",
                 "actual": score, "threshold": 80.0,
                 "verdict": "fail" if score <= 80 else "pass"},
            ],
            "findings": [],
        }

    def rebuild(current):
        return None

    outcome = run_coarse_revision_loop(
        reference=ref, report_loader=report_loader, rebuild=rebuild,
        proposal_provider=OfflineFixtureCoarseProposalProvider(),
        max_revisions=10)
    assert outcome["status"] == "approved", outcome
    effective = effective_shot_reference(outcome["reference"], "shot_001")
    chars = {c["name"]: c for c in effective["characters"]}
    a = chars["米迦尔"]["position"]
    b = chars["伊恩"]["position"]
    gap = ((a["x"] - b["x"]) ** 2 + (a["z"] - b["z"]) ** 2) ** 0.5
    assert gap > 0.8
    assert any(
        r.get("component") == "character_position"
        for rev in outcome["rounds"]
        for r in rev["prescriptions"])
