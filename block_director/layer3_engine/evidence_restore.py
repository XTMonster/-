"""Blender adapter for restoring one authoritative shot evidence version."""

from __future__ import annotations

from typing import Any, Dict, Mapping

from ..contracts.evidence import EvidenceError, EvidenceStore
from ..contracts.world_state import (
    normalize_world_state,
    world_state_fingerprint,
)
from ..utils.threading_guard import main_thread_only


def _world_state_diff(
    expected: Mapping[str, Any],
    observed: Mapping[str, Any],
) -> list[str]:
    differences: list[str] = []
    for section in ("characters", "cameras", "props", "anchors"):
        wanted = dict(expected.get(section) or {})
        actual = dict(observed.get(section) or {})
        for name in sorted(set(wanted) | set(actual)):
            if wanted.get(name) != actual.get(name):
                differences.append(
                    f"{section}.{name}: expected {wanted.get(name)!r}, "
                    f"observed {actual.get(name)!r}")
        if (world_state_fingerprint(wanted)
                != world_state_fingerprint(actual)):
            differences.append(
                f"{section}: canonical serialization differs")
    for key in sorted(set(expected) | set(observed)):
        if key in {"characters", "cameras", "props", "anchors"}:
            continue
        if expected.get(key) != observed.get(key):
            differences.append(
                f"{key}: expected {expected.get(key)!r}, "
                f"observed {observed.get(key)!r}")
    return differences


@main_thread_only("restore_evidence_version")
def restore_evidence_version(
    store: EvidenceStore,
    shot_id: str,
    version: int | None = None,
) -> Dict[str, Any]:
    """Rebuild the recorded Blockout scene and verify its live world state."""
    import bpy

    from ..utils.geometry import facing_to_rotation_z
    from .blockout_scene import BD_BLOCKOUT_PREFIX, ensure_blockout_scene
    from .scene_sync import is_user_animated
    from .world_state import collect_blockout_world_state

    selected = store.best_version(shot_id) if version is None else int(version)
    evidence = store.get(shot_id, selected)
    errors = evidence.verify_errors()
    if errors:
        raise EvidenceError(
            f"evidence {shot_id}@{selected} is not restorable: "
            + "; ".join(errors))
    protected = sorted(
        str(obj.name)
        for obj in bpy.data.objects
        if str(obj.name).startswith(BD_BLOCKOUT_PREFIX)
        and is_user_animated(obj)
    )
    if protected:
        raise EvidenceError(
            "automatic restore would overwrite user-owned animation: "
            + ", ".join(protected))
    build = ensure_blockout_scene(evidence.manifest, clear_scene=True)
    expected = normalize_world_state(dict(evidence.world_state))
    previous_frame = int(bpy.context.scene.frame_current)
    primitives = {
        str(item.get("id") or ""): item
        for item in (evidence.manifest.get("primitives") or [])
        if isinstance(item, Mapping) and item.get("id")
    }

    def object_for(source_type: str, source_id: str):
        for primitive_id, primitive in primitives.items():
            source = primitive.get("source")
            if not isinstance(source, Mapping):
                continue
            if (str(source.get("type") or "") == source_type
                    and str(source.get("id") or primitive_id) == source_id):
                return bpy.data.objects.get(
                    f"{BD_BLOCKOUT_PREFIX}{primitive_id}")
        return None

    notes: list[str] = []
    for name, state in dict(expected.get("characters") or {}).items():
        obj = object_for("character", str(name))
        if obj is None:
            raise EvidenceError(f"recorded character object is missing: {name}")
        obj.location = tuple(float(v) for v in state["position"])
        obj.rotation_euler = (
            0.0, 0.0,
            facing_to_rotation_z(tuple(float(v) for v in state["facing"])),
        )
        notes.append(f"character:{name}")
    for name, state in dict(expected.get("props") or {}).items():
        obj = object_for("prop", str(name))
        if obj is None:
            raise EvidenceError(f"recorded prop object is missing: {name}")
        obj.location = tuple(float(v) for v in state["position"])
        obj.rotation_euler[2] = float(state.get("rotation_z") or 0.0)
        notes.append(f"prop:{name}")
    cameras = {
        str(item.get("shot_id") or ""): item
        for item in (evidence.manifest.get("cameras") or [])
        if isinstance(item, Mapping) and item.get("shot_id")
    }
    for live_shot_id, state in dict(expected.get("cameras") or {}).items():
        camera = cameras.get(str(live_shot_id))
        if camera is None:
            raise EvidenceError(
                f"recorded camera is missing from manifest: {live_shot_id}")
        camera_id = str(
            camera.get("camera_id") or f"cam_{live_shot_id}")
        obj = bpy.data.objects.get(f"{BD_BLOCKOUT_PREFIX}{camera_id}")
        target = bpy.data.objects.get(
            f"{BD_BLOCKOUT_PREFIX}CamTarget_{live_shot_id}")
        if obj is None or target is None:
            raise EvidenceError(
                f"recorded camera objects are missing: {live_shot_id}")
        obj.location = tuple(float(v) for v in state["position"])
        target.location = tuple(float(v) for v in state["target"])
        obj.data.lens = float(state.get("lens_mm") or 50.0)
        notes.append(f"camera:{live_shot_id}")
    for name, state in dict(expected.get("anchors") or {}).items():
        obj = object_for("anchor", str(name))
        if obj is None:
            raise EvidenceError(f"recorded anchor object is missing: {name}")
        obj.location = tuple(float(v) for v in state["position"])
        notes.append(f"anchor:{name}")

    bpy.context.view_layer.update()
    recorded_shot_states = "shot_states" in expected
    shot_rows = sorted(
        (
            row for row in (evidence.manifest.get("shot_table") or [])
            if isinstance(row, Mapping)
        ),
        key=lambda row: (
            int(row.get("start_frame") or 1),
            int(row.get("order") or 0),
            str(row.get("shot_id") or ""),
        ),
    )
    verification_frame = (
        int(shot_rows[0].get("start_frame") or 1) if shot_rows else None)
    if recorded_shot_states and verification_frame is not None:
        #: A modern runtime world contains two different truths:
        #: one current-frame table and one table per shot.  Evaluate the stable
        #: per-shot truth at the first shot boundary so restoring the same
        #: evidence is deterministic regardless of where the user left the
        #: playhead.
        bpy.context.scene.frame_set(verification_frame)
        bpy.context.view_layer.update()
    try:
        observed = normalize_world_state(
            collect_blockout_world_state(evidence.manifest))
    finally:
        bpy.context.scene.frame_set(previous_frame)
        bpy.context.view_layer.update()
    observed_fp = world_state_fingerprint(observed)
    expected_fp = world_state_fingerprint(expected)
    differences: list[str] = []
    if recorded_shot_states:
        expected_shots = dict(expected.get("shot_states") or {})
        observed_shots = dict(observed.get("shot_states") or {})
        for recorded_shot in sorted(
                set(expected_shots) | set(observed_shots)):
            wanted = dict(expected_shots.get(recorded_shot) or {})
            actual = dict(observed_shots.get(recorded_shot) or {})
            differences.extend(
                f"shot_states.{recorded_shot}.{item}"
                for item in _world_state_diff(wanted, actual)
            )
    else:
        #: Historical evidence predates per-shot runtime tables.  Its only
        #: restorable physical truth is the current-frame table, so compare the
        #: complete legacy world exactly.
        comparison_observed = {
            key: value for key, value in observed.items()
            if key != "shot_states"
        }
        differences.extend(_world_state_diff(expected, comparison_observed))
    if differences:
        compared_fp = (
            world_state_fingerprint({"shot_states": observed.get(
                "shot_states") or {}})
            if recorded_shot_states else observed_fp
        )
        raise EvidenceError(
            "restored Blender world state does not match evidence "
            f"({compared_fp} != {expected_fp}): "
            + "; ".join(differences or ["unknown world-state difference"]))
    return {
        "ok": True,
        "shot_id": shot_id,
        "version": selected,
        "evidence_digest": evidence.digest,
        "world_state_fingerprint": observed_fp,
        "world_state_comparison": {
            "shot_states": (
                "strict" if recorded_shot_states
                else "not_recorded_legacy_evidence"),
            "verification_frame": verification_frame,
            "current_frame": previous_frame,
        },
        "restored": notes,
        "build": build,
    }


__all__ = ["restore_evidence_version"]
