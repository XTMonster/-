"""Versioned coarse-observation bundles with frame-level evidence."""

from __future__ import annotations

import json

from PIL import Image

from block_director.contracts.observation import (
    ObservationBundle,
    build_observation_bundle,
)
from block_director.contracts.blockout import manifest_fingerprint


def _write_png(path, rgba):
    image = Image.new("RGBA", (4, 3))
    image.putdata([rgba] * 12)
    image.save(path)


def _fixture(tmp_path):
    evidence_dir = tmp_path / "coarse" / "observations" / "attempt-001"
    preview = evidence_dir / "preview"
    preview.mkdir(parents=True)
    frames = []
    for shot_id, frame, phase, rgba in (
        ("shot_001", 1, "first", (255, 0, 0, 255)),
        ("shot_001", 12, "middle", (0, 255, 0, 255)),
        ("shot_001", 24, "last", (0, 0, 255, 255)),
    ):
        path = preview / f"{shot_id}_f{frame:04d}.png"
        _write_png(path, rgba)
        frames.append({
            "shot_id": shot_id,
            "frame": frame,
            "phase": phase,
            "png": str(path),
            "bytes": path.stat().st_size,
            "uniform": True,
        })
    reference = {
        "schema_version": "coarse-world-reference/v1",
        "scene_id": "scene",
        "characters": [{"name": "甲", "position": {"x": 0, "y": 0, "z": 0}}],
        "camera_intents": [],
        "shots": [{"shot_id": "shot_001", "characters": ["甲"]}],
    }
    manifest = {
        "schema_version": "blockout-manifest/v1",
        "scene_id": "scene",
        "primitives": [],
        "cameras": [],
        "shot_table": [{"shot_id": "shot_001"}],
    }
    report = {
        "schema_version": "blockout-report/v1",
        "manifest_fingerprint": manifest_fingerprint(manifest),
        "verdict": "fail",
        "findings": [],
        "checks": [{
            "check_id": "composition",
            "shot_id": "shot_001",
            "actual": 79.0,
            "threshold": 80.0,
            "verdict": "fail",
        }],
        "visual_states": [
            {
                "shot_id": item["shot_id"],
                "frame": item["frame"],
                "phase": item["phase"],
                "png": item["png"],
                "reviewed": False,
            }
            for item in frames
        ],
    }
    world_state = {
        "schema_version": "runtime-world/v1",
        "characters": {"甲": {"position": [0, 0, 0], "facing": [0, 1, 0]}},
        "cameras": {},
        "props": {},
    }
    return evidence_dir, report, reference, manifest, world_state


def test_observation_bundle_binds_report_manifest_reference_and_frames(tmp_path):
    evidence_dir, report, reference, manifest, world_state = _fixture(tmp_path)

    bundle = build_observation_bundle(
        reference=reference,
        manifest=manifest,
        report=report,
        world_state=world_state,
        evidence_dir=evidence_dir,
    )

    assert bundle.complete is True
    assert bundle.observation_id.startswith("obs-")
    assert bundle.reference_fingerprint
    assert bundle.manifest_fingerprint == manifest_fingerprint(manifest)
    assert bundle.report_fingerprint
    assert len(bundle.frames) == 3
    assert {item.shot_id for item in bundle.frames} == {"shot_001"}
    assert [item.frame for item in bundle.frames] == [1, 12, 24]
    assert all(item.readable for item in bundle.frames)
    assert all(len(item.file_sha256) == 64 for item in bundle.frames)
    assert all(len(item.pixel_sha256) == 64 for item in bundle.frames)
    assert bundle.verify() is True


def test_three_arbitrary_frames_cannot_impersonate_first_middle_last(tmp_path):
    evidence_dir, report, reference, manifest, world_state = _fixture(tmp_path)
    for index, frame in enumerate((2, 3, 4)):
        path = evidence_dir / "preview" / f"shot_001_f{frame:04d}.png"
        _write_png(path, (index + 1, index + 2, index + 3, 255))
        report["visual_states"][index].update({
            "frame": frame,
            "phase": "",
            "png": str(path),
        })

    bundle = build_observation_bundle(
        reference=reference,
        manifest=manifest,
        report=report,
        world_state=world_state,
        evidence_dir=evidence_dir,
    )

    assert bundle.complete is False
    assert any("first/middle/last" in item for item in bundle.errors), bundle.errors


def test_report_with_forged_manifest_fingerprint_is_blocked(tmp_path):
    evidence_dir, report, reference, manifest, world_state = _fixture(tmp_path)
    report["manifest_fingerprint"] = "manifest-fp"

    bundle = build_observation_bundle(
        reference=reference,
        manifest=manifest,
        report=report,
        world_state=world_state,
        evidence_dir=evidence_dir,
    )

    assert bundle.complete is False
    assert any("manifest_fingerprint" in item for item in bundle.errors)


def test_observation_bundle_round_trips_atomically(tmp_path):
    evidence_dir, report, reference, manifest, world_state = _fixture(tmp_path)
    bundle = build_observation_bundle(
        reference=reference,
        manifest=manifest,
        report=report,
        world_state=world_state,
        evidence_dir=evidence_dir,
    )
    path = evidence_dir / "observation.json"

    bundle.write_atomic(path)
    loaded = ObservationBundle.load(path)

    assert loaded.to_dict() == bundle.to_dict()
    assert loaded.verify() is True


def test_observation_bundle_blocks_missing_or_mixed_frames(tmp_path):
    evidence_dir, report, reference, manifest, world_state = _fixture(tmp_path)
    first = report["visual_states"][0]["png"]
    bundle = build_observation_bundle(
        reference=reference,
        manifest=manifest,
        report=report,
        world_state=world_state,
        evidence_dir=evidence_dir,
    )

    from pathlib import Path

    Path(first).unlink()
    assert bundle.complete is False
    assert bundle.verify() is False
    assert any("missing" in item or "unreadable" in item
               for item in bundle.errors)

    _write_png(Path(first), (12, 34, 56, 255))
    assert bundle.verify() is False
    assert any("digest" in item for item in bundle.verify_errors())


def test_bad_report_shape_never_becomes_a_complete_observation(tmp_path):
    evidence_dir, report, reference, manifest, world_state = _fixture(tmp_path)
    report["visual_states"] = "not-a-list"

    bundle = build_observation_bundle(
        reference=reference,
        manifest=manifest,
        report=report,
        world_state=world_state,
        evidence_dir=evidence_dir,
    )

    assert bundle.complete is False
    assert bundle.errors


def test_serialized_observation_has_no_non_finite_values(tmp_path):
    evidence_dir, report, reference, manifest, world_state = _fixture(tmp_path)
    report["checks"][0]["actual"] = float("nan")
    bundle = build_observation_bundle(
        reference=reference,
        manifest=manifest,
        report=report,
        world_state=world_state,
        evidence_dir=evidence_dir,
    )

    assert bundle.complete is False
    assert any("finite" in item or "serial" in item for item in bundle.errors)
    json.dumps(bundle.to_dict(), allow_nan=False)
