"""Physical proof that shot-local staging reaches the Blender blockout world."""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402

RESULTS: dict = {}


def _design() -> dict:
    return {
        "schema_version": "spatial-design-snapshot/v1",
        "scene_id": "local_staging",
        "characters": [{
            "name": "米迦尔",
            "position": {"x": 0.0, "y": 0.0, "z": 0.0},
            "facing": [0.0, 1.0, 0.0],
            "rotation": None,
            "motion": None,
            "gaze": None,
            "provenance": "plan_intent",
        }],
        "props": [],
        "anchors": [],
        "camera_intents": [
            {
                "shot_id": "shot_001",
                "position": [0.0, 3.0, 1.5],
                "target": [1.25, 0.5, 1.0],
                "lens": 35.0,
                "fov_deg": 54.4,
                "provenance": "agent_local_revision",
                "resolved": True,
            },
            {
                "shot_id": "shot_002",
                "position": [0.0, 3.0, 1.5],
                "target": [0.0, 0.0, 1.0],
                "lens": 35.0,
                "fov_deg": 54.4,
                "provenance": "plan_intent",
                "resolved": True,
            },
        ],
        "shots": [
            {
                "shot_id": "shot_001",
                "order": 1,
                "duration_frames": 24,
                "characters": ["米迦尔"],
                "actions": [],
            },
            {
                "shot_id": "shot_002",
                "order": 2,
                "duration_frames": 24,
                "characters": ["米迦尔"],
                "actions": [],
            },
        ],
        "shot_staging": {
            "shot_001": {
                "米迦尔": {
                    "position": {"x": 1.25, "y": 0.5, "z": 0.0},
                    "provenance": "agent_local_revision",
                    "reason": "只调整第一镜",
                },
            },
        },
        "notes": [],
    }


def _at_frame(scene, frame: int, object_name: str) -> dict:
    scene.frame_set(int(frame))
    bpy.context.view_layer.update()
    obj = bpy.data.objects[object_name]
    return {
        "location": [round(float(value), 6)
                     for value in obj.matrix_world.translation],
        "hide_render": bool(obj.hide_render),
    }


def run_probe(out_dir: Path) -> dict:
    from block_director.cinema.blockout import build_blockout_manifest
    from block_director.layer3_engine.blockout_scene import (
        blockout_scene_is_current,
        build_blockout_scene,
        ensure_blockout_scene,
    )
    from block_director.layer3_engine.world_state import (
        collect_blockout_world_state,
    )

    manifest = build_blockout_manifest(design=_design(), plan=None)
    build_blockout_scene(manifest, clear_scene=True)
    scene = bpy.context.scene
    object_name = "BD_Blockout_char_米迦尔"

    shot_one = _at_frame(scene, 1, object_name)
    shot_one_mid = _at_frame(scene, 12, object_name)
    shot_one_last = _at_frame(scene, 24, object_name)
    shot_two = _at_frame(scene, 25, object_name)
    shot_two_last = _at_frame(scene, 48, object_name)
    world = collect_blockout_world_state(manifest)

    mismatches: list[str] = []
    expected_shot_one = [1.25, 0.5, 0.85]
    expected_shot_two = [0.0, 0.0, 0.85]
    for label, state in (
        ("shot_one", shot_one),
        ("shot_one_mid", shot_one_mid),
        ("shot_one_last", shot_one_last),
    ):
        if any(abs(state["location"][i] - expected_shot_one[i]) > 1e-4
               for i in range(3)):
            mismatches.append(
                f"{label} live={state['location']} expected={expected_shot_one}")
    for label, state in (
        ("shot_two", shot_two),
        ("shot_two_last", shot_two_last),
    ):
        if any(abs(state["location"][i] - expected_shot_two[i]) > 1e-4
               for i in range(3)):
            mismatches.append(
                f"{label} live={state['location']} expected={expected_shot_two}")

    shot_states = world.get("shot_states") or {}
    recorded_one = (
        ((shot_states.get("shot_001") or {}).get("characters") or {})
        .get("米迦尔", {}).get("position")
    )
    recorded_two = (
        ((shot_states.get("shot_002") or {}).get("characters") or {})
        .get("米迦尔", {}).get("position")
    )
    if recorded_one is None or any(
            abs(float(recorded_one[i]) - expected_shot_one[i]) > 1e-4
            for i in range(3)):
        mismatches.append(
            f"world shot_001 character={recorded_one!r} "
            f"expected={expected_shot_one}")
    if recorded_two is None or any(
            abs(float(recorded_two[i]) - expected_shot_two[i]) > 1e-4
            for i in range(3)):
        mismatches.append(
            f"world shot_002 character={recorded_two!r} "
            f"expected={expected_shot_two}")

    current_before = blockout_scene_is_current(manifest)
    if not current_before:
        mismatches.append(
            "freshly built manifest scene was not recognised as current")

    #: Simulate a scene produced by an older build that has the same manifest
    #: fingerprint and object names but no per-shot location keys.  Its base
    #: location can still match shot_001, so object existence + fingerprint is
    #: insufficient evidence that shot_002 will render correctly.
    char = bpy.data.objects[object_name]
    char.animation_data_clear()
    char.location = tuple(expected_shot_one)
    scene.frame_set(25)
    bpy.context.view_layer.update()
    current_without_keys = blockout_scene_is_current(manifest)
    if current_without_keys:
        mismatches.append(
            "stale scene without shot-position keys was wrongly considered "
            "current")

    ensured = ensure_blockout_scene(manifest, clear_scene=True)
    current_after_rebuild = blockout_scene_is_current(manifest)
    if ensured.get("reused") is not False:
        mismatches.append(
            f"stale scene was reused instead of rebuilt: {ensured!r}")
    if not current_after_rebuild:
        mismatches.append(
            "rebuilt shot-position scene was not recognised as current")
    rebuilt_shot_two = _at_frame(scene, 25, object_name)
    if any(abs(rebuilt_shot_two["location"][i] - expected_shot_two[i]) > 1e-4
           for i in range(3)):
        mismatches.append(
            f"rebuilt shot_002 live={rebuilt_shot_two['location']} "
            f"expected={expected_shot_two}")

    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "manifest": manifest,
        "live": {
            "shot_one": shot_one,
            "shot_one_mid": shot_one_mid,
            "shot_one_last": shot_one_last,
            "shot_two": shot_two,
            "shot_two_last": shot_two_last,
        },
        "world_state": world,
        "scene_current": {
            "before_corruption": current_before,
            "without_shot_position_keys": current_without_keys,
            "ensure_after_stale": ensured,
            "after_rebuild": current_after_rebuild,
            "rebuilt_shot_two": rebuilt_shot_two,
        },
        "mismatches": mismatches,
    }
    (out_dir / "coarse_local_staging_probe.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": not mismatches, "checks": payload}


def main() -> int:
    argv = list(sys.argv)
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    out_dir = ROOT / "docs" / "evidence" / "20261021-coarse-local-staging-probe"
    for index, item in enumerate(argv):
        if item == "--out" and index + 1 < len(argv):
            out_dir = Path(argv[index + 1])
            break
    try:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        RESULTS["coarse_local_staging_probe"] = run_probe(out_dir)
    except Exception as exc:  # noqa: BLE001
        RESULTS["coarse_local_staging_probe"] = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "trace": traceback.format_exc(limit=5),
        }

    passed = [name for name, value in RESULTS.items() if value.get("ok")]
    failed = [name for name, value in RESULTS.items() if not value.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS},
        ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
