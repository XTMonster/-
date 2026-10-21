"""Public behaviour of the complete detail pipeline."""

from __future__ import annotations

import json
import sys
import types

from block_director.layer5_orchestrator.detail_pipeline import (
    run_detail_pipeline,
)


def _install_pipeline_boundaries(
    monkeypatch, tmp_path, *, sequence_verdict="fail",
    capture_manifests=False, refreshed_manifest=None,
    composition_score=85.0,
):
    calls = []
    manifests = []

    def build_blockout_scene(*_args, **_kwargs):
        return None

    def apply_detail_beats(*_args, **_kwargs):
        return None

    def refresh_blockout_composition(*_args, **_kwargs):
        report = {
            "schema_version": "blockout-report/v1",
            "verdict": "pass",
            "findings": [],
            "checks": [{
                "check_id": "composition",
                "shot_id": "shot_001",
                "actual": composition_score,
                "threshold": 80.0,
                "verdict": (
                    "pass" if composition_score > 80.0 else "fail"
                ),
            }],
        }
        if refreshed_manifest is None:
            return report
        return {
            "report": report,
            "manifest": refreshed_manifest,
            "reference": {"shots": [], "characters": [],
                          "camera_intents": []},
        }

    def run_blockout_sequence_review(manifest, out_dir, *,
                                     render_video=False):
        calls.append(bool(render_video))
        manifests.append(manifest)
        review = {
            "verdict": sequence_verdict,
            "findings": [],
        }
        video = {"rendered": False}
        if render_video:
            source = tmp_path / "rendered_but_not_approved.mp4"
            source.write_bytes(b"diagnostic")
            video = {
                "rendered": True,
                "full_path": str(source),
                "shot_videos": [],
            }
        return {"review": review, "video": video}

    def render_blockout_sequence_video(manifest, out_dir, *, fps=24,
                                       shot_ids=None):
        calls.append(("render", tuple(shot_ids or ())))
        if capture_manifests:
            manifests.append(manifest)
        target = tmp_path / "rendered_session.mp4"
        target.write_bytes(b"session-video")
        return {
            "rendered": True,
            "full_path": str(target),
            "shot_videos": [],
        }

    modules = {
        "block_director.layer3_engine.blockout_scene": types.SimpleNamespace(
            build_blockout_scene=build_blockout_scene,
        ),
        "block_director.layer3_engine.detail_scene": types.SimpleNamespace(
            apply_detail_beats=apply_detail_beats,
        ),
        "block_director.layer8_delivery.blockout_preview": types.SimpleNamespace(
            refresh_blockout_composition=refresh_blockout_composition,
        ),
        "block_director.layer8_delivery.blockout_sequence": types.SimpleNamespace(
            run_blockout_sequence_review=run_blockout_sequence_review,
            render_blockout_sequence_video=render_blockout_sequence_video,
        ),
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    if capture_manifests:
        return calls, manifests
    return calls


def _baseline():
    return {
        "state": "frozen",
        "reference": {
            "characters": [{
                "name": "米迦尔",
                "position": {"x": 0.0, "y": 0.0, "z": 0.0},
            }],
            "camera_intents": [{
                "shot_id": "shot_001",
                "position": [0.0, 6.0, 2.0],
                "target": [0.0, 0.0, 0.9],
                "lens": 35.0,
            }],
        },
        "manifest": {"cameras": [], "shot_table": []},
        "report": {"findings": [], "checks": []},
    }


def _plan():
    return {
        "shots": [{
            "shot_id": "shot_001",
            "order": 1,
            "duration_frames": 24,
            "characters": ["米迦尔"],
            "shot_type": "MS",
            "framing_target": "米迦尔",
        }],
    }


def _two_shot_plan():
    return {
        "shots": [
            {
                "shot_id": "shot_001",
                "order": 1,
                "duration_frames": 24,
                "characters": ["米迦尔"],
                "shot_type": "MS",
                "framing_target": "米迦尔",
            },
            {
                "shot_id": "shot_002",
                "order": 2,
                "duration_frames": 24,
                "characters": ["伊恩"],
                "shot_type": "MS",
                "framing_target": "伊恩",
            },
        ],
    }


class _DetailSession:
    """Public scene-session seam used by the detail pipeline tests."""

    def __init__(self, scores, evidence_dir, *, sequence_verdict="pass"):
        self.scores = dict(scores)
        self.evidence_dir = evidence_dir
        self.sequence_verdict = sequence_verdict
        self.prepared = False
        self.sequence_calls = []
        self.applied = []
        self.restored = []
        self.evidence = []
        self.reference = _baseline()["reference"]
        self.manifest = {"cameras": [], "shot_table": [], "primitives": []}
        self.report = {
            "schema_version": "blockout-report/v1",
            "verdict": "pass",
            "findings": [],
            "checks": [],
        }

    def prepare(self):
        self.prepared = True

    def observe(self, reference, shot_id):
        score = float(self.scores[shot_id])
        self.report = {
            "schema_version": "blockout-report/v1",
            "verdict": "pass" if score > 80.0 else "fail",
            "findings": [],
            "checks": [{
                "check_id": "composition",
                "shot_id": shot_id,
                "actual": score,
                "threshold": 80.0,
                "verdict": "pass" if score > 80.0 else "fail",
            }],
        }
        files = []
        for phase in ("first", "middle", "last"):
            path = self.evidence_dir / f"{shot_id}-{phase}.png"
            path.write_bytes(phase.encode("ascii"))
            digest = "a" * 64
            files.append({
                "shot_id": shot_id,
                "frame": {"first": 1, "middle": 12, "last": 24}[phase],
                "phase": phase,
                "path": str(path),
                "file_sha256": digest,
                "pixel_sha256": digest,
                "readable": True,
            })
        return {
            "observation_id": f"obs-{shot_id}-{score}",
            "complete": True,
            "errors": [],
            "reference": reference,
            "manifest": self.manifest,
            "report": self.report,
            "world_state": {
                "shot_states": {
                    shot_id: {
                        "characters": {
                            "米迦尔" if shot_id == "shot_001" else "伊恩": {
                                "position": [0.0, 0.0, 0.0],
                            },
                        },
                        "cameras": {
                            shot_id: {
                                "position": [0.0, 3.0, 1.5],
                                "target": [0.0, 0.0, 1.0],
                            },
                        },
                    },
                },
            },
            "frames": files,
        }

    def apply(self, reference, shot_id):
        self.applied.append(shot_id)

    def restore(self, reference, shot_id):
        self.restored.append(shot_id)

    def review_sequence(self, reference):
        self.sequence_calls.append(reference)
        return {"verdict": self.sequence_verdict, "findings": []}

    def record_evidence(self, shot_id, observation, version):
        self.evidence.append((shot_id, observation, version))


def test_sequence_failure_never_publishes_a_final_video(
    monkeypatch, tmp_path,
):
    evidence_dir = tmp_path / "frames"
    evidence_dir.mkdir()
    _install_pipeline_boundaries(monkeypatch, tmp_path)
    session = _DetailSession(
        {"shot_001": 82.0},
        evidence_dir,
        sequence_verdict="fail",
    )
    baseline = _baseline()
    baseline["report"] = {
        "schema_version": "blockout-report/v1",
        "verdict": "pass",
        "findings": [],
        "checks": [{
            "check_id": "composition",
            "shot_id": "shot_001",
            "actual": 82.0,
            "threshold": 80.0,
            "verdict": "pass",
        }],
    }

    report = run_detail_pipeline(
        baseline=baseline,
        plan=_plan(),
        out_dir=tmp_path / "detail",
        render_video=True,
        session=session,
    )

    assert len(session.sequence_calls) == 1
    assert report["gates"]["sequence"] == "fail"
    assert report["gates"]["final"] == "blocked"
    assert report["final"] is False
    assert report["artifacts"]["final_video"] is None
    assert not (tmp_path / "detail" / "final_video.mp4").exists()
    assert not (
        tmp_path / "detail" / "detail_final_manifest.json").exists()
    assert (
        tmp_path / "detail" / "detail_retained_manifest.json").is_file()
    assert report["artifacts"]["detail_manifest"] == str(
        tmp_path / "detail" / "detail_retained_manifest.json")
    assert report["artifacts"]["detail_final_manifest"] is None


def test_unfrozen_or_failed_coarse_baseline_never_publishes_final(
    monkeypatch, tmp_path,
):
    _install_pipeline_boundaries(
        monkeypatch, tmp_path, sequence_verdict="pass")
    baseline = _baseline()
    baseline["state"] = "draft"
    baseline["report"]["verdict"] = "fail"
    baseline["report"]["findings"] = [{
        "check_id": "E_BLOCKOUT_EMPTY_WALL",
        "shot_id": "shot_001",
        "severity": "error",
        "message": "相机对空墙",
    }]

    report = run_detail_pipeline(
        baseline=baseline,
        plan=_plan(),
        out_dir=tmp_path / "detail",
        render_video=True,
    )

    assert report["gates"]["coarse"] == "blocked"
    assert report["gates"]["baseline"] == "unfrozen"
    assert report["gates"]["final"] == "blocked"
    assert report["final"] is False
    assert report["artifacts"]["final_video"] is None
    assert not (tmp_path / "detail" / "final_video.mp4").exists()


def test_sequence_and_render_use_the_remeasured_manifest(
    monkeypatch, tmp_path,
):
    from block_director.contracts.blockout import manifest_fingerprint

    evidence_dir = tmp_path / "frames"
    evidence_dir.mkdir()
    baseline = _baseline()
    refreshed = dict(baseline["manifest"])
    refreshed["notes"] = ["remeasured-live-world"]
    calls, manifests = _install_pipeline_boundaries(
        monkeypatch,
        tmp_path,
        sequence_verdict="pass",
        capture_manifests=True,
        refreshed_manifest=refreshed,
    )
    session = _DetailSession({"shot_001": 82.0}, evidence_dir)
    session.manifest = refreshed
    baseline["report"] = {
        "schema_version": "blockout-report/v1",
        "verdict": "pass",
        "findings": [],
        "checks": [{
            "check_id": "composition",
            "shot_id": "shot_001",
            "actual": 82.0,
            "threshold": 80.0,
            "verdict": "pass",
        }],
    }

    report = run_detail_pipeline(
        baseline=baseline,
        plan=_plan(),
        out_dir=tmp_path / "detail",
        render_video=True,
        session=session,
    )

    assert calls == [("render", ())]
    assert len(manifests) == 1
    assert all(manifest is refreshed for manifest in manifests)
    assert len(session.sequence_calls) == 1
    final_manifest = json.loads(
        (tmp_path / "detail" / "detail_final_manifest.json")
        .read_text(encoding="utf-8"))
    assert manifest_fingerprint(final_manifest) == manifest_fingerprint(refreshed)
    assert report["artifacts"]["detail_final_manifest"].endswith(
        "detail_final_manifest.json")


def test_failed_nonempty_shot_prevents_sequence_review(
    monkeypatch, tmp_path,
):
    evidence_dir = tmp_path / "frames"
    evidence_dir.mkdir()
    _install_pipeline_boundaries(
        monkeypatch, tmp_path, composition_score=70.0)
    session = _DetailSession(
        {"shot_001": 82.0, "shot_002": 80.0},
        evidence_dir,
    )

    report = run_detail_pipeline(
        baseline=_baseline(),
        plan=_two_shot_plan(),
        out_dir=tmp_path / "detail",
        render_video=False,
        session=session,
    )

    assert session.prepared is True
    assert session.sequence_calls == []
    assert report["gates"]["sequence"] == "blocked"
    assert report["gates"]["final"] == "blocked"


def test_sequence_review_runs_once_after_every_shot_passes(
    monkeypatch, tmp_path,
):
    evidence_dir = tmp_path / "frames"
    evidence_dir.mkdir()
    _install_pipeline_boundaries(monkeypatch, tmp_path)
    session = _DetailSession(
        {"shot_001": 82.0, "shot_002": 81.0},
        evidence_dir,
    )
    baseline = _baseline()
    baseline["report"] = {
        "schema_version": "blockout-report/v1",
        "verdict": "pass",
        "findings": [],
        "checks": [
            {
                "check_id": "composition",
                "shot_id": shot_id,
                "actual": score,
                "threshold": 80.0,
                "verdict": "pass",
            }
            for shot_id, score in (
                ("shot_001", 82.0),
                ("shot_002", 81.0),
            )
        ],
    }

    report = run_detail_pipeline(
        baseline=baseline,
        plan=_two_shot_plan(),
        out_dir=tmp_path / "detail",
        render_video=False,
        session=session,
    )

    assert len(session.sequence_calls) == 1
    assert all(
        value["status"] == "passed"
        for value in report["detail_loop"]["shots"].values()
    )
    assert report["gates"]["sequence"] == "pass"
    assert report["gates"]["final"] == "pass"


def test_failed_shot_without_agent_provider_blocks_in_per_shot_loop(
    monkeypatch, tmp_path,
):
    """A failed detail shot cannot bypass the Agent-driven revision loop."""

    evidence_dir = tmp_path / "frames"
    evidence_dir.mkdir()
    _install_pipeline_boundaries(monkeypatch, tmp_path)
    session = _DetailSession({"shot_001": 70.0}, evidence_dir)

    report = run_detail_pipeline(
        baseline=_baseline(),
        plan=_plan(),
        out_dir=tmp_path / "detail",
        render_video=False,
        session=session,
    )

    shot = report["detail_loop"]["shots"]["shot_001"]
    assert shot["status"] == "failed"
    assert shot["blocked_code"] == "agent_proposal_unavailable"
    assert report["gates"]["detail"] == "blocked"
    assert report["gates"]["final"] == "blocked"


def test_user_animation_conflict_from_session_apply_blocks_pipeline(
    monkeypatch, tmp_path,
):
    """A physical user-edit conflict must become a named pipeline verdict."""
    from block_director.cinema.detail_loop import DetailLoopBlocked

    evidence_dir = tmp_path / "frames"
    evidence_dir.mkdir()
    _install_pipeline_boundaries(monkeypatch, tmp_path)
    session = _DetailSession({"shot_001": 70.0}, evidence_dir)
    baseline = _baseline()
    baseline["reference"].update({
        "schema_version": "coarse-world-reference/v1",
        "props": [],
        "anchors": [],
        "shots": _plan()["shots"],
        "shot_staging": {},
        "revisions": [],
    })
    session.reference = json.loads(json.dumps(baseline["reference"]))
    session.proposal_provider = lambda *, request: {
        "schema_version": "coarse-proposal/v1",
        "provider_kind": "agent",
        "reason": "move the subject into frame",
        "prescriptions": [{
            "prescription_id": "detail-shot-001",
            "scope": "character",
            "shot_id": "shot_001",
            "entity": "米迦尔",
            "component": "character_position",
            "target_value": {"x": 0.25, "y": 0.0, "z": 0.0},
            "reason": "composition repair",
            "evidence_refs": ["composition:fail"],
        }],
    }

    def blocked_apply(_reference, shot_id):
        raise DetailLoopBlocked(
            "automatic detail repair would overwrite user-owned animation",
            code="user_animation_conflict",
            details={"shot_id": shot_id, "objects": ["BD_Character_米迦尔"]},
        )

    session.apply = blocked_apply
    report = run_detail_pipeline(
        baseline=baseline,
        plan=_plan(),
        out_dir=tmp_path / "detail",
        render_video=False,
        session=session,
    )

    shot = report["detail_loop"]["shots"]["shot_001"]
    assert shot["status"] == "blocked", json.dumps(
        shot, ensure_ascii=False)
    assert shot["blocked_code"] == "user_animation_conflict"
    assert "user-owned animation" in shot["blocked_reason"]
    assert report["gates"]["detail"] == "blocked"
    assert report["gates"]["final"] == "blocked"
    assert session.sequence_calls == []


def test_transport_builds_the_session_with_the_live_agent_dependencies(
    monkeypatch, tmp_path,
):
    """Production detail runs must receive the current model and knowledge."""
    evidence_dir = tmp_path / "frames"
    evidence_dir.mkdir()
    _install_pipeline_boundaries(monkeypatch, tmp_path)
    session = _DetailSession({"shot_001": 82.0}, evidence_dir)
    transport = types.SimpleNamespace(chat=lambda *_args, **_kwargs: None)
    knowledge = object()
    captured = {}

    def session_factory(**kwargs):
        captured.update(kwargs)
        return session

    report = run_detail_pipeline(
        baseline=_baseline(),
        plan=_plan(),
        out_dir=tmp_path / "detail",
        render_video=False,
        transport=transport,
        knowledge=knowledge,
        session_factory=session_factory,
        run_id="run-node123",
        scene_id="node123",
    )

    assert captured["transport"] is transport
    assert captured["knowledge"] is knowledge
    assert captured["run_id"] == "run-node123"
    assert captured["scene_id"] == "node123"
    assert captured["proposal_provider"] is not None
    assert session.prepared is True
    assert report["detail_loop"]["shots"]["shot_001"]["status"] == "passed"


def test_transport_session_provider_receives_the_configured_token_budget(
    monkeypatch, tmp_path,
):
    """The detail Agent call must use the same model budget as the UI/headless."""
    import block_director.layer5_orchestrator.coarse_agent as coarse_agent

    evidence_dir = tmp_path / "frames"
    evidence_dir.mkdir()
    _install_pipeline_boundaries(monkeypatch, tmp_path)
    session = _DetailSession({"shot_001": 82.0}, evidence_dir)
    transport = types.SimpleNamespace(chat=lambda *_args, **_kwargs: None)
    knowledge = object()
    provider = object()
    captured = {}

    def make_provider(*, transport, knowledge, max_tokens, stage):
        captured.update({
            "transport": transport,
            "knowledge": knowledge,
            "max_tokens": max_tokens,
            "stage": stage,
        })
        return provider

    monkeypatch.setattr(
        coarse_agent,
        "make_coarse_proposal_provider",
        make_provider,
    )

    def session_factory(**kwargs):
        captured["factory"] = kwargs
        return session

    run_detail_pipeline(
        baseline=_baseline(),
        plan=_plan(),
        out_dir=tmp_path / "detail",
        render_video=False,
        transport=transport,
        knowledge=knowledge,
        proposal_max_tokens=4321,
        session_factory=session_factory,
    )

    assert captured["transport"] is transport
    assert captured["knowledge"] is knowledge
    assert captured["max_tokens"] == 4321
    assert captured["stage"] == "detail"
    assert captured["factory"]["proposal_provider"] is provider


def test_passing_session_exports_the_gated_final_video(
    monkeypatch, tmp_path,
):
    evidence_dir = tmp_path / "frames"
    evidence_dir.mkdir()
    calls = _install_pipeline_boundaries(monkeypatch, tmp_path)
    session = _DetailSession({"shot_001": 82.0}, evidence_dir)
    baseline = _baseline()
    baseline["report"] = {
        "schema_version": "blockout-report/v1",
        "verdict": "pass",
        "findings": [],
        "checks": [{
            "check_id": "composition",
            "shot_id": "shot_001",
            "actual": 82.0,
            "threshold": 80.0,
            "verdict": "pass",
        }],
    }

    report = run_detail_pipeline(
        baseline=baseline,
        plan=_plan(),
        out_dir=tmp_path / "detail",
        render_video=True,
        session=session,
    )

    final_video = tmp_path / "detail" / "final_video.mp4"
    assert ("render", ()) in calls
    assert report["gates"]["final"] == "pass"
    assert report["final"] is True
    assert report["video"]["final"] is True
    assert report["artifacts"]["final_video"] == str(final_video)
    assert final_video.is_file()


def test_measurement_only_path_can_never_claim_final(
    monkeypatch, tmp_path,
):
    calls = _install_pipeline_boundaries(
        monkeypatch, tmp_path,
        sequence_verdict="pass",
        composition_score=85.0,
    )
    baseline = _baseline()
    baseline["report"] = {
        "schema_version": "blockout-report/v1",
        "verdict": "pass",
        "findings": [],
        "checks": [{
            "check_id": "composition",
            "shot_id": "shot_001",
            "actual": 85.0,
            "threshold": 80.0,
            "verdict": "pass",
        }],
    }

    report = run_detail_pipeline(
        baseline=baseline,
        plan=_plan(),
        out_dir=tmp_path / "detail",
        render_video=True,
    )

    final_video = tmp_path / "detail" / "final_video.mp4"
    assert report["detail_loop"]["status"] == "blocked"
    assert report["gates"]["detail"] == "blocked"
    assert report["gates"]["final"] == "blocked"
    assert report["final"] is False
    assert report["artifacts"]["final_video"] is None
    assert not final_video.exists()
    assert not (
        tmp_path / "detail" / "detail_final_manifest.json").exists()
    assert (
        tmp_path / "detail" / "detail_retained_manifest.json").is_file()
    assert report["artifacts"]["detail_final_manifest"] is None
    assert calls
    assert report["video"]["rendered"] is True
    assert report["video"]["diagnostic"] is True
    assert report["video"]["final"] is False
