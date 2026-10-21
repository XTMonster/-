"""Probe: detail repair mutates and restores only the requested shot."""

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
        "scene_id": "detail-session-target-scope",
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

    manifest = build_blockout_manifest(design=design, plan=plan)
    return {
        "schema_version": "coarse-baseline/v1",
        "state": "frozen",
        "reference": design,
        "manifest": manifest,
        "report": {
            "schema_version": "blockout-report/v1",
            "verdict": "pass",
            "findings": [],
            "checks": [
                {
                    "check_id": "composition",
                    "shot_id": shot_id,
                    "actual": 88.0,
                    "threshold": 80.0,
                    "verdict": "pass",
                }
                for shot_id in ("shot_001", "shot_002")
            ],
        },
    }


def _key_signature(obj) -> list:
    action = (
        obj.animation_data.action
        if obj.animation_data and obj.animation_data.action else None
    )
    if action is None:
        return []
    from block_director.utils.blender_compat import action_fcurves

    return sorted(
        (
            str(curve.data_path),
            int(curve.array_index),
            round(float(point.co.x), 6),
            round(float(point.co.y), 6),
        )
        for curve in action_fcurves(action)
        for point in curve.keyframe_points
    )


def _live_at(obj, frame: int) -> list[float]:
    bpy.context.scene.frame_set(int(frame))
    bpy.context.view_layer.update()
    return [
        round(float(value), 6)
        for value in obj.matrix_world.translation
    ]


def run_probe(out_dir: Path) -> dict:
    from block_director.layer3_engine.detail_session import DetailSceneSession

    bpy.ops.wm.read_factory_settings(use_empty=True)
    design = _design()
    plan = _plan(design)
    baseline = _baseline(design, plan)
    session = DetailSceneSession(
        baseline=baseline,
        plan=plan,
        out_dir=out_dir,
        run_id="detail-target-scope",
        scene_id=design["scene_id"],
    )
    session.prepare()

    char = bpy.data.objects["BD_Blockout_char_甲"]
    cam_one = bpy.data.objects["BD_Blockout_cam_shot_001"]
    target_one = bpy.data.objects["BD_Blockout_CamTarget_shot_001"]
    cam_two = bpy.data.objects["BD_Blockout_cam_shot_002"]
    target_two = bpy.data.objects["BD_Blockout_CamTarget_shot_002"]

    neighbor_before = {
        "camera_location": [round(float(v), 6) for v in cam_two.location],
        "target_location": [round(float(v), 6) for v in target_two.location],
        "camera_keys": _key_signature(cam_two),
        "target_keys": _key_signature(target_two),
        "character_at_25": _live_at(char, 25),
    }
    target_before = {
        "camera_location": _live_at(cam_one, 1),
        "target_location": _live_at(target_one, 1),
        "character_at_1": _live_at(char, 1),
    }

    candidate = copy.deepcopy(design)
    candidate["camera_intents"][0].update({
        "position": [0.4, -4.2, 1.8],
        "target": [0.25, 0.0, 1.05],
        "lens": 42.0,
        "provenance": "agent_local_revision",
    })
    candidate["shot_staging"] = {
        "shot_001": {
            "甲": {
                "position": {"x": 0.35, "y": 0.1, "z": 0.0},
                "provenance": "agent_local_revision",
                "reason": "target-shot composition",
            },
        },
    }
    session.apply(candidate, "shot_001")

    changed = {
        "camera_location": _live_at(cam_one, 1),
        "target_location": _live_at(target_one, 1),
        "lens": round(float(cam_one.data.lens), 6),
        "character_at_1": _live_at(char, 1),
        "character_at_25": _live_at(char, 25),
    }
    neighbor_during = {
        "camera_location": [round(float(v), 6) for v in cam_two.location],
        "target_location": [round(float(v), 6) for v in target_two.location],
        "camera_keys": _key_signature(cam_two),
        "target_keys": _key_signature(target_two),
    }

    restore_result = session.restore(design, "shot_001")
    restored = {
        "camera_location": _live_at(cam_one, 1),
        "target_location": _live_at(target_one, 1),
        "lens": round(float(cam_one.data.lens), 6),
        "character_at_1": _live_at(char, 1),
    }
    neighbor_after = {
        "camera_location": [round(float(v), 6) for v in cam_two.location],
        "target_location": [round(float(v), 6) for v in target_two.location],
        "camera_keys": _key_signature(cam_two),
        "target_keys": _key_signature(target_two),
        "character_at_25": _live_at(char, 25),
    }
    checks = {
        "target_camera_changed": (
            changed["camera_location"] != target_before["camera_location"]),
        "target_lens_changed": changed["lens"] == 42.0,
        "target_character_changed": (
            changed["character_at_1"] != target_before["character_at_1"]),
        "neighbor_camera_during_unchanged": (
            neighbor_during["camera_location"]
            == neighbor_before["camera_location"]
            and neighbor_during["camera_keys"]
            == neighbor_before["camera_keys"]),
        "neighbor_target_during_unchanged": (
            neighbor_during["target_location"]
            == neighbor_before["target_location"]
            and neighbor_during["target_keys"]
            == neighbor_before["target_keys"]),
        "shared_character_neighbor_frame_unchanged": (
            changed["character_at_25"]
            == neighbor_before["character_at_25"]),
        "target_camera_restored": (
            restored["camera_location"] == target_before["camera_location"]
            and restored["target_location"]
            == target_before["target_location"]
            and restored["lens"] == 50.0),
        "target_character_restored": (
            restored["character_at_1"]
            == target_before["character_at_1"]),
        "neighbor_after_restore_unchanged": (
            neighbor_after == neighbor_before),
        "restore_recollected_live_state": (
            isinstance(restore_result, dict)
            and restore_result.get("ok") is True
            and bool(restore_result.get("world_state_fingerprint"))),
    }
    payload = {
        "ok": all(checks.values()),
        "checks": checks,
        "target_before": target_before,
        "changed": changed,
        "restored": restored,
        "neighbor_before": neighbor_before,
        "neighbor_during": neighbor_during,
        "neighbor_after": neighbor_after,
        "restore_result": restore_result,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "detail_target_scope_probe.json").write_text(
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
        / "20261021-detail-session-target-scope")
    for index, item in enumerate(argv):
        if item == "--out" and index + 1 < len(argv):
            out_dir = Path(argv[index + 1])
            break
    try:
        result = run_probe(out_dir.resolve())
    except Exception as exc:  # noqa: BLE001
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
