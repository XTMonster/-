"""Immutable, versioned per-shot quality evidence.

The store is pure Python and does not import ``bpy``.  A Blender adapter may
capture or restore the physical world, but the evidence itself is portable and
can be replayed without an LLM.
"""

from __future__ import annotations

import copy
import json
import math
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from .audit import canonical_fingerprint

EVIDENCE_SCHEMA_VERSION = "shot-evidence/v3"
EVIDENCE_STORE_SCHEMA_VERSION = "evidence-store/v3"
_FRAME_PHASES = ("first", "middle", "last")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_REQUIRED_BASIS_FINGERPRINTS = (
    "observation_id",
    "bundle_fingerprint",
    "reference_fingerprint",
    "manifest_fingerprint",
    "report_fingerprint",
    "world_state_fingerprint",
    "scene_content_fingerprint",
)


class EvidenceError(ValueError):
    """Evidence is missing, malformed, non-contiguous or tampered with."""


def _mapping(value: Any, field_name: str) -> Dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise EvidenceError(f"{field_name} must be a mapping")
    return copy.deepcopy(dict(value))


@dataclass(frozen=True)
class ShotEvidence:
    """One immutable shot version with enough state to restore and audit it."""

    run_id: str
    scene_id: str
    shot_id: str
    version: int
    parent_version: Optional[int]
    reason: str
    created_at: str
    plan: Mapping[str, Any]
    reference: Mapping[str, Any]
    manifest: Mapping[str, Any]
    world_state: Mapping[str, Any]
    shot_contract: Mapping[str, Any] = field(default_factory=dict)
    shot_slice: Mapping[str, Any] = field(default_factory=dict)
    build: Mapping[str, Any] = field(default_factory=dict)
    audit: Mapping[str, Any] = field(default_factory=dict)
    measurements: Mapping[str, Any] = field(default_factory=dict)
    score_breakdown: Mapping[str, Any] = field(default_factory=dict)
    gates: Mapping[str, Any] = field(default_factory=dict)
    hard_gates: Mapping[str, Any] = field(default_factory=dict)
    sequence_gate: Mapping[str, Any] = field(default_factory=dict)
    frames: Any = field(default_factory=dict)
    semantic_review: Mapping[str, Any] = field(default_factory=dict)
    rag: Mapping[str, Any] = field(default_factory=dict)
    correction: Mapping[str, Any] = field(default_factory=dict)
    correction_candidates: Any = field(default_factory=list)
    applied_operations: Any = field(default_factory=list)
    remeasurement: Mapping[str, Any] = field(default_factory=dict)
    disposition: Mapping[str, Any] = field(default_factory=dict)
    absence_reasons: Mapping[str, Any] = field(default_factory=dict)
    basis_fingerprints: Mapping[str, Any] = field(default_factory=dict)
    delivery_eligible: bool = False
    schema_version: str = EVIDENCE_SCHEMA_VERSION
    digest: str = ""

    def __post_init__(self) -> None:
        for name in ("run_id", "scene_id", "shot_id", "reason", "created_at"):
            if not str(getattr(self, name)).strip():
                raise EvidenceError(f"{name} must be non-empty")
        if self.schema_version != EVIDENCE_SCHEMA_VERSION:
            raise EvidenceError(
                f"unsupported evidence schema: {self.schema_version!r}")
        if isinstance(self.version, bool) or int(self.version) < 0:
            raise EvidenceError("version must be a non-negative integer")
        if int(self.version) == 0 and self.parent_version is not None:
            raise EvidenceError("version 0 must not have a parent")
        if int(self.version) > 0 and self.parent_version != int(self.version) - 1:
            raise EvidenceError("parent_version must name the previous version")
        for name in (
            "plan", "shot_contract", "reference", "manifest", "world_state",
            "shot_slice", "build", "audit", "measurements",
            "score_breakdown", "gates", "hard_gates", "sequence_gate",
            "semantic_review", "rag", "correction", "remeasurement",
            "disposition", "absence_reasons", "basis_fingerprints",
        ):
            object.__setattr__(self, name, _mapping(getattr(self, name), name))
        for name in ("correction_candidates", "applied_operations"):
            value = getattr(self, name)
            if not isinstance(value, (list, tuple)):
                raise EvidenceError(f"{name} must be a list")
            object.__setattr__(self, name, copy.deepcopy(list(value)))
        for section, reason in self.absence_reasons.items():
            if not str(section).strip() or not str(reason).strip():
                raise EvidenceError(
                    "absence_reasons must map non-empty section names "
                    "to non-empty reasons")
        object.__setattr__(self, "frames", copy.deepcopy(self.frames))
        object.__setattr__(self, "version", int(self.version))
        object.__setattr__(self, "delivery_eligible", bool(self.delivery_eligible))
        computed = canonical_fingerprint(self._payload(include_digest=False))
        if self.digest and self.digest != computed:
            raise EvidenceError("evidence digest mismatch")
        object.__setattr__(self, "digest", computed)

    @classmethod
    def create(cls, **kwargs: Any) -> "ShotEvidence":
        return cls(**kwargs)

    def _payload(self, *, include_digest: bool) -> Dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "scene_id": self.scene_id,
            "shot_id": self.shot_id,
            "version": self.version,
            "parent_version": self.parent_version,
            "reason": self.reason,
            "created_at": self.created_at,
            "plan": self.plan,
            "shot_contract": self.shot_contract,
            "reference": self.reference,
            "manifest": self.manifest,
            "world_state": self.world_state,
            "shot_slice": self.shot_slice,
            "build": self.build,
            "audit": self.audit,
            "measurements": self.measurements,
            "score_breakdown": self.score_breakdown,
            "gates": self.gates,
            "hard_gates": self.hard_gates,
            "sequence_gate": self.sequence_gate,
            "frames": self.frames,
            "semantic_review": self.semantic_review,
            "rag": self.rag,
            "correction": self.correction,
            "correction_candidates": self.correction_candidates,
            "applied_operations": self.applied_operations,
            "remeasurement": self.remeasurement,
            "disposition": self.disposition,
            "absence_reasons": self.absence_reasons,
            "basis_fingerprints": self.basis_fingerprints,
            "delivery_eligible": self.delivery_eligible,
        }
        if include_digest:
            payload["digest"] = self.digest
        return payload

    def to_dict(self, *, include_digest: bool = True) -> Dict[str, Any]:
        return copy.deepcopy(self._payload(include_digest=include_digest))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ShotEvidence":
        if not isinstance(data, Mapping):
            raise EvidenceError("evidence record must be an object")
        supplied_digest = str(data.get("digest") or "")
        if not supplied_digest:
            raise EvidenceError("evidence record is missing digest")
        values = dict(data)
        try:
            record = cls(**values)
        except TypeError as exc:
            raise EvidenceError(f"evidence record has invalid fields: {exc}") from exc
        if record.digest != supplied_digest:
            raise EvidenceError("evidence digest mismatch")
        return record

    def restore_payload(self) -> Dict[str, Any]:
        """Return the exact plan/reference/manifest/world state for this version."""
        return {
            "plan": copy.deepcopy(dict(self.plan)),
            "reference": copy.deepcopy(dict(self.reference)),
            "manifest": copy.deepcopy(dict(self.manifest)),
            "world_state": copy.deepcopy(dict(self.world_state)),
            "shot_slice": copy.deepcopy(dict(self.shot_slice)),
        }

    def is_stale(self, current_basis: Mapping[str, Any]) -> bool:
        expected = dict(self.basis_fingerprints)
        if not expected:
            return True
        return any(expected.get(key) != value
                   for key, value in current_basis.items())

    def is_passing(self) -> bool:
        """Whether this version carries an explicit passing shot gate."""
        return self.gates.get("shot_passed") is True

    def absence_reason(self, section: str) -> str:
        """Return the recorded reason that a section is genuinely absent."""
        return str(self.absence_reasons.get(str(section)) or "").strip()

    def verify_errors(self) -> list[str]:
        errors: list[str] = []
        for name in (
            "plan", "reference", "manifest", "world_state", "shot_slice",
            "measurements", "gates", "basis_fingerprints",
        ):
            if not getattr(self, name):
                errors.append(f"{name} evidence is missing")
        if not self.frames and not self.absence_reason("frames"):
            errors.append(
                "frames evidence is missing without an absence reason")
        elif self.frames:
            errors.extend(self._frame_errors())
        for key in _REQUIRED_BASIS_FINGERPRINTS:
            if not str(self.basis_fingerprints.get(key) or "").strip():
                errors.append(f"basis_fingerprints.{key} is missing")
        for section in (
            "shot_contract",
            "build",
            "audit",
            "score_breakdown",
            "hard_gates",
            "sequence_gate",
            "semantic_review",
            "rag",
            "correction_candidates",
            "applied_operations",
            "remeasurement",
            "disposition",
        ):
            if not getattr(self, section) and not self.absence_reason(section):
                errors.append(
                    f"{section} evidence is missing without an absence reason")
        if self.gates.get("evidence_complete") is True and self.absence_reasons:
            errors.append(
                "evidence_complete cannot be true while evidence is absent: "
                + ", ".join(sorted(self.absence_reasons)))
        try:
            rebuilt = type(self).from_dict(self.to_dict())
        except (EvidenceError, TypeError, ValueError) as exc:
            errors.append(f"evidence round-trip failed: {exc}")
        else:
            if rebuilt.digest != self.digest:
                errors.append("evidence digest is not stable")
        return errors

    def _frame_errors(self) -> list[str]:
        if not isinstance(self.frames, (list, tuple)):
            return ["frames evidence must be a list"]
        rows = [
            dict(row) if isinstance(row, Mapping) else {}
            for row in self.frames
        ]
        phases = tuple(str(row.get("phase") or "") for row in rows)
        errors: list[str] = []
        if phases != _FRAME_PHASES:
            errors.append(
                f"{self.shot_id}: frames must contain exactly "
                f"first/middle/last in order (got {phases!r})")
        for index, row in enumerate(rows):
            label = f"{self.shot_id}: frame[{index}]"
            if str(row.get("shot_id") or "") != self.shot_id:
                errors.append(f"{label} shot_id does not match evidence")
            try:
                frame = int(row.get("frame"))
            except (TypeError, ValueError):
                frame = 0
            if frame < 1:
                errors.append(f"{label} frame number is missing")
            path = str(row.get("path") or row.get("png") or "")
            if not path:
                errors.append(f"{label} frame path is missing")
            for digest_name in ("file_sha256", "pixel_sha256"):
                digest = str(row.get(digest_name) or "")
                if not _SHA256_RE.fullmatch(digest):
                    errors.append(f"{label} {digest_name} is missing")
            if row.get("readable") is not True:
                errors.append(f"{label} is not marked readable")
        return errors


class EvidenceStore:
    """Append-only evidence histories plus best/adopted pointers."""

    def __init__(self, *, run_id: str, scene_id: str):
        if not str(run_id).strip() or not str(scene_id).strip():
            raise EvidenceError("run_id and scene_id must be non-empty")
        self.run_id = str(run_id)
        self.scene_id = str(scene_id)
        self._histories: Dict[str, list[ShotEvidence]] = {}
        self._best: Dict[str, int] = {}
        self._adopted: Dict[str, int] = {}

    def append(self, evidence: ShotEvidence) -> ShotEvidence:
        if evidence.run_id != self.run_id or evidence.scene_id != self.scene_id:
            raise EvidenceError("evidence run/scene does not match store")
        history = self._histories.setdefault(evidence.shot_id, [])
        expected = len(history)
        if evidence.version != expected:
            raise EvidenceError(
                f"version must be contiguous from 0 (expected {expected})")
        history.append(ShotEvidence.from_dict(evidence.to_dict()))
        return ShotEvidence.from_dict(history[-1].to_dict())

    def consider_candidate(self, evidence: ShotEvidence) -> ShotEvidence:
        """Append one version and retain it only when its quality ranks higher.

        Candidate dispositions are producer claims, not authority.  The store
        compares the canonical passing state, composition score and hard-error
        count against the current best so a mislabeled regression or tie can
        never overwrite the physical best pointer.
        """
        stored = self.append(evidence)
        try:
            current_best = self.get(
                stored.shot_id, self.best_version(stored.shot_id))
        except KeyError:
            selected = True
        else:
            selected = _evidence_rank(stored) > _evidence_rank(current_best)
        if selected:
            self.mark_best(stored.shot_id, stored.version)
            if stored.is_passing():
                self.mark_adopted(stored.shot_id, stored.version)
        return stored

    def get(self, shot_id: str, version: int) -> ShotEvidence:
        try:
            item = self._histories[str(shot_id)][int(version)]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise KeyError(f"unknown evidence version: {shot_id}@{version}") from exc
        return ShotEvidence.from_dict(item.to_dict())

    def history(self, shot_id: str) -> list[ShotEvidence]:
        return [ShotEvidence.from_dict(item.to_dict())
                for item in self._histories.get(str(shot_id), ())]

    def _require_version(self, shot_id: str, version: int) -> None:
        self.get(shot_id, version)

    def mark_best(self, shot_id: str, version: int) -> None:
        self._require_version(shot_id, version)
        self._best[str(shot_id)] = int(version)

    def mark_adopted(self, shot_id: str, version: int) -> None:
        record = self.get(shot_id, version)
        best = self._best.get(str(shot_id))
        if best != int(version):
            raise EvidenceError(
                f"{shot_id}@{version}: adopted version must equal best")
        if not record.is_passing():
            raise EvidenceError(
                f"{shot_id}@{version}: adopted version must be passing")
        self._adopted[str(shot_id)] = int(version)

    def best_version(self, shot_id: str) -> int:
        try:
            return int(self._best[str(shot_id)])
        except KeyError as exc:
            raise KeyError(f"no best version for shot: {shot_id}") from exc

    def adopted_version(self, shot_id: str) -> int:
        try:
            return int(self._adopted[str(shot_id)])
        except KeyError as exc:
            raise KeyError(f"no adopted version for shot: {shot_id}") from exc

    def restore(self, shot_id: str, version: Optional[int] = None) -> Dict[str, Any]:
        selected = self.best_version(shot_id) if version is None else int(version)
        return self.get(shot_id, selected).restore_payload()

    def validate(self) -> list[str]:
        errors: list[str] = []
        for shot_id, history in sorted(self._histories.items()):
            if not history:
                errors.append(f"{shot_id}: history is empty")
                continue
            if shot_id not in self._best:
                errors.append(f"{shot_id}: missing best pointer")
            for expected, record in enumerate(history):
                if record.version != expected:
                    errors.append(
                        f"{shot_id}: non-contiguous version {record.version}")
                errors.extend(
                    f"{shot_id}@{record.version}: {item}"
                    for item in record.verify_errors())
        for name, pointers in (("best", self._best),
                               ("adopted", self._adopted)):
            for shot_id, version in sorted(pointers.items()):
                if shot_id not in self._histories:
                    errors.append(f"{name} points at unknown shot {shot_id}")
                elif version < 0 or version >= len(self._histories[shot_id]):
                    errors.append(
                        f"{name} points at unknown version {shot_id}@{version}")
        for shot_id, adopted in sorted(self._adopted.items()):
            if self._best.get(shot_id) != adopted:
                errors.append(
                    f"{shot_id}: adopted version must also be best")
        return errors

    def fingerprint(self) -> str:
        return canonical_fingerprint(self.to_dict())

    def summary(self) -> Dict[str, Any]:
        return {
            "status": "authoritative",
            "schema_version": EVIDENCE_STORE_SCHEMA_VERSION,
            "run_id": self.run_id,
            "scene_id": self.scene_id,
            "store_fingerprint": self.fingerprint(),
            "shots": sorted(self._histories),
            "versions": {
                shot_id: len(history)
                for shot_id, history in sorted(self._histories.items())
            },
            "best": dict(sorted(self._best.items())),
            "adopted": dict(sorted(self._adopted.items())),
            "errors": self.validate(),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": EVIDENCE_STORE_SCHEMA_VERSION,
            "run_id": self.run_id,
            "scene_id": self.scene_id,
            "histories": {
                shot_id: [item.to_dict() for item in history]
                for shot_id, history in sorted(self._histories.items())
            },
            "best": dict(sorted(self._best.items())),
            "adopted": dict(sorted(self._adopted.items())),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EvidenceStore":
        if not isinstance(data, Mapping):
            raise EvidenceError("evidence store must be an object")
        if data.get("schema_version") != EVIDENCE_STORE_SCHEMA_VERSION:
            raise EvidenceError("unsupported evidence store schema")
        store = cls(run_id=str(data.get("run_id") or ""),
                    scene_id=str(data.get("scene_id") or ""))
        histories = data.get("histories")
        if not isinstance(histories, Mapping):
            raise EvidenceError("histories must be an object")
        for shot_id, items in sorted(histories.items()):
            if not isinstance(items, list):
                raise EvidenceError(f"history {shot_id} must be a list")
            for item in items:
                store.append(ShotEvidence.from_dict(item))
        for shot_id, version in dict(data.get("best") or {}).items():
            store.mark_best(str(shot_id), int(version))
        for shot_id, version in dict(data.get("adopted") or {}).items():
            store.mark_adopted(str(shot_id), int(version))
        return store

    def save_atomic(self, path: Path | str) -> Path:
        errors = self.validate()
        if errors:
            raise EvidenceError(
                "evidence store is not authoritative: " + "; ".join(errors))
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            serialized = json.dumps(
                self.to_dict(),
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise EvidenceError(
                f"evidence store contains non-finite or non-JSON values: {exc}"
            ) from exc
        temporary = ""
        try:
            with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=target.parent,
                    prefix=f".{target.name}.",
                    suffix=".tmp",
                    delete=False) as handle:
                temporary = handle.name
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        except Exception:
            if temporary:
                try:
                    Path(temporary).unlink(missing_ok=True)
                except OSError:
                    pass
            raise
        return target

    @classmethod
    def load(cls, path: Path | str) -> "EvidenceStore":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        try:
            store = cls.from_dict(data)
        except EvidenceError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise EvidenceError(f"invalid evidence store: {exc}") from exc
        errors = store.validate()
        if errors:
            raise EvidenceError(
                "invalid evidence store: " + "; ".join(errors))
        return store


def _evidence_rank(evidence: ShotEvidence) -> tuple[int, float, int]:
    composition = evidence.measurements.get("composition")
    score = (
        composition.get("score")
        if isinstance(composition, Mapping)
        else composition
    )
    try:
        numeric_score = float(score)
    except (TypeError, ValueError):
        numeric_score = float("-inf")
    if not math.isfinite(numeric_score):
        numeric_score = float("-inf")
    hard_error_count = evidence.score_breakdown.get("hard_error_count")
    try:
        hard_errors = int(hard_error_count or 0)
    except (TypeError, ValueError):
        hard_errors = 0
    return (
        1 if evidence.is_passing() else 0,
        numeric_score,
        -hard_errors,
    )


@dataclass(frozen=True)
class StaleEvidenceStore:
    """Display-only view; stale evidence can never authorize a pipeline gate."""

    payload: Mapping[str, Any]
    status: str
    reason: str

    @property
    def authoritative(self) -> bool:
        return False

    @property
    def stale(self) -> bool:
        return self.status == "stale"

    @property
    def run_id(self) -> str:
        return str(self.payload.get("run_id") or "")

    @property
    def scene_id(self) -> str:
        return str(self.payload.get("scene_id") or "")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": str(
                self.payload.get("schema_version") or ""),
            "run_id": self.run_id,
            "scene_id": self.scene_id,
            "status": self.status,
            "reason": self.reason,
            "payload": copy.deepcopy(dict(self.payload)),
        }

    def summary(self) -> Dict[str, Any]:
        best = self.payload.get("best")
        adopted = self.payload.get("adopted")
        histories = self.payload.get("histories")
        return {
            "status": self.status,
            "schema_version": str(
                self.payload.get("schema_version") or ""),
            "run_id": self.run_id,
            "scene_id": self.scene_id,
            "store_fingerprint": "",
            "shots": sorted(histories) if isinstance(histories, Mapping) else [],
            "versions": {
                str(shot_id): len(items)
                for shot_id, items in histories.items()
                if isinstance(items, list)
            } if isinstance(histories, Mapping) else {},
            "best": dict(best) if isinstance(best, Mapping) else {},
            "adopted": dict(adopted) if isinstance(adopted, Mapping) else {},
            "errors": [self.reason],
        }


EvidenceStoreView = EvidenceStore | StaleEvidenceStore


def inspect_evidence_store_payload(
    data: Any,
) -> tuple[Optional[EvidenceStore], Dict[str, Any]]:
    """Parse authoritative evidence, or retain an explicit stale view."""
    if not isinstance(data, Mapping):
        return None, {
            "status": "invalid",
            "schema_version": "",
            "reason": "evidence store is not an object",
        }
    schema = str(data.get("schema_version") or "")
    histories = data.get("histories")
    legacy_record_schema = any(
        str(record.get("schema_version") or "")
        != EVIDENCE_SCHEMA_VERSION
        for items in (histories.values()
                      if isinstance(histories, Mapping) else ())
        if isinstance(items, list)
        for record in items
        if isinstance(record, Mapping)
    )
    try:
        store = EvidenceStore.from_dict(data)
    except (EvidenceError, KeyError, TypeError, ValueError) as exc:
        return None, {
            "status": (
                "stale"
                if schema != EVIDENCE_STORE_SCHEMA_VERSION
                or legacy_record_schema
                else "invalid"),
            "schema_version": schema,
            "reason": str(exc),
        }
    errors = store.validate()
    if errors:
        return None, {
            "status": "invalid",
            "schema_version": schema,
            "reason": "; ".join(errors),
        }
    return store, store.summary()


def inspect_evidence_store(
    path: Path | str,
) -> tuple[Optional[EvidenceStore], Dict[str, Any]]:
    """Load a store for display without letting old evidence authorize a gate."""
    target = Path(path)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return None, {
            "status": "invalid",
            "schema_version": "",
            "reason": f"cannot read evidence store: {exc}",
        }
    return inspect_evidence_store_payload(data)


def evidence_status_text(status: Mapping[str, Any] | None) -> str:
    """Render one evidence status without promoting stale data to authority."""
    if not isinstance(status, Mapping):
        return "证据：未检查"
    value = str(status.get("status") or "invalid")
    reason = str(status.get("reason") or "").strip()
    if value == "authoritative":
        best = status.get("best")
        shots = len(best) if isinstance(best, Mapping) else 0
        return f"证据：权威（{shots} 镜有 best）"
    if value == "stale":
        suffix = f"：{reason}" if reason else ""
        return f"证据：已过期，只读展示，不可用于验收{suffix}"
    if value == "missing":
        suffix = f"：{reason}" if reason else ""
        return f"证据：缺失{suffix}"
    suffix = f"：{reason}" if reason else ""
    return f"证据：无效{suffix}"


__all__ = [
    "EVIDENCE_SCHEMA_VERSION",
    "EVIDENCE_STORE_SCHEMA_VERSION",
    "EvidenceError",
    "EvidenceStore",
    "EvidenceStoreView",
    "ShotEvidence",
    "StaleEvidenceStore",
    "evidence_status_text",
    "inspect_evidence_store",
    "inspect_evidence_store_payload",
]
