"""Probe: detail composition refresh must preserve the approved live world.

The detail stage is allowed to re-measure composition.  It is not allowed to
replace the live Blockout scene with a fresh deterministic build, because that
silently discards Agent-authored object identity, keyframes, guide objects and
edit markers before sequence review and final rendering.

This probe builds one tiny Blockout shot, applies an Agent-approved edit to its
camera, adds an Agent-owned guide and a detail beat marker, then calls the real
``refresh_blockout_composition`` path.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402


def _plan() -> dict:
    return {
        "scene_heading": "detail-world-preservation-probe",
        "shots": [{
            "shot_id": "shot_001",
            "order": 1,
            "intent": "Agent 相机编辑必须进入最终审核和渲染",
            "shot_type": "MS",
            "duration_frames": 24,
            "characters": ["米迦尔"],
            "actions": [],
            "camera": {
                "side": "front",
                "lens": 35,
                "movements": [{
                    "type": "dolly_in",
                    "amount": 0.2,
                    "start_frame": 1,
                    "end_frame": 24,
                }],
            },
        }],
    }


def _baseline(plan: dict) -> dict:
    from block_director.cinema.blockout import build_blockout_manifest
    from block_director.cinema.spatial_design import build_design_snapshot
    from block_director.layer5_orchestrator.understand import deterministic_brief

    brief = deterministic_brief(parsed=None, characters=["米迦尔"])
    reference = build_design_snapshot(
        brief=brief,
        plan=plan,
        cast_positions={"米迦尔": [-1.2, 0.0, 0.0]},
        cast_facings={"米迦尔": [0.0, 1.0, 0.0]},
        scene_id=str(plan["scene_heading"]),
    )
    reference["shots"] = [dict(plan["shots"][0])]
    manifest = build_blockout_manifest(design=reference, plan=plan)
    return {
        "state": "frozen",
        "reference": reference,
        "manifest": manifest,
        "report": {
            "schema_version": "blockout-report/v1",
            "verdict": "pass",
            "findings": [],
            "checks": [{
                "check_id": "composition",
                "shot_id": "shot_001",
                "actual": 90.0,
                "threshold": 80.0,
                "verdict": "pass",
            }],
        },
    }


def _key_signature(obj) -> list:
    action = (obj.animation_data.action
              if obj.animation_data and obj.animation_data.action else None)
    if action is None:
        return []
    from block_director.utils.blender_compat import action_fcurves

    return sorted(
        (
            str(curve.data_path),
            int(curve.array_index),
            round(float(point.co.x), 4),
            round(float(point.co.y), 6),
        )
        for curve in action_fcurves(action)
        for point in curve.keyframe_points
    )


def main() -> None:
    argv = list(sys.argv)
    out = ROOT / "docs" / "evidence" / "20261021-detail-world-preservation"
    if "--" in argv:
        args = argv[argv.index("--") + 1:]
        if "--out" in args:
            out = Path(args[args.index("--out") + 1])
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)

    plan = _plan()
    baseline = _baseline(plan)

    from block_director.layer3_engine.blockout_scene import build_blockout_scene
    from block_director.layer3_engine.detail_scene import apply_detail_beats
    from block_director.layer8_delivery.blockout_preview import (
        refresh_blockout_composition,
    )

    build_blockout_scene(baseline["manifest"], clear_scene=True)
    camera = bpy.data.objects["BD_Blockout_cam_shot_001"]
    camera["bd_agent_approval"] = "approved-shot-001-r7"
    camera["bd_agent_edited"] = True
    camera.location = (2.25, -3.75, 1.35)
    if camera.animation_data is not None:
        camera.animation_data_clear()
    first = bpy.context.scene.frame_current
    bpy.context.scene.frame_set(1)
    camera.keyframe_insert(data_path="location", frame=1)
    camera.location = (2.05, -3.55, 1.30)
    camera.keyframe_insert(data_path="location", frame=24)

    guide = bpy.data.objects.new("BD_AgentApprovedGuide", None)
    bpy.context.scene.collection.objects.link(guide)
    guide.location = (0.75, -1.25, 0.5)
    guide["bd_agent_approval"] = "approved-shot-001-r7"

    apply_detail_beats([{
        "shot_id": "shot_001",
        "beats": [{"frame": 8, "action": "抬头"}],
    }], baseline["manifest"])
    bpy.context.scene.frame_set(first)

    before = {
        "camera_name": camera.name,
        "camera_marker": camera.get("bd_agent_approval"),
        "camera_keys": _key_signature(camera),
        "guide_exists": bpy.data.objects.get("BD_AgentApprovedGuide") is not None,
        "detail_beat_exists": (
            bpy.context.scene.timeline_markers.get(
                "BD_DetailBeat_shot_001") is not None
        ),
    }
    report = refresh_blockout_composition(
        baseline=baseline,
        out_dir=out,
        expected=plan,
        reference_json=baseline["reference"],
    )
    after_camera = bpy.data.objects.get("BD_Blockout_cam_shot_001")
    after = {
        "camera_name": after_camera.name if after_camera is not None else None,
        "camera_marker": (
            after_camera.get("bd_agent_approval")
            if after_camera is not None else None
        ),
        "camera_keys": (
            _key_signature(after_camera) if after_camera is not None else []
        ),
        "guide_exists": bpy.data.objects.get("BD_AgentApprovedGuide") is not None,
        "detail_beat_exists": (
            bpy.context.scene.timeline_markers.get(
                "BD_DetailBeat_shot_001") is not None
        ),
    }
    refreshed_manifest = json.loads(
        (out / "refreshed_manifest.json").read_text(encoding="utf-8"))
    refreshed_camera = next(
        camera for camera in refreshed_manifest.get("cameras") or []
        if str(camera.get("shot_id") or "") == "shot_001"
    )
    manifest_camera_matches = all(
        abs(float(refreshed_camera["position"][index])
            - [2.25, -3.75, 1.35][index]) <= 1e-4
        for index in range(3)
    )
    ok = (
        after["camera_marker"] == before["camera_marker"]
        and after["camera_keys"] == before["camera_keys"]
        and after["guide_exists"] is True
        and after["detail_beat_exists"] is True
        and manifest_camera_matches
        and bool(report.get("checks"))
    )

    payload = {
        "ok": ok,
        "before": before,
        "after": after,
        "refreshed_camera": refreshed_camera,
        "manifest_camera_matches": manifest_camera_matches,
        "report_checks": report.get("checks") or [],
        "out": str(out),
    }
    (out / "detail_world_preservation_probe.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("BD_TEST_RESULT " + json.dumps({
        **payload,
        "passed": 1 if ok else 0,
        "failed": 0 if ok else 1,
        "checks": {
            "camera_identity_preserved": (
                after["camera_name"] == before["camera_name"]),
            "camera_edit_preserved": (
                after["camera_marker"] == before["camera_marker"]),
            "camera_keys_preserved": (
                after["camera_keys"] == before["camera_keys"]),
            "agent_guide_preserved": after["guide_exists"],
            "detail_beat_preserved": after["detail_beat_exists"],
            "refreshed_manifest_matches_live_camera": manifest_camera_matches,
        },
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
