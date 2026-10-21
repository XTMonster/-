"""Probe: detail mutation protects user animation only in its target scope."""

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
        "scene_id": "detail-session-protection",
        "characters": [
            {
                "name": "甲",
                "position": {"x": 0.0, "y": 0.0, "z": 0.0},
                "facing": [0.0, 1.0, 0.0],
            },
            {
                "name": "乙",
                "position": {"x": 3.0, "y": 0.0, "z": 0.0},
                "facing": [0.0, 1.0, 0.0],
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
            },
            {
                "shot_id": "shot_002",
                "order": 2,
                "duration_frames": 24,
                "characters": ["乙"],
                "shot_type": "WS",
            },
        ],
        "shot_staging": {},
    }


def _baseline(design: dict) -> dict:
    from block_director.cinema.blockout import build_blockout_manifest

    plan = {"shots": [copy.deepcopy(shot) for shot in design["shots"]]}
    return plan, {
        "state": "frozen",
        "reference": design,
        "manifest": build_blockout_manifest(design=design, plan=plan),
        "report": {"verdict": "pass", "findings": [], "checks": []},
    }


def _candidate(design: dict) -> dict:
    result = copy.deepcopy(design)
    result["camera_intents"][0].update({
        "position": [0.5, -4.0, 1.8],
        "target": [0.25, 0.0, 1.0],
        "lens": 42.0,
        "provenance": "agent_local_revision",
    })
    result["shot_staging"] = {
        "shot_001": {
            "甲": {
                "position": {"x": 0.4, "y": 0.1, "z": 0.0},
                "provenance": "agent_local_revision",
                "reason": "composition repair",
            },
        },
    }
    return result


def _snapshot(objects: dict[str, object]) -> dict:
    return {
        name: [round(float(value), 6) for value in obj.location]
        for name, obj in objects.items()
    }


def _new_session(out_dir: Path):
    from block_director.layer3_engine.detail_session import DetailSceneSession

    bpy.ops.wm.read_factory_settings(use_empty=True)
    design = _design()
    plan, baseline = _baseline(design)
    session = DetailSceneSession(
        baseline=baseline,
        plan=plan,
        out_dir=out_dir,
        run_id="detail-session-protection",
        scene_id=design["scene_id"],
    )
    session.prepare()
    return design, session


def _target_scope_blocks_without_mutation(out_dir: Path) -> dict:
    from block_director.cinema.detail_loop import DetailLoopBlocked
    from block_director.layer3_engine.scene_sync import mark_user_animated

    design, session = _new_session(out_dir / "target")
    camera = bpy.data.objects["BD_Blockout_cam_shot_001"]
    target = bpy.data.objects["BD_Blockout_CamTarget_shot_001"]
    character = bpy.data.objects["BD_Blockout_char_甲"]
    mark_user_animated(character)
    mark_user_animated(camera)
    before = _snapshot({
        "camera": camera,
        "target": target,
        "character": character,
    })
    blocked_code = ""
    try:
        session.apply(_candidate(design), "shot_001")
    except DetailLoopBlocked as exc:
        blocked_code = exc.code
    after = _snapshot({
        "camera": camera,
        "target": target,
        "character": character,
    })
    return {
        "ok": blocked_code == "user_animation_conflict" and before == after,
        "blocked_code": blocked_code,
        "before": before,
        "after": after,
    }


def _scope_violation_blocks_without_mutation(out_dir: Path) -> dict:
    from block_director.cinema.detail_loop import DetailLoopBlocked

    design, session = _new_session(out_dir / "scope")
    camera = bpy.data.objects["BD_Blockout_cam_shot_001"]
    target = bpy.data.objects["BD_Blockout_CamTarget_shot_001"]
    character = bpy.data.objects["BD_Blockout_char_甲"]
    neighbor = bpy.data.objects["BD_Blockout_cam_shot_002"]
    before = _snapshot({
        "camera": camera,
        "target": target,
        "character": character,
        "neighbor": neighbor,
    })
    reference_before = copy.deepcopy(session.reference)
    manifest_before = copy.deepcopy(session.manifest)
    candidate = _candidate(design)
    candidate["camera_intents"][1]["position"] = [9.0, -5.0, 1.6]
    blocked_code = ""
    try:
        session.apply(candidate, "shot_001")
    except DetailLoopBlocked as exc:
        blocked_code = exc.code
    after = _snapshot({
        "camera": camera,
        "target": target,
        "character": character,
        "neighbor": neighbor,
    })
    return {
        "ok": (
            blocked_code == "detail_scope_violation"
            and before == after
            and session.reference == reference_before
            and session.manifest == manifest_before
        ),
        "blocked_code": blocked_code,
        "before": before,
        "after": after,
        "reference_unchanged": session.reference == reference_before,
        "manifest_unchanged": session.manifest == manifest_before,
    }


def _neighbor_scope_animation_does_not_block(out_dir: Path) -> dict:
    from block_director.layer3_engine.scene_sync import mark_user_animated

    design, session = _new_session(out_dir / "neighbor")
    neighbor_camera = bpy.data.objects["BD_Blockout_cam_shot_002"]
    neighbor_character = bpy.data.objects["BD_Blockout_char_乙"]
    mark_user_animated(neighbor_camera)
    mark_user_animated(neighbor_character)
    neighbor_before = _snapshot({
        "camera": neighbor_camera,
        "character": neighbor_character,
    })
    error = ""
    try:
        session.apply(_candidate(design), "shot_001")
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
    target = bpy.data.objects["BD_Blockout_cam_shot_001"]
    neighbor_after = _snapshot({
        "camera": neighbor_camera,
        "character": neighbor_character,
    })
    return {
        "ok": not error
        and neighbor_before == neighbor_after
        and [round(float(v), 6) for v in target.location]
        == [0.5, -4.0, 1.8],
        "error": error,
        "neighbor_before": neighbor_before,
        "neighbor_after": neighbor_after,
        "target": [round(float(v), 6) for v in target.location],
    }


def run_probe(out_dir: Path) -> dict:
    checks = {
        "target_scope_blocks_without_mutation":
            _target_scope_blocks_without_mutation(out_dir),
        "scope_violation_blocks_without_mutation":
            _scope_violation_blocks_without_mutation(out_dir),
        "neighbor_scope_animation_does_not_block":
            _neighbor_scope_animation_does_not_block(out_dir),
    }
    payload = {
        "ok": all(value["ok"] for value in checks.values()),
        "checks": checks,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "detail_session_protection_probe.json").write_text(
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
        / "20261021-detail-session-protection")
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
