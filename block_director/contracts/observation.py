"""Pure observation evidence bound to one rendered scene state."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .audit import canonical_fingerprint
from .blockout import manifest_fingerprint
from .coarse_reference import coarse_reference_content_fingerprint
from .world_state import normalize_world_state, world_state_fingerprint

OBSERVATION_SCHEMA_VERSION = "coarse-observation/v1"
FRAME_PHASES = ("first", "middle", "last")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pixel_sha256(path: Path) -> tuple[str, int, int]:
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow is required to decode frame evidence") from exc
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
        digest = hashlib.sha256(rgba.tobytes()).hexdigest()
        return digest, int(rgba.width), int(rgba.height)


def _json_safe(value: Any, field: str) -> None:
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} is not JSON-safe or contains non-finite values") from exc


def _encode_non_finite(
    value: Any,
    *,
    path: str,
) -> tuple[Any, list[str]]:
    """Return a JSON-safe copy while preserving where invalid floats occurred."""
    if isinstance(value, Mapping):
        result: dict[Any, Any] = {}
        errors: list[str] = []
        for key, item in value.items():
            normalized, item_errors = _encode_non_finite(
                item, path=f"{path}.{key}")
            result[key] = normalized
            errors.extend(item_errors)
        return result, errors
    if isinstance(value, (list, tuple)):
        result_list: list[Any] = []
        errors = []
        for index, item in enumerate(value):
            normalized, item_errors = _encode_non_finite(
                item, path=f"{path}[{index}]")
            result_list.append(normalized)
            errors.extend(item_errors)
        return result_list, errors
    if isinstance(value, float) and not math.isfinite(value):
        token = "NaN" if math.isnan(value) else (
            "Infinity" if value > 0 else "-Infinity")
        return {
            "$type": "non-finite-float",
            "value": token,
        }, [f"{path} contains non-finite float {token}"]
    return value, []


@dataclass(frozen=True)
class FrameEvidence:
    shot_id: str
    frame: int
    phase: str
    path: str
    file_sha256: str
    pixel_sha256: str
    width: int
    height: int
    file_bytes: int
    readable: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "shot_id": self.shot_id,
            "frame": self.frame,
            "phase": self.phase,
            "path": self.path,
            "file_sha256": self.file_sha256,
            "pixel_sha256": self.pixel_sha256,
            "width": self.width,
            "height": self.height,
            "file_bytes": self.file_bytes,
            "readable": self.readable,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FrameEvidence":
        return cls(
            shot_id=str(data.get("shot_id") or ""),
            frame=int(data.get("frame") or 0),
            phase=str(data.get("phase") or ""),
            path=str(data.get("path") or ""),
            file_sha256=str(data.get("file_sha256") or ""),
            pixel_sha256=str(data.get("pixel_sha256") or ""),
            width=int(data.get("width") or 0),
            height=int(data.get("height") or 0),
            file_bytes=int(data.get("file_bytes") or 0),
            readable=bool(data.get("readable")),
        )

    def verify_errors(self) -> list[str]:
        if not self.shot_id:
            return ["frame shot_id is missing"]
        if self.frame < 1:
            return [f"{self.shot_id}: frame must be >= 1"]
        if self.phase not in FRAME_PHASES:
            return [
                f"{self.shot_id}@{self.frame}: unknown frame phase "
                f"{self.phase!r}; expected one of first/middle/last"
            ]
        path = Path(self.path)
        if not path.is_file():
            return [f"{self.shot_id}@{self.frame}: missing frame {path}"]
        if not self.readable:
            return [f"{self.shot_id}@{self.frame}: frame was not readable"]
        try:
            file_digest = _file_sha256(path)
            pixel_digest, width, height = _pixel_sha256(path)
        except Exception as exc:  # noqa: BLE001 - file damage is evidence damage
            return [
                f"{self.shot_id}@{self.frame}: unreadable frame "
                f"({type(exc).__name__}: {exc})"
            ]
        errors: list[str] = []
        if file_digest != self.file_sha256:
            errors.append(f"{self.shot_id}@{self.frame}: file digest changed")
        if pixel_digest != self.pixel_sha256:
            errors.append(f"{self.shot_id}@{self.frame}: pixel digest changed")
        if (width, height) != (self.width, self.height):
            errors.append(
                f"{self.shot_id}@{self.frame}: dimensions changed "
                f"{self.width}x{self.height} -> {width}x{height}")
        if path.stat().st_size != self.file_bytes:
            errors.append(f"{self.shot_id}@{self.frame}: file size changed")
        return errors


@dataclass(frozen=True)
class ObservationBundle:
    """Report + manifest + world state + rendered frames from one attempt."""

    observation_id: str
    reference_fingerprint: str
    manifest_fingerprint: str
    report_fingerprint: str
    world_state_fingerprint: str
    bundle_fingerprint: str
    evidence_dir: str
    reference: Mapping[str, Any]
    manifest: Mapping[str, Any]
    report: Mapping[str, Any]
    world_state: Mapping[str, Any]
    frames: tuple[FrameEvidence, ...]
    static_errors: tuple[str, ...]
    complete_hint: bool
    schema_version: str = OBSERVATION_SCHEMA_VERSION

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "observation_id": self.observation_id,
            "reference_fingerprint": self.reference_fingerprint,
            "manifest_fingerprint": self.manifest_fingerprint,
            "report_fingerprint": self.report_fingerprint,
            "world_state_fingerprint": self.world_state_fingerprint,
            "evidence_dir": self.evidence_dir,
            "reference": self.reference,
            "manifest": self.manifest,
            "report": self.report,
            "world_state": self.world_state,
            "frames": [item.to_dict() for item in self.frames],
            "static_errors": list(self.static_errors),
            "complete_hint": self.complete_hint,
        }

    def verify_errors(self) -> list[str]:
        errors = list(self.static_errors)
        if self.schema_version != OBSERVATION_SCHEMA_VERSION:
            errors.append(f"unsupported observation schema: {self.schema_version}")
        computed_bundle = canonical_fingerprint(self._identity_payload())
        if self.bundle_fingerprint != computed_bundle:
            errors.append("observation bundle digest mismatch")
        if (self.reference_fingerprint
                != coarse_reference_content_fingerprint(self.reference)):
            errors.append("reference fingerprint mismatch")
        expected_manifest = manifest_fingerprint(self.manifest)
        if self.manifest_fingerprint != expected_manifest:
            errors.append("manifest fingerprint mismatch")
        report_manifest = str(self.report.get("manifest_fingerprint") or "")
        if report_manifest != expected_manifest:
            errors.append("report manifest_fingerprint mismatch")
        if self.report_fingerprint != canonical_fingerprint(self.report):
            errors.append("report fingerprint mismatch")
        if (self.world_state_fingerprint
                != world_state_fingerprint(self.world_state)):
            errors.append("world state fingerprint mismatch")
        for frame in self.frames:
            errors.extend(frame.verify_errors())
        try:
            _json_safe(self.to_payload(include_dynamic=False), "observation")
        except ValueError as exc:
            errors.append(f"observation is not serializable: {exc}")
        return errors

    @property
    def errors(self) -> tuple[str, ...]:
        return tuple(self.verify_errors())

    @property
    def complete(self) -> bool:
        return bool(self.complete_hint and not self.verify_errors())

    def verify(self) -> bool:
        return self.complete

    def to_payload(self, *, include_dynamic: bool = True) -> dict[str, Any]:
        payload = self._identity_payload()
        payload["bundle_fingerprint"] = self.bundle_fingerprint
        if include_dynamic:
            payload["complete"] = self.complete
            payload["errors"] = list(self.errors)
        return copy.deepcopy(payload)

    def to_dict(self) -> dict[str, Any]:
        return self.to_payload(include_dynamic=True)

    def write_atomic(self, path: Path | str) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".tmp")
        temporary.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2,
                       allow_nan=False),
            encoding="utf-8",
        )
        os.replace(temporary, target)
        return target

    @classmethod
    def load(cls, path: Path | str) -> "ObservationBundle":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, Mapping):
            raise ValueError("observation must be an object")
        bundle = cls.from_dict(data)
        if not bundle.verify():
            raise ValueError("observation verification failed: "
                             + "; ".join(bundle.verify_errors()))
        return bundle

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ObservationBundle":
        return cls(
            observation_id=str(data.get("observation_id") or ""),
            reference_fingerprint=str(
                data.get("reference_fingerprint") or ""),
            manifest_fingerprint=str(data.get("manifest_fingerprint") or ""),
            report_fingerprint=str(data.get("report_fingerprint") or ""),
            world_state_fingerprint=str(
                data.get("world_state_fingerprint") or ""),
            bundle_fingerprint=str(data.get("bundle_fingerprint") or ""),
            evidence_dir=str(data.get("evidence_dir") or ""),
            reference=copy.deepcopy(dict(data.get("reference") or {})),
            manifest=copy.deepcopy(dict(data.get("manifest") or {})),
            report=copy.deepcopy(dict(data.get("report") or {})),
            world_state=copy.deepcopy(dict(data.get("world_state") or {})),
            frames=tuple(
                FrameEvidence.from_dict(item)
                for item in (data.get("frames") or [])
                if isinstance(item, Mapping)
            ),
            static_errors=tuple(
                str(item) for item in (data.get("static_errors") or [])),
            complete_hint=bool(data.get("complete_hint")),
            schema_version=str(
                data.get("schema_version") or OBSERVATION_SCHEMA_VERSION),
        )

    @classmethod
    def from_payload(
        cls,
        *,
        reference: Mapping[str, Any],
        manifest: Mapping[str, Any],
        report: Mapping[str, Any],
        world_state: Mapping[str, Any],
        evidence_dir: Path | str,
        frame_records: Sequence[Mapping[str, Any]] | None = None,
        complete_hint: bool | None = None,
        require_frames: bool = False,
    ) -> "ObservationBundle":
        return build_observation_bundle(
            reference=reference,
            manifest=manifest,
            report=report,
            world_state=world_state,
            evidence_dir=evidence_dir,
            frame_records=frame_records,
            complete_hint=complete_hint,
            require_frames=require_frames,
        )


def _frame_evidence(item: Mapping[str, Any]) -> FrameEvidence:
    path = Path(str(item.get("png") or item.get("path") or "")).resolve()
    readable = False
    file_digest = ""
    pixel_digest = ""
    width = 0
    height = 0
    file_bytes = 0
    if path.is_file() and path.stat().st_size > 0:
        file_bytes = path.stat().st_size
        try:
            file_digest = _file_sha256(path)
            pixel_digest, width, height = _pixel_sha256(path)
            readable = True
        except Exception:  # noqa: BLE001 - retained as explicit unreadable evidence
            readable = False
    return FrameEvidence(
        shot_id=str(item.get("shot_id") or ""),
        frame=int(item.get("frame") or 0),
        phase=str(item.get("phase") or ""),
        path=str(path),
        file_sha256=file_digest,
        pixel_sha256=pixel_digest,
        width=width,
        height=height,
        file_bytes=file_bytes,
        readable=readable,
    )


def describe_frame_record(item: Mapping[str, Any]) -> dict[str, Any]:
    """Return digest-backed evidence for the exact image file on disk."""
    if not isinstance(item, Mapping):
        raise TypeError("frame record must be a mapping")
    return _frame_evidence(item).to_dict()


def build_observation_bundle(
    *,
    reference: Mapping[str, Any],
    manifest: Mapping[str, Any],
    report: Mapping[str, Any],
    world_state: Mapping[str, Any],
    evidence_dir: Path | str,
    frame_records: Sequence[Mapping[str, Any]] | None = None,
    complete_hint: bool | None = None,
    require_frames: bool = True,
) -> ObservationBundle:
    """Bind one report to its exact reference, manifest, world and frames."""
    if not isinstance(reference, Mapping):
        raise ValueError("reference must be a mapping")
    if not isinstance(manifest, Mapping):
        raise ValueError("manifest must be a mapping")
    if not isinstance(report, Mapping):
        raise ValueError("report must be a mapping")
    if not isinstance(world_state, Mapping):
        raise ValueError("world_state must be a mapping")

    static_errors: list[str] = []
    if frame_records is None:
        visual_states = report.get("visual_states")
        if not isinstance(visual_states, list):
            static_errors.append("report.visual_states must be a list")
            frame_records = []
        else:
            frame_records = [
                item for item in visual_states if isinstance(item, Mapping)]
            if len(frame_records) != len(visual_states):
                static_errors.append("report.visual_states contains bad rows")
    frames = tuple(_frame_evidence(item) for item in frame_records)
    for frame in frames:
        if not frame.readable:
            static_errors.append(
                f"{frame.shot_id}@{frame.frame}: missing or unreadable frame")

    if require_frames:
        by_shot: dict[str, list[FrameEvidence]] = {}
        for frame in frames:
            by_shot.setdefault(frame.shot_id, []).append(frame)
        composition_shots = {
            str(check.get("shot_id") or "")
            for check in (report.get("checks") or [])
            if isinstance(check, Mapping)
            and str(check.get("check_id") or "") == "composition"
        }
        for shot_id in sorted(composition_shots):
            actual = tuple(item.phase for item in by_shot.get(shot_id, ()))
            if shot_id and actual != FRAME_PHASES:
                static_errors.append(
                    f"{shot_id}: expected exactly first/middle/last frame "
                    f"evidence, got {actual!r}")
        if not composition_shots:
            static_errors.append("report has no composition shot evidence")

    normalized_payloads: dict[str, dict[str, Any]] = {}
    for field, value in (
        ("reference", reference),
        ("manifest", manifest),
        ("report", report),
        ("world_state", world_state),
    ):
        normalized, non_finite_errors = _encode_non_finite(
            value, path=field)
        static_errors.extend(non_finite_errors)
        try:
            _json_safe(normalized, field)
        except ValueError as exc:
            static_errors.append(str(exc))
        normalized_payloads[field] = dict(normalized)

    reference_copy = copy.deepcopy(normalized_payloads["reference"])
    manifest_copy = copy.deepcopy(normalized_payloads["manifest"])
    report_copy = copy.deepcopy(normalized_payloads["report"])
    world_copy = normalize_world_state(
        copy.deepcopy(normalized_payloads["world_state"]))
    reference_fp = coarse_reference_content_fingerprint(reference_copy)
    manifest_fp = manifest_fingerprint(manifest_copy)
    report_fp = canonical_fingerprint(report_copy)
    world_fp = world_state_fingerprint(world_copy)
    report_manifest = str(report_copy.get("manifest_fingerprint") or "")
    if report_manifest != manifest_fp:
        static_errors.append(
            "report manifest_fingerprint does not match the bundled manifest")

    identity = {
        "schema_version": OBSERVATION_SCHEMA_VERSION,
        "reference_fingerprint": reference_fp,
        "manifest_fingerprint": manifest_fp,
        "report_fingerprint": report_fp,
        "world_state_fingerprint": world_fp,
        "frames": [
            {
                "shot_id": item.shot_id,
                "frame": item.frame,
                "phase": item.phase,
                "pixel_sha256": item.pixel_sha256,
            }
            for item in frames
        ],
    }
    observation_id = "obs-" + canonical_fingerprint(identity)
    complete = (
        (not static_errors if complete_hint is None else bool(complete_hint))
        and not static_errors
    )
    bundle = ObservationBundle(
        observation_id=observation_id,
        reference_fingerprint=reference_fp,
        manifest_fingerprint=manifest_fp,
        report_fingerprint=report_fp,
        world_state_fingerprint=world_fp,
        bundle_fingerprint="",
        evidence_dir=str(Path(evidence_dir).resolve()),
        reference=reference_copy,
        manifest=manifest_copy,
        report=report_copy,
        world_state=world_copy,
        frames=frames,
        static_errors=tuple(static_errors),
        complete_hint=complete,
    )
    bundle_fp = canonical_fingerprint(bundle._identity_payload())
    return ObservationBundle(
        **{
            **bundle.__dict__,
            "bundle_fingerprint": bundle_fp,
        }
    )


__all__ = [
    "FrameEvidence",
    "FRAME_PHASES",
    "OBSERVATION_SCHEMA_VERSION",
    "ObservationBundle",
    "build_observation_bundle",
    "describe_frame_record",
]
