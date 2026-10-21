"""Probe: detail apply preserves declared camera movement and scene range."""

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
        "scene_id": "detail-session-camera-motion",
        "characters": [{
            "name": "甲",
            "position": {"x": 0.0, "y": 0.0, "z": 0.0},
            "facing": [0.0, 1.0, 0.0],
        }],
        "props": [],
        "anchors": [],
        "camera_intents": [{
            "shot_id": "shot_001",
            "position": [0.0, -5.0, 1.6],
            "target": [0.0, 0.0, 1.0],
            "lens": 50.0,
        }],
        "shots": [{
            "shot_id": "shot_001",
            "order": 1,
            "duration_frames": 24,
            "characters": ["甲"],
            "shot_type": "MS",
            "camera": {"movements": []},
        }],
        "shot_staging": {},
    }


def _baseline(design: dict) -> tuple[dict, dict]:
    from block_director.cinema.blockout import build_blockout_manifest

    plan = {"shots": copy.deepcopy(design["shots"])}
    return plan, {
        "schema_version": "coarse-baseline/v1",
        "state": "frozen",
        "reference": design,
        "manifest": build_blockout_manifest(design=design, plan=plan),
        "report": {
            "schema_version": "blockout-report/v1",
            "verdict": "pass",
            "findings": [],
            "checks": [],
        },
    }


def _location_at(obj, frame: int) -> list[float]:
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
    plan, baseline = _baseline(design)
    session = DetailSceneSession(
        baseline=baseline,
        plan=plan,
        out_dir=out_dir,
        run_id="detail-camera-motion",
        scene_id=design["scene_id"],
    )
    session.prepare()

    camera = bpy.data.objects["BD_Blockout_cam_shot_001"]
    target = bpy.data.objects["BD_Blockout_CamTarget_shot_001"]
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = 96

    candidate = copy.deepcopy(design)
    candidate["shots"][0]["camera"] = {
        "movements": [{
            "type": "dolly_in",
            "amount": 0.8,
            "start_frame": 1,
            "end_frame": 12,
        }, {
            "type": "pan_right",
            "amount": 15.0,
            "start_frame": 13,
            "end_frame": 24,
        }],
    }
    session.apply(candidate, "shot_001")

    camera_track = {
        str(frame): _location_at(camera, frame)
        for frame in (1, 6, 12, 18, 24)
    }
    target_track = {
        str(frame): _location_at(target, frame)
        for frame in (1, 6, 12, 18, 24)
    }
    range_after_apply = [int(scene.frame_start), int(scene.frame_end)]

    restore_result = session.restore(design, "shot_001")
    camera_restored = {
        str(frame): _location_at(camera, frame)
        for frame in (1, 6, 12, 18, 24)
    }
    range_after_restore = [int(scene.frame_start), int(scene.frame_end)]

    checks = {
        "camera_motion_has_intermediate_key": (
            camera_track["6"] != camera_track["1"]
            and camera_track["12"] != camera_track["1"]
            and camera_track["24"] != camera_track["1"]
        ),
        "target_motion_has_intermediate_key": (
            target_track["18"] != target_track["1"]
            and target_track["24"] != target_track["1"]
        ),
        "scene_range_unchanged_after_apply": (
            range_after_apply == [1, 96]),
        "restore_returns_static_camera": (
            len(set(
                tuple(values)
                for values in camera_restored.values()
            )) == 1
        ),
        "scene_range_unchanged_after_restore": (
            range_after_restore == [1, 96]),
        "restore_recollected_live_state": (
            bool(
                restore_result.get("ok") is True
                and restore_result.get("world_state_fingerprint")
            )),
    }
    payload = {
        "ok": all(checks.values()),
        "checks": checks,
        "camera_track": camera_track,
        "target_track": target_track,
        "camera_restored": camera_restored,
        "range_after_apply": range_after_apply,
        "range_after_restore": range_after_restore,
        "restore_result": restore_result,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "detail_camera_motion_probe.json").write_text(
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
        / "20261021-detail-session-camera-motion")
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
