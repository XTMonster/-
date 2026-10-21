"""Consumer-side validation of a canonical delivery classification."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence, Tuple

from ..contracts.quality import DELIVERY_CLASSES


CONCAT_FILENAMES = {
    "final": "blockout_full.mp4",
    "partial": "blockout_partial.mp4",
    "diagnostic": "blockout_diagnostic.mp4",
}
STALE_CONCAT_FILENAMES = (
    "blockout_full.mp4",
    "blockout_partial.mp4",
    "blockout_diagnostic.mp4",
    "final_video.mp4",
)


def concat_filename_for(delivery_class: str) -> str:
    return CONCAT_FILENAMES.get(str(delivery_class or ""), "")


def clear_stale_concat_outputs(out_dir: Path | str) -> list[str]:
    """Remove only prior concatenated films from one export directory."""
    folder = Path(out_dir)
    removed: list[str] = []
    for name in STALE_CONCAT_FILENAMES:
        path = folder / name
        if not (path.is_file() or path.is_symlink()):
            continue
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        removed.append(name)
    return removed


def clear_stale_shot_video_outputs(out_dir: Path | str) -> list[str]:
    """Remove prior per-shot clips without touching concatenated identities."""
    folder = Path(out_dir)
    if not folder.is_dir():
        return []
    removed: list[str] = []
    canonical = set(STALE_CONCAT_FILENAMES)
    for path in sorted(folder.glob("blockout_*.mp4")):
        if path.name in canonical or not (path.is_file() or path.is_symlink()):
            continue
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        removed.append(path.name)
    return removed


def clear_stale_shot_outputs(
    export_dir: Path | str, shot_ids: Sequence[str],
) -> list[str]:
    """Remove per-shot products for the named plan shots only."""
    folder = Path(export_dir)
    removed: list[str] = []
    for raw_shot_id in shot_ids:
        shot_id = str(raw_shot_id or "")
        if (
            not shot_id
            or shot_id in {".", ".."}
            or "/" in shot_id
            or "\\" in shot_id
        ):
            continue
        files = [
            folder / f"blockout_{shot_id}{suffix}"
            for suffix in (".mp4", ".mkv", ".avi")
        ]
        files.append(folder / "first_frames" / f"{shot_id}.png")
        for path in files:
            if not (path.is_file() or path.is_symlink()):
                continue
            try:
                path.unlink()
            except FileNotFoundError:
                continue
            removed.append(path.relative_to(folder).as_posix())
        directories = [
            folder / f"depth_shot_{shot_id}",
            folder / "masks" / shot_id,
        ]
        for path in directories:
            if path.is_symlink():
                path.unlink()
                removed.append(path.relative_to(folder).as_posix())
            elif path.is_dir():
                shutil.rmtree(path)
                removed.append(path.relative_to(folder).as_posix())
    return removed


def actual_shot_video(
    shot_id: str, path: Path | str, frames: int,
) -> dict[str, Any] | None:
    """Return a shot-video entry only when the claimed file really exists."""
    candidate = Path(path)
    if not candidate.is_file():
        return None
    return {
        "shot_id": str(shot_id),
        "video": str(candidate),
        "frames": int(frames),
    }


@dataclass(frozen=True)
class DeliveryPackage:
    delivery_class: str
    selected_shots: Tuple[str, ...]
    failed_shots: Tuple[str, ...] = ()
    pending_review_shots: Tuple[str, ...] = ()
    reasons: Tuple[str, ...] = ()
    legacy_unscoped: bool = False

    @property
    def blocked(self) -> bool:
        return self.delivery_class == "blocked"

    @property
    def requires_artifacts(self) -> bool:
        return not self.legacy_unscoped and not self.blocked

    @property
    def concat_filename(self) -> str:
        return concat_filename_for(self.delivery_class)


def _ordered_ids(values: Iterable[Any]) -> Tuple[str, ...]:
    return tuple(
        str(value) for value in values or () if str(value)
    )


def _unique(values: Iterable[str]) -> bool:
    values = tuple(values)
    return len(values) == len(set(values))


def resolve_delivery_package(
    quality: Mapping[str, Any] | None,
    shot_ids: Sequence[str],
) -> DeliveryPackage:
    """Validate one producer result without inventing a second classification."""
    ordered = _ordered_ids(shot_ids)
    if not _unique(ordered):
        return DeliveryPackage(
            "blocked", ordered, reasons=("duplicate_plan_shot_ids",))
    if quality is None:
        return DeliveryPackage(
            "", ordered, legacy_unscoped=True)

    producer_reasons = tuple(dict.fromkeys(
        str(item) for item in quality.get("reasons") or [] if str(item)
    ))
    errors: list[str] = []
    class_name = str(quality.get("delivery_class") or "")
    if class_name not in DELIVERY_CLASSES:
        return DeliveryPackage(
            "blocked",
            (),
            reasons=tuple(dict.fromkeys(
                producer_reasons + ("invalid_delivery_class",))),
        )

    selected = _ordered_ids(quality.get("selected_shots") or ())
    passed = _ordered_ids(quality.get("passed_shots") or ())
    failed = _ordered_ids(quality.get("failed_shots") or ())
    pending = _ordered_ids(quality.get("pending_review_shots") or ())
    reviewed = _ordered_ids(quality.get("sequence_reviewed_shots") or ())
    delivered = _ordered_ids(quality.get("delivered_shots") or ())
    plan_set = set(ordered)

    if not _unique(selected) or not _unique(passed) \
            or not _unique(failed) or not _unique(pending) \
            or not _unique(delivered):
        errors.append("duplicate_delivery_shot_ids")
    if set(passed) & set(failed):
        errors.append("passed_failed_overlap")
    if set(pending) & (set(passed) | set(failed)):
        errors.append("pending_overlaps_disposition")
    if any(set(values) - plan_set
           for values in (selected, passed, failed, pending)):
        errors.append("delivery_shot_not_in_plan")
    if not _unique(reviewed):
        errors.append("duplicate_sequence_review_shot_ids")
    if set(reviewed) - plan_set:
        errors.append("sequence_review_shot_not_in_plan")
    if set(delivered) - plan_set:
        errors.append("delivered_shot_not_in_plan")
    artifact_check_complete = quality.get("artifact_check_complete") is True
    if delivered and not artifact_check_complete:
        errors.append("delivered_artifacts_without_complete_check")
    if artifact_check_complete and (
        len(set(delivered)) != len(delivered)
        or set(delivered) != set(selected)
    ):
        errors.append("delivered_artifacts_do_not_match_selection")

    disposition_sets = (set(passed), set(failed), set(pending))
    for shot_id in ordered:
        count = sum(shot_id in values for values in disposition_sets)
        if count == 0:
            errors.append(f"plan_shot_missing_disposition:{shot_id}")
        elif count > 1:
            errors.append(f"plan_shot_multiple_dispositions:{shot_id}")

    if class_name == "blocked":
        return DeliveryPackage(
            "blocked", selected, failed, pending,
            tuple(dict.fromkeys(producer_reasons + tuple(errors))))
    if class_name == "final":
        if set(selected) != plan_set:
            errors.append("final_does_not_select_every_shot")
        if set(passed) != plan_set:
            errors.append("final_passed_set_differs_from_plan")
        if failed or pending:
            errors.append("final_contains_nonpassing_shots")
        if quality.get("sequence_review_passed") is not True:
            errors.append("final_sequence_review_not_passed")
        if reviewed != selected:
            errors.append("final_sequence_review_scope_mismatch")
    elif class_name == "partial":
        if not selected:
            errors.append("partial_has_no_selected_shots")
        if selected != passed:
            errors.append("selected_shots_not_exactly_passed")
        if pending:
            errors.append("partial_contains_pending_review")
        if quality.get("sequence_review_passed") is not True:
            errors.append("partial_sequence_review_not_passed")
        if reviewed != selected:
            errors.append("partial_sequence_review_scope_mismatch")
    elif class_name == "diagnostic":
        if not selected:
            errors.append("diagnostic_has_no_inspection_shots")
        if set(selected) != plan_set:
            errors.append("diagnostic_does_not_select_every_shot")

    if errors:
        return DeliveryPackage(
            "blocked", selected, failed, pending,
            tuple(dict.fromkeys(producer_reasons + tuple(errors))))
    return DeliveryPackage(
        class_name, selected, failed, pending, producer_reasons)


def delivery_artifacts_match(
    package: DeliveryPackage, delivered_shot_ids: Iterable[str],
) -> bool:
    if not package.requires_artifacts:
        return False
    delivered_ids = _ordered_ids(delivered_shot_ids)
    return (
        _unique(delivered_ids)
        and set(delivered_ids) == set(package.selected_shots)
    )


__all__ = [
    "CONCAT_FILENAMES",
    "STALE_CONCAT_FILENAMES",
    "DeliveryPackage",
    "actual_shot_video",
    "clear_stale_concat_outputs",
    "clear_stale_shot_outputs",
    "clear_stale_shot_video_outputs",
    "concat_filename_for",
    "delivery_artifacts_match",
    "resolve_delivery_package",
]
