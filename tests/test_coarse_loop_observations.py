"""Coarse loop must retain the observation that physically survives rollback."""

from __future__ import annotations

from block_director.cinema.coarse_loop import run_coarse_revision_loop
from block_director.contracts.blockout import manifest_fingerprint
from block_director.contracts.coarse_reference import (
    coarse_reference_content_fingerprint,
)
from block_director.contracts.observation import ObservationBundle
from block_director.contracts.world_state import world_state_fingerprint
from block_director.layer5_orchestrator.coarse_agent import (
    OfflineFixtureCoarseProposalProvider,
)


def _reference():
    return {
        "schema_version": "coarse-world-reference/v1",
        "scene_id": "scene",
        "characters": [{
            "name": "甲",
            "position": {"x": 0.0, "y": 0.0, "z": 0.0},
            "facing": [0.0, 1.0, 0.0],
        }],
        "camera_intents": [{
            "shot_id": "shot_001",
            "position": [0.0, 3.0, 1.5],
            "target": [0.0, 0.0, 1.0],
            "lens": 35.0,
            "movement": None,
        }],
        "shots": [{
            "shot_id": "shot_001",
            "order": 1,
            "duration_frames": 24,
            "characters": ["甲"],
            "actions": [],
        }],
        "revisions": [],
        "notes": [],
    }


def _report(score, *, fingerprint="report"):
    return {
        "schema_version": "blockout-report/v1",
        "manifest_fingerprint": fingerprint,
        "verdict": "pass" if score > 80.0 else "fail",
        "findings": [],
        "checks": [{
            "check_id": "composition",
            "shot_id": "shot_001",
            "actual": score,
            "threshold": 80.0,
            "verdict": "pass" if score > 80.0 else "fail",
        }],
        "visual_states": [],
    }


def _observation(
    reference,
    score,
    *,
    manifest_fp,
    complete=True,
    evidence_dir=None,
):
    manifest = {
        "schema_version": "blockout-manifest/v1",
        "scene_id": "scene",
        "primitives": [],
        "cameras": [],
        "shot_table": [],
        "observation_marker": manifest_fp,
    }
    return ObservationBundle.from_payload(
        reference=reference,
        manifest=manifest,
        report=_report(
            score, fingerprint=manifest_fingerprint(manifest)),
        world_state={
            "schema_version": "runtime-world/v1",
            "characters": {},
            "cameras": {},
            "props": {},
            "observation_marker": manifest_fp,
        },
        evidence_dir=evidence_dir or f"memory/{manifest_fp}",
        frame_records=[],
        complete_hint=complete,
    )


def test_rollback_reobserves_best_and_exposes_latest_candidate_separately():
    initial = _reference()
    observations = []
    restore_calls = []

    def observe(ref):
        attempt = len(observations) + 1
        if attempt == 1:
            bundle = _observation(
                ref, 70.0, manifest_fp="best")
        elif attempt == 2:
            bundle = _observation(
                ref, 50.0, manifest_fp="candidate")
        else:
            bundle = _observation(
                ref, 70.0, manifest_fp="best-after-rollback")
        observations.append(bundle)
        return bundle

    def rebuild(ref):
        return None

    def restore(ref):
        restore_calls.append(ref)
        rebuild(ref)

    outcome = run_coarse_revision_loop(
        reference=initial,
        report_loader=observe,
        rebuild=rebuild,
        restore_best=restore,
        proposal_provider=OfflineFixtureCoarseProposalProvider(),
        max_revisions=3,
        no_gain_limit=1,
    )

    assert outcome["status"] == "blocked"
    assert restore_calls, "rollback must physically restore before re-observation"
    assert len(observations) >= 3
    assert outcome["best_observation_id"] == observations[-1].observation_id
    assert outcome["latest_candidate_observation_id"] == (
        observations[1].observation_id)
    assert outcome["latest_observation_id"] == observations[-1].observation_id
    assert outcome["report"]["checks"][0]["actual"] == 70.0
    assert outcome["latest_candidate_report"]["checks"][0]["actual"] == 50.0
    assert outcome["manifest"]["observation_marker"] == (
        "best-after-rollback")
    assert outcome["world_state"]["observation_marker"] == (
        "best-after-rollback")
    assert outcome["manifest"] == observations[-1].manifest


def test_agent_request_carries_remeasured_round_history_after_rollback():
    """A restored Agent must see why the previous proposal lost.

    Real node123 run: every plan-level coarse attempt restored the physical
    best, then the next Agent call repeated the exact same prescriptions because
    the request contained no previous candidate score or disposition.  The
    remeasured candidate history is the evidence that prevents this loop.
    """
    observations = iter([
        _observation(_reference(), 70.0, manifest_fp="best"),
        _observation(_reference(), 60.0, manifest_fp="candidate"),
        _observation(_reference(), 70.0, manifest_fp="best-after-rollback"),
        _observation(_reference(), 82.0, manifest_fp="new-candidate"),
    ])
    requests = []
    fixture = OfflineFixtureCoarseProposalProvider()

    class CaptureFixture:
        provider_kind = "offline_fixture"

        def __call__(self, request):
            requests.append(request)
            return fixture(request=request)

    outcome = run_coarse_revision_loop(
        reference=_reference(),
        report_loader=lambda _reference: next(observations),
        rebuild=lambda _reference: None,
        restore_best=lambda _reference: None,
        proposal_provider=CaptureFixture(),
        max_revisions=3,
        no_gain_limit=3,
    )

    assert outcome["status"] == "approved"
    assert len(requests) == 2
    assert requests[0].history == ()
    history = requests[1].history
    assert len(history) == 1
    round_one = history[0]
    assert round_one["round_no"] == 1
    assert round_one["disposition"] == "revert"
    assert round_one["candidate_score"] == 60.0
    assert round_one["best_score_before"] == 70.0
    assert round_one["best_score_after"] == 70.0
    assert round_one["candidate_fingerprint"]
    assert round_one["prescriptions"][0]["component"] in {
        "distance", "target", "strafe", "position.y", "position.z",
        "character_position",
    }


def test_incomplete_observation_can_never_be_approved():
    outcome = run_coarse_revision_loop(
        reference=_reference(),
        report_loader=lambda ref: _observation(
            ref, 90.0, manifest_fp="pass-but-no-frames", complete=False),
        rebuild=lambda ref: None,
        max_revisions=1,
    )

    assert outcome["status"] == "blocked"
    assert outcome["report"]["checks"][0]["actual"] == 90.0
    assert "证据" in outcome["blocked_reason"]


def test_round_records_which_observation_remeasured_its_candidate():
    observations = iter([
        {
            "observation_id": "obs-trigger",
            "complete": True,
            "report": _report(70.0),
        },
        {
            "observation_id": "obs-candidate",
            "complete": True,
            "report": _report(82.0),
        },
    ])

    def provider(request):
        return {
            "schema_version": "coarse-proposal/v1",
            "provider_kind": "test_agent",
            "reason": "推近镜头",
            "prescriptions": [{
                "prescription_id": "agent_shot_001_push",
                "scope": "camera",
                "shot_id": "shot_001",
                "entity": "cam_shot_001",
                "component": "distance",
                "target_value": {
                    "position": {"x": 0.0, "y": 2.7, "z": 1.5},
                    "target": {"x": 0.0, "y": 0.0, "z": 1.0},
                },
                "reason": "构图不足",
                "evidence_refs": ["composition:shot_001"],
            }],
        }

    outcome = run_coarse_revision_loop(
        reference=_reference(),
        report_loader=lambda _reference: next(observations),
        rebuild=lambda _reference: None,
        proposal_provider=provider,
        max_revisions=2,
    )

    assert outcome["status"] == "approved"
    assert outcome["rounds"][0]["observation_id"] == "obs-trigger"
    assert outcome["rounds"][0]["candidate_observation_id"] == "obs-candidate"


def test_round_binds_candidate_rebuild_observation_comparison_and_rollback():
    observations = iter([
        _observation(_reference(), 70.0, manifest_fp="best"),
        _observation(_reference(), 82.0, manifest_fp="candidate"),
    ])

    outcome = run_coarse_revision_loop(
        reference=_reference(),
        report_loader=lambda _reference: next(observations),
        rebuild=lambda _reference: None,
        restore_best=lambda _reference: None,
        proposal_provider=OfflineFixtureCoarseProposalProvider(),
        max_revisions=2,
    )

    assert outcome["status"] == "approved"
    candidate_round = outcome["rounds"][0]
    candidate = candidate_round["candidate"]
    assert candidate["observation_id"] == (
        candidate_round["candidate_observation_id"])
    assert candidate["report"]["checks"][0]["actual"] == 82.0
    assert candidate["manifest_fingerprint"] == (
        candidate_round["candidate_manifest_fingerprint"])
    assert candidate["world_state_fingerprint"] == world_state_fingerprint({
        "schema_version": "runtime-world/v1",
        "characters": {},
        "cameras": {},
        "props": {},
        "observation_marker": "candidate",
    })
    assert candidate["rebuild_summary"]["camera_count"] == 0
    assert candidate["rebuild_summary"]["shot_count"] == 0
    assert candidate_round["comparison"]["disposition"] == "new_high"
    assert candidate_round["rollback"]["applied"] is False


def test_repeated_non_best_physical_state_rolls_back_and_stops_the_loop():
    observations = [
        _observation(_reference(), 70.0, manifest_fp="best"),
        _observation(_reference(), 50.0, manifest_fp="candidate-a"),
        _observation(_reference(), 70.0, manifest_fp="best-restored"),
        _observation(_reference(), 50.0, manifest_fp="candidate-a"),
        _observation(_reference(), 70.0, manifest_fp="best-after-cycle"),
    ]
    observation_calls = []
    restore_calls = []

    def observe(reference):
        observation_calls.append(reference)
        return observations[len(observation_calls) - 1]

    def rebuild(reference):
        return None

    def restore(reference):
        restore_calls.append(reference)
        rebuild(reference)

    def provider(request):
        y = 2.9 if request.round_no == 1 else 2.8
        return {
            "schema_version": "coarse-proposal/v1",
            "source": "agent",
            "provider_kind": "cycle-probe",
            "reason": f"测试第 {request.round_no} 轮候选",
            "prescriptions": [{
                "prescription_id": f"cycle_push_{request.round_no}",
                "scope": "camera",
                "shot_id": "shot_001",
                "entity": "cam_shot_001",
                "component": "distance",
                "target_value": {
                    "position": {"x": 0.0, "y": y, "z": 1.5},
                    "target": {"x": 0.0, "y": 0.0, "z": 1.0},
                },
                "reason": "制造可辨识候选",
                "evidence_refs": ["composition:shot_001"],
            }],
        }

    outcome = run_coarse_revision_loop(
        reference=_reference(),
        report_loader=observe,
        rebuild=rebuild,
        restore_best=restore,
        proposal_provider=provider,
        max_revisions=10,
        no_gain_limit=10,
    )

    assert outcome["status"] == "blocked"
    assert outcome["blocked_code"] == "candidate_cycle_detected"
    assert len(observation_calls) == 5
    assert len(restore_calls) == 2
    assert outcome["rollback_count"] == 2
    repeated_round = outcome["rounds"][-1]
    assert repeated_round["comparison"]["disposition"] == (
        "rollback_repeated_state")
    assert repeated_round["rollback"]["applied"] is True
    assert repeated_round["rollback_applied"] is True
    assert repeated_round["cycle_detected"] is True
    assert repeated_round["no_gain"] == 2
    assert repeated_round["rollback"]["to_observation_id"] == (
        outcome["best_observation_id"])


def test_equal_score_with_different_physical_state_is_a_rollback_tie():
    observations = [
        _observation(_reference(), 70.0, manifest_fp="best"),
        _observation(_reference(), 70.0, manifest_fp="candidate"),
        _observation(_reference(), 70.0, manifest_fp="best-restored"),
    ]
    observation_calls = []
    restore_calls = []

    def observe(reference):
        observation_calls.append(reference)
        return observations[len(observation_calls) - 1]

    def rebuild(reference):
        return None

    def restore(reference):
        restore_calls.append(reference)
        rebuild(reference)

    def provider(request):
        return {
            "schema_version": "coarse-proposal/v1",
            "source": "agent",
            "provider_kind": "tie-probe",
            "reason": "different physical state at the same score",
            "prescriptions": [{
                "prescription_id": "tie_candidate",
                "scope": "camera",
                "shot_id": "shot_001",
                "entity": "cam_shot_001",
                "component": "distance",
                "target_value": {
                    "position": {"x": 0.0, "y": 2.7, "z": 1.5},
                    "target": {"x": 0.0, "y": 0.0, "z": 1.0},
                },
                "reason": "produce a non-best physical state",
                "evidence_refs": ["composition:shot_001"],
            }],
        }

    outcome = run_coarse_revision_loop(
        reference=_reference(),
        report_loader=observe,
        rebuild=rebuild,
        restore_best=restore,
        proposal_provider=provider,
        max_revisions=3,
        no_gain_limit=1,
    )

    assert outcome["status"] == "blocked"
    assert outcome["blocked_code"] == "no_improvement_limit"
    assert len(restore_calls) == 1
    assert outcome["rollback_count"] == 1
    candidate_round = outcome["rounds"][0]
    assert candidate_round["comparison"]["disposition"] == "tie"
    assert candidate_round["rollback"]["applied"] is True
    assert candidate_round["rollback_applied"] is True
    assert candidate_round["no_gain"] == 1
    assert candidate_round["rollback"]["to_observation_id"] == (
        outcome["best_observation_id"])
    assert outcome["latest_candidate_observation_id"] == (
        observations[1].observation_id)
    assert outcome["best_observation_id"] == observations[2].observation_id
    assert outcome["manifest"]["observation_marker"] == "best-restored"
    assert outcome["world_state"]["observation_marker"] == "best-restored"


def test_no_gain_limit_counts_failed_candidate_rounds_not_best_restores():
    observations = [
        _observation(_reference(), 70.0, manifest_fp="best"),
        _observation(_reference(), 60.0, manifest_fp="candidate-a"),
        _observation(_reference(), 70.0, manifest_fp="best"),
        _observation(_reference(), 61.0, manifest_fp="candidate-b"),
        _observation(_reference(), 70.0, manifest_fp="best"),
        _observation(_reference(), 62.0, manifest_fp="candidate-c"),
        _observation(_reference(), 70.0, manifest_fp="best"),
    ]
    observation_calls = []
    restore_calls = []
    provider_rounds = []

    def observe(reference):
        observation_calls.append(reference)
        return observations[len(observation_calls) - 1]

    def restore(reference):
        restore_calls.append(reference)

    def provider(request):
        provider_rounds.append(request.round_no)
        return {
            "schema_version": "coarse-proposal/v1",
            "source": "agent",
            "provider_kind": "distinct-no-gain-probe",
            "reason": "produce a new physical state without a higher score",
            "prescriptions": [{
                "prescription_id": f"distinct_candidate_{request.round_no}",
                "scope": "camera",
                "shot_id": "shot_001",
                "entity": "cam_shot_001",
                "component": "distance",
                "target_value": {
                    "position": {
                        "x": 0.0,
                        "y": 2.9 - 0.1 * request.round_no,
                        "z": 1.5,
                    },
                    "target": {"x": 0.0, "y": 0.0, "z": 1.0},
                },
                "reason": "distinct lower-scoring candidate",
                "evidence_refs": ["composition:shot_001"],
            }],
        }

    outcome = run_coarse_revision_loop(
        reference=_reference(),
        report_loader=observe,
        rebuild=lambda _reference: None,
        restore_best=restore,
        proposal_provider=provider,
        max_revisions=10,
        no_gain_limit=3,
    )

    assert outcome["status"] == "blocked"
    assert outcome["blocked_code"] == "no_improvement_limit"
    assert provider_rounds == [1, 2, 3]
    assert len(restore_calls) == 3
    candidate_rounds = [
        row for row in outcome["rounds"]
        if row.get("candidate_observation_id")
    ]
    assert len(candidate_rounds) == 3
    assert outcome["rounds"][-1]["disposition"] == (
        "proposal_from_restored_best")
    assert outcome["no_gain"] == 3
    assert outcome["latest_candidate_observation_id"] == (
        observations[5].observation_id)
    assert outcome["best_observation_id"] == observations[-1].observation_id


def test_fifty_round_limit_keeps_best_and_latest_candidate_separate():
    by_observation = {}
    candidate_ids = []
    best_ids = []
    provider_rounds = []

    def observe(reference):
        revisions = reference.get("revisions") or []
        is_candidate = bool(revisions)
        marker = (
            "candidate-"
            + coarse_reference_content_fingerprint(reference)
            if is_candidate else "best"
        )
        score = (
            60.0
            if is_candidate else
            70.0
        )
        observation = _observation(
            reference,
            score,
            manifest_fp=marker,
            evidence_dir=f"memory/observation-{len(by_observation) + 1:03d}",
        )
        by_observation[observation.observation_id] = observation
        (candidate_ids if is_candidate else best_ids).append(
            observation.observation_id)
        return observation

    def provider(request):
        provider_rounds.append(request.round_no)
        return {
            "schema_version": "coarse-proposal/v1",
            "source": "agent",
            "provider_kind": "max-round-probe",
            "reason": "produce distinct lower candidates",
            "prescriptions": [{
                "prescription_id": f"max_round_candidate_{request.round_no}",
                "scope": "camera",
                "shot_id": "shot_001",
                "entity": "cam_shot_001",
                "component": "distance",
                "target_value": {
                    "position": {
                        "x": 0.0,
                        "y": 2.9 - 0.01 * request.round_no,
                        "z": 1.5,
                    },
                    "target": {"x": 0.0, "y": 0.0, "z": 1.0},
                },
                "reason": "distinct lower-scoring candidate",
                "evidence_refs": ["composition:shot_001"],
            }],
        }

    outcome = run_coarse_revision_loop(
        reference=_reference(),
        report_loader=observe,
        rebuild=lambda _reference: None,
        restore_best=lambda _reference: None,
        proposal_provider=provider,
        no_gain_limit=100,
    )

    assert outcome["status"] == "blocked"
    assert outcome["blocked_code"] == "max_revisions_reached"
    assert provider_rounds == list(range(1, 50))
    assert len(outcome["rounds"]) == 50
    assert len(candidate_ids) == 49
    assert len(best_ids) == 50
    assert outcome["latest_candidate_observation_id"] == candidate_ids[-1]
    assert outcome["best_observation_id"] == best_ids[-1]
    assert outcome["latest_observation_id"] == best_ids[-1]
    assert outcome["best_observation_id"] != (
        outcome["latest_candidate_observation_id"])
    assert outcome["latest_candidate_report"]["checks"][0]["actual"] == 60.0
    assert outcome["report"]["checks"][0]["actual"] == 70.0
    assert outcome["best_fingerprint"] == (
        coarse_reference_content_fingerprint(_reference()))
    assert outcome["best_observation"] is not None
    assert by_observation[
        outcome["latest_candidate_observation_id"]
    ].world_state["observation_marker"].startswith("candidate-")


def test_restored_best_remeasurement_updates_reported_quality_and_rank():
    observations = iter([
        _observation(_reference(), 70.0, manifest_fp="best"),
        _observation(_reference(), 60.0, manifest_fp="candidate"),
        _observation(_reference(), 72.0, manifest_fp="best-remeasured"),
    ])

    outcome = run_coarse_revision_loop(
        reference=_reference(),
        report_loader=lambda _reference: next(observations),
        rebuild=lambda _reference: None,
        restore_best=lambda _reference: None,
        proposal_provider=OfflineFixtureCoarseProposalProvider(),
        max_revisions=2,
        no_gain_limit=1,
    )

    assert outcome["status"] == "blocked"
    assert outcome["blocked_code"] == "max_revisions_reached"
    assert outcome["report"]["checks"][0]["actual"] == 72.0
    assert outcome["best_score"] == 72.0
    first_round = outcome["rounds"][0]
    assert first_round["comparison"]["best_score_after"] == 72.0
    assert first_round["comparison"]["best_rank_after"] == [0, 72.0, 0]


def test_approval_after_restore_keeps_latest_candidate_report_separate():
    observations = iter([
        _observation(_reference(), 70.0, manifest_fp="best"),
        _observation(_reference(), 60.0, manifest_fp="candidate"),
        _observation(_reference(), 82.0, manifest_fp="best-remeasured"),
    ])

    outcome = run_coarse_revision_loop(
        reference=_reference(),
        report_loader=lambda _reference: next(observations),
        rebuild=lambda _reference: None,
        restore_best=lambda _reference: None,
        proposal_provider=OfflineFixtureCoarseProposalProvider(),
        max_revisions=3,
        no_gain_limit=1,
    )

    assert outcome["status"] == "approved"
    assert outcome["report"]["checks"][0]["actual"] == 82.0
    assert outcome["latest_candidate_report"]["checks"][0]["actual"] == 60.0
    assert outcome["latest_candidate_observation_id"] != (
        outcome["best_observation_id"])
    assert outcome["rounds"][0]["comparison"]["disposition"] == "revert"


def test_missing_physical_restore_callback_blocks_instead_of_claiming_rollback():
    observations = iter([
        _observation(_reference(), 70.0, manifest_fp="best"),
        _observation(_reference(), 60.0, manifest_fp="candidate"),
    ])

    outcome = run_coarse_revision_loop(
        reference=_reference(),
        report_loader=lambda _reference: next(observations),
        rebuild=lambda _reference: None,
        proposal_provider=OfflineFixtureCoarseProposalProvider(),
        max_revisions=3,
        no_gain_limit=3,
    )

    assert outcome["status"] == "blocked"
    assert outcome["blocked_code"] == "physical_restore_unavailable"
    assert outcome["rollback_count"] == 0
    assert outcome["report"]["checks"][0]["actual"] == 70.0
    assert outcome["latest_candidate_report"]["checks"][0]["actual"] == 60.0
    candidate_round = outcome["rounds"][0]
    assert candidate_round["comparison"]["disposition"] == "revert"
    assert candidate_round["rollback_applied"] is False
    assert candidate_round["rollback"]["applied"] is False

