"""Blender-backed, per-shot session for the detail pipeline.

The pure revision loop owns quality decisions.  This adapter owns the physical
scene: it prepares the frozen blockout, observes exactly one shot at a time,
records immutable evidence, and later applies or restores only that shot's
state.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping

from ..cinema.evidence_builder import build_detail_shot_evidence
from ..contracts.audit import canonical_fingerprint
from ..contracts.evidence import EvidenceStore, ShotEvidence
from ..contracts.observation import describe_frame_record
from ..contracts.observation import ObservationBundle, build_observation_bundle
from ..contracts.quality import blockout_quality_report
from ..contracts.tools import ACTION_TOOLS, SHOT_DRAFT_TOOL
from ..contracts.vlm_review import (
    VLM_REVIEW_SCHEMA_V2,
    disposition,
    frame_data_uri,
    review_shot,
)
from ..layer5_orchestrator.correction_candidates import (
    build_correction_candidates,
)
from ..utils.threading_guard import main_thread_only


def _write_json_atomic(payload: Mapping[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(
        dict(payload), ensure_ascii=False, indent=2, allow_nan=False)
    temporary = ""
    try:
        with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False) as handle:
            temporary = handle.name
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        if temporary:
            Path(temporary).unlink(missing_ok=True)
        raise
    return path


def _publish_frame_records(
    frame_records: list[Mapping[str, Any]],
    evidence_dir: Path,
) -> list[dict[str, Any]]:
    """Copy one observation's frames into its immutable evidence directory."""
    frames_dir = evidence_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    published: list[dict[str, Any]] = []
    filenames: set[str] = set()
    for raw in frame_records:
        row = copy.deepcopy(dict(raw))
        source = Path(str(row.get("png") or row.get("path") or ""))
        if not source.is_file():
            published.append(row)
            continue
        if source.name in filenames:
            raise ValueError(
                f"duplicate frame filename in observation: {source.name}")
        filenames.add(source.name)
        destination = frames_dir / source.name
        temporary = destination.with_name(f".{destination.name}.tmp")
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
        row["path"] = str(destination.resolve())
        row["png"] = str(destination.resolve())
        published.append(row)
    return published


def _published_frame_evidence(
    frame_records: list[Mapping[str, Any]],
    evidence_dir: Path,
) -> list[dict[str, Any]]:
    """Copy and then redigest files so evidence names the authoritative bytes."""
    published = _publish_frame_records(frame_records, evidence_dir)
    return [
        describe_frame_record({
            **dict(row),
            "path": str(row.get("path") or row.get("png") or ""),
        })
        for row in published
    ]


def _review_frame_records(
    frame_records: list[Mapping[str, Any]],
    shot_id: str,
) -> list[dict[str, Any]]:
    """Select exactly the raw first/middle/last files rendered this attempt."""
    by_phase = {
        str(row.get("phase") or ""): dict(row)
        for row in frame_records
        if isinstance(row, Mapping)
        and str(row.get("shot_id") or "") == str(shot_id)
    }
    return [
        {
            **by_phase[phase],
            "shot_id": str(shot_id),
            "phase": phase,
            "label": phase,
        }
        for phase in ("first", "middle", "last")
        if phase in by_phase
    ]


def _safe_vlm_report(record: Mapping[str, Any]) -> dict[str, Any]:
    """Strip staging paths; published frame evidence supplies final paths."""
    result = copy.deepcopy(dict(record))
    order = result.get("frame_order")
    if isinstance(order, list):
        for row in order:
            if isinstance(row, dict):
                row.pop("path", None)
                row.pop("png", None)
    rounds = result.get("rounds")
    if isinstance(rounds, list):
        result["rounds"] = [
            _safe_vlm_report(row)
            if isinstance(row, Mapping) else copy.deepcopy(row)
            for row in rounds
        ]
    return result


def _report_measurements(report: Mapping[str, Any], shot_id: str) -> dict[str, Any]:
    quality = blockout_quality_report(report)
    shot_quality = dict(
        (quality.get("shots") or {}).get(str(shot_id)) or {})
    checks = [
        copy.deepcopy(dict(row))
        for row in (report.get("checks") or [])
        if isinstance(row, Mapping)
        and str(row.get("shot_id") or "") == str(shot_id)
    ]
    findings = [
        copy.deepcopy(dict(row))
        for row in (report.get("findings") or [])
        if isinstance(row, Mapping)
        and str(row.get("shot_id") or "") == str(shot_id)
    ]
    composition = dict(shot_quality.get("composition") or {})
    return {
        "program_passed": (
            composition.get("status") in {"pass", "exempt"}
            and int(shot_quality.get("hard_error_count") or 0) == 0
        ),
        "program_score": composition.get("score"),
        "shot_quality": shot_quality,
        "checks": checks,
        "findings": findings,
        "report_fingerprint": canonical_fingerprint(dict(report)),
    }


def _shot_plan(plan: Any, shot_id: str) -> dict[str, Any]:
    rows = plan.get("shots") if isinstance(plan, Mapping) else getattr(
        plan, "shots", None)
    for row in rows or []:
        value = row if isinstance(row, Mapping) else getattr(
            row, "to_dict", lambda: {})()
        if str(value.get("shot_id") or "") == shot_id:
            return copy.deepcopy(dict(value))
    return {}


def _rotation_euler(value: Any) -> tuple[float, float, float]:
    if isinstance(value, Mapping):
        return (
            float(value.get("x") or 0.0),
            float(value.get("y") or 0.0),
            float(value.get("z") or 0.0),
        )
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        return tuple(float(item) for item in value[:3])
    return (0.0, 0.0, 0.0)


def _clear_keys_in_range(data_block: Any, start: int, end: int) -> int:
    animation = getattr(data_block, "animation_data", None)
    action = getattr(animation, "action", None) if animation is not None else None
    if action is None:
        return 0
    from ..utils.blender_compat import action_fcurves

    removed = 0
    for curve in action_fcurves(action):
        doomed = [
            point for point in curve.keyframe_points
            if start <= float(point.co.x) <= end
        ]
        for point in reversed(doomed):
            curve.keyframe_points.remove(point)
            removed += 1
        if doomed:
            curve.update()
    return removed


def _manifest_for_reference(
    reference: Mapping[str, Any],
    plan: Any,
) -> dict[str, Any]:
    from ..cinema.blockout import build_blockout_manifest

    return dict(build_blockout_manifest(design=reference, plan=plan))


def _target_world_state(
    world_state: Mapping[str, Any],
    *,
    plan: Any,
    manifest: Mapping[str, Any],
    shot_id: str,
    render_staging: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project live world tables onto exactly one shot's evidence scope."""
    full_shot_states = world_state.get("shot_states")
    shot_states = (
        copy.deepcopy(dict(full_shot_states))
        if isinstance(full_shot_states, Mapping) else {})
    state = (
        dict(shot_states.get(shot_id) or {})
        if isinstance(shot_states.get(shot_id), Mapping) else {})

    shot = _shot_plan(plan, shot_id)
    character_names = {
        str(name) for name in (shot.get("characters") or []) if str(name)
    }
    framing = shot.get("framing_target")
    if isinstance(framing, Mapping) and (
            str(framing.get("kind") or "") == "character"):
        ref = str(framing.get("ref") or "")
        if ref:
            character_names.add(ref)
    characters = {
        str(name): copy.deepcopy(value)
        for name, value in dict(state.get("characters") or {}).items()
        if str(name) in character_names
    }
    cameras = {
        shot_id: copy.deepcopy(state["cameras"][shot_id])
    } if isinstance(state.get("cameras"), Mapping) and shot_id in state["cameras"] else {}

    shot_row = next(
        (
            row for row in (manifest.get("shot_table") or [])
            if isinstance(row, Mapping)
            and str(row.get("shot_id") or "") == shot_id
        ),
        {},
    )
    prop_ids = {
        str(prop_id) for prop_id in (shot_row.get("prop_ids") or [])
        if str(prop_id)
    }
    props = {
        str(name): copy.deepcopy(value)
        for name, value in dict(state.get("props") or {}).items()
        if str(name) in prop_ids
    }
    anchors = copy.deepcopy(dict(state.get("anchors") or {}))
    targeted_state = {
        "frame": state.get("frame"),
        "characters": characters,
        "cameras": cameras,
        "props": props,
        "anchors": anchors,
    }
    result = {
        "schema_version": str(world_state.get("schema_version") or ""),
        "characters": characters,
        "cameras": cameras,
        "props": props,
        "anchors": anchors,
        "shot_states": {shot_id: targeted_state},
    }
    if render_staging and shot_id in render_staging:
        result["render_staging"] = {
            shot_id: copy.deepcopy(render_staging[shot_id])}
    return result


class DetailSceneSession:
    """Physical adapter consumed by :func:`run_detail_revision_loop`."""

    def __init__(
        self,
        *,
        baseline: Mapping[str, Any],
        plan: Any,
        out_dir: Path | str,
        run_id: str,
        scene_id: str,
        proposal_provider: Callable[..., Mapping[str, Any] | None] | None = None,
        vlm_review: Any = None,
        vlm_transport: Any = None,
        vlm_frame_dir: Path | str | None = None,
        vlm_timeout: float = 60.0,
    ) -> None:
        self.baseline = copy.deepcopy(dict(baseline))
        self.plan = copy.deepcopy(plan) if isinstance(plan, Mapping) else plan
        self.out_dir = Path(out_dir).resolve()
        self.run_id = str(run_id)
        self.scene_id = str(scene_id)
        self.reference = copy.deepcopy(
            dict(self.baseline.get("reference") or {}))
        self.manifest = copy.deepcopy(
            dict(self.baseline.get("manifest") or {}))
        provider = proposal_provider
        self.proposal_provider = (
            (lambda request: provider(request=request))
            if provider is not None else None
        )
        if vlm_review is None:
            from ..settings import get_config

            vlm_review = get_config().vlm_review
        self.vlm_review = vlm_review
        self.vlm_transport = vlm_transport
        self.vlm_frame_dir = (
            Path(vlm_frame_dir).resolve() if vlm_frame_dir else None)
        self.vlm_timeout = float(vlm_timeout)
        self._vlm_history: dict[str, list[dict[str, Any]]] = {}
        self.evidence_store = EvidenceStore(
            run_id=self.run_id, scene_id=self.scene_id)
        self._prepared = False

    @main_thread_only("DetailSceneSession.prepare")
    def prepare(self) -> dict[str, Any]:
        if not self.reference:
            raise ValueError("detail session baseline has no reference")
        if not self.manifest:
            raise ValueError("detail session baseline has no manifest")
        from .blockout_scene import ensure_blockout_scene

        build = ensure_blockout_scene(self.manifest, clear_scene=True)
        self._prepared = True
        return {
            "reference": copy.deepcopy(self.reference),
            "manifest": copy.deepcopy(self.manifest),
            "build": copy.deepcopy(build),
        }

    @main_thread_only("DetailSceneSession.observe")
    def observe(
        self,
        reference: Mapping[str, Any],
        shot_id: str,
    ) -> ObservationBundle:
        if not self._prepared:
            self.prepare()
        target_shot = str(shot_id)
        if not _shot_plan(self.plan, target_shot):
            raise ValueError(f"unknown detail shot: {target_shot}")

        from ..layer8_delivery.blockout_preview import render_blockout_preview
        from .world_state import collect_blockout_world_state

        manifest = copy.deepcopy(dict(self.manifest))
        attempt_root = self.out_dir / "observations" / target_shot
        attempt_root.mkdir(parents=True, exist_ok=True)
        staging_dir = attempt_root / ".staging"
        preview = render_blockout_preview(
            manifest,
            staging_dir,
            expected=self.plan,
            reference_json=reference,
            shot_ids=[target_shot],
        )
        report = copy.deepcopy(dict(preview.get("report") or {}))
        measurements = _report_measurements(report, target_shot)
        report["measurements"] = measurements
        live_world = collect_blockout_world_state(manifest)
        render_staging = preview.get("shot_staging") or {}
        world_state = _target_world_state(
            live_world,
            plan=self.plan,
            manifest=manifest,
            shot_id=target_shot,
            render_staging=render_staging,
        )
        preview_frames = list(preview.get("previews") or [])
        review_required = bool(
            getattr(self.vlm_review, "required", False))
        review_enabled = bool(
            getattr(self.vlm_review, "enabled", False))
        if review_required or review_enabled:
            vlm_review = self._review_observation(
                target_shot, preview_frames, measurements)
            report["vlm_review"] = _safe_vlm_report(vlm_review)
            report["vlm_review_required"] = review_required
            issues = (
                vlm_review.get("issues")
                if vlm_review.get("status") == "ok"
                else []
            )
            geometry_warnings = (
                report.get("guard_warnings")
                if isinstance(report.get("guard_warnings"), list)
                else []
            )
            report["correction_candidates"] = build_correction_candidates(
                geometry_warnings,
                issues or [],
                limit=3,
            )
        bundle = build_observation_bundle(
            reference=reference,
            manifest=manifest,
            report=report,
            world_state=world_state,
            evidence_dir=staging_dir,
            frame_records=preview_frames,
        )
        evidence_dir = attempt_root / bundle.observation_id
        published_frames = _published_frame_evidence(
            preview_frames, evidence_dir)
        bundle = build_observation_bundle(
            reference=reference,
            manifest=manifest,
            report=report,
            world_state=world_state,
            evidence_dir=evidence_dir,
            frame_records=published_frames,
        )
        bundle.write_atomic(evidence_dir / "observation.json")
        _write_json_atomic(bundle.reference, evidence_dir / "reference.json")
        _write_json_atomic(bundle.manifest, evidence_dir / "manifest.json")
        _write_json_atomic(bundle.world_state, evidence_dir / "world_state.json")
        return bundle

    def _review_observation(
        self,
        shot_id: str,
        frame_records: list[Mapping[str, Any]],
        measurements: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Run the configured semantic judge over this attempt's real frames."""
        if not bool(getattr(self.vlm_review, "enabled", False)):
            record = {
                "status": "skipped",
                "outcome": "disabled",
                "reason": "VLM review is required but disabled",
                "error": "",
                "attempts": 0,
                "schema": VLM_REVIEW_SCHEMA_V2,
            }
        elif self.vlm_transport is None:
            record = {
                "status": "skipped",
                "outcome": "unavailable",
                "reason": "VLM review is required but no transport is wired",
                "error": "vlm_transport is None",
                "attempts": 0,
                "schema": VLM_REVIEW_SCHEMA_V2,
            }
        else:
            frames = _review_frame_records(frame_records, shot_id)
            frame_order = [
                describe_frame_record(row) for row in frames
            ]
            shot = _shot_plan(self.plan, shot_id)
            subjects = tuple(
                str(name) for name in (shot.get("characters") or [])
                if str(name)
            )
            tools = ACTION_TOOLS + (SHOT_DRAFT_TOOL,)
            image_frames = [
                (
                    str(row.get("label") or row.get("phase") or ""),
                    frame_data_uri(Path(str(
                        row.get("path") or row.get("png") or ""))),
                )
                for row in frames
            ]
            record = review_shot(
                self.vlm_transport,
                shot_id=shot_id,
                frames=image_frames,
                intent=str(shot.get("intent") or ""),
                composition=(
                    dict(shot.get("composition") or {})
                    if isinstance(shot.get("composition"), Mapping) else {}
                ),
                timeout=self.vlm_timeout,
                subjects=subjects,
                tools=tools,
                frame_records=frame_order,
                measurements=measurements,
            )
        round_no = len(self._vlm_history.get(shot_id) or []) + 1
        record["round"] = round_no
        self._vlm_history.setdefault(shot_id, []).append(
            copy.deepcopy(record))
        latest = copy.deepcopy(record)
        latest["rounds"] = copy.deepcopy(self._vlm_history[shot_id])
        latest["disposition"] = disposition(self._vlm_history[shot_id])
        return latest

    def record_evidence(
        self,
        shot_id: str,
        observation: ObservationBundle | Mapping[str, Any],
        version: Mapping[str, Any],
    ) -> ShotEvidence:
        bundle = (
            observation if isinstance(observation, ObservationBundle)
            else ObservationBundle.from_dict(observation)
        )
        if not bundle.complete:
            raise ValueError(
                "incomplete observations cannot become authoritative evidence")
        record = build_detail_shot_evidence(
            run_id=self.run_id,
            scene_id=self.scene_id,
            plan=self.plan,
            shot_id=str(shot_id),
            observation=bundle,
            version=version,
            detail_reason=str(version.get("reason") or (
                "detail_initial_observation"
                if int(version.get("version") or 0) == 0
                else "detail_revision_candidate")),
        )
        self.evidence_store.consider_candidate(record)
        self.evidence_store.save_atomic(
            self.out_dir / "evidence_store.json")
        return record

    @main_thread_only("DetailSceneSession.apply")
    def apply(
        self,
        reference: Mapping[str, Any],
        shot_id: str,
        *,
        mode: str = "revision",
    ) -> None:
        """Apply one shot's exact camera and staging to the live Blockout."""
        import bpy

        from ..cinema.detail_blocking import reference_scope_review
        from ..cinema.detail_loop import DetailLoopBlocked
        from ..contracts.blockout import (
            BLOCKOUT_MANIFEST_SCHEMA_VERSION,
            manifest_fingerprint,
        )
        from .blockout_scene import (
            BD_BLOCKOUT_PREFIX,
            BLOCKOUT_MANIFEST_FINGERPRINT_PROP,
            _shot_position_origin,
        )
        from .scene_sync import is_user_animated

        target_shot = str(shot_id)
        scope_findings = reference_scope_review(
            previous=self.reference,
            candidate=reference,
            shot_id=target_shot,
            mode=mode,
        )
        if scope_findings:
            raise DetailLoopBlocked(
                f"detail revision for {target_shot} escaped its shot scope",
                code="detail_scope_violation",
                details={
                    "shot_id": target_shot,
                    "findings": scope_findings,
                },
            )
        updated_manifest = _manifest_for_reference(reference, self.plan)
        camera_row = next(
            (
                row for row in (updated_manifest.get("cameras") or [])
                if isinstance(row, Mapping)
                and str(row.get("shot_id") or "") == target_shot
            ),
            None,
        )
        shot_row = next(
            (
                row for row in (updated_manifest.get("shot_table") or [])
                if isinstance(row, Mapping)
                and str(row.get("shot_id") or "") == target_shot
            ),
            None,
        )
        if camera_row is None or shot_row is None:
            raise ValueError(f"detail apply could not resolve shot {target_shot}")

        start = int(camera_row.get("start_frame") or shot_row.get(
            "start_frame") or 1)
        end = int(camera_row.get("end_frame") or shot_row.get(
            "end_frame") or start)
        camera_id = str(
            camera_row.get("camera_id") or f"cam_{target_shot}")
        camera = bpy.data.objects.get(
            f"{BD_BLOCKOUT_PREFIX}{camera_id}")
        target = bpy.data.objects.get(
            f"{BD_BLOCKOUT_PREFIX}CamTarget_{target_shot}")
        if camera is None or target is None:
            raise ValueError(
                f"detail apply is missing camera objects for {target_shot}")

        target_prop_ids = {
            str(value)
            for value in (shot_row.get("prop_ids") or [])
            if str(value)
        }
        target_plan = _shot_plan(self.plan, target_shot)
        target_framing = target_plan.get("framing_target")
        if isinstance(target_framing, Mapping) \
                and str(target_framing.get("kind") or "") == "prop":
            framing_ref = str(target_framing.get("ref") or "")
            if framing_ref:
                target_prop_ids.add(framing_ref)

        protected: list[Any] = [camera, target, camera.data]
        for primitive in updated_manifest.get("primitives") or []:
            if not isinstance(primitive, Mapping):
                continue
            if primitive.get("kind") == "character":
                applies_to_target = any(
                    isinstance(row, Mapping)
                    and str(row.get("shot_id") or "") == target_shot
                    for row in (primitive.get("shot_positions") or [])
                )
            else:
                source = primitive.get("source") or {}
                applies_to_target = (
                    primitive.get("kind") == "prop"
                    and str(source.get("id") or "") in target_prop_ids
                )
            if not applies_to_target:
                continue
            obj = bpy.data.objects.get(
                f"{BD_BLOCKOUT_PREFIX}{primitive.get('id') or ''}")
            if obj is not None:
                protected.append(obj)
        guarded = sorted({
            str(getattr(obj, "name", "") or "")
            for obj in protected
            if obj is not None and is_user_animated(obj)
        })
        if guarded:
            raise DetailLoopBlocked(
                "automatic detail repair would overwrite user-owned animation: "
                + ", ".join(guarded),
                code="user_animation_conflict",
                details={"shot_id": target_shot, "objects": guarded},
            )

        scene = bpy.context.scene
        previous_frame = int(scene.frame_current)
        previous_start = int(scene.frame_start)
        previous_end = int(scene.frame_end)
        touched: list[str] = []
        try:
            scene.frame_start = start
            scene.frame_end = end
            for data_block in (camera, target, camera.data):
                _clear_keys_in_range(data_block, start, end)
            camera.location = tuple(
                float(value) for value in camera_row.get("position") or ())
            target.location = tuple(
                float(value) for value in camera_row.get("target") or ())
            camera.data.lens = float(camera_row.get("lens_mm") or 50.0)
            for frame in (start, end):
                scene.frame_set(frame)
                camera.location = tuple(
                    float(value)
                    for value in camera_row.get("position") or ())
                target.location = tuple(
                    float(value)
                    for value in camera_row.get("target") or ())
                camera.data.lens = float(
                    camera_row.get("lens_mm") or 50.0)
                camera.keyframe_insert(data_path="location", frame=frame)
                target.keyframe_insert(data_path="location", frame=frame)
                camera.data.keyframe_insert(data_path="lens", frame=frame)
            touched.append(f"camera:{target_shot}")

            from .cinema_engine.camera_motion import apply_camera_movement

            for raw_movement in camera_row.get("movements") or []:
                if not isinstance(raw_movement, Mapping):
                    raise ValueError(
                        f"camera movement for {target_shot} must be an object")
                movement_start = max(
                    start,
                    int(raw_movement.get("start_frame") or start),
                )
                movement_end = min(
                    end,
                    int(raw_movement.get("end_frame") or end),
                )
                if movement_end < movement_start:
                    raise ValueError(
                        f"camera movement for {target_shot} falls outside "
                        f"its shot range")
                scene.frame_set(movement_start)
                bpy.context.view_layer.update()
                apply_camera_movement(
                    camera,
                    target,
                    str(raw_movement.get("type") or ""),
                    float(raw_movement.get("amount") or 0.0),
                    movement_start,
                    movement_end,
                )

            for primitive in updated_manifest.get("primitives") or []:
                if not isinstance(primitive, Mapping) \
                        or primitive.get("kind") != "character":
                    continue
                position_row = next(
                    (
                        row
                        for row in (primitive.get("shot_positions") or [])
                        if isinstance(row, Mapping)
                        and str(row.get("shot_id") or "") == target_shot
                    ),
                    None,
                )
                if position_row is None:
                    continue
                object_name = (
                    f"{BD_BLOCKOUT_PREFIX}{primitive.get('id') or ''}")
                obj = bpy.data.objects.get(object_name)
                if obj is None:
                    raise ValueError(
                        f"detail apply is missing character object "
                        f"{object_name}")
                origin = _shot_position_origin(
                    primitive, position_row.get("position") or {})
                _clear_keys_in_range(obj, start, end)
                for frame in (start, end):
                    scene.frame_set(frame)
                    obj.location = origin
                    obj.keyframe_insert(data_path="location", frame=frame)
                source = primitive.get("source") or {}
                touched.append(
                    f"character:{source.get('id') or primitive.get('id')}")

            reference_props = {
                str(row.get("id") or ""): row
                for row in (reference.get("props") or [])
                if isinstance(row, Mapping)
            }
            for primitive in updated_manifest.get("primitives") or []:
                if not isinstance(primitive, Mapping) \
                        or primitive.get("kind") != "prop":
                    continue
                source = primitive.get("source") or {}
                prop_id = str(source.get("id") or "")
                if prop_id not in target_prop_ids:
                    continue
                prop = reference_props.get(prop_id)
                if not isinstance(prop, Mapping):
                    raise ValueError(
                        f"detail apply cannot resolve target prop {prop_id}")
                object_name = (
                    f"{BD_BLOCKOUT_PREFIX}{primitive.get('id') or ''}")
                obj = bpy.data.objects.get(object_name)
                if obj is None:
                    raise ValueError(
                        f"detail apply is missing prop object {object_name}")
                origin = _shot_position_origin(
                    primitive, primitive.get("position") or {})
                rotation = _rotation_euler(prop.get("rotation"))
                _clear_keys_in_range(obj, start, end)
                for frame in (start, end):
                    scene.frame_set(frame)
                    obj.location = origin
                    obj.rotation_euler = rotation
                    obj.keyframe_insert(data_path="location", frame=frame)
                    obj.keyframe_insert(
                        data_path="rotation_euler", frame=frame)
                touched.append(f"prop:{prop_id}")
        finally:
            scene.frame_set(previous_frame)
            scene.frame_start = previous_start
            scene.frame_end = previous_end
            bpy.context.view_layer.update()

        scene[BLOCKOUT_MANIFEST_FINGERPRINT_PROP] = manifest_fingerprint(
            updated_manifest)
        if updated_manifest.get("schema_version") is None:
            updated_manifest["schema_version"] = (
                BLOCKOUT_MANIFEST_SCHEMA_VERSION)
        self.reference = copy.deepcopy(dict(reference))
        self.manifest = updated_manifest
        self._last_apply = {
            "shot_id": target_shot,
            "mode": mode,
            "frame_range": [start, end],
            "touched": touched,
        }

    @main_thread_only("DetailSceneSession.restore")
    def restore(
        self,
        reference: Mapping[str, Any],
        shot_id: str,
    ) -> dict[str, Any]:
        """Restore one shot from its retained reference and verify live state."""
        target_shot = str(shot_id)
        self.apply(reference, target_shot, mode="restore")
        from ..cinema.detail_loop import DetailLoopBlocked
        from ..contracts.world_state import world_state_fingerprint
        from .blockout_scene import _shot_position_origin
        from .world_state import collect_blockout_world_state

        observed = _target_world_state(
            collect_blockout_world_state(self.manifest),
            plan=self.plan,
            manifest=self.manifest,
            shot_id=target_shot,
        )
        camera_row = next(
            (
                row for row in (self.manifest.get("cameras") or [])
                if isinstance(row, Mapping)
                and str(row.get("shot_id") or "") == target_shot
            ),
            None,
        )
        target_state = (
            (observed.get("shot_states") or {}).get(target_shot) or {})
        actual_camera = (target_state.get("cameras") or {}).get(target_shot)
        expected_camera = (
            {
                "position": [
                    round(float(value), 6)
                    for value in camera_row.get("position") or ()
                ],
                "target": [
                    round(float(value), 6)
                    for value in camera_row.get("target") or ()
                ],
                "lens_mm": round(float(camera_row.get("lens_mm") or 50.0), 3),
            }
            if isinstance(camera_row, Mapping) else {}
        )
        differences: list[str] = []
        if not isinstance(actual_camera, Mapping):
            differences.append(f"camera.{target_shot} was not collected")
        elif actual_camera != expected_camera:
            differences.append(
                f"camera.{target_shot}: expected {expected_camera!r}, "
                f"observed {actual_camera!r}")

        actual_characters = dict(target_state.get("characters") or {})
        for primitive in self.manifest.get("primitives") or []:
            if not isinstance(primitive, Mapping) \
                    or primitive.get("kind") != "character":
                continue
            position_row = next(
                (
                    row
                    for row in (primitive.get("shot_positions") or [])
                    if isinstance(row, Mapping)
                    and str(row.get("shot_id") or "") == target_shot
                ),
                None,
            )
            if position_row is None:
                continue
            source = primitive.get("source") or {}
            name = str(source.get("id") or primitive.get("id") or "")
            expected_origin = [
                round(float(value), 6)
                for value in _shot_position_origin(
                    primitive, position_row.get("position") or {})
            ]
            actual = dict(actual_characters.get(name) or {})
            if actual.get("position") != expected_origin:
                differences.append(
                    f"character.{name}: expected {expected_origin!r}, "
                    f"observed {actual.get('position')!r}")

        shot_row = next(
            (
                row for row in (self.manifest.get("shot_table") or [])
                if isinstance(row, Mapping)
                and str(row.get("shot_id") or "") == target_shot
            ),
            {},
        )
        target_prop_ids = {
            str(value)
            for value in (shot_row.get("prop_ids") or [])
            if str(value)
        }
        target_plan = _shot_plan(self.plan, target_shot)
        target_framing = target_plan.get("framing_target")
        if isinstance(target_framing, Mapping) \
                and str(target_framing.get("kind") or "") == "prop":
            framing_ref = str(target_framing.get("ref") or "")
            if framing_ref:
                target_prop_ids.add(framing_ref)
        reference_props = {
            str(row.get("id") or ""): row
            for row in (reference.get("props") or [])
            if isinstance(row, Mapping)
        }
        actual_props = dict(target_state.get("props") or {})
        for primitive in self.manifest.get("primitives") or []:
            if not isinstance(primitive, Mapping) \
                    or primitive.get("kind") != "prop":
                continue
            source = primitive.get("source") or {}
            prop_id = str(source.get("id") or "")
            if prop_id not in target_prop_ids:
                continue
            prop = reference_props.get(prop_id)
            if not isinstance(prop, Mapping):
                differences.append(
                    f"prop.{prop_id} is missing from the retained reference")
                continue
            expected_position = [
                round(float(value), 6)
                for value in _shot_position_origin(
                    primitive, primitive.get("position") or {})
            ]
            expected_rotation = _rotation_euler(prop.get("rotation"))
            actual = dict(actual_props.get(prop_id) or {})
            if actual.get("position") != expected_position:
                differences.append(
                    f"prop.{prop_id}.position: expected "
                    f"{expected_position!r}, observed "
                    f"{actual.get('position')!r}")
            if actual.get("rotation_z") != round(expected_rotation[2], 6):
                differences.append(
                    f"prop.{prop_id}.rotation_z: expected "
                    f"{round(expected_rotation[2], 6)!r}, observed "
                    f"{actual.get('rotation_z')!r}")
        if differences:
            raise DetailLoopBlocked(
                "detail restore did not reproduce the retained physical state: "
                + "; ".join(differences),
                code="physical_restore_mismatch",
                details={
                    "shot_id": target_shot,
                    "differences": differences,
                },
            )
        return {
            "ok": True,
            "shot_id": target_shot,
            "world_state_fingerprint": world_state_fingerprint(observed),
            "world_state": copy.deepcopy(observed),
            "apply": copy.deepcopy(getattr(self, "_last_apply", {})),
        }

    @main_thread_only("DetailSceneSession.review_sequence")
    def review_sequence(self, reference: Mapping[str, Any]) -> Mapping[str, Any]:
        """Review the live retained-best sequence without rendering again."""
        from ..contracts.coarse_reference import (
            coarse_reference_content_fingerprint,
        )
        from ..cinema.detail_loop import DetailLoopBlocked
        from ..layer8_delivery.blockout_sequence import (
            run_blockout_sequence_review,
        )

        if (coarse_reference_content_fingerprint(reference)
                != coarse_reference_content_fingerprint(self.reference)):
            raise DetailLoopBlocked(
                "detail sequence review received a reference that is not "
                "the retained live scene",
                code="sequence_reference_mismatch",
                details={
                    "expected": coarse_reference_content_fingerprint(
                        self.reference),
                    "received": coarse_reference_content_fingerprint(
                        reference),
                },
            )
        reviewed = run_blockout_sequence_review(
            self.manifest,
            self.out_dir / "sequence_review",
            render_video=False,
        )
        review = copy.deepcopy(dict(reviewed.get("review") or {}))
        review["playback"] = copy.deepcopy(reviewed.get("playback") or {})
        review["outputs"] = copy.deepcopy(reviewed.get("outputs") or {})
        return review


__all__ = ["DetailSceneSession"]
