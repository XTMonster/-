"""Blender proof that the coarse loop rolls back the live world, not JSON.

The fixture builds a real two-shot Blockout scene.  A lower-scoring Agent
candidate moves both cameras and is rebuilt twice.  The loop must restore the
physical best after each loss, stop on the repeated physical state, and leave
the scene at the best camera positions and shot-local character keyframes.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402

from block_director.cinema.coarse_loop import (  # noqa: E402
    run_coarse_revision_loop,
)
from block_director.contracts.blockout import (  # noqa: E402
    manifest_fingerprint,
)
from block_director.contracts.observation import (  # noqa: E402
    build_observation_bundle,
)
from block_director.layer3_engine.world_state import (  # noqa: E402
    collect_blockout_world_state,
)
from block_director.utils.blender_compat import action_fcurves  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

RESULTS: dict = {}


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "trace": traceback.format_exc(limit=5),
        }


def _reference() -> dict:
    return {
        "schema_version": "coarse-world-reference/v1",
        "scene_id": "coarse-best-rollback",
        "characters": [{
            "name": "甲",
            "position": {"x": 0.0, "y": 0.0, "z": 0.0},
            "facing": [0.0, 1.0, 0.0],
            "rotation": None,
            "gaze": None,
            "motion_by_shot": [],
        }],
        "props": [],
        "anchors": [],
        "camera_intents": [
            {
                "shot_id": "shot_001",
                "position": [0.0, 5.5, 2.0],
                "target": [0.0, 0.0, 1.0],
                "lens": 35.0,
                "fov_deg": 54.4,
                "movement": None,
                "provenance": "probe_best",
                "resolved": True,
            },
            {
                "shot_id": "shot_002",
                "position": [0.0, 5.5, 2.0],
                "target": [0.0, 0.0, 1.0],
                "lens": 35.0,
                "fov_deg": 54.4,
                "movement": None,
                "provenance": "probe_best",
                "resolved": True,
            },
        ],
        "shots": [
            {
                "shot_id": "shot_001",
                "order": 1,
                "duration_frames": 24,
                "characters": ["甲"],
                "actions": [],
            },
            {
                "shot_id": "shot_002",
                "order": 2,
                "duration_frames": 24,
                "characters": ["甲"],
                "actions": [],
            },
        ],
        "shot_staging": {
            "shot_001": {
                "甲": {
                    "position": {"x": 1.25, "y": 0.5, "z": 0.0},
                    "provenance": "probe_best",
                    "reason": "best shot-local position",
                },
            },
            "shot_002": {
                "甲": {
                    "position": {"x": -1.25, "y": -0.5, "z": 0.0},
                    "provenance": "probe_best",
                    "reason": "best second-shot position",
                },
            },
        },
        "revisions": [],
        "notes": [],
    }


def _report(manifest: dict, score: float) -> dict:
    return {
        "schema_version": "blockout-report/v1",
        "manifest_fingerprint": manifest_fingerprint(manifest),
        "verdict": "fail",
        "findings": [],
        "checks": [
            {
                "check_id": "composition",
                "shot_id": shot_id,
                "actual": score,
                "threshold": 80.0,
                "verdict": "fail",
            }
            for shot_id in ("shot_001", "shot_002")
        ],
        "visual_states": [],
        "notes": ["physical rollback probe fixture score"],
    }


def _position(world: dict, shot_id: str, name: str) -> list[float]:
    return [
        round(float(value), 6)
        for value in (
            ((world.get("shot_states") or {}).get(shot_id) or {})
            .get("characters", {})
            .get(name, {})
            .get("position", [])
        )
    ]


def _camera_position(world: dict, shot_id: str) -> list[float]:
    return [
        round(float(value), 6)
        for value in (
            ((world.get("shot_states") or {}).get(shot_id) or {})
            .get("cameras", {})
            .get(shot_id, {})
            .get("position", [])
        )
    ]


def _keyframe_frames(obj) -> list[int]:
    action = (
        obj.animation_data.action
        if obj.animation_data is not None
        and obj.animation_data.action is not None
        else None
    )
    return sorted({
        int(round(float(point.co.x)))
        for curve in (action_fcurves(action) if action is not None else [])
        for point in curve.keyframe_points
    })


def _live_character(scene, frame: int, object_name: str) -> list[float]:
    scene.frame_set(int(frame))
    bpy.context.view_layer.update()
    return [
        round(float(value), 6)
        for value in bpy.data.objects[object_name].matrix_world.translation
    ]


def _provider(*, request):
    prescriptions = []
    for shot_id in ("shot_001", "shot_002"):
        prescriptions.append({
            "prescription_id": f"probe_low_{shot_id}",
            "scope": "camera",
            "shot_id": shot_id,
            "entity": f"cam_{shot_id}",
            "component": "distance",
            "target_value": {
                "position": {"x": 0.0, "y": 2.7, "z": 2.0},
                "target": {"x": 0.0, "y": 0.0, "z": 1.0},
            },
            "reason": "intentionally lower candidate",
            "evidence_refs": [f"composition:{shot_id}"],
        })
    return {
        "schema_version": "coarse-proposal/v1",
        "source": "agent",
        "provider_kind": "rollback-probe",
        "reason": "drive a lower physical candidate",
        "prescriptions": prescriptions,
    }


def run_probe(out_dir: Path) -> dict:
    from block_director.cinema.blockout import build_blockout_manifest
    from block_director.layer3_engine.blockout_scene import (
        build_blockout_scene,
    )

    bpy.ops.wm.read_factory_settings(use_empty=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    reference = _reference()
    state: dict = {"manifest": {}}
    live_observations: list[dict] = []

    def rebuild(candidate):
        manifest = dict(build_blockout_manifest(
            design=candidate,
            plan=None,
        ))
        build_blockout_scene(manifest, clear_scene=True)
        state["manifest"] = manifest

    def observe(candidate):
        manifest = dict(state["manifest"])
        world = dict(collect_blockout_world_state(manifest))
        shot_one_y = _camera_position(world, "shot_001")[1]
        score = 70.0 if shot_one_y > 4.0 else 50.0
        live_observations.append({
            "score": score,
            "world": world,
            "world_state_fingerprint": world.get("world_state_fingerprint"),
            "camera_positions": {
                shot_id: _camera_position(world, shot_id)
                for shot_id in ("shot_001", "shot_002")
            },
            "character_positions": {
                shot_id: _position(world, shot_id, "甲")
                for shot_id in ("shot_001", "shot_002")
            },
        })
        attempt = out_dir / f"attempt-{len(live_observations):03d}"
        attempt.mkdir(parents=True, exist_ok=True)
        bundle = build_observation_bundle(
            reference=candidate,
            manifest=manifest,
            report=_report(manifest, score),
            world_state=world,
            evidence_dir=attempt,
            frame_records=[],
            complete_hint=True,
            require_frames=False,
        )
        bundle.write_atomic(attempt / "observation.json")
        return bundle

    rebuild(reference)
    initial_world = dict(collect_blockout_world_state(state["manifest"]))
    initial_best = {
        "cameras": {
            shot_id: _camera_position(initial_world, shot_id)
            for shot_id in ("shot_001", "shot_002")
        },
        "characters": {
            shot_id: _position(initial_world, shot_id, "甲")
            for shot_id in ("shot_001", "shot_002")
        },
    }
    outcome = run_coarse_revision_loop(
        reference=reference,
        report_loader=observe,
        rebuild=rebuild,
        restore_best=rebuild,
        proposal_provider=_provider,
        max_revisions=8,
        no_gain_limit=8,
    )

    scene = bpy.context.scene
    character = bpy.data.objects["BD_Blockout_char_甲"]
    final_world = dict(collect_blockout_world_state(state["manifest"]))
    final_live = {
        "cameras": {
            shot_id: _camera_position(final_world, shot_id)
            for shot_id in ("shot_001", "shot_002")
        },
        "characters": {
            shot_id: _position(final_world, shot_id, "甲")
            for shot_id in ("shot_001", "shot_002")
        },
        "character_frame_1": _live_character(
            scene, 1, character.name),
        "character_frame_25": _live_character(
            scene, 25, character.name),
    }
    candidate_rows = [
        row for row in live_observations if float(row["score"]) == 50.0
    ]
    last_round = outcome["rounds"][-1] if outcome["rounds"] else {}
    last_comparison = last_round.get("comparison") or {}
    last_rollback = last_round.get("rollback") or {}

    mismatches: list[str] = []
    if outcome.get("status") != "blocked":
        mismatches.append(f"status={outcome.get('status')!r}")
    if outcome.get("blocked_code") != "candidate_cycle_detected":
        mismatches.append(
            f"blocked_code={outcome.get('blocked_code')!r}")
    if len(candidate_rows) < 2:
        mismatches.append(f"candidate observations={len(candidate_rows)}")
    if int(outcome.get("rollback_count") or 0) < 2:
        mismatches.append(
            f"rollback_count={outcome.get('rollback_count')!r}")
    if last_comparison.get("disposition") != "rollback_repeated_state":
        mismatches.append(
            f"last disposition={last_comparison.get('disposition')!r}")
    if last_rollback.get("applied") is not True:
        mismatches.append("last rollback was not applied")
    if last_rollback.get("to_observation_id") != outcome.get(
            "best_observation_id"):
        mismatches.append("last rollback does not target best observation")
    if final_live["cameras"] != initial_best["cameras"]:
        mismatches.append(
            f"camera world drifted: {final_live['cameras']} != "
            f"{initial_best['cameras']}")
    if final_live["characters"] != initial_best["characters"]:
        mismatches.append(
            f"shot-local characters drifted: {final_live['characters']} != "
            f"{initial_best['characters']}")
    if final_live["character_frame_1"] != [1.25, 0.5, 0.85]:
        mismatches.append(
            f"frame 1 character={final_live['character_frame_1']}")
    if final_live["character_frame_25"] != [-1.25, -0.5, 0.85]:
        mismatches.append(
            f"frame 25 character={final_live['character_frame_25']}")
    if _keyframe_frames(character) != [1, 24, 25, 48]:
        mismatches.append(
            f"character keyframes={_keyframe_frames(character)}")

    payload = {
        "outcome": {
            "status": outcome.get("status"),
            "blocked_code": outcome.get("blocked_code"),
            "blocked_reason": outcome.get("blocked_reason"),
            "best_observation_id": outcome.get("best_observation_id"),
            "latest_candidate_observation_id": outcome.get(
                "latest_candidate_observation_id"),
            "rollback_count": outcome.get("rollback_count"),
            "rounds": outcome.get("rounds"),
        },
        "initial_best": initial_best,
        "final_live": final_live,
        "character_keyframes": _keyframe_frames(character),
        "candidate_observations": [
            {
                "score": row["score"],
                "camera_positions": row["camera_positions"],
                "character_positions": row["character_positions"],
            }
            for row in candidate_rows
        ],
        "mismatches": mismatches,
    }
    (out_dir / "coarse_best_rollback_probe.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"ok": not mismatches, "checks": payload}


def main() -> int:
    argv = list(sys.argv)
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    out_dir = ROOT / "docs" / "evidence" / "20261021-coarse-best-rollback"
    for index, item in enumerate(argv):
        if item == "--out" and index + 1 < len(argv):
            out_dir = Path(argv[index + 1])
            break
    capture_main_thread()
    check("coarse_best_rollback_restores_live_world",
          lambda: run_probe(out_dir.resolve()))
    failed = [name for name, result in RESULTS.items()
              if result.get("ok") is not True]
    print("BD_TEST_RESULT " + json.dumps({
        "passed": [name for name in RESULTS if name not in failed],
        "failed": failed,
        "checks": RESULTS,
    }, ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
