"""Pure observation evidence bound to one rendered scene state."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from .audit import canonical_fingerprint
from .blockout import manifest_fingerprint
from .coarse_reference import coarse_reference_content_fingerprint
from .performance_bake import validate_performance_bake_reference
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


@lru_cache(maxsize=4096)
def _pixel_sha256_cached(
    path: str,
    file_sha256: str,
    file_bytes: int,
) -> tuple[str, int, int]:
    """Decode once per exact file content, not once per integrity check."""
    del file_sha256, file_bytes
    return _pixel_sha256(Path(path))


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


def _document_shot_ids(
    reference: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> tuple[str, ...]:
    ordered: list[str] = []

    def add(value: Any) -> None:
        shot_id = str(value or "")
        if shot_id and shot_id not in ordered:
            ordered.append(shot_id)

    for shot in reference.get("shots") or []:
        if isinstance(shot, Mapping):
            add(shot.get("shot_id"))
    for key in ("shot_table", "cameras"):
        for row in manifest.get(key) or []:
            if isinstance(row, Mapping):
                add(row.get("shot_id"))
    return tuple(ordered)


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
    provenance: str = "rendered"
    source_observation_id: str = ""
    source_bundle_fingerprint: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = {
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
        if self.provenance != "rendered":
            payload["provenance"] = self.provenance
        if self.source_observation_id:
            payload["source_observation_id"] = self.source_observation_id
        if self.source_bundle_fingerprint:
            payload["source_bundle_fingerprint"] = (
                self.source_bundle_fingerprint)
        return payload

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
            provenance=str(data.get("provenance") or "rendered"),
            source_observation_id=str(
                data.get("source_observation_id") or ""),
            source_bundle_fingerprint=str(
                data.get("source_bundle_fingerprint") or ""),
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
        if self.provenance not in {"rendered", "reused"}:
            return [
                f"{self.shot_id}@{self.frame}: unknown frame provenance "
                f"{self.provenance!r}"
            ]
        if self.provenance == "reused" \
                and not self.source_observation_id:
            return [
                f"{self.shot_id}@{self.frame}: reused frame has no source "
                "observation"
            ]
        path = Path(self.path)
        if not path.is_file():
            return [f"{self.shot_id}@{self.frame}: missing frame {path}"]
        if not self.readable:
            return [f"{self.shot_id}@{self.frame}: frame was not readable"]
        try:
            file_bytes = path.stat().st_size
            file_digest = _file_sha256(path)
            pixel_digest, width, height = _pixel_sha256_cached(
                str(path.resolve()),
                file_digest,
                file_bytes,
            )
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
        if file_bytes != self.file_bytes:
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
    performance_bake_ref: Mapping[str, Any] = field(default_factory=dict)
    shot_ids: tuple[str, ...] = ()
    observed_shot_ids: tuple[str, ...] = ()
    reused_shot_sources: Mapping[str, Any] = field(default_factory=dict)
    per_shot: tuple[Mapping[str, Any], ...] = ()
    measurement_provenance: Mapping[str, Any] = field(default_factory=dict)
    scope_policy: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = OBSERVATION_SCHEMA_VERSION

    def _identity_payload(self) -> dict[str, Any]:
        payload = {
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
        if self.performance_bake_ref:
            payload["performance_bake_ref"] = self.performance_bake_ref
        if self.shot_ids:
            payload["shot_ids"] = list(self.shot_ids)
        if self.observed_shot_ids:
            payload["observed_shot_ids"] = list(self.observed_shot_ids)
        if self.reused_shot_sources:
            payload["reused_shot_sources"] = self.reused_shot_sources
        if self.per_shot:
            payload["per_shot"] = list(self.per_shot)
        if self.measurement_provenance:
            payload["measurement_provenance"] = (
                self.measurement_provenance)
        if self.scope_policy:
            payload["scope_policy"] = self.scope_policy
        return payload

    def integrity_errors(self) -> list[str]:
        """Return errors that prove the bundle bytes contradict its identity."""
        errors = []
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
        if self.performance_bake_ref:
            errors.extend(validate_performance_bake_reference(
                self.performance_bake_ref, manifest=self.manifest))
        elif isinstance(self.manifest.get("performance"), Mapping):
            errors.append(
                "performance bake reference is missing for a compiled "
                "performance program")
        return errors

    def verify_errors(self) -> list[str]:
        errors = [*self.static_errors, *self.integrity_errors()]
        if len(set(self.shot_ids)) != len(self.shot_ids) \
                or any(not shot_id for shot_id in self.shot_ids):
            errors.append("shot_ids must be unique non-empty identifiers")
        if self.shot_ids:
            scope = set(self.shot_ids)
            errors.extend(
                f"frame belongs outside observation scope: {frame.shot_id}"
                for frame in self.frames
                if frame.shot_id not in scope
            )
        scope_ids = self.shot_ids or _document_shot_ids(
            self.reference, self.manifest)
        scope_set = set(scope_ids)
        observed = self.observed_shot_ids or scope_ids
        if len(set(observed)) != len(observed) or any(
                not shot_id for shot_id in observed):
            errors.append(
                "observed_shot_ids must be unique non-empty identifiers")
        if set(observed) - scope_set:
            errors.append(
                "observed_shot_ids contain shots outside observation scope")
        reused = tuple(
            shot_id for shot_id in scope_ids if shot_id not in set(observed))
        reused_source_ids = {
            str(shot_id)
            for shot_id in self.reused_shot_sources
            if str(shot_id)
        }
        if reused_source_ids != set(reused):
            errors.append(
                "reused_shot_sources must cover exactly the reused shots: "
                f"expected={sorted(reused)!r}, "
                f"actual={sorted(reused_source_ids)!r}")
        if self.observed_shot_ids and not self.per_shot:
            errors.append(
                "local observation requires complete raw per_shot measurements")
        if self.observed_shot_ids and not self.measurement_provenance:
            errors.append(
                "local observation requires measurement provenance")
        if self.per_shot:
            raw_ids = [
                str(row.get("shot_id") or "")
                for row in self.per_shot
                if isinstance(row, Mapping)
            ]
            if len(raw_ids) != len(self.per_shot) \
                    or len(set(raw_ids)) != len(raw_ids):
                errors.append(
                    "per_shot measurements must have unique shot_id values")
            if set(raw_ids) != scope_set:
                errors.append(
                    "per_shot measurements do not cover observation scope: "
                    f"expected={sorted(scope_set)!r}, "
                    f"actual={sorted(set(raw_ids))!r}")
        if self.measurement_provenance:
            provenance_ids = {
                str(shot_id)
                for shot_id in self.measurement_provenance
                if str(shot_id)
            }
            if provenance_ids != scope_set:
                errors.append(
                    "measurement_provenance does not cover observation scope")
            for shot_id in reused:
                source = self.reused_shot_sources.get(shot_id)
                provenance = self.measurement_provenance.get(shot_id)
                if not isinstance(source, Mapping) or not isinstance(
                        provenance, Mapping):
                    continue
                if str(provenance.get("provenance") or "") != "reused":
                    errors.append(
                        f"{shot_id}: reused measurement provenance is missing")
                source_id = str(source.get("observation_id") or "")
                if not source_id or str(
                        provenance.get("source_observation_id") or ""
                ) != source_id:
                    errors.append(
                        f"{shot_id}: reused measurement source mismatch")
                if str(source.get("physical_fingerprint") or "") != str(
                        provenance.get("physical_fingerprint") or ""):
                    errors.append(
                        f"{shot_id}: reused physical fingerprint mismatch")
        observed_set = set(observed)
        for frame in self.frames:
            if frame.shot_id in observed_set \
                    and frame.provenance == "reused":
                errors.append(
                    f"{frame.shot_id}@{frame.frame}: observed shot reused "
                    "a frame instead of rendering it")
            if frame.shot_id in set(reused) \
                    and frame.provenance != "reused":
                errors.append(
                    f"{frame.shot_id}@{frame.frame}: reused shot lacks "
                    "reused frame provenance")
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

    @property
    def reused_shot_ids(self) -> tuple[str, ...]:
        scope_ids = self.shot_ids or _document_shot_ids(
            self.reference, self.manifest)
        observed = set(self.observed_shot_ids or scope_ids)
        return tuple(
            shot_id for shot_id in scope_ids if shot_id not in observed)

    def to_payload(self, *, include_dynamic: bool = True) -> dict[str, Any]:
        payload = self._identity_payload()
        payload["bundle_fingerprint"] = self.bundle_fingerprint
        if include_dynamic:
            errors = self.verify_errors()
            payload["complete"] = bool(self.complete_hint and not errors)
            payload["errors"] = errors
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
            performance_bake_ref=copy.deepcopy(dict(
                data.get("performance_bake_ref") or {})),
            shot_ids=tuple(
                str(item) for item in (data.get("shot_ids") or [])
                if str(item)
            ),
            observed_shot_ids=tuple(
                str(item) for item in (data.get("observed_shot_ids") or [])
                if str(item)
            ),
            reused_shot_sources=copy.deepcopy(dict(
                data.get("reused_shot_sources") or {})),
            per_shot=tuple(
                copy.deepcopy(dict(item))
                for item in (data.get("per_shot") or [])
                if isinstance(item, Mapping)
            ),
            measurement_provenance=copy.deepcopy(dict(
                data.get("measurement_provenance") or {})),
            scope_policy=copy.deepcopy(dict(
                data.get("scope_policy") or {})),
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
        performance_bake_ref: Mapping[str, Any] | None = None,
        shot_ids: Sequence[str] | None = None,
        observed_shot_ids: Sequence[str] | None = None,
        reused_shot_sources: Mapping[str, Any] | None = None,
        per_shot: Sequence[Mapping[str, Any]] | None = None,
        measurement_provenance: Mapping[str, Any] | None = None,
        scope_policy: Mapping[str, Any] | None = None,
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
            performance_bake_ref=performance_bake_ref,
            shot_ids=shot_ids,
            observed_shot_ids=observed_shot_ids,
            reused_shot_sources=reused_shot_sources,
            per_shot=per_shot,
            measurement_provenance=measurement_provenance,
            scope_policy=scope_policy,
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
            pixel_digest, width, height = _pixel_sha256_cached(
                str(path.resolve()),
                file_digest,
                file_bytes,
            )
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
        provenance=str(item.get("provenance") or "rendered"),
        source_observation_id=str(
            item.get("source_observation_id") or ""),
        source_bundle_fingerprint=str(
            item.get("source_bundle_fingerprint") or ""),
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
    performance_bake_ref: Mapping[str, Any] | None = None,
    shot_ids: Sequence[str] | None = None,
    observed_shot_ids: Sequence[str] | None = None,
    reused_shot_sources: Mapping[str, Any] | None = None,
    per_shot: Sequence[Mapping[str, Any]] | None = None,
    measurement_provenance: Mapping[str, Any] | None = None,
    scope_policy: Mapping[str, Any] | None = None,
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
    scoped_shot_ids = (
        tuple(dict.fromkeys(
            str(item) for item in shot_ids if str(item)
        ))
        if shot_ids is not None else ()
    )
    if shot_ids is not None and not scoped_shot_ids:
        static_errors.append("shot_ids must name at least one shot")
    if performance_bake_ref is not None \
            and not isinstance(performance_bake_ref, Mapping):
        raise ValueError("performance_bake_ref must be a mapping")
    bake_ref = copy.deepcopy(dict(performance_bake_ref or {}))
    if bake_ref:
        static_errors.extend(validate_performance_bake_reference(
            bake_ref, manifest=manifest))
        _json_safe(bake_ref, "performance_bake_ref")
    elif isinstance(manifest.get("performance"), Mapping):
        static_errors.append(
            "performance bake reference is missing for a compiled "
            "performance program")
    manifest_shots = {
        str(item.get("shot_id") or "")
        for item in (manifest.get("shot_table") or [])
        if isinstance(item, Mapping) and str(item.get("shot_id") or "")
    }
    reference_shots = {
        str(item.get("shot_id") or "")
        for item in (reference.get("shots") or [])
        if isinstance(item, Mapping) and str(item.get("shot_id") or "")
    }
    all_shots = manifest_shots or reference_shots
    coverage_ids = (
        scoped_shot_ids
        if shot_ids is not None
        else _document_shot_ids(reference, manifest)
    )
    coverage_set = set(coverage_ids)
    observed_ids = (
        tuple(dict.fromkeys(
            str(item) for item in observed_shot_ids if str(item)
        ))
        if observed_shot_ids is not None else coverage_ids
    )
    if observed_shot_ids is not None and not observed_ids:
        static_errors.append(
            "observed_shot_ids must name at least one shot")
    if reused_shot_sources is not None and not isinstance(
            reused_shot_sources, Mapping):
        raise ValueError("reused_shot_sources must be a mapping")
    reused_sources = copy.deepcopy(dict(reused_shot_sources or {}))
    if measurement_provenance is not None and not isinstance(
            measurement_provenance, Mapping):
        raise ValueError("measurement_provenance must be a mapping")
    provenance = copy.deepcopy(dict(measurement_provenance or {}))
    if scope_policy is not None and not isinstance(scope_policy, Mapping):
        raise ValueError("scope_policy must be a mapping")
    scope_policy_copy = copy.deepcopy(dict(scope_policy or {}))
    raw_per_shot = tuple(
        copy.deepcopy(dict(item))
        for item in (per_shot or [])
        if isinstance(item, Mapping)
    )
    if per_shot is not None and len(raw_per_shot) != len(per_shot):
        static_errors.append("per_shot contains non-object rows")
    for field, value in (
        ("reused_shot_sources", reused_sources),
        ("per_shot", list(raw_per_shot)),
        ("measurement_provenance", provenance),
        ("scope_policy", scope_policy_copy),
    ):
        try:
            _json_safe(value, field)
        except ValueError as exc:
            static_errors.append(str(exc))
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
        if manifest_shots and reference_shots and (
                manifest_shots != reference_shots):
            static_errors.append(
                "manifest/reference shot coverage mismatch: "
                f"manifest={sorted(manifest_shots)!r}, "
                f"reference={sorted(reference_shots)!r}")
        if not all_shots:
            static_errors.append(
                "manifest/reference has no shot coverage identity")
        unknown_scope_shots = sorted(set(scoped_shot_ids) - all_shots)
        if unknown_scope_shots:
            static_errors.append(
                "observation scope names shots outside manifest/reference: "
                f"{unknown_scope_shots!r}")
        expected_shots = set(coverage_ids)
        composition_counts: dict[str, int] = {}
        empty_shots: dict[str, int] = {}
        for check in (report.get("checks") or []):
            if not isinstance(check, Mapping):
                continue
            check_id = str(check.get("check_id") or "")
            shot_id = str(check.get("shot_id") or "")
            if check_id == "composition" and shot_id:
                composition_counts[shot_id] = (
                    composition_counts.get(shot_id, 0) + 1)
            elif (check_id == "empty_shot"
                  and str(check.get("verdict") or "") in {"pass", "exempt"}
                  and shot_id):
                empty_shots[shot_id] = empty_shots.get(shot_id, 0) + 1
        composition_shots = set(composition_counts)
        unknown_evidence_shots = sorted(
            (composition_shots | set(empty_shots)) - expected_shots)
        if unknown_evidence_shots:
            static_errors.append(
                "report has evidence for shots outside manifest/reference: "
                f"{unknown_evidence_shots!r}")
        for shot_id in sorted(expected_shots):
            composition_count = composition_counts.get(shot_id, 0)
            empty_count = empty_shots.get(shot_id, 0)
            if composition_count > 1:
                static_errors.append(
                    f"{shot_id}: duplicate composition evidence")
            if empty_count > 1:
                static_errors.append(
                    f"{shot_id}: duplicate empty_shot evidence")
            if composition_count == 0 and empty_count == 0:
                static_errors.append(
                    f"{shot_id}: missing composition or empty_shot evidence")
            if composition_count == 1:
                actual = tuple(
                    item.phase for item in by_shot.get(shot_id, ()))
                if actual != FRAME_PHASES:
                    static_errors.append(
                        f"{shot_id}: expected exactly first/middle/last frame "
                        f"evidence, got {actual!r}")
        if not composition_shots and not empty_shots:
            static_errors.append("report has no composition shot evidence")

    local_provenance_requested = any(value is not None for value in (
        observed_shot_ids,
        reused_shot_sources,
        per_shot,
        measurement_provenance,
    ))
    if set(observed_ids) - coverage_set:
        static_errors.append(
            "observed_shot_ids contain shots outside observation scope")
    reused_ids = tuple(
        shot_id for shot_id in coverage_ids if shot_id not in set(observed_ids))
    if local_provenance_requested:
        if not raw_per_shot:
            static_errors.append(
                "local observation requires raw per_shot measurements")
        if not provenance:
            static_errors.append(
                "local observation requires measurement provenance")
        source_ids = {
            str(shot_id) for shot_id in reused_sources if str(shot_id)}
        if source_ids != set(reused_ids):
            static_errors.append(
                "reused_shot_sources must cover exactly the reused shots: "
                f"expected={sorted(reused_ids)!r}, "
                f"actual={sorted(source_ids)!r}")
        provenance_ids = {
            str(shot_id) for shot_id in provenance if str(shot_id)}
        if provenance_ids != coverage_set:
            static_errors.append(
                "measurement_provenance does not cover observation scope")
    raw_ids = [
        str(row.get("shot_id") or "")
        for row in raw_per_shot
    ]
    if raw_per_shot and (
            len(set(raw_ids)) != len(raw_ids)
            or set(raw_ids) != coverage_set):
        static_errors.append(
            "per_shot measurements must cover observation scope exactly")

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
                "provenance": item.provenance,
                "source_observation_id": item.source_observation_id,
            }
            for item in frames
        ],
    }
    if observed_shot_ids is not None:
        identity["observed_shot_ids"] = list(observed_ids)
    if reused_sources:
        identity["reused_shot_sources"] = reused_sources
    if raw_per_shot:
        identity["per_shot"] = list(raw_per_shot)
    if scope_policy_copy:
        identity["scope_policy"] = scope_policy_copy
    observation_id = "obs-" + canonical_fingerprint(identity)
    if provenance:
        for shot_id in observed_ids:
            entry = provenance.setdefault(shot_id, {})
            if not isinstance(entry, Mapping):
                static_errors.append(
                    f"{shot_id}: measurement provenance must be an object")
                continue
            entry = copy.deepcopy(dict(entry))
            entry.setdefault("provenance", "rendered")
            entry.setdefault("source_observation_id", observation_id)
            entry.setdefault(
                "source_bundle_fingerprint", "")
            provenance[shot_id] = entry
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
        performance_bake_ref=bake_ref,
        shot_ids=scoped_shot_ids,
        observed_shot_ids=(
            observed_ids if observed_shot_ids is not None else ()),
        reused_shot_sources=reused_sources,
        per_shot=raw_per_shot,
        measurement_provenance=provenance,
        scope_policy=scope_policy_copy,
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
