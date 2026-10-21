"""Probe: a lower-scoring detail candidate restores the physical best."""

from __future__ import annotations

import copy
import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402


def _design() -> dict:
    return {
        "schema_version": "spatial-design-snapshot/v1",
        "scene_id": "detail-session-best-rollback",
        "characters": [{
            "name": "甲",
            "position": {"x": 0.0, "y": 0.0, "z": 0.0},
            "facing": [0.0, 1.0, 0.0],
            "provenance": "plan_intent",
        }],
        "props": [],
        "anchors": [],
        "camera_intents": [
            {
                "shot_id": "shot_001",
                "position": [0.0, -5.0, 1.6],
                "target": [0.0, 0.0, 1.0],
                "lens": 50.0,
            },
            {
                "shot_id": "shot_002",
                "position": [3.0, -5.0, 1.6],
                "target": [0.0, 0.0, 1.0],
                "lens": 35.0,
            },
        ],
        "shots": [
            {
                "shot_id": "shot_001",
                "order": 1,
                "duration_frames": 24,
                "characters": ["甲"],
                "shot_type": "MS",
                "framing_target": {
                    "kind": "character",
                    "ref": "甲",
                    "part": "none",
                },
            },
            {
                "shot_id": "shot_002",
                "order": 2,
                "duration_frames": 24,
                "characters": ["甲"],
                "shot_type": "WS",
                "framing_target": {
                    "kind": "character",
                    "ref": "甲",
                    "part": "none",
                },
            },
        ],
        "shot_staging": {},
    }


def _plan(design: dict) -> dict:
    return {"shots": [dict(shot) for shot in design["shots"]]}


def _baseline(design: dict, plan: dict) -> dict:
    from block_director.cinema.blockout import build_blockout_manifest

    return {
        "schema_version": "coarse-baseline/v1",
        "state": "frozen",
        "reference": design,
        "manifest": build_blockout_manifest(design=design, plan=plan),
        "report": {
            "schema_version": "blockout-report/v1",
            "verdict": "pass",
            "findings": [],
            "checks": [{
                "check_id": "composition",
                "shot_id": "shot_001",
                "actual": 88.0,
                "threshold": 80.0,
                "verdict": "pass",
            }],
        },
    }


def _scored_observation(observation, score: float):
    from block_director.contracts.observation import (
        build_observation_bundle,
    )

    report = copy.deepcopy(dict(observation.report))
    report["verdict"] = "fail"
    report["findings"] = []
    report["checks"] = [{
        "check_id": "composition",
        "shot_id": "shot_001",
        "actual": float(score),
        "threshold": 80.0,
        "verdict": "fail",
    }]
    return build_observation_bundle(
        reference=observation.reference,
        manifest=observation.manifest,
        report=report,
        world_state=observation.world_state,
        evidence_dir=Path(observation.evidence_dir),
        frame_records=[frame.to_dict() for frame in observation.frames],
    )


def _live_at(obj, frame: int) -> list[float]:
    bpy.context.scene.frame_set(int(frame))
    bpy.context.view_layer.update()
    return [
        round(float(value), 6)
        for value in obj.matrix_world.translation
    ]


def run_probe(out_dir: Path) -> dict:
    from block_director.cinema.detail_loop import (
        run_detail_revision_loop,
    )
    from block_director.layer3_engine.detail_session import (
        DetailSceneSession,
    )

    bpy.ops.wm.read_factory_settings(use_empty=True)
    design = _design()
    plan = _plan(design)
    baseline = _baseline(design, plan)
    session = DetailSceneSession(
        baseline=baseline,
        plan=plan,
        out_dir=out_dir,
        run_id="detail-best-rollback",
        scene_id=design["scene_id"],
    )
    session.prepare()

    camera = bpy.data.objects["BD_Blockout_cam_shot_001"]
    target = bpy.data.objects["BD_Blockout_CamTarget_shot_001"]
    neighbor_camera = bpy.data.objects["BD_Blockout_cam_shot_002"]
    neighbor_target = bpy.data.objects["BD_Blockout_CamTarget_shot_002"]
    before = {
        "camera": _live_at(camera, 1),
        "target": _live_at(target, 1),
        "neighbor_camera": _live_at(neighbor_camera, 1),
        "neighbor_target": _live_at(neighbor_target, 1),
    }
    scores = iter((70.0, 60.0))
    observed_world = []

    def observe(reference, shot_id):
        observation = session.observe(reference, shot_id)
        observed_world.append(copy.deepcopy(observation.world_state))
        return _scored_observation(observation, next(scores))

    def proposal_provider(*, request):
        return {
            "schema_version": "coarse-proposal/v1",
            "provider_kind": "probe_fixture",
            "reason": "intentionally regress the target camera",
            "prescriptions": [{
                "prescription_id": "regress_target",
                "scope": "camera",
                "shot_id": "shot_001",
                "entity": "cam_shot_001",
                "component": "target",
                "target_value": {"x": 2.5, "y": 0.0, "z": 1.0},
                "reason": "probe a lower-scoring candidate",
                "evidence_refs": ["composition:fail"],
            }],
        }

    outcome = run_detail_revision_loop(
        detail_shots=[{
            "shot_id": "shot_001",
            "characters": [{"name": "甲"}],
        }],
        reference=design,
        observe=observe,
        rebuild=session.apply,
        restore_best=session.restore,
        proposal_provider=proposal_provider,
        record_evidence=session.record_evidence,
        max_revisions=1,
        no_gain_limit=1,
    )
    after = {
        "camera": _live_at(camera, 1),
        "target": _live_at(target, 1),
        "neighbor_camera": _live_at(neighbor_camera, 1),
        "neighbor_target": _live_at(neighbor_target, 1),
    }
    shot = outcome["shots"]["shot_001"]
    try:
        adopted = session.evidence_store.adopted_version("shot_001")
    except KeyError:
        adopted = None
    checks = {
        "shot_stops_as_failed": shot["status"] == "failed",
        "failure_is_named": shot["blocked_code"] == "no_improvement_limit",
        "best_version_is_zero": shot["best_version"] == 0,
        "best_score_is_initial": shot["best_score"] == 70.0,
        "candidate_disposition_is_revert": (
            shot["versions"][-1]["disposition"] == "revert"),
        "physical_camera_restored": after["camera"] == before["camera"],
        "physical_target_restored": after["target"] == before["target"],
        "neighbor_camera_unchanged": (
            after["neighbor_camera"] == before["neighbor_camera"]),
        "neighbor_target_unchanged": (
            after["neighbor_target"] == before["neighbor_target"]),
        "retained_reference_is_original": (
            outcome["reference"].get("shot_staging") == {}
            and outcome["reference"].get("camera_intents")
            == design.get("camera_intents")),
        "evidence_history_has_two_versions": (
            len(session.evidence_store.history("shot_001")) == 2),
        "evidence_best_points_to_initial": (
            session.evidence_store.best_version("shot_001") == 0),
        "evidence_has_no_adopted_failure": (
            adopted is None),
        "candidate_world_was_observed": len(observed_world) == 2,
    }
    payload = {
        "ok": all(checks.values()),
        "checks": checks,
        "before": before,
        "after": after,
        "shot": shot,
        "reference": outcome["reference"],
        "evidence_store": session.evidence_store.to_dict(),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "detail_best_rollback_probe.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return payload


def main() -> int:
    argv = list(sys.argv)
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    out_dir = (
        ROOT / "docs" / "evidence"
        / "20261021-detail-session-best-rollback")
    for index, item in enumerate(argv):
        if item == "--out" and index + 1 < len(argv):
            out_dir = Path(argv[index + 1])
            break
    try:
        result = run_probe(out_dir.resolve())
    except Exception as exc:  # noqa: BLE001 - probe must report the real failure
        result = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "trace": traceback.format_exc(limit=8),
        }
    print("BD_TEST_RESULT " + json.dumps({
        **result,
        "passed": 1 if result.get("ok") else 0,
        "failed": 0 if result.get("ok") else 1,
        "checks": result.get("checks") or {},
    }, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
