"""Pure correction-candidate disposition contract."""

from __future__ import annotations

import copy
from typing import Any, Dict, Iterable, List


def correction_candidate_dispositions(
    candidates: Iterable[Any],
    operations: Iterable[Any],
    *,
    shot_id: str,
) -> List[Dict[str, Any]]:
    """Bind every candidate to applied, rejected, or explicitly deferred."""
    target_shot = str(shot_id or "")
    if not target_shot:
        raise ValueError("shot_id must be non-empty")
    candidate_rows = list(candidates)
    operation_rows = list(operations)
    by_candidate: Dict[str, List[Dict[str, Any]]] = {}
    for raw in operation_rows:
        if not isinstance(raw, dict):
            raise ValueError(f"correction operation must be a dict: {raw!r}")
        referenced = raw.get("candidate_ids")
        if referenced is None and raw.get("candidate_id"):
            referenced = [raw.get("candidate_id")]
        for candidate_id in referenced or ():
            value = str(candidate_id or "")
            if value:
                by_candidate.setdefault(value, []).append(copy.deepcopy(raw))

    result: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for raw in candidate_rows:
        if not isinstance(raw, dict):
            raise ValueError(f"correction candidate must be a dict: {raw!r}")
        candidate_id = str(raw.get("candidate_id") or "")
        if not candidate_id:
            raise ValueError(
                f"correction candidate is missing candidate_id: {raw!r}")
        if candidate_id in seen:
            raise ValueError(f"duplicate candidate_id: {candidate_id}")
        seen.add(candidate_id)
        matched = by_candidate.get(candidate_id, [])
        if any(item.get("applied") is True for item in matched):
            disposition = "applied"
        elif matched:
            disposition = "rejected"
        else:
            disposition = "deferred"
        row = copy.deepcopy(raw)
        row.update({
            "shot_id": target_shot,
            "disposition": disposition,
            "operation_ids": [
                str(item.get("prescription_id") or "")
                for item in matched
                if str(item.get("prescription_id") or "")
            ],
        })
        result.append(row)
    return result


def correction_candidate_lifecycle(
    previous_candidates: Iterable[Any],
    current_candidates: Iterable[Any],
    operations: Iterable[Any],
    *,
    shot_id: str,
) -> List[Dict[str, Any]]:
    """Attach resolved/persisting/new state to terminal dispositions."""
    previous = list(previous_candidates)
    current = list(current_candidates)
    current_by_id: Dict[str, Dict[str, Any]] = {}
    for raw in current:
        if not isinstance(raw, dict):
            raise ValueError(f"correction candidate must be a dict: {raw!r}")
        candidate_id = str(raw.get("candidate_id") or "")
        if not candidate_id:
            raise ValueError(
                f"correction candidate is missing candidate_id: {raw!r}")
        if candidate_id in current_by_id:
            raise ValueError(f"duplicate candidate_id: {candidate_id}")
        current_by_id[candidate_id] = copy.deepcopy(raw)

    rows = correction_candidate_dispositions(
        previous, operations, shot_id=shot_id)
    previous_ids = {
        str(row.get("candidate_id") or "") for row in rows
    }
    for row in rows:
        row["issue_state"] = (
            "persisting"
            if str(row["candidate_id"]) in current_by_id
            else "resolved"
        )
    for candidate_id, raw in current_by_id.items():
        if candidate_id in previous_ids:
            continue
        row = copy.deepcopy(raw)
        row.update({
            "shot_id": str(shot_id),
            "disposition": "deferred",
            "operation_ids": [],
            "issue_state": "new",
        })
        rows.append(row)
    return rows


__all__ = [
    "correction_candidate_dispositions",
    "correction_candidate_lifecycle",
]
