"""Structured coarse-blocking proposals emitted by the director agent.

The agent proposes intent and explicit local changes; the deterministic tool
layer remains responsible for validating and applying them.  A proposal can
never mutate Blender directly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Tuple

COARSE_PROPOSAL_SCHEMA_VERSION = "coarse-proposal/v1"

ALLOWED_CAMERA_COMPONENTS = frozenset({
    "distance", "strafe", "target", "position.y", "position.z",
})
ALLOWED_COMPONENTS = frozenset(
    set(ALLOWED_CAMERA_COMPONENTS) | {"character_position"})


def camera_entity_id(camera: Mapping[str, Any] | None, shot_id: str) -> str:
    """Canonical camera entity for one shot.

    The validator, tool schema and agent prompt all derive their legal camera
    names from this function so the fallback spelling cannot drift.
    """
    return str(
        (camera or {}).get("camera_id")
        or f"cam_{shot_id}"
    )


def legal_entities_by_shot(
    reference: Mapping[str, Any],
    shot_ids: list[str] | None = None,
) -> Dict[str, Dict[str, List[str]]]:
    """Return the exact entity values a proposal may use for each shot."""
    shots = {
        str(item.get("shot_id") or ""): item
        for item in (reference.get("shots") or [])
        if isinstance(item, Mapping) and item.get("shot_id")
    }
    cameras = {
        str(item.get("shot_id") or ""): item
        for item in (reference.get("camera_intents") or [])
        if isinstance(item, Mapping) and item.get("shot_id")
    }
    wanted = (
        [str(item) for item in shot_ids]
        if shot_ids is not None
        else list(shots)
    )
    result: Dict[str, Dict[str, List[str]]] = {}
    for shot_id in wanted:
        shot = shots.get(shot_id) or {}
        camera = cameras.get(shot_id)
        camera_values: List[str] = []
        if camera is not None:
            explicit = str(camera.get("camera_id") or "")
            fallback = f"cam_{shot_id}"
            if explicit:
                camera_values.append(explicit)
            if fallback not in camera_values:
                camera_values.append(fallback)
        characters = [
            str(name) for name in (shot.get("characters") or [])
            if str(name).strip()
        ]
        result[shot_id] = {
            "camera": camera_values,
            "character": characters,
        }
    return result


class CoarseProposalError(ValueError):
    """Agent proposal failed at a named layer of the coarse transaction.

    ``code`` is intentionally stable and machine-readable.  The coarse loop
    forwards it to ``blocked_code`` instead of flattening every provider-side
    failure into one generic error.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "coarse_proposal_invalid",
        details: Mapping[str, Any] | None = None,
        recoverable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = str(code or "coarse_proposal_invalid")
        self.details = dict(details or {})
        #: Protocol failures are model-output variance, not evidence that the
        #: rendered observation is unusable.  The coarse loop may retry these
        #: against the same observation under its proposal-attempt ceiling.
        self.recoverable = bool(recoverable)


@dataclass(frozen=True)
class CoarseProposalRequest:
    """One immutable observation handed to the coarse director agent.

    The loop owns observation capture; providers receive this request and
    return a proposal.  Keeping one DTO prevents the loop and provider adapters
    from drifting into separate keyword APIs.
    """

    round_no: int
    observation_id: str
    reference: Mapping[str, Any]
    report: Mapping[str, Any]
    manifest: Mapping[str, Any] = field(default_factory=dict)
    world_state: Mapping[str, Any] = field(default_factory=dict)
    frames: Tuple[Mapping[str, Any], ...] = ()
    #: Remeasured decisions from earlier rounds.  This is deliberately a
    #: compact ledger, not the full reports or frames: after a rollback the
    #: next Agent call must know which local transformations already lost or
    #: repeated a physical state, without replaying unbounded scene evidence.
    history: Tuple[Mapping[str, Any], ...] = ()
    knowledge_context: str = ""

    def __post_init__(self) -> None:
        import copy

        object.__setattr__(self, "reference", copy.deepcopy(dict(self.reference)))
        object.__setattr__(self, "report", copy.deepcopy(dict(self.report)))
        object.__setattr__(
            self, "manifest", copy.deepcopy(dict(self.manifest)))
        object.__setattr__(
            self, "world_state", copy.deepcopy(dict(self.world_state)))
        object.__setattr__(
            self,
            "frames",
            tuple(
                copy.deepcopy(dict(item))
                for item in self.frames
                if isinstance(item, Mapping)
            ),
        )
        object.__setattr__(
            self,
            "history",
            tuple(
                copy.deepcopy(dict(item))
                for item in self.history
                if isinstance(item, Mapping)
            ),
        )
        object.__setattr__(self, "knowledge_context", str(
            self.knowledge_context or ""))

    @property
    def frame_digests(self) -> Dict[str, Dict[str, str]]:
        """Stable shorthand for prompt evidence and proposal provenance."""
        result: Dict[str, Dict[str, str]] = {}
        for frame in self.frames:
            shot_id = str(frame.get("shot_id") or "")
            phase = str(frame.get("phase") or "")
            key = f"{shot_id}:{phase}" if shot_id or phase else ""
            if not key:
                continue
            result[key] = {
                "frame": str(frame.get("frame") or ""),
                "file_sha256": str(frame.get("file_sha256") or ""),
                "pixel_sha256": str(frame.get("pixel_sha256") or ""),
                "path": str(frame.get("path") or frame.get("png") or ""),
            }
        return result


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise CoarseProposalError(f"{field} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise CoarseProposalError(
            f"{field} must be a finite number") from exc
    if not math.isfinite(number):
        raise CoarseProposalError(f"{field} must be a finite number")
    return number


def _validate_vector(value: Any, field: str) -> None:
    if isinstance(value, Mapping):
        for axis in ("x", "y", "z"):
            if axis not in value:
                raise CoarseProposalError(f"{field} is missing {axis}")
            _finite_number(value[axis], f"{field}.{axis}")
        return
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        for index, item in enumerate(value[:3]):
            _finite_number(item, f"{field}[{index}]")
        return
    raise CoarseProposalError(f"{field} must be a 3D coordinate")


def validate_coarse_proposal(
    proposal: Any,
    *,
    reference: Mapping[str, Any],
) -> Dict[str, Any]:
    """Validate authority and shape, returning a deep-ish normalised copy."""
    if not isinstance(proposal, Mapping):
        raise CoarseProposalError("proposal must be an object")
    if proposal.get("schema_version") != COARSE_PROPOSAL_SCHEMA_VERSION:
        raise CoarseProposalError(
            f"schema_version must be {COARSE_PROPOSAL_SCHEMA_VERSION}")
    raw_prescriptions = proposal.get("prescriptions")
    if not isinstance(raw_prescriptions, list) or not raw_prescriptions:
        raise CoarseProposalError("proposal.prescriptions must be non-empty")
    shots = {
        str(item.get("shot_id") or ""): item
        for item in (reference.get("shots") or [])
        if isinstance(item, Mapping)
    }
    characters = {
        str(item.get("name") or "")
        for item in (reference.get("characters") or [])
        if isinstance(item, Mapping)
    }
    cameras = {
        str(item.get("shot_id") or ""): item
        for item in (reference.get("camera_intents") or [])
        if isinstance(item, Mapping)
    }
    prescriptions: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(raw_prescriptions):
        if not isinstance(raw, Mapping):
            raise CoarseProposalError(
                f"prescriptions[{index}] must be an object")
        item = dict(raw)
        prescription_id = str(item.get("prescription_id") or "").strip()
        if not prescription_id:
            raise CoarseProposalError(
                f"prescriptions[{index}] is missing prescription_id")
        if prescription_id in seen_ids:
            raise CoarseProposalError(
                f"duplicate prescription_id: {prescription_id}")
        seen_ids.add(prescription_id)
        shot_id = str(item.get("shot_id") or "").strip()
        if shot_id not in shots:
            raise CoarseProposalError(
                f"{prescription_id}: unknown shot_id {shot_id!r}")
        if shot_id not in cameras:
            raise CoarseProposalError(
                f"{prescription_id}: shot has no camera intent {shot_id!r}")
        component = str(item.get("component") or "").strip()
        if component not in ALLOWED_COMPONENTS:
            raise CoarseProposalError(
                f"{prescription_id}: unsupported component {component!r}")
        scope = str(item.get("scope") or "").strip()
        expected_scope = (
            "character" if component == "character_position" else "camera")
        if scope != expected_scope:
            raise CoarseProposalError(
                f"{prescription_id}: scope must be {expected_scope!r}")
        entity = str(item.get("entity") or "").strip()
        if not entity:
            raise CoarseProposalError(
                f"{prescription_id}: entity is required")
        if scope == "character":
            if entity not in characters:
                raise CoarseProposalError(
                    f"{prescription_id}: unknown character {entity!r}")
            if entity not in {
                    str(name) for name in
                    (shots[shot_id].get("characters") or [])}:
                raise CoarseProposalError(
                    f"{prescription_id}: character {entity!r} is not in "
                    f"{shot_id}")
        else:
            allowed_camera_entities = set(
                legal_entities_by_shot(
                    reference, [shot_id])[shot_id]["camera"])
            if entity not in allowed_camera_entities:
                raise CoarseProposalError(
                    f"{prescription_id}: camera entity {entity!r} does not "
                    f"belong to {shot_id}")
        reason = str(item.get("reason") or "").strip()
        if not reason:
            raise CoarseProposalError(
                f"{prescription_id}: reason is required")
        refs = item.get("evidence_refs")
        if not isinstance(refs, list) or not [
                str(ref).strip() for ref in refs if str(ref).strip()]:
            raise CoarseProposalError(
                f"{prescription_id}: evidence_refs must be non-empty")
        target_value = item.get("target_value")
        if component in {
                "target", "character_position", "position.y", "position.z"}:
            if component in {"target", "character_position"}:
                _validate_vector(
                    target_value, f"{prescription_id}.target_value")
            else:
                _finite_number(
                    target_value, f"{prescription_id}.target_value")
        elif component in {"distance", "strafe"}:
            if not isinstance(target_value, Mapping):
                raise CoarseProposalError(
                    f"{prescription_id}.target_value must be an object")
            _validate_vector(
                target_value.get("position"),
                f"{prescription_id}.target_value.position")
            if "target" in target_value:
                _validate_vector(
                    target_value.get("target"),
                    f"{prescription_id}.target_value.target")
        item["prescription_id"] = prescription_id
        item["shot_id"] = shot_id
        item["component"] = component
        item["scope"] = scope
        item["entity"] = entity
        item["reason"] = reason
        item["evidence_refs"] = [
            str(ref).strip() for ref in refs if str(ref).strip()]
        if "candidate_ids" in item:
            candidate_ids = item["candidate_ids"]
            if not isinstance(candidate_ids, list) \
                    or not candidate_ids \
                    or any(not isinstance(value, str) or not value.strip()
                           for value in candidate_ids):
                raise CoarseProposalError(
                    f"{prescription_id}: candidate_ids must be a non-empty "
                    "array of non-empty strings when present")
            item["candidate_ids"] = [
                str(value).strip() for value in candidate_ids]
        prescriptions.append(item)

    result = dict(proposal)
    result["schema_version"] = COARSE_PROPOSAL_SCHEMA_VERSION
    result["prescriptions"] = prescriptions
    result["reason"] = str(proposal.get("reason") or "").strip()
    return result


def emit_coarse_proposal_tool(reference: Mapping[str, Any]) -> Dict[str, Any]:
    """OpenAI-compatible strict-ish schema for the coarse director call."""
    shot_ids = [
        str(item.get("shot_id") or "")
        for item in (reference.get("shots") or [])
        if isinstance(item, Mapping) and item.get("shot_id")
    ]
    character_names = [
        str(item.get("name") or "")
        for item in (reference.get("characters") or [])
        if isinstance(item, Mapping) and item.get("name")
    ]
    legal = legal_entities_by_shot(reference, shot_ids)
    entity_values: List[str] = []
    for shot_id in shot_ids:
        row = legal.get(shot_id) or {}
        for scope in ("character", "camera"):
            for value in row.get(scope) or []:
                if value not in entity_values:
                    entity_values.append(value)
    for name in character_names:
        if name not in entity_values:
            entity_values.append(name)
    vector = {
        "type": "object",
        "required": ["x", "y", "z"],
        "additionalProperties": False,
        "properties": {
            "x": {"type": "number"},
            "y": {"type": "number"},
            "z": {"type": "number"},
        },
    }
    camera_position_value = {
        "type": "object",
        "required": ["position"],
        "additionalProperties": False,
        "properties": {
            "position": vector,
            "target": vector,
        },
    }
    component_shapes = (
        ("distance", "camera", camera_position_value),
        ("strafe", "camera", camera_position_value),
        ("target", "camera", vector),
        ("position.y", "camera", {"type": "number"}),
        ("position.z", "camera", {"type": "number"}),
        ("character_position", "character", vector),
    )
    return {
        "type": "function",
        "function": {
            "name": "emit_coarse_proposal",
            "description": (
                "提交本轮粗排局部修改提案。只提出影响镜头构图的结构化改动；"
                "程序会校验、应用、重建、重新测量并决定是否采纳。"),
            "parameters": {
                "type": "object",
                "required": [
                    "schema_version", "reason", "prescriptions"],
                "additionalProperties": False,
                "properties": {
                    "schema_version": {
                        "type": "string",
                        "enum": [COARSE_PROPOSAL_SCHEMA_VERSION],
                    },
                    "reason": {"type": "string", "minLength": 1},
                    "prescriptions": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "required": [
                                "prescription_id", "scope", "shot_id",
                                "entity", "component", "target_value",
                                "reason", "evidence_refs"],
                            "additionalProperties": False,
                            "properties": {
                                "prescription_id": {"type": "string"},
                                "scope": {
                                    "type": "string",
                                    "enum": ["camera", "character"],
                                },
                                "shot_id": {
                                    "type": "string",
                                    "enum": shot_ids,
                                },
                                "entity": {
                                    "type": "string",
                                    "enum": entity_values,
                                    "description": (
                                        "只允许本场已知实体。camera 范围必须"
                                        "逐字填写 legal_entities_by_shot[shot_id]"
                                        ".camera 中的值，不得写 'camera'；"
                                        "character 范围填写同一表中该镜的"
                                        "精确角色名。"
                                    ),
                                },
                                "component": {
                                    "type": "string",
                                    "enum": sorted(ALLOWED_COMPONENTS),
                                },
                                "target_value": {
                                    "oneOf": [
                                        {"type": "number"},
                                        vector,
                                        camera_position_value,
                                    ],
                                    "description": (
                                        "target / character_position: {x,y,z}; "
                                        "distance / strafe: "
                                        "{position:{x,y,z},target?:{x,y,z}}; "
                                        "position.y / position.z: number."
                                    ),
                                },
                                "reason": {
                                    "type": "string", "minLength": 1},
                                "evidence_refs": {
                                    "type": "array",
                                    "minItems": 1,
                                    "items": {"type": "string"},
                                },
                                "candidate_ids": {
                                    "type": "array",
                                    "minItems": 1,
                                    "items": {
                                        "type": "string",
                                        "minLength": 1,
                                    },
                                    "description": (
                                        "逐字引用失败镜 correction_candidates "
                                        "中的 candidate_id；没有候选时省略。"),
                                },
                            },
                            "allOf": [
                                {
                                    "if": {
                                        "properties": {
                                            "component": {"const": component},
                                        },
                                        "required": ["component"],
                                    },
                                    "then": {
                                        "properties": {
                                            "scope": {"const": scope},
                                            "target_value": target_value_schema,
                                        },
                                        "required": ["scope", "target_value"],
                                    },
                                }
                                for component, scope, target_value_schema
                                in component_shapes
                            ],
                        },
                    },
                },
            },
        },
    }


__all__ = [
    "COARSE_PROPOSAL_SCHEMA_VERSION",
    "ALLOWED_CAMERA_COMPONENTS",
    "ALLOWED_COMPONENTS",
    "CoarseProposalRequest",
    "CoarseProposalError",
    "camera_entity_id",
    "legal_entities_by_shot",
    "validate_coarse_proposal",
    "emit_coarse_proposal_tool",
]
