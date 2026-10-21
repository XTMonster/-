"""Public behaviour of the geometry + VLM correction loop."""

from __future__ import annotations

from block_director.contracts.guard import Confidence, GuardWarning, Severity
from block_director.layer5_orchestrator.correction_candidates import (
    build_correction_candidates,
    correction_candidate_dispositions,
    correction_candidate_lifecycle,
)


def _edge_warning():
    return GuardWarning(
        shot_id="shot_001",
        frame_range=(1, 24),
        type="edge_clip",
        subject="char_001",
        evidence={"edge_clip_ratio": 0.2, "edge_clip_max": 0.05},
        severity=Severity.ERROR,
        confidence=Confidence.HIGH,
    )


def test_each_merged_candidate_has_one_terminal_disposition():
    candidates = build_correction_candidates(
        [_edge_warning()],
        [
            {
                "kind": "subject_cut_by_edge",
                "subject": "char_001",
                "frame": 1,
                "suggested_tool": "reframe",
            },
            {
                "kind": "occluded",
                "subject": "char_002",
                "frame": 12,
                "suggested_tool": "move_character",
            },
        ],
        limit=4,
    )

    assert [item["source"] for item in candidates] == ["both", "vlm"]
    assert all(item["candidate_id"] for item in candidates)
    both, vlm_only = candidates

    dispositions = correction_candidate_dispositions(
        candidates,
        [
            {
                "prescription_id": "p-reframe",
                "candidate_ids": [both["candidate_id"]],
                "applied": True,
            },
            {
                "prescription_id": "p-rejected",
                "candidate_ids": [both["candidate_id"]],
                "applied": False,
                "reason": "axis conflict",
            },
        ],
        shot_id="shot_001",
    )

    by_id = {
        item["candidate_id"]: item for item in dispositions
    }
    assert by_id[both["candidate_id"]]["disposition"] == "applied"
    assert by_id[both["candidate_id"]]["operation_ids"] == [
        "p-reframe",
        "p-rejected",
    ]
    assert by_id[vlm_only["candidate_id"]]["disposition"] == "deferred"
    assert by_id[vlm_only["candidate_id"]]["operation_ids"] == []
    assert all(
        item["shot_id"] == "shot_001"
        and item["disposition"] in {"applied", "rejected", "deferred"}
        for item in dispositions
    )


def test_candidate_ids_show_resolved_persisting_and_new_issues():
    before = [
        {
            "candidate_id": "correction-resolved",
            "kind": "subject_cut_by_edge",
            "subject": "char_001",
        },
        {
            "candidate_id": "correction-persisting",
            "kind": "occluded",
            "subject": "char_002",
        },
    ]
    after = [
        {
            "candidate_id": "correction-persisting",
            "kind": "occluded",
            "subject": "char_002",
        },
        {
            "candidate_id": "correction-new",
            "kind": "lead_room_wrong",
            "subject": "char_001",
        },
    ]

    rows = correction_candidate_lifecycle(
        before,
        after,
        [{
            "prescription_id": "reframe-001",
            "candidate_ids": ["correction-resolved"],
            "applied": True,
        }],
        shot_id="shot_001",
    )

    assert {
        row["candidate_id"]: (
            row["disposition"], row["issue_state"],
        )
        for row in rows
    } == {
        "correction-resolved": ("applied", "resolved"),
        "correction-persisting": ("deferred", "persisting"),
        "correction-new": ("deferred", "new"),
    }
