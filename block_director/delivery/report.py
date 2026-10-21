"""Pure delivery report identity shared by Blender and headless adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping

from ..contracts.quality import DELIVERY_CLASSES
from .failures import (
    delivered_shot_ids,
    passed_shot_ids,
    pending_review_shot_ids,
)


@dataclass
class DeliveryReport:
    out_dir: str = ""
    aborted: bool = False
    reason: str = ""
    files: List[str] = field(default_factory=list)
    shots: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    total_frames: int = 0
    duration_s: float = 0.0
    audit_leaks: List[str] = field(default_factory=list)
    depth_shots: List[Dict[str, Any]] = field(default_factory=list)
    mask_shots: List[Dict[str, Any]] = field(default_factory=list)
    full_video: str = ""
    total_frames_concat: int = 0
    missing_clips: List[str] = field(default_factory=list)
    delivery_class: str = ""
    delivery_quality: Dict[str, Any] = field(default_factory=dict)

    @property
    def canonical_delivery_class(self) -> str:
        if not self.delivery_quality:
            return ""
        top_level = str(self.delivery_class or "")
        nested = str(
            (self.delivery_quality or {}).get("delivery_class") or "")
        if (
            top_level not in DELIVERY_CLASSES
            or nested not in DELIVERY_CLASSES
            or top_level != nested
        ):
            return ""
        return top_level

    @property
    def artifact_evidence_complete(self) -> bool:
        quality = self.delivery_quality or {}
        selected = self._quality_ids("selected_shots")
        delivered = self._quality_ids("delivered_shots")
        return bool(
            quality.get("artifact_check_complete") is True
            and selected
            and len(selected) == len(set(selected))
            and len(delivered) == len(set(delivered))
            and set(delivered) == set(selected)
        )

    @property
    def ok(self) -> bool:
        if self.aborted or not self.files:
            return False
        if self.delivery_quality and not self.canonical_delivery_class:
            return False
        if self.canonical_delivery_class == "blocked":
            return False
        if self.canonical_delivery_class and not self.artifact_evidence_complete:
            return False
        return not self.missing_clips

    def _quality_ids(self, key: str) -> List[str]:
        return [
            str(item)
            for item in (self.delivery_quality or {}).get(key) or []
            if str(item)
        ]

    def to_dict(self) -> Dict[str, Any]:
        actual_delivered = delivered_shot_ids(self.shots)
        quality = dict(self.delivery_quality or {})
        canonical_class = self.canonical_delivery_class
        return {
            "ok": self.ok,
            "aborted": self.aborted,
            "reason": self.reason,
            "out_dir": self.out_dir,
            "files": list(self.files),
            "shots": list(self.shots),
            "warnings": list(self.warnings),
            "total_frames": self.total_frames,
            "duration_s": round(self.duration_s, 2),
            "audit_leaks": list(self.audit_leaks),
            "depth_shots": list(self.depth_shots),
            "mask_shots": list(self.mask_shots),
            "full_video": self.full_video,
            "total_frames_concat": self.total_frames_concat,
            "missing_clips": list(self.missing_clips),
            "delivery_class": canonical_class,
            "delivery_quality": quality,
            "final": bool(canonical_class == "final" and self.ok),
            "delivered_shots": actual_delivered,
            "passed_shots": (
                self._quality_ids("passed_shots")
                if quality else passed_shot_ids(self.shots)),
            "failed_shots": self._quality_ids("failed_shots"),
            "pending_review_shots": (
                self._quality_ids("pending_review_shots")
                if quality else pending_review_shot_ids(self.shots)),
            "selected_shots": self._quality_ids("selected_shots"),
            "artifact_check_complete": bool(
                quality.get("artifact_check_complete")),
        }


__all__ = ["DeliveryReport"]
