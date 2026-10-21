"""Probe: detail observations can render and report one target shot only."""

from __future__ import annotations

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
        "scene_id": "detail-preview-subset",
        "characters": [
            {
                "name": "甲",
                "position": {"x": 0.0, "y": 0.0, "z": 0.0},
                "facing": [0.0, 1.0, 0.0],
                "provenance": "plan_intent",
            },
            {
                "name": "乙",
                "position": {"x": 3.0, "y": 0.0, "z": 0.0},
                "facing": [0.0, 1.0, 0.0],
                "provenance": "plan_intent",
            },
        ],
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
                "target": [3.0, 0.0, 1.0],
                "lens": 50.0,
            },
        ],
        "shots": [
            {
                "shot_id": "shot_001",
                "order": 1,
                "duration_frames": 24,
                "characters": ["甲"],
                "shot_type": "MS",
            },
            {
                "shot_id": "shot_002",
                "order": 2,
                "duration_frames": 24,
                "characters": ["乙"],
                "shot_type": "MS",
            },
        ],
        "shot_staging": {
            "shot_001": {
                "甲": {
                    "position": {"x": 0.4, "y": 0.0, "z": 0.0},
                    "provenance": "agent_local_revision",
                    "reason": "filtered detail candidate",
                },
            },
        },
    }


def _plan() -> dict:
    return {"shots": [dict(shot) for shot in _design()["shots"]]}


def _shot_ids_from_rows(rows) -> list[str]:
    return list(dict.fromkeys(
        str(row.get("shot_id") or "")
        for row in rows
        if isinstance(row, dict) and str(row.get("shot_id") or "")
    ))


def run_probe(out_dir: Path) -> dict:
    from block_director.cinema.blockout import build_blockout_manifest
    from block_director.layer3_engine.blockout_scene import (
        build_blockout_scene,
    )
    from block_director.layer8_delivery.blockout_preview import (
        render_blockout_preview,
    )

    bpy.ops.wm.read_factory_settings(use_empty=True)
    manifest = build_blockout_manifest(design=_design(), plan=_plan())
    build_blockout_scene(manifest, clear_scene=True)
    scene = bpy.context.scene
    staged_object = bpy.data.objects["BD_Blockout_char_甲"]
    caller_camera = bpy.data.objects["BD_Blockout_cam_shot_002"]
    scene.camera = caller_camera
    scene.frame_set(20)
    bpy.context.view_layer.update()
    caller_frame = int(scene.frame_current)
    caller_staging = tuple(float(value) for value in staged_object.location)

    default = render_blockout_preview(
        manifest, out_dir / "all", expected=_plan(), reference_json=_design())
    default_rows = list(default.get("previews") or [])
    default_checks = list((default.get("report") or {}).get("checks") or [])
    default_state = {
        "camera": scene.camera.name if scene.camera is not None else "",
        "frame": int(scene.frame_current),
        "staging": tuple(float(value) for value in staged_object.location),
    }

    scene.camera = caller_camera
    scene.frame_set(caller_frame)
    scene.camera = caller_camera
    bpy.context.view_layer.update()
    staged_object.location = caller_staging
    subset = render_blockout_preview(
        manifest,
        out_dir / "shot_001",
        expected=_plan(),
        reference_json=_design(),
        shot_ids=["shot_001"],
    )
    subset_rows = list(subset.get("previews") or [])
    subset_checks = list((subset.get("report") or {}).get("checks") or [])
    subset_state = {
        "camera": scene.camera.name if scene.camera is not None else "",
        "frame": int(scene.frame_current),
        "staging": tuple(float(value) for value in staged_object.location),
    }

    scene.frame_set(caller_frame)
    bpy.context.view_layer.update()
    staged_object.location = caller_staging
    invalid_error = ""
    try:
        render_blockout_preview(
            manifest,
            out_dir / "invalid",
            expected=_plan(),
            reference_json=_design(),
            shot_ids=["shot_999"],
        )
    except ValueError as exc:
        invalid_error = str(exc)
    invalid_state = {
        "camera": scene.camera.name if scene.camera is not None else "",
        "frame": int(scene.frame_current),
        "staging": tuple(float(value) for value in staged_object.location),
    }

    expected_caller_state = {
        "camera": caller_camera.name,
        "frame": caller_frame,
        "staging": caller_staging,
    }
    checks = {
        "default_preview_has_both_shots": (
            set(_shot_ids_from_rows(default_rows))
            == {"shot_001", "shot_002"}),
        "default_report_has_both_compositions": (
            {
                str(row.get("shot_id") or "")
                for row in default_checks
                if row.get("check_id") == "composition"
            }
            == {"shot_001", "shot_002"}),
        "default_restores_camera": (
            default_state["camera"] == caller_camera.name),
        "default_restores_frame": default_state["frame"] == caller_frame,
        "default_restores_staging": (
            default_state["staging"] == caller_staging),
        "subset_renders_only_target": (
            _shot_ids_from_rows(subset_rows) == ["shot_001"]),
        "subset_has_three_phase_frames": (
            [str(row.get("phase") or "") for row in subset_rows]
            == ["first", "middle", "last"]),
        "subset_preview_files_exist": all(
            Path(str(row.get("png") or "")).is_file()
            for row in subset_rows),
        "subset_report_has_only_target": (
            {
                str(row.get("shot_id") or "")
                for row in subset_checks
                if row.get("shot_id")
            }
            == {"shot_001"}),
        "subset_report_has_no_sequence_mismatch": not any(
            row.get("check_id") == "E_BLOCKOUT_SHOT_SEQUENCE_MISMATCH"
            for row in (subset.get("report") or {}).get("findings") or []),
        "subset_restores_camera": (
            subset_state["camera"] == caller_camera.name),
        "subset_restores_frame": subset_state["frame"] == caller_frame,
        "subset_restores_staging": (
            subset_state["staging"] == caller_staging),
        "invalid_shot_names_missing_id": "shot_999" in invalid_error,
        "invalid_restores_camera": (
            invalid_state["camera"] == caller_camera.name),
        "invalid_restores_frame": invalid_state["frame"] == caller_frame,
        "invalid_restores_staging": (
            invalid_state["staging"] == caller_staging),
    }
    payload = {
        "ok": all(checks.values()),
        "checks": checks,
        "expected_caller_state": expected_caller_state,
        "default_state": default_state,
        "subset_state": subset_state,
        "invalid_state": invalid_state,
        "invalid_error": invalid_error,
        "default_shot_ids": _shot_ids_from_rows(default_rows),
        "subset_shot_ids": _shot_ids_from_rows(subset_rows),
        "subset_report_check_ids": [
            {
                "check_id": row.get("check_id"),
                "shot_id": row.get("shot_id"),
            }
            for row in subset_checks
        ],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "detail_preview_subset_probe.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return payload


def main() -> int:
    argv = list(sys.argv)
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    out_dir = ROOT / "docs" / "evidence" / "20261021-detail-preview-subset"
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
