"""Immutable per-shot version history (pure Python, no bpy/IO)."""

from __future__ import annotations

from dataclasses import dataclass
import copy
from typing import Any, Dict, Mapping

_REASONS = frozenset({"initial", "repair", "react", "rollback", "manual_restore"})


@dataclass(frozen=True)
class ShotVersion:
    shot_id: str
    version: int
    plan: Any
    build_summary: Mapping[str, Any]
    audit_summary: Mapping[str, Any]
    adversarial_summary: Mapping[str, Any]
    created_at: str
    reason: str

    def __post_init__(self) -> None:
        if not str(self.shot_id).strip():
            raise ValueError("shot_id must be non-empty")
        if int(self.version) < 0:
            raise ValueError("version must be non-negative")
        if str(self.reason) not in _REASONS:
            raise ValueError(f"unsupported version reason: {self.reason}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "shot_id": str(self.shot_id), "version": int(self.version),
            "plan": copy.deepcopy(self.plan),
            "build_summary": copy.deepcopy(dict(self.build_summary)),
            "audit_summary": copy.deepcopy(dict(self.audit_summary)),
            "adversarial_summary": copy.deepcopy(dict(self.adversarial_summary)),
            "created_at": str(self.created_at), "reason": str(self.reason),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ShotVersion":
        return cls(
            shot_id=str(data["shot_id"]), version=int(data["version"]),
            plan=copy.deepcopy(data.get("plan")),
            build_summary=copy.deepcopy(data.get("build_summary") or {}),
            audit_summary=copy.deepcopy(data.get("audit_summary") or {}),
            adversarial_summary=copy.deepcopy(data.get("adversarial_summary") or {}),
            created_at=str(data.get("created_at", "")), reason=str(data["reason"]))


class ShotVersionHistory:
    """Append-only history for one shot; old entries are never mutated."""

    def __init__(self, shot_id: str):
        if not str(shot_id).strip():
            raise ValueError("shot_id must be non-empty")
        self.shot_id = str(shot_id)
        self._versions: list[ShotVersion] = []

    def append(self, version: ShotVersion) -> ShotVersion:
        if version.shot_id != self.shot_id:
            raise ValueError("version shot_id does not match history")
        expected = len(self._versions)
        if version.version != expected:
            raise ValueError(f"version must be contiguous from 0 (expected {expected})")
        frozen = ShotVersion.from_dict(version.to_dict())
        self._versions.append(frozen)
        return frozen

    def get(self, version: int) -> ShotVersion:
        try:
            item = self._versions[int(version)]
        except (IndexError, ValueError) as exc:
            raise KeyError(f"unknown shot version: {version}") from exc
        return ShotVersion.from_dict(item.to_dict())

    def latest(self) -> ShotVersion:
        if not self._versions:
            raise KeyError(f"no versions recorded for {self.shot_id}")
        return self.get(len(self._versions) - 1)

    def restore(self, version: int) -> Any:
        return copy.deepcopy(self.get(version).plan)

    def __len__(self) -> int:
        return len(self._versions)

    def to_dict(self) -> Dict[str, Any]:
        return {"shot_id": self.shot_id,
                "versions": [item.to_dict() for item in self._versions]}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ShotVersionHistory":
        history = cls(str(data["shot_id"]))
        for item in data.get("versions", ()):
            history.append(ShotVersion.from_dict(item))
        return history


__all__ = ["ShotVersion", "ShotVersionHistory"]
