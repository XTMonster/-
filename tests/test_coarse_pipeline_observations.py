"""Coarse pipeline must publish one physically bound observation version."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from block_director.contracts.blockout import manifest_fingerprint
from block_director.contracts.audit import canonical_fingerprint
from block_director.contracts.evidence import EvidenceStore
from block_director.layer5_orchestrator.coarse_pipeline import (
    CoarsePipelineAdapters,
    run_coarse_pipeline,
)
from block_director.layer5_orchestrator.coarse_agent import (
    OfflineFixtureCoarseProposalProvider,
)


def _plan():
    return {
        "scene_heading": "测试场",
        "shots": [{
            "shot_id": "shot_001",
            "order": 1,
            "intent": "甲站在镜头中央",
            "shot_type": "MS",
            "duration_frames": 24,
            "characters": ["甲"],
            "actions": [],
        }],
    }


def _reference():
    return {
        "schema_version": "coarse-world-reference/v1",
        "scene_id": "scene",
        "characters": [{
            "name": "甲",
            "position": {"x": 0.0, "y": 0.0, "z": 0.0},
            "facing": [0.0, 1.0, 0.0],
        }],
        "props": [],
        "anchors": [],
        "camera_intents": [{
            "shot_id": "shot_001",
            "position": [0.0, 3.0, 1.5],
            "target": [0.0, 0.0, 1.0],
            "lens": 35.0,
            "movement": None,
        }],
        "shots": [dict(_plan()["shots"][0])],
        "revisions": [],
        "notes": [],
    }


def _write_frame(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (8, 6), (40, 80, 120, 255)).save(path)


def test_pipeline_applies_declared_retime_before_coarse_build(tmp_path):
    """Coarse must not build a drifted 48-frame shot declared as 1 second.

    Real node123 attempt-002 declared 1056 frames but built 1571 frames.
    ``run_coarse_pipeline`` received the post-editor plan directly and only the
    later driver BUILDING seam ran the spatial ruler.  The coarse observations
    therefore sampled the wrong timeline and could never be repaired by the
    camera/character-only proposal schema.
    """
    plan = _plan()
    plan["shots"][0]["duration_frames"] = 48
    plan["shots"][0]["declared_duration_frames"] = 24
    reference = _reference()
    reference["shots"][0]["duration_frames"] = 48
    seen = []

    def build_manifest(*, design, plan):
        seen.append({
            "plan_frames": plan.shots[0].duration_frames,
            "reference_frames": design["shots"][0]["duration_frames"],
        })
        return {
            "schema_version": "blockout-manifest/v1",
            "scene_id": "scene",
            "primitives": [{
                "id": "char_jia",
                "kind": "character",
                "source": {"type": "character", "id": "甲"},
            }],
            "cameras": [{
                "camera_id": "cam_shot_001",
                "shot_id": "shot_001",
                "position": [0.0, 3.0, 1.5],
                "target": [0.0, 0.0, 1.0],
                "lens": 35.0,
                "start_frame": 1,
                "end_frame": 24,
            }],
            "shot_table": [{
                "shot_id": "shot_001",
                "order": 1,
                "character_ids": ["甲"],
                "prop_ids": [],
                "shot_type": "MS",
            }],
            "reference_revision_count": len(design.get("revisions") or []),
        }

    def render_preview(manifest, out_dir, expected=None, reference_json=None):
        del expected, reference_json
        previews = []
        for phase, frame in (
            ("first", 1),
            ("middle", 12),
            ("last", 24),
        ):
            path = Path(out_dir) / "preview" / f"shot_001_f{frame:04d}.png"
            _write_frame(path)
            previews.append({
                "shot_id": "shot_001",
                "frame": frame,
                "phase": phase,
                "png": str(path),
                "bytes": path.stat().st_size,
                "uniform": False,
            })
        report = {
            "schema_version": "blockout-report/v1",
            "manifest_fingerprint": manifest_fingerprint(manifest),
            "verdict": "pass",
            "findings": [],
            "checks": [{
                "check_id": "composition",
                "shot_id": "shot_001",
                "actual": 82.0,
                "threshold": 80.0,
                "verdict": "pass",
            }],
            "visual_states": [],
        }
        return {
            "report": report,
            "previews": previews,
            "evidence_dir": str(out_dir),
            "settings": {},
        }

    adapters = CoarsePipelineAdapters(
        build_manifest=build_manifest,
        build_scene=lambda manifest: None,
        render_preview=render_preview,
        collect_world_state=lambda manifest: {
            "schema_version": "runtime-world/v1",
            "characters": {
                "甲": {
                    "position": [0.0, 0.0, 0.0],
                    "facing": [0.0, 1.0, 0.0],
                },
            },
            "cameras": {
                "shot_001": {
                    "position": [0.0, 3.0, 1.5],
                    "target": [0.0, 0.0, 1.0],
                    "lens_mm": 35.0,
                    "manifest_revision_count": manifest.get(
                        "reference_revision_count"),
                },
            },
            "props": {},
            "anchors": {},
        },
    )
    out = tmp_path / "run"

    result = run_coarse_pipeline(
        plan=plan,
        reference=reference,
        scene_id="scene",
        out_dir=out,
        max_revisions=2,
        adapters=adapters,
    )

    assert result["coarse_status"] == "approved"
    assert seen == [{"plan_frames": 24, "reference_frames": 24}]
    assert result["plan_prescriptions"][0]["operation"] == "retime_shot"
    assert result["plan_prescriptions"][0]["applied"] is True
    assert any(
        item["metric"] == "shot_duration_planned"
        and item["value"] == 1.0
        for item in result["plan_measurements"]
    )
    plan_after = json.loads(
        (out / "plan_after.json").read_text(encoding="utf-8"))
    assert plan_after["shots"][0]["duration_frames"] == 24
    assert plan_after["shots"][0]["declared_duration_frames"] == 24
    assert result["artifacts"]["plan_after"] == str(out / "plan_after.json")


def test_pipeline_keeps_attempt_evidence_and_publishes_only_best(tmp_path):
    observations = []

    def build_manifest(*, design, plan):
        del plan
        reference = design
        return {
            "schema_version": "blockout-manifest/v1",
            "scene_id": "scene",
            "primitives": [{
                "id": "char_jia",
                "kind": "character",
                "source": {"type": "character", "id": "甲"},
            }],
            "cameras": [{
                "camera_id": "cam_shot_001",
                "shot_id": "shot_001",
                "position": [0.0, 3.0, 1.5],
                "target": [0.0, 0.0, 1.0],
                "lens": 35.0,
                "start_frame": 1,
                "end_frame": 24,
            }],
            "shot_table": [{
                "shot_id": "shot_001",
                "order": 1,
                "character_ids": ["甲"],
                "prop_ids": [],
                "shot_type": "MS",
            }],
            "reference_revision_count": len(reference.get("revisions") or []),
        }

    def render_preview(manifest, out_dir, expected=None, reference_json=None):
        del expected, reference_json
        attempt = len(observations) + 1
        score = 70.0 if attempt == 1 else 82.0
        preview_dir = Path(out_dir) / "preview"
        previews = []
        for phase, frame in (
            ("first", 1),
            ("middle", 12),
            ("last", 24),
        ):
            path = preview_dir / f"shot_001_f{frame:04d}.png"
            _write_frame(path)
            previews.append({
                "shot_id": "shot_001",
                "frame": frame,
                "phase": phase,
                "png": str(path),
                "bytes": path.stat().st_size,
                "uniform": False,
            })
        report = {
            "schema_version": "blockout-report/v1",
            "manifest_fingerprint": manifest_fingerprint(manifest),
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
        observations.append({"manifest": manifest, "report": report})
        return {
            "report": report,
            "previews": previews,
            "evidence_dir": str(out_dir),
            "settings": {},
        }

    def collect_world_state(manifest):
        return {
            "schema_version": "runtime-world/v1",
            "characters": {
                "甲": {
                    "position": [0.0, 0.0, 0.0],
                    "facing": [0.0, 1.0, 0.0],
                },
            },
            "cameras": {
                "shot_001": {
                    "position": [0.0, 3.0, 1.5],
                    "target": [0.0, 0.0, 1.0],
                    "lens_mm": 35.0,
                    "manifest_revision_count": manifest.get(
                        "reference_revision_count"),
                },
            },
            "props": {},
            "anchors": {},
        }

    adapters = CoarsePipelineAdapters(
        build_manifest=build_manifest,
        build_scene=lambda manifest: None,
        render_preview=render_preview,
        collect_world_state=collect_world_state,
    )
    out = tmp_path / "run"
    (out / "preview").mkdir(parents=True)
    (out / "preview" / "stale_from_previous_run.png").write_bytes(b"stale")

    result = run_coarse_pipeline(
        plan=_plan(),
        reference=_reference(),
        scene_id="scene",
        out_dir=out,
        max_revisions=3,
        adapters=adapters,
        proposal_provider=OfflineFixtureCoarseProposalProvider(),
    )

    assert result["coarse_status"] == "approved"
    attempts = sorted((out / "coarse" / "observations").glob("attempt-*"))
    assert [path.name for path in attempts] == ["attempt-001", "attempt-002"]
    loaded = []
    for attempt in attempts:
        payload = json.loads(
            (attempt / "observation.json").read_text(encoding="utf-8"))
        assert payload["complete"] is True
        assert len(payload["frames"]) == 3
        loaded.append(payload)

    final_report = json.loads(
        (out / "blockout_report.json").read_text(encoding="utf-8"))
    final_manifest = json.loads(
        (out / "blockout_manifest.json").read_text(encoding="utf-8"))
    final_world = json.loads(
        (out / "blockout_world_state.json").read_text(encoding="utf-8"))

    assert final_report["checks"][0]["actual"] == 82.0
    assert final_report["manifest_fingerprint"] == manifest_fingerprint(
        final_manifest)
    assert final_world["cameras"]["shot_001"]["manifest_revision_count"] >= 1
    assert result["best_observation_id"] == loaded[-1]["observation_id"]
    assert result["artifacts"]["best_observation"] == str(
        attempts[-1] / "observation.json")
    candidate_round = result["rounds"][0]
    assert candidate_round["candidate"]["observation_id"] == (
        loaded[-1]["observation_id"])
    assert candidate_round["candidate"]["report"]["checks"][0][
        "actual"] == 82.0
    assert candidate_round["candidate"]["rebuild_summary"][
        "camera_count"] == 1
    assert candidate_round["comparison"]["disposition"] == "new_high"
    assert candidate_round["rollback"]["applied"] is False
    store = EvidenceStore.load(out / "coarse" / "evidence_store.json")
    history = store.history("shot_001")
    assert [item.version for item in history] == [0, 1]
    assert store.best_version("shot_001") == 1
    assert store.adopted_version("shot_001") == 1
    assert history[0].measurements["composition"]["score"] == 70.0
    assert history[1].measurements["composition"]["score"] == 82.0
    assert history[1].gates["coarse_passed"] is True
    assert history[1].delivery_eligible is False
    assert len(history[1].frames) == 3
    assert result["artifacts"]["evidence_store"] == str(
        out / "coarse" / "evidence_store.json")
    assert not (out / "preview" / "stale_from_previous_run.png").exists()
    assert sorted(path.name for path in (out / "preview").glob("*.png")) == [
        "shot_001_f0001.png",
        "shot_001_f0012.png",
        "shot_001_f0024.png",
    ]


def test_blocked_pipeline_keeps_diagnostic_best_without_adopting_or_freezing(
    tmp_path,
):
    attempts = []

    def build_manifest(*, design, plan):
        del plan
        return {
            "schema_version": "blockout-manifest/v1",
            "scene_id": "scene",
            "primitives": [],
            "cameras": [{
                "camera_id": "cam_shot_001",
                "shot_id": "shot_001",
                "position": [0.0, 3.0, 1.5],
                "target": [0.0, 0.0, 1.0],
                "lens": 35.0,
                "start_frame": 1,
                "end_frame": 24,
            }],
            "shot_table": [{
                "shot_id": "shot_001",
                "order": 1,
                "character_ids": ["甲"],
                "prop_ids": [],
                "shot_type": "MS",
            }],
            "reference_revision_count": len(design.get("revisions") or []),
        }

    def render_preview(manifest, out_dir, expected=None, reference_json=None):
        del expected, reference_json
        previews = []
        for phase, frame in (
            ("first", 1),
            ("middle", 12),
            ("last", 24),
        ):
            path = Path(out_dir) / "preview" / f"shot_001_f{frame:04d}.png"
            _write_frame(path)
            previews.append({
                "shot_id": "shot_001",
                "frame": frame,
                "phase": phase,
                "png": str(path),
                "bytes": path.stat().st_size,
                "uniform": False,
            })
        report = {
            "schema_version": "blockout-report/v1",
            "manifest_fingerprint": manifest_fingerprint(manifest),
            "verdict": "fail",
            "findings": [],
            "checks": [{
                "check_id": "composition",
                "shot_id": "shot_001",
                "actual": 70.0,
                "threshold": 80.0,
                "verdict": "fail",
            }],
            "visual_states": [],
        }
        attempts.append(report)
        return {
            "report": report,
            "previews": previews,
            "evidence_dir": str(out_dir),
            "settings": {},
        }

    def collect_world_state(manifest):
        return {
            "schema_version": "runtime-world/v1",
            "characters": {},
            "cameras": {
                "shot_001": {
                    "position": [0.0, 3.0, 1.5],
                    "target": [0.0, 0.0, 1.0],
                    "lens_mm": 35.0,
                    "manifest_revision_count": manifest.get(
                        "reference_revision_count"),
                },
            },
            "props": {},
            "anchors": {},
        }

    adapters = CoarsePipelineAdapters(
        build_manifest=build_manifest,
        build_scene=lambda manifest: None,
        render_preview=render_preview,
        collect_world_state=collect_world_state,
    )
    out = tmp_path / "blocked"

    result = run_coarse_pipeline(
        plan=_plan(),
        reference=_reference(),
        scene_id="scene",
        out_dir=out,
        max_revisions=2,
        adapters=adapters,
        proposal_provider=OfflineFixtureCoarseProposalProvider(),
    )

    assert result["coarse_status"] == "blocked"
    assert result["gates"]["coarse"] == "blocked"
    assert result["gates"]["baseline"] == "missing"
    assert result["artifacts"]["baseline"] is None
    assert not (out / "coarse_world_baseline.json").exists()
    attempts = sorted((out / "coarse" / "observations").glob("attempt-*"))
    loaded = [
        json.loads(
            (path / "observation.json").read_text(encoding="utf-8"))
        for path in attempts
    ]
    assert result["latest_candidate_observation_id"] == (
        loaded[1]["observation_id"])
    assert result["latest_candidate_report"]["checks"][0]["actual"] == 70.0
    first_round = result["rounds"][0]
    assert first_round["comparison"]["disposition"] == "tie"
    assert first_round["rollback"]["applied"] is True
    assert first_round["candidate"]["report"]["checks"][0][
        "actual"] == 70.0
    store = EvidenceStore.load(out / "coarse" / "evidence_store.json")
    assert store.summary()["adopted"] == {}
    best = store.get("shot_001", store.best_version("shot_001"))
    assert best.gates["shot_passed"] is False
    assert best.gates["coarse_passed"] is False
    assert best.delivery_eligible is False
    best_attempt = next(
        payload for payload in loaded
        if payload["observation_id"] == result["best_observation_id"])
    assert best.basis_fingerprints["report_fingerprint"] == canonical_fingerprint(
        best_attempt["report"])
