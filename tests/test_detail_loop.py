"""Public behaviour of the per-shot detail revision loop."""

from __future__ import annotations

import copy

import pytest

from block_director.cinema.detail_loop import (
    DetailLoopBlocked,
    run_detail_revision_loop,
)


def _reference():
    return {
        "schema_version": "coarse-world-reference/v1",
        "scene_id": "node123",
        "characters": [
            {
                "name": "米迦尔",
                "position": {"x": 0.0, "y": 0.0, "z": 0.0},
                "facing": [0.0, 1.0, 0.0],
            },
            {
                "name": "伊恩",
                "position": {"x": 1.0, "y": 0.0, "z": 0.0},
                "facing": [0.0, -1.0, 0.0],
            },
        ],
        "props": [],
        "anchors": [],
        "camera_intents": [
            {
                "shot_id": "shot_001",
                "position": [0.0, 3.0, 1.5],
                "target": [0.0, 0.0, 1.0],
                "lens": 35.0,
            },
            {
                "shot_id": "shot_002",
                "position": [3.0, 0.0, 1.5],
                "target": [1.0, 0.0, 1.0],
                "lens": 50.0,
            },
        ],
        "shots": [
            {
                "shot_id": "shot_001",
                "order": 1,
                "duration_frames": 24,
                "characters": ["米迦尔"],
            },
            {
                "shot_id": "shot_002",
                "order": 2,
                "duration_frames": 24,
                "characters": ["伊恩"],
            },
        ],
        "shot_staging": {},
        "revisions": [],
    }


def _detail_shots():
    return [
        {
            "shot_id": "shot_001",
            "characters": [{"name": "米迦尔"}],
        },
        {
            "shot_id": "shot_002",
            "characters": [{"name": "伊恩"}],
        },
    ]


def _world_x_from_reference(reference, shot_id):
    staging = (reference.get("shot_staging") or {}).get(shot_id) or {}
    entity = "米迦尔" if shot_id == "shot_001" else "伊恩"
    if entity in staging:
        return float(staging[entity]["position"]["x"])
    character = next(
        item for item in reference["characters"]
        if item["name"] == entity
    )
    return float(character["position"]["x"])


def _observation(
    *,
    observation_id,
    shot_id,
    score,
    complete=True,
    hard_error=False,
    world_x=0.0,
    reference=None,
):
    findings = []
    if hard_error:
        findings.append({
            "check_id": "E_BLOCKOUT_EMPTY_WALL",
            "shot_id": shot_id,
            "severity": "error",
            "message": "injected hard error",
        })
    return {
        "observation_id": observation_id,
        "complete": bool(complete),
        "errors": [] if complete else ["missing first/middle/last frames"],
        "reference": copy.deepcopy(reference or _reference()),
        "manifest": {"scene_id": "node123", "cameras": [],
                     "shot_table": []},
        "report": {
            "schema_version": "blockout-report/v1",
            "findings": findings,
            "checks": [{
                "check_id": "composition",
                "shot_id": shot_id,
                "actual": score,
                "threshold": 80.0,
                "verdict": (
                    "pass"
                    if isinstance(score, (int, float)) and score > 80.0
                    else "fail"
                ),
            }],
        },
        "world_state": {
            "shot_states": {
                shot_id: {
                    "characters": {"subject": {"position": [world_x, 0, 0]}},
                    "cameras": {
                        shot_id: {"position": [0, 3, 1.5],
                                  "target": [0, 0, 1]},
                    },
                },
            },
        },
        "frames": [
            {
                "shot_id": shot_id,
                "frame": frame,
                "phase": phase,
                "path": f"/evidence/{shot_id}_{phase}.png",
                "file_sha256": "a" * 64,
                "pixel_sha256": "b" * 64,
                "readable": True,
            }
            for frame, phase in (
                (1, "first"),
                (12, "middle"),
                (24, "last"),
            )
        ],
    }


def _proposal(shot_id, *, x=0.25):
    entity = "米迦尔" if shot_id == "shot_001" else "伊恩"
    return {
        "schema_version": "coarse-proposal/v1",
        "provider_kind": "agent",
        "reason": f"improve {shot_id}",
        "prescriptions": [{
            "prescription_id": f"detail_{shot_id}",
            "scope": "character",
            "shot_id": shot_id,
            "entity": entity,
            "component": "character_position",
            "target_value": {"x": x, "y": 0.0, "z": 0.0},
            "reason": "move subject inside the framing window",
            "evidence_refs": ["composition:fail"],
        }],
    }


def test_one_passed_shot_survives_another_shots_failure():
    observations = {
        "shot_001": [_observation(
            observation_id="obs-1-pass",
            shot_id="shot_001",
            score=82.0,
        )],
        "shot_002": [_observation(
            observation_id="obs-2-fail",
            shot_id="shot_002",
            score=70.0,
        )],
    }
    sequence_calls = []

    outcome = run_detail_revision_loop(
        detail_shots=_detail_shots(),
        reference=_reference(),
        observe=lambda reference, shot_id: observations[shot_id].pop(0),
        rebuild=lambda reference, shot_id: None,
        restore_best=lambda reference, shot_id: None,
        proposal_provider=None,
        sequence_review=lambda reference: sequence_calls.append(reference)
        or {"verdict": "pass"},
    )

    assert outcome["status"] == "blocked"
    assert outcome["shots"]["shot_001"]["status"] == "passed"
    assert outcome["shots"]["shot_001"]["adopted_version"] == 0
    assert outcome["shots"]["shot_002"]["status"] == "failed"
    assert outcome["shots"]["shot_002"]["blocked_code"] == (
        "agent_proposal_unavailable")
    assert sequence_calls == []


def test_later_passed_shot_cannot_mask_an_earlier_failed_shot():
    observations = {
        "shot_001": [_observation(
            observation_id="obs-1-fail",
            shot_id="shot_001",
            score=70.0,
        ), _observation(
            observation_id="obs-1-fail-2",
            shot_id="shot_001",
            score=70.0,
            world_x=0.25,
        )],
        "shot_002": [_observation(
            observation_id="obs-2-fail",
            shot_id="shot_002",
            score=70.0,
        ), _observation(
            observation_id="obs-2-pass",
            shot_id="shot_002",
            score=82.0,
        )],
    }
    sequence_calls = []

    outcome = run_detail_revision_loop(
        detail_shots=_detail_shots(),
        reference=_reference(),
        observe=lambda reference, shot_id: observations[shot_id].pop(0),
        rebuild=lambda reference, shot_id: None,
        restore_best=lambda reference, shot_id: None,
        proposal_provider=lambda *, request: _proposal(next(
            str(check["shot_id"])
            for check in request.report["checks"]
            if check.get("check_id") == "composition"
        )),
        max_revisions=1,
        sequence_review=lambda reference: sequence_calls.append(reference)
        or {"verdict": "pass"},
    )

    assert outcome["status"] == "blocked"
    assert outcome["shots"]["shot_001"]["status"] == "failed"
    assert outcome["shots"]["shot_002"]["status"] == "passed"
    assert outcome["sequence_review"]["shot_phase"]["all_passed"] is False
    assert sequence_calls == []


def test_successive_improvements_replace_best_until_the_shot_passes():
    observations = iter([
        _observation(
            observation_id="obs-base", shot_id="shot_001",
            score=70.0, world_x=0.0),
        _observation(
            observation_id="obs-mid", shot_id="shot_001",
            score=75.0, world_x=0.25),
        _observation(
            observation_id="obs-pass", shot_id="shot_001",
            score=82.0, world_x=0.5),
    ])
    restores = []

    outcome = run_detail_revision_loop(
        detail_shots=[_detail_shots()[0]],
        reference=_reference(),
        observe=lambda reference, shot_id: next(observations),
        rebuild=lambda reference, shot_id: None,
        restore_best=lambda reference, shot_id: restores.append(shot_id),
        proposal_provider=lambda *, request: _proposal(
            "shot_001", x=0.25 if request.round_no == 1 else 0.5),
        sequence_review=lambda reference: {"verdict": "pass"},
    )

    shot = outcome["shots"]["shot_001"]
    assert outcome["status"] == "approved"
    assert shot["status"] == "passed"
    assert shot["best_version"] == 2
    assert shot["adopted_version"] == 2
    assert shot["best_score"] == 82.0
    assert [item["score"] for item in shot["versions"]] == [
        70.0, 75.0, 82.0]
    assert restores == []


def test_regression_restores_the_physical_best_and_keeps_it_for_diagnostic():
    observations = iter([
        _observation(
            observation_id="obs-best", shot_id="shot_001",
            score=75.0, world_x=0.25),
        _observation(
            observation_id="obs-worse", shot_id="shot_001",
            score=69.0, world_x=9.0),
    ])
    restore_calls = []

    outcome = run_detail_revision_loop(
        detail_shots=[_detail_shots()[0]],
        reference=_reference(),
        observe=lambda reference, shot_id: next(observations),
        rebuild=lambda reference, shot_id: None,
        restore_best=lambda reference, shot_id: restore_calls.append(
            (copy.deepcopy(reference), shot_id)),
        proposal_provider=lambda *, request: _proposal("shot_001", x=9.0),
        max_revisions=1,
    )

    shot = outcome["shots"]["shot_001"]
    assert outcome["status"] == "blocked"
    assert shot["status"] == "failed"
    assert shot["best_version"] == 0
    assert shot["best_score"] == 75.0
    assert shot["versions"][-1]["disposition"] == "revert"
    assert len(restore_calls) == 1
    assert restore_calls[0][1] == "shot_001"
    assert outcome["reference"]["shot_staging"] == {}


def test_identical_candidate_score_is_a_tie_and_restores_best():
    observations = iter([
        _observation(
            observation_id="obs-best", shot_id="shot_001",
            score=75.0, world_x=0.25),
        _observation(
            observation_id="obs-tie", shot_id="shot_001",
            score=75.0, world_x=0.5),
    ])
    restore_calls = []

    outcome = run_detail_revision_loop(
        detail_shots=[_detail_shots()[0]],
        reference=_reference(),
        observe=lambda reference, shot_id: next(observations),
        rebuild=lambda reference, shot_id: None,
        restore_best=lambda reference, shot_id: restore_calls.append(shot_id),
        proposal_provider=lambda *, request: _proposal("shot_001", x=0.5),
        max_revisions=1,
    )

    shot = outcome["shots"]["shot_001"]
    assert shot["versions"][-1]["disposition"] == "tie"
    assert shot["best_version"] == 0
    assert shot["best_score"] == 75.0
    assert restore_calls == ["shot_001"]


def test_repeated_physical_state_stops_the_shot_and_restores_best():
    restore_calls = []

    def observe(reference, shot_id):
        world_x = _world_x_from_reference(reference, shot_id)
        score = 75.0 if world_x == 0.5 else 70.0
        return _observation(
            observation_id=f"obs-x-{world_x}",
            shot_id=shot_id,
            score=score,
            world_x=world_x,
            reference=reference,
        )

    outcome = run_detail_revision_loop(
        detail_shots=[_detail_shots()[0]],
        reference=_reference(),
        observe=observe,
        rebuild=lambda reference, shot_id: None,
        restore_best=lambda reference, shot_id: restore_calls.append(shot_id),
        proposal_provider=lambda *, request: _proposal(
            "shot_001",
            x=0.5 if request.round_no == 1 else 0.0,
        ),
    )

    shot = outcome["shots"]["shot_001"]
    assert shot["status"] == "failed"
    assert shot["blocked_code"] == "candidate_cycle_detected"
    assert shot["best_score"] == 75.0
    assert shot["versions"][-1]["disposition"] == "candidate_cycle"
    assert restore_calls == ["shot_001"]


def test_user_owned_animation_conflict_blocks_without_retrying_or_overwriting():
    observations = iter([
        _observation(
            observation_id="obs-base", shot_id="shot_001",
            score=70.0, world_x=0.0),
        _observation(
            observation_id="obs-candidate", shot_id="shot_001",
            score=69.0, world_x=0.25),
    ])

    def restore_best(reference, shot_id):
        raise DetailLoopBlocked(
            "automatic restore would overwrite user-owned animation",
            code="user_animation_conflict",
        )

    outcome = run_detail_revision_loop(
        detail_shots=[_detail_shots()[0]],
        reference=_reference(),
        observe=lambda reference, shot_id: next(observations),
        rebuild=lambda reference, shot_id: None,
        restore_best=restore_best,
        proposal_provider=lambda *, request: _proposal("shot_001"),
        max_revisions=3,
        no_gain_limit=1,
    )

    shot = outcome["shots"]["shot_001"]
    assert shot["status"] == "blocked"
    assert shot["blocked_code"] == "user_animation_conflict"
    assert "user-owned animation" in shot["blocked_reason"]
    assert len(shot["versions"]) == 2


def test_cross_shot_candidate_is_rejected_and_neighbor_reference_is_unchanged():
    observations = iter([
        _observation(
            observation_id="obs-base", shot_id="shot_001",
            score=70.0, world_x=0.0),
    ])
    reference = _reference()
    original_neighbor = copy.deepcopy(reference["camera_intents"][1])

    outcome = run_detail_revision_loop(
        detail_shots=[_detail_shots()[0]],
        reference=reference,
        observe=lambda current, shot_id: next(observations),
        rebuild=lambda current, shot_id: None,
        restore_best=lambda current, shot_id: None,
        proposal_provider=lambda *, request: {
            "schema_version": "coarse-proposal/v1",
            "provider_kind": "agent",
            "reason": "invalid global edit",
            "prescriptions": [{
                "prescription_id": "moves_neighbor",
                "scope": "character",
                "shot_id": "shot_002",
                "entity": "伊恩",
                "component": "character_position",
                "target_value": {"x": 9.0, "y": 0.0, "z": 0.0},
                "reason": "wrong shot",
                "evidence_refs": ["composition:fail"],
            }],
        },
    )

    shot = outcome["shots"]["shot_001"]
    assert shot["status"] == "failed"
    assert shot["blocked_code"] == "proposal_scope_violation"
    assert outcome["reference"]["camera_intents"][1] == original_neighbor
    assert outcome["reference"].get("shot_staging") == {}


def test_sequence_review_runs_only_after_every_non_empty_shot_passes():
    observations = {
        "shot_001": [_observation(
            observation_id="obs-1", shot_id="shot_001", score=82.0)],
        "shot_002": [_observation(
            observation_id="obs-2", shot_id="shot_002", score=81.0)],
    }
    calls = []

    outcome = run_detail_revision_loop(
        detail_shots=_detail_shots(),
        reference=_reference(),
        observe=lambda reference, shot_id: observations[shot_id].pop(0),
        rebuild=lambda reference, shot_id: None,
        restore_best=lambda reference, shot_id: None,
        proposal_provider=None,
        sequence_review=lambda reference: calls.append(
            copy.deepcopy(reference)) or {
                "verdict": "fail",
                "findings": [{"check_id": "rhythm", "severity": "error"}],
            },
    )

    shot_phase = outcome["sequence_review"]["shot_phase"]
    assert shot_phase["all_passed"] is True
    assert outcome["sequence_review"]["verdict"] == "fail"
    assert outcome["status"] == "blocked"
    assert len(calls) == 1


def test_composition_boundary_80_is_never_passed():
    observations = iter([
        _observation(
            observation_id="obs-base", shot_id="shot_001",
            score=79.0, world_x=0.0),
        _observation(
            observation_id="obs-boundary", shot_id="shot_001",
            score=80.0, world_x=0.25),
    ])

    outcome = run_detail_revision_loop(
        detail_shots=[_detail_shots()[0]],
        reference=_reference(),
        observe=lambda reference, shot_id: next(observations),
        rebuild=lambda reference, shot_id: None,
        restore_best=lambda reference, shot_id: None,
        proposal_provider=lambda *, request: _proposal("shot_001"),
        max_revisions=1,
    )

    shot = outcome["shots"]["shot_001"]
    assert shot["status"] == "failed"
    assert shot["best_version"] == 1
    assert shot["best_score"] == 80.0
    assert shot["adopted_version"] is None


def test_incomplete_observation_cannot_become_a_best_or_adopted_version():
    outcome = run_detail_revision_loop(
        detail_shots=[_detail_shots()[0]],
        reference=_reference(),
        observe=lambda reference, shot_id: _observation(
            observation_id="obs-missing-frames",
            shot_id=shot_id,
            score=95.0,
            complete=False,
        ),
        rebuild=lambda reference, shot_id: None,
        restore_best=lambda reference, shot_id: None,
        proposal_provider=lambda *, request: pytest.fail(
            "an incomplete observation must stop before proposing"),
    )

    shot = outcome["shots"]["shot_001"]
    assert shot["status"] == "blocked"
    assert shot["blocked_code"] == "observation_evidence_incomplete"
    assert shot["best_version"] is None
    assert shot["adopted_version"] is None


def test_complete_flag_cannot_hide_missing_review_frame_evidence():
    observation = _observation(
        observation_id="obs-missing-middle",
        shot_id="shot_001",
        score=95.0,
    )
    observation["frames"] = [
        row for row in observation["frames"]
        if row["phase"] != "middle"
    ]

    outcome = run_detail_revision_loop(
        detail_shots=[_detail_shots()[0]],
        reference=_reference(),
        observe=lambda reference, shot_id: observation,
        rebuild=lambda reference, shot_id: None,
        restore_best=lambda reference, shot_id: None,
        proposal_provider=lambda *, request: pytest.fail(
            "missing review-frame evidence must stop before proposing"),
    )

    shot = outcome["shots"]["shot_001"]
    assert shot["status"] == "blocked"
    assert shot["blocked_code"] == "observation_evidence_incomplete"
    assert "middle" in shot["blocked_reason"]
    assert shot["best_version"] is None
    assert shot["adopted_version"] is None


def test_candidate_evidence_retains_the_exact_proposal_that_was_applied():
    observations = iter([
        _observation(
            observation_id="obs-before", shot_id="shot_001",
            score=70.0, world_x=0.0),
        _observation(
            observation_id="obs-after", shot_id="shot_001",
            score=82.0, world_x=0.25),
    ])
    recorded = []

    run_detail_revision_loop(
        detail_shots=[_detail_shots()[0]],
        reference=_reference(),
        observe=lambda reference, shot_id: next(observations),
        rebuild=lambda reference, shot_id: None,
        restore_best=lambda reference, shot_id: None,
        proposal_provider=lambda *, request: _proposal("shot_001"),
        sequence_review=lambda reference: {"verdict": "pass"},
        record_evidence=lambda shot_id, observation, version: (
            recorded.append((shot_id, observation, version))),
    )

    candidate = recorded[1][2]
    assert candidate["proposal"]["schema_version"] == "coarse-proposal/v1"
    assert candidate["proposal"]["reason"] == "improve shot_001"
    assert candidate["proposal"]["prescriptions"][0]["shot_id"] == "shot_001"


def test_geometry_and_vlm_candidates_reach_terminal_dispositions():
    before = _observation(
        observation_id="obs-before", shot_id="shot_001",
        score=70.0, world_x=0.0)
    before["report"]["correction_candidates"] = [
        {
            "candidate_id": "correction-reframe",
            "kind": "subject_cut_by_edge",
            "subject": "米迦尔",
            "source": "both",
            "severity": "error",
            "suggested_tool": "reframe",
        },
        {
            "candidate_id": "correction-deferred",
            "kind": "occluded",
            "subject": "米迦尔",
            "source": "vlm",
            "severity": "advisory",
            "suggested_tool": "move_camera",
        },
        {
            "candidate_id": "correction-resolved",
            "kind": "lead_room_wrong",
            "subject": "米迦尔",
            "source": "vlm",
            "severity": "advisory",
            "suggested_tool": "reframe",
        },
    ]
    after = _observation(
        observation_id="obs-after", shot_id="shot_001",
        score=82.0, world_x=0.25)
    after["report"]["correction_candidates"] = [
        before["report"]["correction_candidates"][0],
        before["report"]["correction_candidates"][1],
        {
            "candidate_id": "correction-new",
            "kind": "shot_size_mismatch",
            "subject": "米迦尔",
            "source": "vlm",
            "severity": "advisory",
            "suggested_tool": "reframe",
        },
    ]
    observations = iter([before, after])
    proposal = _proposal("shot_001")
    proposal["prescriptions"][0]["candidate_ids"] = [
        "correction-reframe"]

    outcome = run_detail_revision_loop(
        detail_shots=[_detail_shots()[0]],
        reference=_reference(),
        observe=lambda reference, shot_id: next(observations),
        rebuild=lambda reference, shot_id: None,
        restore_best=lambda reference, shot_id: None,
        proposal_provider=lambda *, request: proposal,
        sequence_review=lambda reference: {"verdict": "pass"},
    )

    versions = outcome["shots"]["shot_001"]["versions"]
    assert {
        item["candidate_id"]: item["disposition"]
        for item in versions[0]["correction_candidates"]
    } == {
        "correction-reframe": "deferred",
        "correction-deferred": "deferred",
        "correction-resolved": "deferred",
    }
    assert {
        item["candidate_id"]: item["disposition"]
        for item in versions[1]["correction_candidates"]
    } == {
        "correction-reframe": "applied",
        "correction-deferred": "deferred",
        "correction-resolved": "deferred",
        "correction-new": "deferred",
    }
    assert {
        item["candidate_id"]: item["issue_state"]
        for item in versions[1]["correction_candidates"]
    } == {
        "correction-reframe": "persisting",
        "correction-deferred": "persisting",
        "correction-resolved": "resolved",
        "correction-new": "new",
    }


def test_agent_cannot_reference_a_candidate_id_from_another_observation():
    before = _observation(
        observation_id="obs-known-candidates",
        shot_id="shot_001",
        score=70.0,
        world_x=0.0,
    )
    before["report"]["correction_candidates"] = [{
        "candidate_id": "correction-known",
        "kind": "subject_cut_by_edge",
        "subject": "米迦尔",
        "source": "both",
        "severity": "error",
        "suggested_tool": "reframe",
    }]
    proposal = _proposal("shot_001")
    proposal["prescriptions"][0]["candidate_ids"] = [
        "correction-hallucinated"]
    rebuilds = []

    outcome = run_detail_revision_loop(
        detail_shots=[_detail_shots()[0]],
        reference=_reference(),
        observe=lambda reference, shot_id: before,
        rebuild=lambda reference, shot_id: rebuilds.append(shot_id),
        restore_best=lambda reference, shot_id: None,
        proposal_provider=lambda *, request: proposal,
    )

    shot = outcome["shots"]["shot_001"]
    assert shot["status"] == "failed"
    assert shot["blocked_code"] == "invalid_candidate_reference"
    assert "correction-hallucinated" in shot["blocked_reason"]
    assert rebuilds == []


def test_vlm_score_cannot_replace_the_program_composition_score():
    observation = _observation(
        observation_id="obs-vlm-conflict",
        shot_id="shot_001",
        score=82.0,
    )
    observation["report"]["vlm_review"] = {
        "status": "ok",
        "outcome": "reviewed_pass",
        "score": 1,
        "reason": "judge dislikes the frame",
        "issues": [],
        "frame_order": [],
        "measurements": {},
    }
    observation["report"]["measurements"] = {
        "program_score": 82.0,
        "composition": {"score": 82.0, "threshold": 80.0},
    }

    outcome = run_detail_revision_loop(
        detail_shots=[_detail_shots()[0]],
        reference=_reference(),
        observe=lambda reference, shot_id: observation,
        rebuild=lambda reference, shot_id: None,
        restore_best=lambda reference, shot_id: None,
        proposal_provider=None,
        sequence_review=lambda reference: {"verdict": "pass"},
    )

    shot = outcome["shots"]["shot_001"]
    assert outcome["status"] == "approved"
    assert shot["status"] == "passed"
    assert shot["best_score"] == 82.0
    assert shot["versions"][0]["score"] == 82.0
    assert shot["versions"][0]["semantic_review"]["score"] == 1
    assert shot["versions"][0]["measurements"]["program_score"] == 82.0


def test_required_vlm_skip_blocks_instead_of_passing_the_shot():
    observation = _observation(
        observation_id="obs-vlm-required-skip",
        shot_id="shot_001",
        score=95.0,
    )
    observation["report"]["vlm_review_required"] = True
    observation["report"]["vlm_review"] = {
        "status": "skipped",
        "outcome": "missing_frame",
        "reason": "没有可评审的帧",
        "attempts": 0,
    }

    outcome = run_detail_revision_loop(
        detail_shots=[_detail_shots()[0]],
        reference=_reference(),
        observe=lambda reference, shot_id: observation,
        rebuild=lambda reference, shot_id: None,
        restore_best=lambda reference, shot_id: None,
        proposal_provider=lambda *, request: pytest.fail(
            "a required review skip must stop before proposing"),
    )

    shot = outcome["shots"]["shot_001"]
    assert outcome["status"] == "blocked"
    assert shot["status"] == "blocked"
    assert shot["blocked_code"] == "semantic_review_required"
    assert shot["best_version"] is None
    assert "missing_frame" in shot["blocked_reason"]


def test_three_round_vlm_escalation_blocks_without_repeating_the_shot():
    observation = _observation(
        observation_id="obs-vlm-escalated",
        shot_id="shot_001",
        score=95.0,
    )
    observation["report"]["vlm_review_required"] = True
    observation["report"]["vlm_review"] = {
        "status": "ok",
        "outcome": "reviewed_open",
        "score": 2,
        "issues": [{
            "kind": "occluded",
            "subject": "米迦尔",
            "frame": 12,
            "suggested_tool": "move_camera",
        }],
        "disposition": {
            "status": "escalate_human",
            "issues": [{
                "key": "occluded|米迦尔",
                "kind": "occluded",
                "subject": "米迦尔",
                "status": "persisting",
            }],
            "escalated_keys": ["occluded|米迦尔"],
        },
    }

    outcome = run_detail_revision_loop(
        detail_shots=[_detail_shots()[0]],
        reference=_reference(),
        observe=lambda reference, shot_id: observation,
        rebuild=lambda reference, shot_id: None,
        restore_best=lambda reference, shot_id: None,
        proposal_provider=lambda *, request: pytest.fail(
            "an escalated repeat issue must stop before proposing again"),
    )

    shot = outcome["shots"]["shot_001"]
    assert shot["status"] == "blocked"
    assert shot["blocked_code"] == "semantic_review_escalated"
    assert "occluded|米迦尔" in shot["blocked_reason"]


def test_provider_contract_accepts_the_keyword_only_agent_seam():
    observations = iter([
        _observation(
            observation_id="obs-before", shot_id="shot_001",
            score=70.0, world_x=0.0),
        _observation(
            observation_id="obs-after", shot_id="shot_001",
            score=82.0, world_x=0.25),
    ])
    seen = []

    def keyword_only_provider(*, request):
        seen.append(request)
        return _proposal("shot_001")

    outcome = run_detail_revision_loop(
        detail_shots=[_detail_shots()[0]],
        reference=_reference(),
        observe=lambda reference, shot_id: next(observations),
        rebuild=lambda reference, shot_id: None,
        restore_best=lambda reference, shot_id: None,
        proposal_provider=keyword_only_provider,
        sequence_review=lambda reference: {"verdict": "pass"},
    )

    assert outcome["shots"]["shot_001"]["status"] == "passed"
    assert outcome["shots"]["shot_001"]["best_score"] == 82.0
    assert len(seen) == 1
    assert seen[0].round_no == 1
