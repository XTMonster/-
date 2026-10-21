"""Canonical final/partial/diagnostic delivery classification."""

from __future__ import annotations

from dataclasses import replace

from block_director.contracts.audit import canonical_fingerprint
from block_director.contracts.blockout import manifest_fingerprint
from block_director.contracts.coarse_reference import (
    coarse_reference_content_fingerprint,
)
from block_director.contracts.evidence import EvidenceStore, ShotEvidence
from block_director.contracts.plan import Plan
from block_director.contracts.quality import classify_delivery_quality
from block_director.delivery.failures import align_failures_payload
from block_director.contracts.world_state import world_state_fingerprint
from block_director.delivery.manifest import build_manifest
from block_director.delivery.package import (
    actual_shot_video,
    clear_stale_concat_outputs,
    clear_stale_shot_outputs,
    clear_stale_shot_video_outputs,
    concat_filename_for,
    delivery_artifacts_match,
    resolve_delivery_package,
)
from block_director.delivery.prompts import render_prompt_sheet
from block_director.delivery.readme import render_readme
from block_director.delivery.report import DeliveryReport


def _shot_evidence(
    score: float,
    *,
    shot_id: str = "shot_001",
    delivery_eligible: bool | None = None,
    hard_gate_status: str = "pass",
    manifest: dict | None = None,
) -> ShotEvidence:
    reference = {"characters": {"甲": {"position": [0.0, 0.0, 0.0]}}}
    manifest = manifest or {
        "scene_id": "scene-1",
        "shot_table": [{"shot_id": shot_id}],
    }
    world_state = {
        "shot_states": {
            shot_id: {
                "characters": {"甲": {"position": [0.0, 0.0, 0.0]}},
            },
        },
    }
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
    observation_id = f"obs-{shot_id}-{score}"
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
    passed = score > 80.0
    hard_gate_passed = hard_gate_status == "pass"
    return ShotEvidence.create(
        run_id="run-1",
        scene_id="scene-1",
        shot_id=shot_id,
        version=0,
        parent_version=None,
        reason="initial",
        created_at="2026-10-21T00:00:00Z",
        plan={"scene": {"shots": [{"shot_id": shot_id}]}},
        shot_contract={
            "shot_id": shot_id,
            "characters": ["甲"],
        },
        reference=reference,
        manifest=manifest,
        world_state=world_state,
        shot_slice={"shot_id": shot_id, "camera": f"cam_{shot_id}"},
        build={
            "status": "observed",
            "manifest_fingerprint": basis["manifest_fingerprint"],
        },
        audit={
            "verdict": report["verdict"],
            "report_fingerprint": basis["report_fingerprint"],
        },
        measurements={
            "composition": {
                "status": "pass" if passed else "fail",
                "score": score,
                "threshold": 80.0,
            },
        },
        score_breakdown={
            "composition": score,
            "hard_error_count": 0,
        },
        gates={
            "observation_complete": True,
            "shot_passed": passed,
        },
        hard_gates={
            "status": hard_gate_status,
            "passed": hard_gate_passed,
            "failed": (
                [] if hard_gate_passed
                else [{"code": "E_HARD_GATE", "severity": "error"}]
            ),
            "evaluated": ["composition"],
        },
        sequence_gate={
            "status": "not_evaluated",
            "reason": "sequence review is run-level",
        },
        frames=[
            {
                "shot_id": shot_id,
                "frame": frame,
                "phase": phase,
                "path": f"/evidence/{shot_id}-{phase}.png",
                "file_sha256": "a" * 64,
                "pixel_sha256": "b" * 64,
                "readable": True,
            }
            for frame, phase in ((1, "first"), (12, "middle"), (24, "last"))
        ],
        absence_reasons={
            "semantic_review": "semantic review is disabled for this fixture",
            "rag": "no RAG call is needed by this fixture",
            "correction_candidates": "the passing fixture needs no corrections",
            "applied_operations": "no correction was applied",
            "remeasurement": "the initial observation has no prior candidate",
            "disposition": "the fixture records observation only",
        },
        basis_fingerprints=basis,
        delivery_eligible=(
            passed if delivery_eligible is None else delivery_eligible
        ),
    )


def _store(score: float) -> EvidenceStore:
    store = EvidenceStore(run_id="run-1", scene_id="scene-1")
    record = store.append(_shot_evidence(score))
    store.mark_best("shot_001", record.version)
    if record.is_passing():
        store.mark_adopted("shot_001", record.version)
    return store


def _multi_store(
    scores: dict[str, float],
    *,
    run_id: str = "run-1",
    scene_id: str = "scene-1",
) -> EvidenceStore:
    store = EvidenceStore(run_id=run_id, scene_id=scene_id)
    manifest = {
        "scene_id": scene_id,
        "shot_table": [{"shot_id": shot_id} for shot_id in scores],
    }
    for shot_id, score in scores.items():
        source = replace(
            _shot_evidence(
                score,
                shot_id=shot_id,
                manifest=manifest,
            ),
            run_id=run_id,
            scene_id=scene_id,
            digest="",
        )
        record = store.append(source)
        store.mark_best(shot_id, record.version)
        if record.is_passing():
            store.mark_adopted(shot_id, record.version)
    return store


def _sequence(verdict: str = "pass") -> dict:
    return {
        "schema_version": "blockout-sequence-review/v1",
        "manifest_fingerprint": "sequence-fingerprint",
        "shot_ids": ["shot_001"],
        "verdict": verdict,
        "checks": [],
        "findings": [],
    }


def test_strict_composition_boundary_controls_the_delivery_class():
    below = classify_delivery_quality(
        evidence_store=_store(79.99),
        shot_ids=["shot_001"],
        sequence_review=_sequence(),
    )
    boundary = classify_delivery_quality(
        evidence_store=_store(80.0),
        shot_ids=["shot_001"],
        sequence_review=_sequence(),
    )
    above = classify_delivery_quality(
        evidence_store=_store(80.01),
        shot_ids=["shot_001"],
        sequence_review=_sequence(),
    )

    assert below["delivery_class"] == "diagnostic"
    assert boundary["delivery_class"] == "diagnostic"
    assert above["delivery_class"] == "final"
    assert below["failed_shots"] == ["shot_001"]
    assert boundary["failed_shots"] == ["shot_001"]
    assert above["passed_shots"] == ["shot_001"]


def test_hard_gate_failure_is_never_passing_even_when_shot_gate_says_true():
    record = replace(
        _shot_evidence(
            82.0,
            delivery_eligible=True,
            hard_gate_status="fail",
        ),
        digest="",
    )

    assert record.gates["shot_passed"] is True
    assert record.hard_gates["status"] == "fail"
    assert record.is_passing() is False


def test_non_delivery_eligible_evidence_cannot_enter_final_or_partial():
    store = EvidenceStore(run_id="run-1", scene_id="scene-1")
    record = store.append(_shot_evidence(82.0, delivery_eligible=False))
    store.mark_best("shot_001", record.version)
    store.mark_adopted("shot_001", record.version)

    result = classify_delivery_quality(
        evidence_store=store,
        shot_ids=["shot_001"],
        sequence_review=_sequence(),
    )

    assert result["delivery_class"] == "diagnostic"
    assert result["passed_shots"] == []
    assert result["failed_shots"] == ["shot_001"]
    assert result["adoption_explanations"]["shot_001"] == (
        "shot_evidence_not_delivery_eligible")


def test_mixed_result_is_partial_only_after_the_exact_passed_subset_is_reviewed():
    result = classify_delivery_quality(
        evidence_store=_multi_store({
            "shot_001": 82.0,
            "shot_002": 80.0,
        }),
        shot_ids=["shot_001", "shot_002"],
        sequence_review={
            "verdict": "pass",
            "shot_ids": ["shot_001"],
        },
    )

    assert result["delivery_class"] == "partial"
    assert result["passed_shots"] == ["shot_001"]
    assert result["failed_shots"] == ["shot_002"]
    assert result["selected_shots"] == ["shot_001"]
    assert result["sequence_reviewed_shots"] == ["shot_001"]
    assert result["sequence_review_passed"] is True


def test_failed_subset_sequence_falls_back_to_explicit_diagnostic_delivery():
    result = classify_delivery_quality(
        evidence_store=_multi_store({
            "shot_001": 82.0,
            "shot_002": 80.0,
        }),
        shot_ids=["shot_001", "shot_002"],
        sequence_review={
            "verdict": "fail",
            "shot_ids": ["shot_001"],
        },
    )

    assert result["delivery_class"] == "diagnostic"
    assert result["selected_shots"] == ["shot_001", "shot_002"]
    assert result["sequence_review_passed"] is False
    assert "full_sequence_review_not_passed" in result["reasons"]


def test_all_failed_shots_produce_a_diagnostic_not_a_partial_package():
    result = classify_delivery_quality(
        evidence_store=_multi_store({
            "shot_001": 79.0,
            "shot_002": 72.0,
        }),
        shot_ids=["shot_001", "shot_002"],
        sequence_review={
            "verdict": "fail",
            "shot_ids": [],
        },
    )

    assert result["delivery_class"] == "diagnostic"
    assert result["passed_shots"] == []
    assert result["selected_shots"] == ["shot_001", "shot_002"]
    assert result["failed_shots"] == ["shot_001", "shot_002"]


def test_empty_run_cannot_claim_final_even_with_an_empty_sequence_pass():
    result = classify_delivery_quality(
        evidence_store=EvidenceStore(run_id="run-1", scene_id="scene-1"),
        shot_ids=[],
        sequence_review={
            "verdict": "pass",
            "shot_ids": [],
        },
    )

    assert result["delivery_class"] == "blocked"
    assert result["selected_shots"] == []
    assert "no_non_empty_shots" in result["reasons"]


def test_pending_re_review_prevents_final_identity():
    result = classify_delivery_quality(
        evidence_store=_multi_store({
            "shot_001": 82.0,
            "shot_002": 84.0,
        }),
        shot_ids=["shot_001", "shot_002"],
        sequence_review={
            "verdict": "pass",
            "shot_ids": ["shot_001", "shot_002"],
        },
        pending_review_shot_ids=["shot_002"],
    )

    assert result["delivery_class"] == "diagnostic"
    assert result["pending_review_shots"] == ["shot_002"]
    assert result["selected_shots"] == ["shot_001", "shot_002"]
    assert result["passed_shots"] == ["shot_001"]
    assert result["failed_shots"] == []


def test_inconsistent_delivered_artifact_set_is_blocked():
    result = classify_delivery_quality(
        evidence_store=_multi_store({
            "shot_001": 82.0,
            "shot_002": 84.0,
        }),
        shot_ids=["shot_001", "shot_002"],
        sequence_review={
            "verdict": "pass",
            "shot_ids": ["shot_001", "shot_002"],
        },
        delivered_shot_ids=["shot_001"],
    )

    assert result["delivery_class"] == "blocked"
    assert result["delivered_shots"] == ["shot_001"]
    assert "delivered_artifact_set_mismatch" in result["reasons"]


def test_incomplete_authoritative_evidence_blocks_instead_of_becoming_diagnostic():
    payload = _shot_evidence(82.0).to_dict(include_digest=False)
    payload["shot_slice"] = {}
    record = ShotEvidence.create(**payload)
    store = EvidenceStore(run_id="run-1", scene_id="scene-1")
    store.append(record)
    store.mark_best("shot_001", 0)
    store.mark_adopted("shot_001", 0)

    result = classify_delivery_quality(
        evidence_store=store,
        shot_ids=["shot_001"],
        sequence_review=_sequence(),
    )

    assert result["delivery_class"] == "blocked"
    assert any("shot_slice" in reason for reason in result["reasons"])


def test_missing_authoritative_evidence_store_blocks_every_delivery_identity():
    result = classify_delivery_quality(
        evidence_store=None,
        shot_ids=["shot_001"],
        sequence_review=_sequence(),
        delivered_shot_ids=["shot_001"],
    )

    assert result["delivery_class"] == "blocked"
    assert result["passed_shots"] == []
    assert result["failed_shots"] == []
    assert result["selected_shots"] == []
    assert result["delivered_shots"] == ["shot_001"]
    assert result["artifact_check_complete"] is True
    assert result["reasons"] == ["authoritative_evidence_store_unavailable"]


def test_best_score_above_threshold_without_adoption_is_explained_as_failure():
    store = EvidenceStore(run_id="run-1", scene_id="scene-1")
    record = store.append(_shot_evidence(84.0))
    store.mark_best("shot_001", record.version)

    result = classify_delivery_quality(
        evidence_store=store,
        shot_ids=["shot_001"],
        sequence_review=_sequence(),
    )

    assert result["delivery_class"] == "diagnostic"
    assert result["failed_shots"] == ["shot_001"]
    assert result["adoption_explanations"]["shot_001"] == (
        "best_score_above_threshold_but_version_not_adopted")


def test_user_edit_conflict_blocks_every_delivery_class():
    result = classify_delivery_quality(
        evidence_store=_store(82.0),
        shot_ids=["shot_001"],
        sequence_review=_sequence(),
        blocked_shots={"shot_001": "user_animation_conflict"},
    )

    assert result["delivery_class"] == "blocked"
    assert "shot_001:user_animation_conflict" in result["reasons"]


def test_pending_review_identity_must_belong_to_the_run():
    result = classify_delivery_quality(
        evidence_store=_store(82.0),
        shot_ids=["shot_001"],
        sequence_review=_sequence(),
        pending_review_shot_ids=["shot_999"],
    )

    assert result["delivery_class"] == "blocked"
    assert "pending_review_shot_not_in_run:shot_999" in result["reasons"]


def test_duplicate_shot_identity_blocks_delivery_instead_of_double_counting():
    result = classify_delivery_quality(
        evidence_store=_store(82.0),
        shot_ids=["shot_001", "shot_001"],
        sequence_review={
            "verdict": "pass",
            "shot_ids": ["shot_001", "shot_001"],
        },
    )

    assert result["delivery_class"] == "blocked"
    assert "duplicate_shot_ids" in result["reasons"]


def test_manifest_and_readme_use_the_partial_identity_from_the_same_result(
    tmp_path,
):
    quality = classify_delivery_quality(
        evidence_store=_multi_store({
            "shot_001": 82.0,
            "shot_002": 80.0,
        }),
        shot_ids=["shot_001", "shot_002"],
        sequence_review={
            "verdict": "pass",
            "shot_ids": ["shot_001"],
        },
    )
    plan = Plan.from_dict({"shots": [
        {
            "shot_id": "shot_001",
            "order": 1,
            "intent": "通过镜",
            "shot_type": "MS",
            "duration_frames": 24,
        },
        {
            "shot_id": "shot_002",
            "order": 2,
            "intent": "失败镜",
            "shot_type": "CU",
            "duration_frames": 24,
        },
    ]})

    manifest = build_manifest(plan, delivery_quality=quality)
    readme = render_readme(
        manifest,
        out_dir=tmp_path,
        delivery_quality=quality,
    )

    assert manifest["delivery"]["class"] == "partial"
    assert manifest["shots"][0]["delivery_status"] == "passed"
    assert manifest["shots"][1]["delivery_status"] == "failed"
    assert manifest["shots"][0]["delivery_included"] is True
    assert manifest["shots"][1]["delivery_included"] is False
    assert manifest["shots"][0]["video_file"] == "blockout_shot_001.mp4"
    assert manifest["shots"][1]["video_file"] is None
    assert manifest["shots"][1]["first_frame"] is None
    assert manifest["delivery"]["selected_frames"] == 24
    assert "镜头数：1，总时长 1.0 秒" in readme
    assert "镜头数：2，总时长 2.0 秒" not in readme
    assert "交付身份：**partial**" in readme
    assert "shot_002" in readme
    assert "已从 PARTIAL 成片中省略" in readme
    assert "本包只包含：shot_001" in readme
    assert "shot_002 没有参考视频、首帧、遮罩或深度序列" in readme


def test_stale_concat_cleanup_removes_only_canonical_files(tmp_path):
    canonical = [
        "blockout_full.mp4",
        "blockout_partial.mp4",
        "blockout_diagnostic.mp4",
        "final_video.mp4",
    ]
    for name in canonical:
        (tmp_path / name).write_bytes(b"stale")
    unrelated = tmp_path / "notes.txt"
    unrelated.write_text("keep", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    nested_copy = nested / "blockout_full.mp4"
    nested_copy.write_bytes(b"keep nested")

    removed = clear_stale_concat_outputs(tmp_path)

    assert removed == canonical
    assert all(not (tmp_path / name).exists() for name in canonical)
    assert unrelated.read_text(encoding="utf-8") == "keep"
    assert nested_copy.read_bytes() == b"keep nested"


def test_actual_shot_video_entry_requires_the_file_on_disk(tmp_path):
    missing = tmp_path / "blockout_shot_001.mp4"

    assert actual_shot_video("shot_001", missing, 24) is None

    missing.write_bytes(b"video")
    assert actual_shot_video("shot_001", missing, 24) == {
        "shot_id": "shot_001",
        "video": str(missing),
        "frames": 24,
    }


def test_stale_shot_video_cleanup_is_scoped_to_generated_top_level_clips(
    tmp_path,
):
    stale = [
        tmp_path / "blockout_shot_001.mp4",
        tmp_path / "blockout_shot_002.mp4",
    ]
    for path in stale:
        path.write_bytes(b"stale")
    unrelated = tmp_path / "notes.txt"
    unrelated.write_text("keep", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    nested_copy = nested / "blockout_shot_003.mp4"
    nested_copy.write_bytes(b"keep nested")

    removed = clear_stale_shot_video_outputs(tmp_path)

    assert removed == [path.name for path in stale]
    assert all(not path.exists() for path in stale)
    assert unrelated.read_text(encoding="utf-8") == "keep"
    assert nested_copy.read_bytes() == b"keep nested"


def test_stale_shot_cleanup_removes_only_plan_shot_products(tmp_path):
    export_dir = tmp_path / "export"
    first_frames = export_dir / "first_frames"
    depth = export_dir / "depth_shot_shot_002"
    masks = export_dir / "masks" / "shot_002"
    for folder in (first_frames, depth, masks):
        folder.mkdir(parents=True)
    stale_paths = [
        export_dir / "blockout_shot_001.mp4",
        first_frames / "shot_001.png",
    ]
    for path in stale_paths:
        path.write_bytes(b"stale")
    (depth / "frame_0001.png").write_bytes(b"stale")
    (masks / "frame_0001.png").write_bytes(b"stale")
    unrelated = export_dir / "blockout_shot_003.mp4"
    unrelated.write_bytes(b"keep")

    removed = clear_stale_shot_outputs(
        export_dir, ["shot_001", "shot_002"])

    assert not any(path.exists() for path in stale_paths)
    assert not depth.exists()
    assert not masks.exists()
    assert unrelated.read_bytes() == b"keep"
    assert {
        "blockout_shot_001.mp4",
        "first_frames/shot_001.png",
        "depth_shot_shot_002",
        "masks/shot_002",
    }.issubset(set(removed))


def test_readme_names_only_the_concat_identity_for_its_delivery_class(
    tmp_path,
):
    plan = Plan.from_dict({"shots": [{
        "shot_id": "shot_001",
        "order": 1,
        "intent": "交付身份测试",
        "shot_type": "MS",
        "duration_frames": 24,
    }]})
    cases = {
        "final": (
            "blockout_full.mp4",
            "各镜按顺序接成的全片",
        ),
        "partial": (
            "blockout_partial.mp4",
            "只包含通过镜头",
        ),
        "diagnostic": (
            "blockout_diagnostic.mp4",
            "诊断",
        ),
    }

    for delivery_class, (filename, description) in cases.items():
        folder = tmp_path / delivery_class
        folder.mkdir()
        quality = {
            "schema_version": "quality-contract/v1",
            "delivery_class": delivery_class,
            "selected_shots": ["shot_001"],
            "passed_shots": ["shot_001"],
            "failed_shots": [],
            "pending_review_shots": [],
        }
        manifest = build_manifest(
            plan,
            generated_at="2026-10-21T00:00:00+08:00",
            delivery_quality=quality,
        )
        (folder / filename).write_bytes(b"video")

        readme = render_readme(
            manifest,
            out_dir=folder,
            delivery_quality=quality,
        )

        assert f"`{filename}`" in readme
        assert description in readme


def test_blocked_readme_does_not_advertise_a_stale_concat_video(tmp_path):
    plan = Plan.from_dict({"shots": [{
        "shot_id": "shot_001",
        "order": 1,
        "intent": "阻塞交付测试",
        "shot_type": "MS",
        "duration_frames": 24,
    }]})
    quality = {
        "schema_version": "quality-contract/v1",
        "delivery_class": "blocked",
        "selected_shots": [],
        "passed_shots": [],
        "failed_shots": [],
        "pending_review_shots": [],
    }
    manifest = build_manifest(
        plan,
        generated_at="2026-10-21T00:00:00+08:00",
        delivery_quality=quality,
    )
    (tmp_path / "blockout_full.mp4").write_bytes(b"stale")

    readme = render_readme(
        manifest,
        out_dir=tmp_path,
        delivery_quality=quality,
    )

    assert "blockout_full.mp4" not in readme
    assert "blockout_partial.mp4" not in readme
    assert "blockout_diagnostic.mp4" not in readme


def test_prompt_sheet_marks_omitted_partial_shots_as_not_delivered():
    quality = classify_delivery_quality(
        evidence_store=_multi_store({
            "shot_001": 82.0,
            "shot_002": 80.0,
        }),
        shot_ids=["shot_001", "shot_002"],
        sequence_review={
            "verdict": "pass",
            "shot_ids": ["shot_001"],
        },
    )
    plan = Plan.from_dict({"shots": [
        {
            "shot_id": "shot_001",
            "order": 1,
            "intent": "通过镜",
            "shot_type": "MS",
            "duration_frames": 24,
        },
        {
            "shot_id": "shot_002",
            "order": 2,
            "intent": "失败镜",
            "shot_type": "CU",
            "duration_frames": 24,
        },
    ]})

    prompt = render_prompt_sheet(
        plan,
        delivery_quality=quality,
        failures=[{"shot_id": "shot_002", "best_score": 80.0,
                   "no_gain_rounds": 3, "reason": "not passing"}],
    )
    failed_section = prompt.split("## shot_002", 1)[1].split("## ", 1)[0]

    assert "- 交付身份：**partial**" in prompt
    assert "未包含在本次 PARTIAL 交付包" in failed_section
    assert "**参考视频**：export/blockout_shot_002.mp4" not in failed_section


def test_delivery_report_keeps_package_completeness_separate_from_finality():
    quality = {
        "schema_version": "quality-contract/v1",
        "delivery_class": "partial",
        "selected_shots": ["shot_001"],
        "passed_shots": ["shot_001"],
        "failed_shots": ["shot_002"],
        "delivered_shots": ["shot_001"],
        "artifact_check_complete": True,
    }
    report = DeliveryReport(
        out_dir="export",
        files=["export/shots.json", "export/blockout_partial.mp4"],
        delivery_class="partial",
        delivery_quality=quality,
    )

    payload = report.to_dict()

    assert report.ok is True
    assert payload["delivery_class"] == "partial"
    assert payload["delivery_quality"] == quality
    assert payload["selected_shots"] == ["shot_001"]
    assert payload["final"] is False


def test_nonblocked_delivery_report_requires_exact_artifact_evidence():
    quality = {
        "schema_version": "quality-contract/v1",
        "delivery_class": "partial",
        "selected_shots": ["shot_001"],
        "passed_shots": ["shot_001"],
        "failed_shots": ["shot_002"],
        "delivered_shots": [],
        "artifact_check_complete": True,
    }
    report = DeliveryReport(
        out_dir="export",
        files=["export/shots.json", "export/blockout_partial.mp4"],
        delivery_class="partial",
        delivery_quality=quality,
    )

    assert report.ok is False
    assert report.to_dict()["final"] is False


def test_delivery_report_cannot_self_assert_final_without_canonical_quality():
    report = DeliveryReport(
        out_dir="export",
        files=["export/blockout_full.mp4"],
        delivery_class="final",
    )

    payload = report.to_dict()

    assert report.canonical_delivery_class == ""
    assert payload["delivery_class"] == ""
    assert payload["final"] is False


def test_legacy_delivery_report_keeps_package_ok_without_final_identity():
    report = DeliveryReport(
        out_dir="export",
        files=["export/shots.json", "export/blockout_full.mp4"],
    )

    payload = report.to_dict()

    assert report.ok is True
    assert report.canonical_delivery_class == ""
    assert payload["delivery_class"] == ""
    assert payload["delivery_quality"] == {}
    assert payload["final"] is False


def test_driver_snapshot_never_invents_final_without_sequence_review():
    from test_backtrack_no_stop_on_fail import _run_backtrack

    driver, _ = _run_backtrack()
    driver.evidence_store = _multi_store(
        {
            "shot_001": 82.0,
            "shot_002": 84.0,
        },
        run_id=str(driver.audit.run_id),
    )

    quality = driver.snapshot()["delivery_quality"]

    assert quality["delivery_class"] == "diagnostic"
    assert quality["sequence_review_passed"] is False
    assert quality["full_sequence_review_passed"] is False


def test_driver_snapshot_consumes_the_attached_canonical_quality_engine():
    from dataclasses import replace

    from test_backtrack_no_stop_on_fail import _run_backtrack
    from block_director.contracts.quality_engine import QualityEngine

    driver, _ = _run_backtrack()
    run_id = str(driver.audit.run_id)
    scene_id = "scene-driver-quality"
    shot_ids = [str(shot.shot_id) for shot in driver.plan.shots]
    store = EvidenceStore(run_id=run_id, scene_id=scene_id)
    manifest = {
        "scene_id": scene_id,
        "shot_table": [{"shot_id": shot_id} for shot_id in shot_ids],
    }
    for shot_id in shot_ids:
        record = replace(
            _shot_evidence(
                82.0,
                shot_id=shot_id,
                manifest=manifest,
            ),
            run_id=run_id,
            scene_id=scene_id,
            digest="",
        )
        store.append(record)
        store.mark_best(shot_id, record.version)
        store.mark_adopted(shot_id, record.version)
    engine = QualityEngine.start(
        run_id=run_id,
        scene_id=scene_id,
        plan=driver.plan,
        evidence_store=store,
    )
    engine.record_sequence_review(engine.bind_sequence_review({
        "schema_version": "blockout-sequence-review/v1",
        "shot_ids": shot_ids,
        "verdict": "pass",
        "checks": [],
        "findings": [],
    }))
    state = engine.to_dict()

    driver.attach_quality_engine_state(state)
    snapshot = driver.snapshot()

    assert snapshot["quality_engine_state"] == state
    assert snapshot["quality_result"]["delivery_class"] == "final"
    assert snapshot["delivery_quality"] == (
        snapshot["quality_result"]["delivery"])


def test_blocked_delivery_report_can_never_reuse_package_ok():
    quality = {
        "schema_version": "quality-contract/v1",
        "delivery_class": "blocked",
        "reasons": ["authoritative_evidence_store_unavailable"],
        "selected_shots": [],
    }
    report = DeliveryReport(
        out_dir="export",
        aborted=True,
        reason="quality blocked",
        files=["export/shots.json"],
        delivery_class="blocked",
        delivery_quality=quality,
    )

    assert report.ok is False
    assert report.to_dict()["delivery_class"] == "blocked"


def test_delivery_package_scope_keeps_partial_to_the_exact_passed_subset():
    quality = {
        "schema_version": "quality-contract/v1",
        "delivery_class": "partial",
        "selected_shots": ["shot_001"],
        "passed_shots": ["shot_001"],
        "failed_shots": ["shot_002"],
        "pending_review_shots": [],
        "sequence_reviewed_shots": ["shot_001"],
        "sequence_review_passed": True,
    }

    package = resolve_delivery_package(
        quality, ["shot_001", "shot_002"])

    assert package.delivery_class == "partial"
    assert package.selected_shots == ("shot_001",)
    assert package.failed_shots == ("shot_002",)
    assert package.concat_filename == "blockout_partial.mp4"
    assert delivery_artifacts_match(package, ["shot_001"]) is True
    assert delivery_artifacts_match(
        package, ["shot_001", "shot_002"]) is False


def test_delivery_classes_share_one_canonical_concat_filename_mapping():
    assert concat_filename_for("final") == "blockout_full.mp4"
    assert concat_filename_for("partial") == "blockout_partial.mp4"
    assert concat_filename_for("diagnostic") == "blockout_diagnostic.mp4"
    assert concat_filename_for("blocked") == ""


def test_partial_delivery_package_preserves_informational_producer_reasons():
    quality = {
        "schema_version": "quality-contract/v1",
        "delivery_class": "partial",
        "reasons": ["failed_shots_omitted_from_partial_delivery"],
        "selected_shots": ["shot_001"],
        "passed_shots": ["shot_001"],
        "failed_shots": ["shot_002"],
        "pending_review_shots": [],
        "sequence_reviewed_shots": ["shot_001"],
        "sequence_review_passed": True,
        "delivered_shots": ["shot_001"],
        "artifact_check_complete": True,
    }

    package = resolve_delivery_package(
        quality, ["shot_001", "shot_002"])

    assert package.delivery_class == "partial"
    assert package.reasons == (
        "failed_shots_omitted_from_partial_delivery",
    )
    assert delivery_artifacts_match(package, ["shot_001"]) is True


def test_delivery_package_names_diagnostic_and_blocks_invalid_scope():
    diagnostic = resolve_delivery_package(
        {
            "schema_version": "quality-contract/v1",
            "delivery_class": "diagnostic",
            "selected_shots": ["shot_001", "shot_002"],
            "passed_shots": ["shot_001"],
            "failed_shots": ["shot_002"],
            "pending_review_shots": [],
        },
        ["shot_001", "shot_002"],
    )
    blocked = resolve_delivery_package(
        {
            "schema_version": "quality-contract/v1",
            "delivery_class": "partial",
            "selected_shots": ["shot_002"],
            "passed_shots": ["shot_001"],
            "failed_shots": ["shot_002"],
            "pending_review_shots": [],
            "sequence_reviewed_shots": ["shot_001"],
            "sequence_review_passed": True,
        },
        ["shot_001", "shot_002"],
    )

    assert diagnostic.concat_filename == "blockout_diagnostic.mp4"
    assert blocked.delivery_class == "blocked"
    assert blocked.concat_filename == ""
    assert "selected_shots_not_exactly_passed" in blocked.reasons


def test_delivery_package_rejects_self_reported_artifact_mismatch():
    package = resolve_delivery_package(
        {
            "schema_version": "quality-contract/v1",
            "delivery_class": "partial",
            "selected_shots": ["shot_001"],
            "passed_shots": ["shot_001"],
            "failed_shots": ["shot_002"],
            "pending_review_shots": [],
            "sequence_reviewed_shots": ["shot_001"],
            "sequence_review_passed": True,
            "delivered_shots": ["shot_002"],
            "artifact_check_complete": True,
        },
        ["shot_001", "shot_002"],
    )

    assert package.delivery_class == "blocked"
    assert "delivered_artifacts_do_not_match_selection" in package.reasons


def test_every_plan_shot_needs_exactly_one_delivery_disposition():
    package = resolve_delivery_package(
        {
            "schema_version": "quality-contract/v1",
            "delivery_class": "partial",
            "selected_shots": ["shot_001"],
            "passed_shots": ["shot_001"],
            "failed_shots": ["shot_002"],
            "pending_review_shots": [],
            "sequence_reviewed_shots": ["shot_001"],
            "sequence_review_passed": True,
        },
        ["shot_001", "shot_002", "shot_003"],
    )

    assert package.delivery_class == "blocked"
    assert "plan_shot_missing_disposition:shot_003" in package.reasons


def test_partial_sequence_review_must_cover_exactly_its_selected_shots():
    package = resolve_delivery_package(
        {
            "schema_version": "quality-contract/v1",
            "delivery_class": "partial",
            "selected_shots": ["shot_001"],
            "passed_shots": ["shot_001"],
            "failed_shots": ["shot_002"],
            "pending_review_shots": [],
            "sequence_reviewed_shots": ["shot_001", "shot_002"],
            "sequence_review_passed": True,
        },
        ["shot_001", "shot_002"],
    )

    assert package.delivery_class == "blocked"
    assert "partial_sequence_review_scope_mismatch" in package.reasons


def test_failures_payload_is_exactly_derived_from_the_delivery_identity():
    quality = {
        "schema_version": "quality-contract/v1",
        "delivery_class": "diagnostic",
        "selected_shots": ["shot_001", "shot_002"],
        "passed_shots": ["shot_001"],
        "failed_shots": ["shot_002"],
        "pending_review_shots": ["shot_003"],
        "adoption_explanations": {
            "shot_002": "required_hard_gate_not_passed",
        },
    }
    aligned = align_failures_payload(
        {
            "schema_version": "delivery-failures/v1",
            "failures": [
                {"shot_id": "shot_002", "best_score": 79.0,
                 "no_gain_rounds": 3, "reason": "composition did not pass"},
                {"shot_id": "shot_999", "best_score": 1.0,
                 "no_gain_rounds": 1, "reason": "stale"},
            ],
            "pending_review": [
                {"shot_id": "shot_003", "status": "finished",
                 "best_score": 70.0, "reason": "needs review"},
            ],
        },
        quality,
    )

    assert aligned["delivery_class"] == "diagnostic"
    assert aligned["selected_shots"] == ["shot_001", "shot_002"]
    assert [item["shot_id"] for item in aligned["failures"]] == ["shot_002"]
    assert aligned["failures"][0]["best_score"] == 79.0
    assert [item["shot_id"] for item in aligned["pending_review"]] == [
        "shot_003"]
