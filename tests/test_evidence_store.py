"""Immutable per-shot evidence and physical-state restore pointers."""

from __future__ import annotations

import json

import pytest

from block_director.contracts.audit import canonical_fingerprint
from block_director.contracts.blockout import manifest_fingerprint
from block_director.contracts.coarse_reference import (
    coarse_reference_content_fingerprint,
)
from block_director.contracts.evidence import (
    EvidenceError,
    EvidenceStore,
    ShotEvidence,
)
from block_director.contracts.world_state import world_state_fingerprint


def _record(
    version: int,
    score: float,
    *,
    x: float = 0.0,
    shot_id: str = "shot_001",
) -> ShotEvidence:
    plan = {"shots": [{"shot_id": "shot_001", "version": version}]}
    reference = {"characters": {"甲": {"position": [x, 0.0, 0.0]}}}
    manifest = {"cameras": {}}
    world_state = {"characters": {"甲": {"position": [x, 0.0, 0.0]}}}
    report = {
        "verdict": "pass" if score > 80.0 else "fail",
        "manifest_fingerprint": manifest_fingerprint(manifest),
        "checks": [{
            "check_id": "composition",
            "shot_id": shot_id,
            "actual": score,
        }],
    }
    scene_content = canonical_fingerprint({
        "reference": reference,
        "manifest": manifest,
        "world_state": world_state,
    })
    observation_id = f"obs-{canonical_fingerprint([shot_id, version, scene_content])}"
    basis = {
        "observation_id": observation_id,
        "bundle_fingerprint": canonical_fingerprint({
            "observation_id": observation_id,
            "scene_content": scene_content,
        }),
        "reference_fingerprint": coarse_reference_content_fingerprint(reference),
        "manifest_fingerprint": manifest_fingerprint(manifest),
        "report_fingerprint": canonical_fingerprint(report),
        "world_state_fingerprint": world_state_fingerprint(world_state),
        "scene_content_fingerprint": scene_content,
    }
    return ShotEvidence.create(
        run_id="run-1",
        scene_id="scene-1",
        shot_id=shot_id,
        version=version,
        parent_version=None if version == 0 else version - 1,
        reason="initial" if version == 0 else "repair",
        created_at=f"2026-10-21T00:00:0{version}Z",
        plan=plan,
        shot_contract={
            "shot_id": shot_id,
            "shot_type": "MS",
            "version": version,
        },
        reference=reference,
        manifest=manifest,
        world_state=world_state,
        shot_slice={"shot_id": shot_id, "camera": "cam_001"},
        build={
            "status": "unit-fixture",
            "object_count": 0,
            "manifest_fingerprint": f"manifest-{version}",
        },
        audit={
            "verdict": "pass" if score > 80.0 else "fail",
            "report_fingerprint": basis["report_fingerprint"],
        },
        measurements={"composition": score},
        score_breakdown={
            "composition": score,
            "hard_error_count": 0,
        },
        gates={
            "composition": "pass" if score > 80.0 else "fail",
            "shot_passed": score > 80.0,
        },
        hard_gates={
            "status": "pass",
            "failed": [],
            "evaluated": ["unit-fixture hard gates"],
        },
        absence_reasons={
            "frames": "unit fixture does not render frame images",
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
    )


def test_store_restores_an_exact_shot_version():
    store = EvidenceStore(run_id="run-1", scene_id="scene-1")
    first = store.append(_record(0, 70.0, x=1.0))
    store.mark_best("shot_001", 0)
    store.append(_record(1, 50.0, x=9.0))

    restored = store.restore("shot_001", first.version)

    assert store.best_version("shot_001") == 0
    assert restored["plan"]["shots"][0]["version"] == 0
    assert restored["reference"]["characters"]["甲"]["position"] == [1.0, 0.0, 0.0]
    assert restored["world_state"]["characters"]["甲"]["position"] == [1.0, 0.0, 0.0]


def test_considering_a_worse_candidate_keeps_the_passing_best():
    store = EvidenceStore(run_id="run-1", scene_id="scene-1")

    store.consider_candidate(_record(0, 82.0, x=1.0))
    store.consider_candidate(_record(1, 70.0, x=9.0))

    assert store.best_version("shot_001") == 0
    assert store.adopted_version("shot_001") == 0


def test_failed_diagnostic_best_survives_ties_cycles_and_persistence(tmp_path):
    store = EvidenceStore(run_id="run-1", scene_id="scene-1")
    store.consider_candidate(_record(0, 70.0, x=1.0))
    store.consider_candidate(_record(1, 75.0, x=2.0))
    store.consider_candidate(_record(2, 75.0, x=3.0))
    store.consider_candidate(_record(3, 70.0, x=1.0))

    assert store.best_version("shot_001") == 1
    with pytest.raises(KeyError):
        store.adopted_version("shot_001")

    loaded = EvidenceStore.load(
        store.save_atomic(tmp_path / "evidence.json"))

    assert loaded.best_version("shot_001") == 1
    assert loaded.get("shot_001", 1).measurements["composition"] == 75.0
    assert loaded.validate() == []


def test_store_round_trips_atomically_and_rejects_tampering(tmp_path):
    store = EvidenceStore(run_id="run-1", scene_id="scene-1")
    store.append(_record(0, 70.0))
    store.mark_best("shot_001", 0)
    path = store.save_atomic(tmp_path / "evidence.json")

    loaded = EvidenceStore.load(path)
    assert loaded.to_dict() == store.to_dict()

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["histories"]["shot_001"][0]["measurements"]["composition"] = 99.0
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(EvidenceError, match="digest mismatch"):
        EvidenceStore.load(path)


def test_atomic_save_rejects_non_finite_json_without_replacing_target(tmp_path):
    store = EvidenceStore(run_id="run-1", scene_id="scene-1")
    store.append(_record(0, 70.0))
    store.mark_best("shot_001", 0)
    path = store.save_atomic(tmp_path / "evidence.json")
    original = path.read_text(encoding="utf-8")

    payload = _record(1, 82.0).to_dict(include_digest=False)
    payload["measurements"]["variance"] = float("nan")
    non_finite = ShotEvidence.create(**payload)
    store.append(non_finite)
    store.mark_best("shot_001", 1)

    with pytest.raises(EvidenceError, match="finite"):
        store.save_atomic(path)

    assert path.read_text(encoding="utf-8") == original


def test_store_rejects_non_contiguous_versions():
    store = EvidenceStore(run_id="run-1", scene_id="scene-1")

    with pytest.raises(EvidenceError, match="contiguous"):
        store.append(_record(1, 70.0))


def test_store_rejects_duplicate_version_writes():
    store = EvidenceStore(run_id="run-1", scene_id="scene-1")
    store.append(_record(0, 70.0))

    with pytest.raises(EvidenceError, match="contiguous"):
        store.append(_record(0, 70.0))


def test_non_empty_history_without_best_is_invalid():
    store = EvidenceStore(run_id="run-1", scene_id="scene-1")
    store.append(_record(0, 70.0))

    errors = store.validate()

    assert any("missing best pointer" in item for item in errors)


def test_adopted_pointer_must_equal_best():
    store = EvidenceStore(run_id="run-1", scene_id="scene-1")
    store.append(_record(0, 82.0))
    store.append(_record(1, 84.0))
    store.mark_best("shot_001", 0)

    with pytest.raises(EvidenceError, match="best"):
        store.mark_adopted("shot_001", 1)


def test_failed_best_cannot_be_adopted():
    store = EvidenceStore(run_id="run-1", scene_id="scene-1")
    store.append(_record(0, 70.0))
    store.mark_best("shot_001", 0)

    with pytest.raises(EvidenceError, match="passing"):
        store.mark_adopted("shot_001", 0)

    assert store.validate() == []


def test_direct_load_rejects_history_without_best(tmp_path):
    store = EvidenceStore(run_id="run-1", scene_id="scene-1")
    store.append(_record(0, 82.0))
    path = tmp_path / "evidence.json"
    path.write_text(
        json.dumps(store.to_dict(), ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )

    with pytest.raises(EvidenceError, match="best pointer"):
        EvidenceStore.load(path)


def test_direct_load_rejects_dangling_best_pointer(tmp_path):
    store = EvidenceStore(run_id="run-1", scene_id="scene-1")
    store.append(_record(0, 82.0))
    payload = store.to_dict()
    payload["best"] = {"shot_001": 7}
    path = tmp_path / "evidence.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )

    with pytest.raises(EvidenceError, match="unknown evidence version"):
        EvidenceStore.load(path)


def test_store_keeps_independent_histories_and_best_for_multiple_shots():
    store = EvidenceStore(run_id="run-1", scene_id="scene-1")
    store.append(_record(0, 70.0, x=1.0, shot_id="shot_001"))
    store.append(_record(0, 81.0, x=2.0, shot_id="shot_002"))
    store.mark_best("shot_001", 0)
    store.mark_best("shot_002", 0)
    store.mark_adopted("shot_002", 0)

    assert store.summary()["versions"] == {"shot_001": 1, "shot_002": 1}
    assert store.summary()["best"] == {"shot_001": 0, "shot_002": 0}
    assert store.summary()["adopted"] == {"shot_002": 0}
    assert store.validate() == []


def test_store_validation_marks_missing_evidence_explicitly():
    store = EvidenceStore(run_id="run-1", scene_id="scene-1")
    record = ShotEvidence.create(
        run_id="run-1",
        scene_id="scene-1",
        shot_id="shot_001",
        version=0,
        parent_version=None,
        reason="initial",
        created_at="2026-10-21T00:00:00Z",
        plan={"shot": {"shot_id": "shot_001"}},
        reference={"scene_id": "scene-1"},
        manifest={"scene_id": "scene-1"},
        world_state={"characters": {}},
        measurements={"composition": 82.0},
        gates={"shot_passed": True},
    )
    store.append(record)
    store.mark_best("shot_001", 0)

    errors = store.validate()

    assert any("shot_slice" in item for item in errors)
    assert any("basis_fingerprints" in item for item in errors)


def test_atomic_save_refuses_incomplete_evidence(tmp_path):
    store = EvidenceStore(run_id="run-1", scene_id="scene-1")
    store.append(ShotEvidence.create(
        run_id="run-1",
        scene_id="scene-1",
        shot_id="shot_001",
        version=0,
        parent_version=None,
        reason="initial",
        created_at="2026-10-21T00:00:00Z",
        plan={"shot": {"shot_id": "shot_001"}},
        reference={"scene_id": "scene-1"},
        manifest={"scene_id": "scene-1"},
        world_state={"characters": {}},
        measurements={"composition": 82.0},
        gates={"shot_passed": True},
    ))
    store.mark_best("shot_001", 0)

    with pytest.raises(EvidenceError, match="shot_slice"):
        store.save_atomic(tmp_path / "evidence.json")


def test_empty_frame_evidence_requires_an_explicit_absence_reason():
    payload = _record(0, 82.0).to_dict(include_digest=False)
    payload["frames"] = []
    payload["absence_reasons"] = {}
    store = EvidenceStore(run_id="run-1", scene_id="scene-1")
    store.append(ShotEvidence.create(**payload))
    store.mark_best("shot_001", 0)

    errors = store.validate()

    assert any(
        "frames evidence is missing without an absence reason" in item
        for item in errors
    )


def test_explicit_absence_cannot_be_reported_as_complete_evidence():
    payload = _record(0, 82.0).to_dict(include_digest=False)
    payload["frames"] = []
    payload["absence_reasons"] = {
        "frames": "frame rendering was unavailable in this unit fixture",
    }
    payload["gates"]["evidence_complete"] = True
    store = EvidenceStore(run_id="run-1", scene_id="scene-1")
    store.append(ShotEvidence.create(**payload))
    store.mark_best("shot_001", 0)

    errors = store.validate()

    assert any(
        "evidence_complete cannot be true while evidence is absent" in item
        for item in errors
    )


def test_shot_evidence_persists_hard_and_sequence_gate_states():
    payload = _record(0, 82.0).to_dict(include_digest=False)
    payload["hard_gates"] = {
        "status": "pass",
        "failed": [],
        "evaluated": ["axis", "occlusion"],
    }
    payload["sequence_gate"] = {
        "status": "not_evaluated",
        "reason": "sequence review runs after per-shot quality",
    }
    store = EvidenceStore(run_id="run-1", scene_id="scene-1")
    store.append(ShotEvidence.create(**payload))
    store.mark_best("shot_001", 0)

    loaded = EvidenceStore.from_dict(store.to_dict()).get("shot_001", 0)

    assert loaded.hard_gates["status"] == "pass"
    assert loaded.sequence_gate["status"] == "not_evaluated"
    assert loaded.sequence_gate["reason"]


def test_hard_and_sequence_gate_absence_must_be_explicit():
    payload = _record(0, 82.0).to_dict(include_digest=False)
    payload["hard_gates"] = {}
    payload["sequence_gate"] = {}
    payload["absence_reasons"] = {
        "frames": "unit fixture does not render frame images",
    }
    store = EvidenceStore(run_id="run-1", scene_id="scene-1")
    store.append(ShotEvidence.create(**payload))
    store.mark_best("shot_001", 0)

    errors = store.validate()

    assert any(
        "hard_gates evidence is missing without an absence reason" in item
        for item in errors
    )
    assert any(
        "sequence_gate evidence is missing without an absence reason" in item
        for item in errors
    )


def test_correction_candidates_operations_remeasurement_and_disposition_round_trip():
    payload = _record(0, 82.0).to_dict(include_digest=False)
    payload["correction_candidates"] = [{
        "candidate_id": "cand-1",
        "change": "raise camera by 0.2 m",
    }]
    payload["applied_operations"] = [{
        "operation_id": "op-1",
        "candidate_id": "cand-1",
        "status": "applied",
    }]
    payload["remeasurement"] = {
        "score": 83.0,
        "world_state_fingerprint": "new-world",
    }
    payload["disposition"] = {
        "status": "resolved",
        "reason": "remeasured score passed",
    }
    store = EvidenceStore(run_id="run-1", scene_id="scene-1")
    store.append(ShotEvidence.create(**payload))
    store.mark_best("shot_001", 0)

    loaded = EvidenceStore.from_dict(store.to_dict()).get("shot_001", 0)

    assert loaded.correction_candidates[0]["candidate_id"] == "cand-1"
    assert loaded.applied_operations[0]["operation_id"] == "op-1"
    assert loaded.remeasurement["score"] == 83.0
    assert loaded.disposition["status"] == "resolved"


def test_correction_chain_sections_require_absence_reasons():
    payload = _record(0, 82.0).to_dict(include_digest=False)
    for section in (
        "correction_candidates",
        "applied_operations",
        "remeasurement",
        "disposition",
    ):
        payload["absence_reasons"].pop(section, None)
    store = EvidenceStore(run_id="run-1", scene_id="scene-1")
    store.append(ShotEvidence.create(**payload))
    store.mark_best("shot_001", 0)

    errors = store.validate()

    for section in (
        "correction_candidates",
        "applied_operations",
        "remeasurement",
        "disposition",
    ):
        assert any(
            f"{section} evidence is missing without an absence reason"
            in item
            for item in errors
        )


def test_shot_contract_build_audit_and_score_breakdown_round_trip():
    payload = _record(0, 82.0).to_dict(include_digest=False)
    payload["shot_contract"] = {
        "shot_id": "shot_001",
        "shot_type": "MS",
        "intent": "establish",
    }
    payload["build"] = {
        "status": "published",
        "object_count": 7,
        "manifest_fingerprint": "manifest-build",
    }
    payload["audit"] = {
        "verdict": "pass",
        "report_fingerprint": "report-build",
    }
    payload["score_breakdown"] = {
        "composition": 82.0,
        "hard_error_count": 0,
        "sequence": None,
    }
    store = EvidenceStore(run_id="run-1", scene_id="scene-1")
    store.append(ShotEvidence.create(**payload))
    store.mark_best("shot_001", 0)

    loaded = EvidenceStore.from_dict(store.to_dict()).get("shot_001", 0)

    assert loaded.shot_contract["shot_type"] == "MS"
    assert loaded.build["object_count"] == 7
    assert loaded.audit["verdict"] == "pass"
    assert loaded.score_breakdown["composition"] == 82.0


def test_core_build_audit_and_score_sections_require_absence_reasons():
    payload = _record(0, 82.0).to_dict(include_digest=False)
    for section in (
        "shot_contract",
        "build",
        "audit",
        "score_breakdown",
    ):
        payload[section] = {}
    store = EvidenceStore(run_id="run-1", scene_id="scene-1")
    store.append(ShotEvidence.create(**payload))
    store.mark_best("shot_001", 0)

    errors = store.validate()

    for section in (
        "shot_contract",
        "build",
        "audit",
        "score_breakdown",
    ):
        assert any(
            f"{section} evidence is missing without an absence reason"
            in item
            for item in errors
        )


def test_non_empty_frames_must_have_first_middle_last_paths_and_digests():
    payload = _record(0, 82.0).to_dict(include_digest=False)
    payload["absence_reasons"].pop("frames", None)
    payload["frames"] = [{
        "shot_id": "shot_001",
        "frame": 1,
        "phase": "first",
        "path": "",
        "file_sha256": "",
        "pixel_sha256": "",
        "readable": False,
    }]
    store = EvidenceStore(run_id="run-1", scene_id="scene-1")
    store.append(ShotEvidence.create(**payload))
    store.mark_best("shot_001", 0)

    errors = store.validate()

    assert any(
        "frames must contain exactly first/middle/last" in item
        for item in errors
    )
    assert any("frame path is missing" in item for item in errors)
    assert any("file_sha256 is missing" in item for item in errors)
    assert any("pixel_sha256 is missing" in item for item in errors)


def test_semantic_review_and_rag_absence_must_be_explicit():
    payload = _record(0, 82.0).to_dict(include_digest=False)
    payload["absence_reasons"].pop("semantic_review", None)
    payload["absence_reasons"].pop("rag", None)
    store = EvidenceStore(run_id="run-1", scene_id="scene-1")
    store.append(ShotEvidence.create(**payload))
    store.mark_best("shot_001", 0)

    errors = store.validate()

    assert any(
        "semantic_review evidence is missing without an absence reason"
        in item
        for item in errors
    )
    assert any(
        "rag evidence is missing without an absence reason" in item
        for item in errors
    )


def test_basis_fingerprints_must_be_complete():
    store = EvidenceStore(run_id="run-1", scene_id="scene-1")
    payload = _record(0, 82.0).to_dict(include_digest=False)
    payload["basis_fingerprints"] = {}
    store.append(ShotEvidence.create(**payload))
    store.mark_best("shot_001", 0)

    errors = store.validate()

    for key in (
        "observation_id",
        "bundle_fingerprint",
        "reference_fingerprint",
        "manifest_fingerprint",
        "report_fingerprint",
        "world_state_fingerprint",
        "scene_content_fingerprint",
    ):
        assert any(
            f"basis_fingerprints.{key} is missing" in item
            for item in errors
        )
