"""Blender probe: an evidence best must restore the live Blockout world."""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402

from block_director.contracts.audit import canonical_fingerprint  # noqa: E402
from block_director.contracts.blockout import (  # noqa: E402
    manifest_fingerprint,
)
from block_director.contracts.coarse_reference import (  # noqa: E402
    coarse_reference_content_fingerprint,
)
from block_director.contracts.evidence import (  # noqa: E402
    EvidenceError,
    EvidenceStore,
    ShotEvidence,
)
from block_director.contracts.world_state import (  # noqa: E402
    world_state_fingerprint,
)
from block_director.layer3_engine.evidence_restore import (  # noqa: E402
    restore_evidence_version,
)
from block_director.layer3_engine.scene_sync import (  # noqa: E402
    is_user_animated,
    mark_user_animated,
)
from block_director.utils.threading_guard import (  # noqa: E402
    capture_main_thread,
)

RESULTS: dict = {}


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "trace": traceback.format_exc(limit=4),
        }


def _fixture(
    *,
    include_shot_states: bool = False,
    corrupt_shot_states: bool = False,
):
    manifest = {
        "schema_version": "blockout-manifest/v1",
        "scene_id": "evidence-restore",
        "primitives": [
            {
                "id": "char_jia",
                "kind": "character",
                "source": {"type": "character", "id": "甲"},
                "position": {"x": 0.0, "y": 0.0, "z": 0.0},
                "size": {"x": 0.6, "y": 0.6, "z": 1.7},
                "z_anchor": "foot",
                "color": "#8899aa",
            },
            {
                "id": "prop_coin",
                "kind": "prop",
                "source": {"type": "prop", "id": "gold_coin"},
                "position": {"x": 1.0, "y": 0.0, "z": 0.8},
                "size": {"x": 0.2, "y": 0.2, "z": 0.2},
                "z_anchor": "center",
                "color": "#aa8844",
            },
            {
                "id": "anchor_mark",
                "kind": "anchor",
                "source": {"type": "anchor", "id": "A"},
                "position": {"x": -1.0, "y": 1.0, "z": 0.2},
                "size": {"x": 0.3, "y": 0.3, "z": 0.3},
                "z_anchor": "center",
                "color": "#999999",
            },
        ],
        "cameras": [{
            "shot_id": "shot_001",
            "camera_id": "cam_shot_001",
            "position": [0.0, 3.0, 1.5],
            "target": [0.0, 0.0, 1.0],
            "lens_mm": 35.0,
            "movements": [],
            "start_frame": 1,
            "end_frame": 24,
        }],
        "shot_table": [{
            "shot_id": "shot_001",
            "order": 1,
            "character_ids": ["甲"],
            "prop_ids": ["gold_coin"],
            "shot_type": "MS",
        }],
    }
    world = {
        "schema_version": "runtime-world/v1",
        "characters": {
            "甲": {"position": [2.0, -1.0, 0.0], "facing": [1.0, 0.0, 0.0]},
        },
        "cameras": {
            "shot_001": {
                "position": [4.0, 5.0, 2.0],
                "target": [2.0, -1.0, 1.0],
                "lens_mm": 50.0,
            },
        },
        "props": {
            "gold_coin": {
                "position": [2.2, -0.8, 0.9],
                "rotation_z": 0.25,
            },
        },
        "anchors": {"A": {"position": [-2.0, 1.5, 0.2]}},
    }
    if include_shot_states:
        shot_state = {
            "frame": 1,
            "characters": {
                "甲": {
                    "position": (
                        [9.0, 9.0, 0.0]
                        if corrupt_shot_states else [2.0, -1.0, 0.0]
                    ),
                    "facing": [1.0, 0.0, 0.0],
                },
            },
            "cameras": {
                "shot_001": {
                    "position": [4.0, 5.0, 2.0],
                    "target": [2.0, -1.0, 1.0],
                    "lens_mm": 50.0,
                },
            },
            "props": {
                "gold_coin": {
                    "position": [2.2, -0.8, 0.9],
                    "rotation_z": 0.25,
                },
            },
            "anchors": {"A": {"position": [-2.0, 1.5, 0.2]}},
        }
        world["shot_states"] = {"shot_001": shot_state}
    reference = {"scene_id": "evidence-restore"}
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
    }
    scene_content = canonical_fingerprint({
        "reference": reference,
        "manifest": manifest,
        "world_state": world,
    })
    observation_id = "obs-" + canonical_fingerprint([
        "physical-restore-probe",
        scene_content,
    ])
    basis = {
        "observation_id": observation_id,
        "bundle_fingerprint": canonical_fingerprint({
            "observation_id": observation_id,
            "reference": reference,
            "manifest": manifest,
            "report": report,
            "world_state": world,
        }),
        "reference_fingerprint": coarse_reference_content_fingerprint(reference),
        "manifest_fingerprint": manifest_fingerprint(manifest),
        "report_fingerprint": canonical_fingerprint(report),
        "world_state_fingerprint": world_state_fingerprint(world),
        "scene_content_fingerprint": scene_content,
    }
    store = EvidenceStore(run_id="probe", scene_id="evidence-restore")
    store.append(ShotEvidence.create(
        run_id="probe",
        scene_id="evidence-restore",
        shot_id="shot_001",
        version=0,
        parent_version=None,
        reason="probe",
        created_at="2026-10-21T00:00:00Z",
        plan={"shot": {"shot_id": "shot_001"}},
        shot_contract={
            "shot_id": "shot_001",
            "shot_type": "MS",
            "intent": "physical restore probe",
        },
        reference=reference,
        manifest=manifest,
        world_state=world,
        shot_slice={"shot_id": "shot_001"},
        build={
            "status": "probe-fixture",
            "object_count": 4,
            "manifest_fingerprint": basis["manifest_fingerprint"],
        },
        audit={
            "verdict": "pass",
            "report_fingerprint": basis["report_fingerprint"],
        },
        measurements={"composition": 82.0},
        score_breakdown={
            "composition": 82.0,
            "hard_error_count": 0,
        },
        gates={"shot_passed": True},
        hard_gates={
            "status": "pass",
            "failed": [],
            "evaluated": ["physical restore probe"],
        },
        absence_reasons={
            "frames": "physical restore probe does not render frame images",
            "sequence_gate":
                "sequence review is outside the physical restore probe",
            "semantic_review":
                "physical restore probe does not include a semantic review",
            "rag":
                "physical restore probe does not include RAG provenance",
            "correction_candidates":
                "physical restore probe does not model correction candidates",
            "applied_operations":
                "physical restore probe does not model applied operations",
            "remeasurement":
                "physical restore probe does not model a remeasurement",
            "disposition":
                "physical restore probe does not model a disposition",
        },
        basis_fingerprints=basis,
    ))
    store.mark_best("shot_001", 0)
    store.mark_adopted("shot_001", 0)
    return store, world


def _two_shot_fixture():
    manifest = {
        "schema_version": "blockout-manifest/v1",
        "scene_id": "evidence-restore-two-shots",
        "primitives": [{
            "id": "char_jia",
            "kind": "character",
            "source": {"type": "character", "id": "甲"},
            "position": {"x": 0.0, "y": 0.0, "z": 0.0},
            "size": {"x": 0.6, "y": 0.6, "z": 1.7},
            "z_anchor": "foot",
            "color": "#8899aa",
            "shot_positions": [
                {
                    "shot_id": "shot_001",
                    "position": {"x": 1.25, "y": 0.5, "z": 0.0},
                    "start_frame": 1,
                    "end_frame": 24,
                    "provenance": "agent_local_revision",
                    "reason": "first-shot staging",
                },
                {
                    "shot_id": "shot_002",
                    "position": {"x": 0.0, "y": 0.0, "z": 0.0},
                    "start_frame": 25,
                    "end_frame": 48,
                    "provenance": "plan_intent",
                    "reason": "",
                },
            ],
        }],
        "cameras": [
            {
                "shot_id": "shot_001",
                "camera_id": "cam_shot_001",
                "position": [0.0, 3.0, 1.5],
                "target": [1.25, 0.5, 1.0],
                "lens_mm": 35.0,
                "movements": [],
                "start_frame": 1,
                "end_frame": 24,
            },
            {
                "shot_id": "shot_002",
                "camera_id": "cam_shot_002",
                "position": [0.0, 3.0, 1.5],
                "target": [0.0, 0.0, 1.0],
                "lens_mm": 35.0,
                "movements": [],
                "start_frame": 25,
                "end_frame": 48,
            },
        ],
        "shot_table": [
            {
                "shot_id": "shot_001",
                "order": 1,
                "start_frame": 1,
                "end_frame": 24,
                "camera_id": "cam_shot_001",
                "character_ids": ["甲"],
                "prop_ids": [],
                "shot_type": "MS",
            },
            {
                "shot_id": "shot_002",
                "order": 2,
                "start_frame": 25,
                "end_frame": 48,
                "camera_id": "cam_shot_002",
                "character_ids": ["甲"],
                "prop_ids": [],
                "shot_type": "MS",
            },
        ],
    }
    camera_states = {
        "shot_001": {
            "position": [0.0, 3.0, 1.5],
            "target": [1.25, 0.5, 1.0],
            "lens_mm": 35.0,
        },
        "shot_002": {
            "position": [0.0, 3.0, 1.5],
            "target": [0.0, 0.0, 1.0],
            "lens_mm": 35.0,
        },
    }
    shot_one_character = {
        "position": [1.25, 0.5, 0.85],
        "facing": [0.0, 1.0, 0.0],
    }
    shot_two_character = {
        "position": [0.0, 0.0, 0.85],
        "facing": [0.0, 1.0, 0.0],
    }
    world = {
        "schema_version": "runtime-world/v1",
        "characters": {"甲": dict(shot_one_character)},
        "cameras": camera_states,
        "props": {},
        "anchors": {},
        "shot_states": {
            "shot_001": {
                "frame": 1,
                "characters": {"甲": dict(shot_one_character)},
                "cameras": camera_states,
                "props": {},
                "anchors": {},
            },
            "shot_002": {
                "frame": 25,
                "characters": {"甲": dict(shot_two_character)},
                "cameras": camera_states,
                "props": {},
                "anchors": {},
            },
        },
    }
    reference = {"scene_id": "evidence-restore-two-shots"}
    report = {
        "schema_version": "blockout-report/v1",
        "manifest_fingerprint": manifest_fingerprint(manifest),
        "verdict": "pass",
        "findings": [],
        "checks": [
            {
                "check_id": "composition",
                "shot_id": "shot_001",
                "actual": 82.0,
                "threshold": 80.0,
                "verdict": "pass",
            },
            {
                "check_id": "composition",
                "shot_id": "shot_002",
                "actual": 84.0,
                "threshold": 80.0,
                "verdict": "pass",
            },
        ],
    }
    scene_content = canonical_fingerprint({
        "reference": reference,
        "manifest": manifest,
        "world_state": world,
    })
    observation_id = "obs-" + canonical_fingerprint([
        "physical-restore-two-shot-probe",
        scene_content,
    ])
    basis = {
        "observation_id": observation_id,
        "bundle_fingerprint": canonical_fingerprint({
            "observation_id": observation_id,
            "reference": reference,
            "manifest": manifest,
            "report": report,
            "world_state": world,
        }),
        "reference_fingerprint": coarse_reference_content_fingerprint(
            reference),
        "manifest_fingerprint": manifest_fingerprint(manifest),
        "report_fingerprint": canonical_fingerprint(report),
        "world_state_fingerprint": world_state_fingerprint(world),
        "scene_content_fingerprint": scene_content,
    }
    store = EvidenceStore(
        run_id="probe",
        scene_id="evidence-restore-two-shots",
    )
    store.append(ShotEvidence.create(
        run_id="probe",
        scene_id="evidence-restore-two-shots",
        shot_id="shot_001",
        version=0,
        parent_version=None,
        reason="two-shot physical best",
        created_at="2026-10-21T00:00:00Z",
        plan={"shots": [
            {"shot_id": "shot_001"},
            {"shot_id": "shot_002"},
        ]},
        shot_contract={
            "shot_id": "shot_001",
            "shot_type": "MS",
            "intent": "two-shot restore probe",
        },
        reference=reference,
        manifest=manifest,
        world_state=world,
        shot_slice={"shot_id": "shot_001", "also_covers": ["shot_002"]},
        build={
            "status": "probe-fixture",
            "object_count": 5,
            "manifest_fingerprint": basis["manifest_fingerprint"],
        },
        audit={
            "verdict": "pass",
            "report_fingerprint": basis["report_fingerprint"],
        },
        measurements={"composition": 82.0},
        score_breakdown={
            "composition": 82.0,
            "hard_error_count": 0,
        },
        gates={"shot_passed": True},
        hard_gates={
            "status": "pass",
            "failed": [],
            "evaluated": ["two-shot physical restore probe"],
        },
        absence_reasons={
            "frames": "two-shot restore probe does not render images",
            "sequence_gate":
                "sequence review is outside the physical restore probe",
            "semantic_review":
                "two-shot restore probe has no semantic review",
            "rag": "two-shot restore probe has no RAG provenance",
            "correction_candidates":
                "two-shot restore probe has no correction candidates",
            "applied_operations":
                "two-shot restore probe has no applied operations",
            "remeasurement":
                "two-shot restore probe has no remeasurement",
            "disposition":
                "two-shot restore probe has no disposition",
        },
        basis_fingerprints=basis,
    ))
    store.mark_best("shot_001", 0)
    store.mark_adopted("shot_001", 0)
    return store, world


def t_restore_rebuilds_and_recovers_live_world():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    store, expected = _fixture()

    first = restore_evidence_version(store, "shot_001")

    char = bpy.data.objects["BD_Blockout_char_jia"]
    char.location = (-9.0, -9.0, 0.0)
    bpy.context.view_layer.update()
    second = restore_evidence_version(store, "shot_001")

    return {
        "ok": first["ok"] and second["ok"]
        and first["world_state_fingerprint"]
        == second["world_state_fingerprint"]
        and tuple(round(v, 4) for v in char.location) == (2.0, -1.0, 0.0)
        and set(second["restored"]) == {
            "character:甲", "prop:gold_coin", "camera:shot_001", "anchor:A"},
        "first": first,
        "second": second,
        "live_character": list(char.location),
        "expected_world": expected,
    }


def t_restore_rebuilds_two_shot_position_keyframes():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    store, expected = _two_shot_fixture()

    first = restore_evidence_version(store, "shot_001")
    scene = bpy.context.scene
    char = bpy.data.objects["BD_Blockout_char_jia"]

    char.animation_data_clear()
    for frame, position in (
        (1, (-9.0, -8.0, 0.85)),
        (25, (8.0, 9.0, 0.85)),
    ):
        scene.frame_set(frame)
        char.location = position
        char.keyframe_insert(data_path="location", frame=frame)
    bpy.context.view_layer.update()

    def live_at(frame):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        live = bpy.data.objects["BD_Blockout_char_jia"]
        return [round(float(value), 4)
                for value in live.matrix_world.translation]

    corrupted = {"shot_001": live_at(1), "shot_002": live_at(25)}
    second = restore_evidence_version(store, "shot_001")
    restored = {"shot_001": live_at(1), "shot_002": live_at(25)}
    wanted = expected["shot_states"]
    expected_live = {
        "shot_001": wanted["shot_001"]["characters"]["甲"]["position"],
        "shot_002": wanted["shot_002"]["characters"]["甲"]["position"],
    }
    return {
        "ok": first["ok"] and second["ok"]
        and corrupted["shot_001"] != expected_live["shot_001"]
        and corrupted["shot_002"] != expected_live["shot_002"]
        and restored == expected_live
        and second["world_state_comparison"]["shot_states"] == "strict",
        "first": first,
        "corrupted": corrupted,
        "restored": restored,
        "expected": expected_live,
        "second": second,
    }


def t_restore_blocks_on_user_animated_objects():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    store, _expected = _fixture()
    restore_evidence_version(store, "shot_001")
    char = bpy.data.objects["BD_Blockout_char_jia"]
    mark_user_animated(char)
    char.location = (-4.0, -4.0, 0.0)
    bpy.context.view_layer.update()
    before = tuple(round(v, 4) for v in char.location)

    blocked = ""
    try:
        restore_evidence_version(store, "shot_001")
    except EvidenceError as exc:
        blocked = str(exc)

    after = tuple(round(v, 4) for v in char.location)
    return {
        "ok": "user" in blocked.lower()
        and "char_jia" in blocked
        and is_user_animated(char)
        and before == after == (-4.0, -4.0, 0.0),
        "blocked": blocked,
        "before": before,
        "after": after,
        "still_user_animated": is_user_animated(char),
    }


def t_restore_rejects_corrupt_modern_shot_states():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    store, _expected = _fixture(
        include_shot_states=True,
        corrupt_shot_states=True,
    )

    blocked = ""
    try:
        restore_evidence_version(store, "shot_001")
    except EvidenceError as exc:
        blocked = str(exc)

    return {
        "ok": "shot_states" in blocked and "does not match evidence" in blocked,
        "blocked": blocked,
        "character_exists": (
            bpy.data.objects.get("BD_Blockout_char_jia") is not None),
    }


def main() -> int:
    capture_main_thread()
    check("restore_rebuilds_and_recovers_live_world",
          t_restore_rebuilds_and_recovers_live_world)
    check("restore_rebuilds_two_shot_position_keyframes",
          t_restore_rebuilds_two_shot_position_keyframes)
    check("restore_blocks_on_user_animated_objects",
          t_restore_blocks_on_user_animated_objects)
    check("restore_rejects_corrupt_modern_shot_states",
          t_restore_rejects_corrupt_modern_shot_states)
    failed = [name for name, value in RESULTS.items()
              if not value.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": [k for k in RESULTS if k not in failed],
         "failed": failed, "checks": RESULTS},
        ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
