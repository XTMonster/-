"""Per-shot staging overlays over a continuous scene reference.

The scene-level ``characters[].position`` remains the continuity baseline.
Local blocking revisions live under::

    shot_staging[shot_id][character_name] = {
        "position": {"x": ..., "y": ..., "z": ...},
        "provenance": "agent_local_revision",
        "reason": "..."
    }

No ``bpy`` imports: manifest construction, camera solving, preview staging and
evidence collection all consume this pure contract.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, Mapping

from block_director.contracts.coarse_reference import (
    effective_shot_reference,
    set_shot_character_position as _set_position,
)


SHOT_STAGING_SCHEMA = "shot-staging/v1"
DEFAULT_LOCAL_PROVENANCE = "agent_local_revision"


def effective_character_position(
    reference: Mapping[str, Any],
    shot_id: str,
    name: str,
) -> Dict[str, float] | None:
    """Return the character position effective in exactly one shot."""
    effective = effective_shot_reference(reference, str(shot_id))
    for character in effective.get("characters") or []:
        if not isinstance(character, Mapping) \
                or str(character.get("name") or "") != str(name):
            continue
        position = character.get("position")
        if not isinstance(position, Mapping):
            return None
        return {
            "x": float(position.get("x", 0.0)),
            "y": float(position.get("y", 0.0)),
            "z": float(position.get("z", 0.0)),
        }
    return None


def effective_reference_for_shot(
    reference: Mapping[str, Any],
    shot_id: str,
) -> Dict[str, Any]:
    """Deep-copy a reference with this shot's staging overlay materialised."""
    return effective_shot_reference(reference, str(shot_id))


def shot_effective_character_positions(
    reference: Mapping[str, Any],
) -> Dict[str, Dict[str, Dict[str, float]]]:
    """All shot-effective positions, including explicit baseline entries."""
    result: Dict[str, Dict[str, Dict[str, float]]] = {}
    for shot in reference.get("shots") or []:
        if not isinstance(shot, Mapping):
            continue
        shot_id = str(shot.get("shot_id") or "")
        if not shot_id:
            continue
        names = [str(name) for name in (shot.get("characters") or [])]
        framing = shot.get("framing_target")
        if isinstance(framing, Mapping) \
                and str(framing.get("kind") or "") == "character":
            ref = str(framing.get("ref") or "")
            if ref and ref not in names:
                names.append(ref)
        positions: Dict[str, Dict[str, float]] = {}
        for name in names:
            position = effective_character_position(reference, shot_id, name)
            if position is not None:
                positions[name] = position
        result[shot_id] = positions
    return result


def set_shot_character_position(
    reference: Dict[str, Any],
    shot_id: str,
    name: str,
    target_value: Any,
    *,
    provenance: str = DEFAULT_LOCAL_PROVENANCE,
    reason: str = "",
) -> Dict[str, float]:
    """Write one local staging entry and return the stored position."""
    return _set_position(
        reference,
        shot_id=str(shot_id),
        name=str(name),
        position=target_value,
        provenance=str(provenance or DEFAULT_LOCAL_PROVENANCE),
        reason=str(reason or ""),
    )


__all__ = [
    "SHOT_STAGING_SCHEMA",
    "DEFAULT_LOCAL_PROVENANCE",
    "effective_character_position",
    "effective_reference_for_shot",
    "shot_effective_character_positions",
    "set_shot_character_position",
]
