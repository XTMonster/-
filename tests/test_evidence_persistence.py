"""EvidenceStore must survive project, resume and replay boundaries."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import MethodType, SimpleNamespace

import pytest
from PIL import Image

from block_director.contracts.audit import canonical_fingerprint
from block_director.contracts.blockout import manifest_fingerprint
from block_director.contracts.coarse_reference import (
    coarse_reference_content_fingerprint,
)
from block_director.contracts.evidence import (
    EvidenceStore,
    ShotEvidence,
    evidence_status_text,
    inspect_evidence_store_payload,
)
from block_director.contracts.plan import Plan
from block_director.contracts.world_state import world_state_fingerprint
from block_director.layer5_orchestrator.states import DriverState
from block_director.layer2_sdl import build_sdl
from block_director.layer5_orchestrator.driver import (
    ResumeState,
    ResumeStateError,
    PrevisDriver,
    load_resume_state,
    save_resume_state,
)
from block_director.layer5_orchestrator.headless_runner import save_run_project
from block_director.layer6_audit.audit_logger import AuditLogger
from block_director.layer9_persistence import load_project, save_project
from block_director.layer9_persistence.replay import replay

from test_sdl import BUILD, demo_plan


class _Registry:
    def names(self):
        return ()

    def execute(self, tool, args):
        raise AssertionError(f"replay must not execute tools: {tool} {args}")


def _frame_rows(tmp_path: Path, shot_id: str) -> list[dict]:
    rows = []
    for frame, phase, color in (
        (1, "first", (220, 30, 30, 255)),
        (12, "middle", (30, 220, 30, 255)),
        (24, "last", (30, 30, 220, 255)),
    ):
        path = tmp_path / "frames" / f"{shot_id}-{phase}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        image = Image.new("RGBA", (8, 8), color)
        image.save(path, format="PNG")
        rgba = image.convert("RGBA")
        rows.append({
            "shot_id": shot_id,
            "frame": frame,
            "phase": phase,
            "path": str(path.resolve()),
            "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "pixel_sha256": hashlib.sha256(rgba.tobytes()).hexdigest(),
            "width": rgba.width,
            "height": rgba.height,
            "file_bytes": path.stat().st_size,
            "readable": True,
        })
    return rows


def _store(*, schema_version: str = "",
           scene_plan: dict | None = None,
           tmp_path: Path | None = None) -> EvidenceStore:
    fixture_dir = tmp_path or Path.cwd() / ".pytest_evidence_fixture"
    report = {
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
    plan_payload = {
        "scene": scene_plan or {"shots": [{"shot_id": "shot_001"}]},
        "shot": {"shot_id": "shot_001"},
    }
    reference = {
        "scene_id": "scene-1",
        "characters": [{"name": "甲", "position": {"x": 1, "y": 0, "z": 0}}],
        "camera_intents": [{"shot_id": "shot_001", "position": [0, 3, 1]}],
    }
    manifest = {
        "scene_id": "scene-1",
        "cameras": [{"shot_id": "shot_001"}],
        "shot_table": [{"shot_id": "shot_001", "character_ids": ["甲"]}],
    }
    world_state = {
        "characters": {"甲": {"position": [1, 0, 0]}},
        "cameras": {"shot_001": {"position": [0, 3, 1]}},
    }
    frames = _frame_rows(fixture_dir, "shot_001")
    report["manifest_fingerprint"] = manifest_fingerprint(manifest)
    observation_id = "obs-" + canonical_fingerprint({
        "shot_id": "shot_001",
        "frames": [
            [row["phase"], row["pixel_sha256"]] for row in frames
        ],
    })
    basis = {
        "observation_id": observation_id,
        "bundle_fingerprint": canonical_fingerprint({
            "observation_id": observation_id,
            "reference": reference,
            "manifest": manifest,
            "report": report,
            "world_state": world_state,
            "frames": frames,
        }),
        "reference_fingerprint": coarse_reference_content_fingerprint(reference),
        "manifest_fingerprint": manifest_fingerprint(manifest),
        "report_fingerprint": canonical_fingerprint(report),
        "world_state_fingerprint": world_state_fingerprint(world_state),
        "scene_content_fingerprint": canonical_fingerprint({
            "reference": reference,
            "manifest": manifest,
            "world_state": world_state,
        }),
    }
    store = EvidenceStore(run_id="run-1", scene_id="scene-1")
    store.append(ShotEvidence.create(
        run_id="run-1",
        scene_id="scene-1",
        shot_id="shot_001",
        version=0,
        parent_version=None,
        reason="coarse_initial_observation",
        created_at="2026-10-21T00:00:00Z",
        plan=plan_payload,
        shot_contract={
            "shot_id": "shot_001",
            "shot_type": "MS",
            "intent": "persistence fixture",
        },
        reference=reference,
        manifest=manifest,
        world_state=world_state,
        build={
            "status": "unit-fixture",
            "object_count": 0,
            "manifest_fingerprint": "unit-fixture-manifest",
        },
        audit={
            "verdict": "pass",
            "report_fingerprint": basis["report_fingerprint"],
        },
        measurements={"component": "blockout"},
        score_breakdown={
            "composition": 82.0,
            "hard_error_count": 0,
        },
        gates={"coarse_passed": True, "shot_passed": True},
        hard_gates={
            "status": "pass",
            "failed": [],
            "evaluated": ["unit-fixture hard gates"],
        },
        shot_slice={
            "shot_001": {
                "reference": {"shot": {"shot_id": "shot_001"}},
                "manifest": {"camera": {"shot_id": "shot_001"}},
                "world_state": {"camera": {"position": [0, 3, 1]}},
            },
        },
        frames=frames,
        absence_reasons={
            "sequence_gate": "sequence review is outside this unit fixture",
            "semantic_review":
                "unit fixture does not include a semantic review",
            "rag":
                "unit fixture does not include RAG provenance",
            "correction_candidates":
                "unit fixture does not model correction candidates",
            "applied_operations":
                "unit fixture does not model applied operations",
            "remeasurement":
                "unit fixture does not model a correction remeasurement",
            "disposition":
                "unit fixture does not model a correction disposition",
        },
        basis_fingerprints=basis,
        delivery_eligible=False,
    ))
    store.mark_best("shot_001", 0)
    store.mark_adopted("shot_001", 0)
    if schema_version:
        payload = store.to_dict()
        payload["schema_version"] = schema_version
        return payload  # type: ignore[return-value]
    return store


def test_project_round_trip_uses_the_authoritative_evidence_store(tmp_path):
    sdl = build_sdl(demo_plan(), build_summary=BUILD)
    store = _store(tmp_path=tmp_path)

    save_project(tmp_path, sdl, evidence_store=store)
    loaded = load_project(tmp_path)

    assert loaded.evidence_status["status"] == "authoritative"
    assert loaded.evidence_store.best_version("shot_001") == 0
    assert loaded.summary()["evidence"]["best"] == {"shot_001": 0}


def test_old_evidence_schema_is_readable_but_never_authoritative(tmp_path):
    sdl = build_sdl(demo_plan(), build_summary=BUILD)
    legacy = _store(schema_version="evidence-store/v0", tmp_path=tmp_path)
    path = save_project(tmp_path, sdl)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["evidence_store"] = legacy
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    loaded = load_project(tmp_path)

    assert loaded.evidence_store is None
    assert loaded.evidence_status["status"] == "stale"
    assert loaded.summary()["evidence"]["status"] == "stale"


def test_previous_schema_v2_is_stale_even_when_store_envelope_is_current(
        tmp_path):
    store = _store(tmp_path=tmp_path)
    payload = store.to_dict()
    payload["histories"]["shot_001"][0]["schema_version"] = "shot-evidence/v2"

    parsed, status = inspect_evidence_store_payload(payload)

    assert parsed is None
    assert status["status"] == "stale"
    assert "unsupported evidence schema" in status["reason"]


def test_stale_evidence_is_readable_but_cannot_resume(tmp_path):
    store = _store(tmp_path=tmp_path)
    payload = store.to_dict()
    payload["histories"]["shot_001"][0]["schema_version"] = "shot-evidence/v2"
    state = ResumeState(
        run_id="run-1",
        evidence_store=payload,
    ).to_dict()

    with pytest.raises(ResumeStateError, match="unsupported evidence schema"):
        ResumeState.from_dict(state)


def test_resume_round_trip_keeps_evidence_and_best_pointer(tmp_path):
    store = _store(tmp_path=tmp_path)
    state = ResumeState(run_id="run-1", evidence_store=store.to_dict())
    path = save_resume_state(tmp_path / "resume_state.json", state)

    loaded = load_resume_state(path)

    assert loaded.evidence_store == store.to_dict()
    assert loaded.evidence_store["best"] == {"shot_001": 0}


def test_zero_llm_replay_loads_and_checks_the_same_evidence(tmp_path):
    store = _store(tmp_path=tmp_path)
    store_path = store.save_atomic(tmp_path / "coarse" / "evidence_store.json")
    report_fp = store.get("shot_001", 0).basis_fingerprints[
        "report_fingerprint"]
    plan_payload = demo_plan().to_dict()
    records = [
        {"kind": "plan_received", "data": {"plan": plan_payload}},
        {
            "kind": "headless_coarse_gate",
            "data": {
                "payload": {
                    "best_report_fingerprint": report_fp,
                    "artifacts": {"evidence_store": str(store_path)},
                },
            },
        },
    ]
    (tmp_path / "audit_log.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in records)
        + "\n",
        encoding="utf-8",
    )

    report = replay(tmp_path, _Registry(), build=False)

    assert report.evidence_status["status"] == "authoritative"
    assert report.evidence_status["consistent"] is True
    assert report.evidence_best == {"shot_001": 0}


def test_replay_retains_stale_evidence_without_a_best_pointer(tmp_path):
    store = _store(tmp_path=tmp_path)
    payload = store.to_dict()
    payload["histories"]["shot_001"][0]["schema_version"] = "shot-evidence/v2"
    path = tmp_path / "coarse" / "evidence_store.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    records = [
        {"kind": "plan_received", "data": {"plan": demo_plan().to_dict()}},
        {
            "kind": "headless_coarse_gate",
            "data": {
                "payload": {
                    "artifacts": {"evidence_store": str(path)},
                },
            },
        },
    ]
    (tmp_path / "audit_log.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in records)
        + "\n",
        encoding="utf-8",
    )

    report = replay(tmp_path, _Registry(), build=False)

    assert report.evidence_store is None
    assert report.evidence_best == {}
    assert report.evidence_status["status"] == "stale"
    assert report.evidence_status["consistent"] is False
    assert "不可用于验收" in evidence_status_text(report.evidence_status)


def test_headless_refuses_to_persist_stale_evidence(tmp_path):
    store = _store(tmp_path=tmp_path)
    payload = store.to_dict()
    payload["histories"]["shot_001"][0]["schema_version"] = "shot-evidence/v2"
    summary = {
        "plan": demo_plan().to_dict(),
        "build": BUILD,
        "evidence_store": payload,
    }

    with pytest.raises(ValueError, match="不是权威证据"):
        save_run_project(summary, out_dir=tmp_path / "saved")


def test_project_resume_and_replay_agree_on_evidence_best_and_quality(
        tmp_path,
):
    sdl = build_sdl(demo_plan(), build_summary=BUILD)
    store = _store(tmp_path=tmp_path)
    expected_fingerprint = store.fingerprint()
    expected_best = store.summary()["best"]
    expected_quality = store.get("shot_001", 0).basis_fingerprints[
        "report_fingerprint"]

    save_project(tmp_path, sdl, evidence_store=store)
    loaded = load_project(tmp_path)
    resume = ResumeState(run_id="run-1", evidence_store=store.to_dict())
    resume_path = save_resume_state(
        tmp_path / "resume_state.json", resume)
    resumed = load_resume_state(resume_path)

    store_path = store.save_atomic(tmp_path / "coarse" / "evidence_store.json")
    plan_payload = demo_plan().to_dict()
    records = [
        {"kind": "plan_received", "data": {"plan": plan_payload}},
        {
            "kind": "headless_coarse_gate",
            "data": {
                "payload": {
                    "best_report_fingerprint": expected_quality,
                    "artifacts": {"evidence_store": str(store_path)},
                },
            },
        },
    ]
    (tmp_path / "audit_log.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in records)
        + "\n",
        encoding="utf-8",
    )
    replayed = replay(tmp_path, _Registry(), build=False)
    resumed_store = EvidenceStore.from_dict(resumed.evidence_store)

    assert loaded.evidence_store is not None
    assert (
        loaded.evidence_store.fingerprint(),
        loaded.evidence_store.summary()["best"],
        loaded.evidence_store.get("shot_001", 0).basis_fingerprints[
            "report_fingerprint"],
    ) == (expected_fingerprint, expected_best, expected_quality)
    assert (
        resumed_store.fingerprint(),
        resumed_store.summary()["best"],
        resumed_store.get("shot_001", 0).basis_fingerprints[
            "report_fingerprint"],
    ) == (expected_fingerprint, expected_best, expected_quality)
    assert replayed.evidence_store is not None
    assert (
        replayed.evidence_store.fingerprint(),
        replayed.evidence_best,
        replayed.evidence_store.get("shot_001", 0).basis_fingerprints[
            "report_fingerprint"],
    ) == (expected_fingerprint, expected_best, expected_quality)


def test_driver_attaches_only_evidence_matching_the_published_best(tmp_path):
    store = _store(tmp_path=tmp_path)
    path = store.save_atomic(tmp_path / "evidence_store.json")
    record = store.get("shot_001", 0)
    payload = {
        "schema_version": "coarse-pipeline-report/v1",
        "best_report_fingerprint": record.basis_fingerprints[
            "report_fingerprint"],
        "best_manifest_fingerprint": "wrong-manifest",
        "artifacts": {"evidence_store": str(path)},
    }
    stub = SimpleNamespace(evidence_store=None)

    error = MethodType(
        PrevisDriver._attach_coarse_evidence,
        stub,
    )({"payload": payload})

    assert "manifest 指纹" in error
    assert stub.evidence_store is None

    payload["best_manifest_fingerprint"] = ""
    error = MethodType(
        PrevisDriver._attach_coarse_evidence,
        stub,
    )({"payload": payload})

    assert error == ""
    assert stub.evidence_store.best_version("shot_001") == 0


def test_coarse_evidence_allows_detail_elaboration_but_rejects_identity_drift(
        tmp_path):
    approved = demo_plan().to_dict()
    store = _store(scene_plan=approved, tmp_path=tmp_path)
    path = store.save_atomic(tmp_path / "evidence_store.json")
    payload = {
        "schema_version": "coarse-pipeline-report/v1",
        "artifacts": {"evidence_store": str(path)},
    }

    detailed = Plan.from_dict(approved)
    detailed.shots[0].actions = [{
        "character_id": detailed.shots[0].characters[0],
        "action_type": "nod",
        "start_frame": 0,
        "end_frame": 12,
    }]
    stub = SimpleNamespace(evidence_store=None, plan=detailed)
    error = MethodType(
        PrevisDriver._attach_coarse_evidence,
        stub,
    )({"payload": payload})
    assert error == ""

    drifted = detailed.to_dict()
    drifted["shots"][0]["characters"] = ["char_999"]
    stub = SimpleNamespace(
        evidence_store=None, plan=Plan.from_dict(drifted))
    error = MethodType(
        PrevisDriver._attach_coarse_evidence,
        stub,
    )({"payload": payload})
    assert "镜头身份" in error
    assert "characters" in error


def test_resume_reuses_a_valid_cached_coarse_decision_without_rerunning(
        tmp_path,
):
    plan = demo_plan()
    plan_payload = plan.to_dict()
    shot_id = plan.shots[0].shot_id
    manifest = {
        "schema_version": "blockout-manifest/v1",
        "scene_id": "scene-1",
        "primitives": [],
        "cameras": [],
        "shot_table": [{"shot_id": shot_id, "character_ids": []}],
    }
    reference = {
        "schema_version": "coarse-world-reference/v1",
        "scene_id": "scene-1",
        "characters": [],
        "props": [],
        "anchors": [],
        "camera_intents": [],
        "shots": plan_payload["shots"],
        "revisions": [],
        "notes": [],
    }
    world_state = {
        "schema_version": "runtime-world/v1",
        "characters": {},
        "cameras": {},
        "props": {},
        "anchors": {},
    }
    report = {
        "schema_version": "blockout-report/v1",
        "manifest_fingerprint": manifest_fingerprint(manifest),
        "verdict": "pass",
        "findings": [],
        "checks": [{
            "check_id": "composition",
            "shot_id": shot_id,
            "actual": 82.0,
            "threshold": 80.0,
            "verdict": "pass",
        }],
    }
    frames = _frame_rows(tmp_path, shot_id)
    scene_content = canonical_fingerprint({
        "reference": reference,
        "manifest": manifest,
        "world_state": world_state,
    })
    observation_id = "obs-" + canonical_fingerprint({
        "shot_id": shot_id,
        "frames": [
            [row["phase"], row["pixel_sha256"]] for row in frames
        ],
    })
    basis = {
        "observation_id": observation_id,
        "bundle_fingerprint": canonical_fingerprint({
            "observation_id": observation_id,
            "reference": reference,
            "manifest": manifest,
            "report": report,
            "world_state": world_state,
            "frames": frames,
        }),
        "report_fingerprint": canonical_fingerprint(report),
        "manifest_fingerprint": manifest_fingerprint(manifest),
        "reference_fingerprint": coarse_reference_content_fingerprint(
            reference),
        "world_state_fingerprint": world_state_fingerprint(world_state),
        "scene_content_fingerprint": scene_content,
    }
    store = EvidenceStore(run_id="run-1", scene_id="scene-1")
    store.append(ShotEvidence.create(
        run_id="run-1",
        scene_id="scene-1",
        shot_id=shot_id,
        version=0,
        parent_version=None,
        reason="coarse_initial_observation",
        created_at="2026-10-21T00:00:00Z",
        plan={"scene": plan_payload, "shot": plan_payload["shots"][0]},
        shot_contract=plan_payload["shots"][0],
        reference=reference,
        manifest=manifest,
        world_state=world_state,
        shot_slice={"shot_id": shot_id},
        build={
            "status": "resume-fixture",
            "manifest_fingerprint": basis["manifest_fingerprint"],
        },
        audit={
            "verdict": "pass",
            "report_fingerprint": basis["report_fingerprint"],
        },
        measurements={"composition": 82.0},
        score_breakdown={
            "composition": 82.0,
            "hard_error_count": 0,
        },
        gates={"coarse_passed": True, "shot_passed": True},
        hard_gates={
            "status": "pass",
            "failed": [],
            "evaluated": ["resume fixture hard gates"],
        },
        frames=frames,
        absence_reasons={
            "sequence_gate":
                "sequence review is outside this resume fixture",
            "semantic_review":
                "resume fixture does not include a semantic review",
            "rag":
                "resume fixture does not include RAG provenance",
            "correction_candidates":
                "resume fixture does not model correction candidates",
            "applied_operations":
                "resume fixture does not model applied operations",
            "remeasurement":
                "resume fixture does not model a correction remeasurement",
            "disposition":
                "resume fixture does not model a correction disposition",
        },
        basis_fingerprints=basis,
        delivery_eligible=False,
    ))
    store.mark_best(shot_id, 0)
    store.mark_adopted(shot_id, 0)
    store_path = store.save_atomic(tmp_path / "coarse" / "evidence_store.json")
    baseline = {
        "schema_version": "coarse-baseline/v1",
        "state": "frozen",
        "reference_fingerprint": basis["reference_fingerprint"],
        "manifest_fingerprint": basis["manifest_fingerprint"],
        "report_fingerprint": basis["report_fingerprint"],
        "manifest": manifest,
        "reference": reference,
        "report": report,
    }
    pipeline_report = {
        "schema_version": "coarse-pipeline-report/v1",
        "run_id": "run-1",
        "scene_id": "scene-1",
        "coarse_status": "approved",
        "best_manifest_fingerprint": basis["manifest_fingerprint"],
        "best_report_fingerprint": basis["report_fingerprint"],
        "best_world_state_fingerprint": basis["world_state_fingerprint"],
        "gates": {"coarse": "pass", "baseline": "frozen"},
        "artifacts": {"evidence_store": str(store_path)},
    }
    decision = {
        "ready": True,
        "gates": {"coarse": "pass", "baseline": "frozen"},
        "payload": pipeline_report,
        "baseline": baseline,
    }
    state = ResumeState(
        run_id="run-1",
        plan=plan_payload,
        evidence_store=store.to_dict(),
        coarse_decision=decision,
    )
    calls = []

    def gate(_plan, brief=None):
        calls.append(brief)
        return {"ready": False, "reason": "must not rerun"}

    class Builder:
        attached = None

        def attach_coarse_baseline(self, value):
            self.attached = value
            return 1

    builder = Builder()
    driver = PrevisDriver(
        transport=SimpleNamespace(
            chat=lambda *_args, **_kwargs: None,
            cancel=lambda *_args, **_kwargs: None,
        ),
        audit=AuditLogger(),
        script="INT. 测试 - 日\n",
        registry=_Registry(),
        builder=builder,
        resume_state=state,
        coarse_gate=gate,
    )

    assert calls == []
    assert driver.state is DriverState.EDITING
    assert builder.attached == baseline
    assert any(event.kind == "coarse_gate_reused"
               for event in driver.audit.recent())
