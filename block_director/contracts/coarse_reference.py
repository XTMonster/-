"""粗编排参考世界坐标 JSON 契约（Ticket 01）。

纯层（不 import bpy）。这份 JSON 是粗排修正循环的**可修改输入与单一真源**：
体块、角色、道具、锚点、相机意图全部写入一份版本化文档；粗排修正循环只改这份
JSON，再重建场景。结构以 ``cinema/spatial_design.build_design_snapshot`` 的
产出为骨架，外加 ``revisions[]`` 修正留痕。

与 ``contracts/blockout.py`` 同口径：轻量结构守卫供生产侧零运行时依赖使用；
完整 jsonschema 校验由测试链负责。
"""

from __future__ import annotations

import json
import copy
from typing import Any, Dict, List, Mapping, MutableMapping

from .audit import canonical_fingerprint

COARSE_REFERENCE_SCHEMA_VERSION = "coarse-world-reference/v1"
LEGACY_DESIGN_SCHEMA_VERSION = "spatial-design-snapshot/v1"
DESIGN_SCHEMA_VERSION = "spatial-understanding-design/v1"

#: v2 ``motion.speed`` is a qualitative closed set.  Coarse routes and their
#: collision/readability checks need the numeric design speed the legacy ledger
#: recorded, so the conversion lives with that wire contract instead of being
#: re-invented by each consumer.
MOTION_SPEED_M_S: Dict[str, float] = {"walk": 1.0, "run": 3.0}

#: 必需节与类型（守卫用，单一真源）。
_REQUIRED_LIST_KEYS = (
    "characters", "props", "anchors", "camera_intents", "shots", "revisions",
)


def _has_coord(value: Any) -> bool:
    """坐标可接受 dict {x,y,z} 或 list/tuple [x,y,z]（与管线同源）。"""
    if isinstance(value, Mapping):
        return all(k in value for k in ("x", "y", "z"))
    return isinstance(value, (list, tuple)) and len(value) >= 3


def load_coarse_reference(text: str) -> Dict[str, Any]:
    """从 JSON 文本读入粗编排参考文档（确定性 dict）。"""
    return json.loads(text)


def dump_coarse_reference(doc: Mapping[str, Any]) -> str:
    """确定性序列化：同一输入两次输出逐位一致。"""
    return json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=2)


def coarse_reference_from_design(
    design: Mapping[str, Any],
    *,
    shots: List[Mapping[str, Any]] | None = None,
    fps: float | None = None,
) -> Dict[str, Any]:
    """Promote a spatial design snapshot to the coarse-reference contract.

    ``cinema.spatial_design.build_design_snapshot`` owns the geometric design
    conversion, while this contract owns the coarse loop's versioned wire
    document.  Keeping the promotion here prevents the pipeline from writing a
    design snapshot under a filename that claims a different schema.

    ``shots`` is the plan-owned semantic layer attached after geometric
    conversion.  Existing ``revisions`` are preserved when re-promoting a
    document; a fresh design starts with an empty revision ledger.
    """
    if not isinstance(design, Mapping):
        raise TypeError(
            f"design must be a mapping, got {type(design).__name__}")
    if fps is not None and (
            isinstance(fps, bool) or not isinstance(fps, (int, float))
            or float(fps) <= 0.0):
        raise ValueError("fps must be a positive number")

    version = str(design.get("schema_version") or "")
    if version == DESIGN_SCHEMA_VERSION:
        result = _coarse_reference_from_design_v2(
            design, shots=shots, fps=fps)
    elif version in {
        LEGACY_DESIGN_SCHEMA_VERSION,
        COARSE_REFERENCE_SCHEMA_VERSION,
    }:
        result = copy.deepcopy(dict(design))
        result["schema_version"] = COARSE_REFERENCE_SCHEMA_VERSION
    else:
        raise ValueError(
            "unsupported design schema_version "
            f"{version!r}; expected {DESIGN_SCHEMA_VERSION!r} or "
            f"{LEGACY_DESIGN_SCHEMA_VERSION!r}")
    if shots is not None:
        if not isinstance(shots, (list, tuple)):
            raise TypeError("shots must be a sequence of mappings")
        result["shots"] = [copy.deepcopy(dict(shot)) for shot in shots]
    else:
        result.setdefault("shots", [])
    result.setdefault("revisions", [])
    findings = validate_coarse_reference(result)
    if findings:
        raise ValueError(
            "invalid coarse reference: " + "; ".join(findings))
    return result


def _unwrap_design_field(
    field: Any,
    *,
    label: str,
) -> tuple[Any, str | None]:
    """Return ``(value, provenance)`` from one v2 field wrapper."""
    if field is None:
        return None, None
    if not isinstance(field, Mapping) or "value" not in field:
        raise ValueError(f"{label} must be a v2 field object or null")
    return copy.deepcopy(field.get("value")), (
        str(field.get("provenance") or "") or None)


def _as_vector(value: Any, *, label: str) -> list[float] | None:
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        raise ValueError(f"{label} must contain three numbers")
    try:
        return [float(value[0]), float(value[1]), float(value[2])]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must contain three numbers") from exc


def _as_position(value: Any, *, label: str) -> Dict[str, float] | None:
    vector = _as_vector(value, label=label)
    if vector is None:
        return None
    return {"x": vector[0], "y": vector[1], "z": vector[2]}


def _coarse_motion(
    motion: Any,
    *,
    shot_id: str,
    label: str,
) -> Dict[str, Any] | None:
    if motion is None:
        return None
    if not isinstance(motion, Mapping):
        raise ValueError(f"{label}.motion must be an object or null")
    start = _as_vector(
        motion.get("from", motion.get("start")),
        label=f"{label}.motion.from",
    )
    end = _as_vector(
        motion.get("to", motion.get("end")),
        label=f"{label}.motion.to",
    )
    if start is None or end is None:
        raise ValueError(f"{label}.motion needs both from/to coordinates")
    action_type = str(motion.get("action_type") or "").strip()
    action_speed_class = action_type.removesuffix("_to")
    speed_class = (
        action_speed_class
        if action_speed_class in MOTION_SPEED_M_S
        else str(motion.get("speed") or "").strip())
    speed = MOTION_SPEED_M_S.get(speed_class)
    if speed is None:
        raise ValueError(
            f"{label}.motion.speed {speed_class!r} is not one of "
            f"{sorted(MOTION_SPEED_M_S)}")
    result: Dict[str, Any] = {
        "shot_id": str(shot_id),
        "start": start,
        "end": end,
        "speed_m_s": speed,
        "provenance": str(motion.get("provenance") or "plan_intent"),
    }
    for key in ("start_frame", "end_frame"):
        if motion.get(key) is not None:
            result[key] = int(motion[key])
    return result


def _coarse_reference_from_design_v2(
    design: Mapping[str, Any],
    *,
    shots: List[Mapping[str, Any]] | None,
    fps: float | None,
) -> Dict[str, Any]:
    """Convert planned v2 spatial facts into the coarse loop's stable shape."""
    from .spatial_snapshot import validate_spatial_artifact

    findings = validate_spatial_artifact(design, "design")
    if findings:
        raise ValueError(
            "invalid spatial-understanding design: " + "; ".join(findings))

    ordered_shot_ids = []
    if shots:
        ordered_shot_ids = [
            str(row.get("shot_id") or "")
            for _, row in sorted(
                enumerate(shots),
                key=lambda item: (
                    int(item[1].get("order"))
                    if item[1].get("order") is not None else item[0],
                    item[0],
                ),
            )
            if str(row.get("shot_id") or "")
        ]
    else:
        ordered_shot_ids = [
            str(shot_id) for shot_id in (design.get("shot_ids") or [])
            if str(shot_id)
        ]
    shot_order = {
        shot_id: index for index, shot_id in enumerate(ordered_shot_ids)
    }

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for index, raw in enumerate(design.get("characters") or []):
        if not isinstance(raw, Mapping):
            raise ValueError(f"characters[{index}] must be an object")
        name = str(raw.get("id") or "")
        if not name:
            raise ValueError(f"characters[{index}] is missing id")
        grouped.setdefault(name, []).append(dict(raw))

    characters: List[Dict[str, Any]] = []
    shot_staging: Dict[str, Dict[str, Any]] = {}
    notes = [str(item) for item in (design.get("notes") or [])]
    for name, raw_entries in grouped.items():
        entries = [
            entry
            for _, entry in sorted(
                enumerate(raw_entries),
                key=lambda item: (
                    shot_order.get(
                        str(item[1].get("shot_id") or ""),
                        len(shot_order),
                    ),
                    item[0],
                ),
            )
        ]
        resolved_positions: List[tuple[Dict[str, Any], str | None]] = []
        resolved_facings: List[tuple[list[float], str | None]] = []
        rotations: List[Dict[str, Any]] = []
        motions: List[Dict[str, Any]] = []
        gazes: List[Dict[str, Any]] = []
        facing_by_shot: List[Dict[str, Any]] = []
        unresolved: List[str] = []

        for entry in entries:
            shot_id = str(entry.get("shot_id") or "")
            position_value, position_provenance = _unwrap_design_field(
                entry.get("position"),
                label=f"character {name}.{shot_id}.position",
            )
            position = _as_position(
                position_value,
                label=f"character {name}.{shot_id}.position",
            )
            if position is not None:
                resolved_positions.append((position, position_provenance))

            facing_value, facing_provenance = _unwrap_design_field(
                entry.get("facing"),
                label=f"character {name}.{shot_id}.facing",
            )
            facing = _as_vector(
                facing_value,
                label=f"character {name}.{shot_id}.facing",
            )
            if facing is not None:
                resolved_facings.append((facing, facing_provenance))
                if shot_id:
                    facing_by_shot.append({
                        "shot_id": shot_id,
                        "direction": facing,
                        "provenance": facing_provenance or "plan_intent",
                    })

            rotation = entry.get("rotation")
            if isinstance(rotation, Mapping) and shot_id:
                rotations.append({"shot_id": shot_id, **copy.deepcopy(dict(rotation))})

            motion = _coarse_motion(
                entry.get("motion"),
                shot_id=shot_id,
                label=f"character {name}.{shot_id}",
            )
            if motion is not None:
                motions.append(motion)

            gaze = entry.get("gaze")
            if isinstance(gaze, Mapping) and shot_id:
                direction_value, direction_provenance = _unwrap_design_field(
                    gaze.get("direction"),
                    label=f"character {name}.{shot_id}.gaze.direction",
                )
                direction = _as_vector(
                    direction_value,
                    label=f"character {name}.{shot_id}.gaze.direction",
                )
                gazes.append({
                    "shot_id": shot_id,
                    "target_id": (
                        str(gaze.get("target_id"))
                        if gaze.get("target_id") is not None else None),
                    "direction": direction,
                    "provenance": str(
                        gaze.get("provenance")
                        or direction_provenance
                        or "plan_intent"),
                })

            unresolved.extend(
                f"{shot_id}:{item}" if shot_id else str(item)
                for item in (entry.get("unresolved") or []))

        if not resolved_positions:
            baseline_position = None
            baseline_provenance = None
        else:
            baseline_position, baseline_provenance = resolved_positions[0]
            for entry in entries:
                shot_id = str(entry.get("shot_id") or "")
                value, provenance = _unwrap_design_field(
                    entry.get("position"),
                    label=f"character {name}.{shot_id}.position",
                )
                position = _as_position(
                    value,
                    label=f"character {name}.{shot_id}.position",
                )
                if (shot_id and position is not None
                        and position != baseline_position):
                    shot_staging.setdefault(shot_id, {})[name] = {
                        "position": copy.deepcopy(position),
                        "provenance": (
                            provenance or baseline_provenance
                            or "plan_intent"),
                        "reason": (
                            "v2 design changed this character's position "
                            "from the scene continuity baseline"),
                    }

        character: Dict[str, Any] = {
            "name": name,
            "position": copy.deepcopy(baseline_position),
            "facing": (
                copy.deepcopy(resolved_facings[0][0])
                if resolved_facings else None),
            "rotation": (
                copy.deepcopy(rotations[0]) if rotations else None),
            "motion": copy.deepcopy(motions[0]) if motions else None,
            "gaze": copy.deepcopy(gazes[0]) if gazes else None,
            "motion_by_shot": motions,
            "gaze_by_shot": gazes,
            "facing_by_shot": facing_by_shot,
            "rotation_by_shot": rotations,
            "unresolved": unresolved,
            "provenance": baseline_provenance or "plan_intent",
        }
        if baseline_position is None:
            notes.append(
                f"角色 {name} 在 v2 设计中无已解析站位；粗排保留未解析，不猜")
        characters.append(character)

    props: List[Dict[str, Any]] = []
    for index, raw in enumerate(design.get("props") or []):
        if not isinstance(raw, Mapping):
            raise ValueError(f"props[{index}] must be an object")
        value, provenance = _unwrap_design_field(
            raw.get("position"),
            label=f"props[{index}].position",
        )
        props.append({
            "id": str(raw.get("id") or ""),
            "kind": str(raw.get("kind") or "prop"),
            "owner": raw.get("owner") or None,
            "parent": raw.get("parent") or None,
            "position": _as_vector(
                value, label=f"props[{index}].position"),
            "rotation": copy.deepcopy(raw.get("rotation")),
            "motion": copy.deepcopy(raw.get("motion")),
            "unresolved": list(raw.get("unresolved") or []),
            "provenance": provenance,
        })

    anchors: List[Dict[str, Any]] = []
    for index, raw in enumerate(design.get("anchors") or []):
        if not isinstance(raw, Mapping):
            raise ValueError(f"anchors[{index}] must be an object")
        value, provenance = _unwrap_design_field(
            raw.get("position"),
            label=f"anchors[{index}].position",
        )
        status = str(raw.get("status") or "")
        resolved = status == "resolved"
        position = _as_vector(
            value, label=f"anchors[{index}].position")
        if resolved != (position is not None):
            raise ValueError(
                f"anchors[{index}] status {status!r} disagrees with position")
        anchors.append({
            "label": str(raw.get("label") or ""),
            "position": position,
            "provenance": provenance,
            "resolved": resolved,
            "unresolved_reason": str(raw.get("reason") or ""),
            "unresolved": list(raw.get("unresolved") or []),
            "unit": {"position": "m"},
        })

    cameras: List[Dict[str, Any]] = []
    for index, raw in enumerate(design.get("camera_intents") or []):
        if not isinstance(raw, Mapping):
            raise ValueError(f"camera_intents[{index}] must be an object")
        shot_id = str(raw.get("shot_id") or "")
        position_value, position_provenance = _unwrap_design_field(
            raw.get("position"),
            label=f"camera_intents[{index}].position",
        )
        target_value, target_provenance = _unwrap_design_field(
            raw.get("target"),
            label=f"camera_intents[{index}].target",
        )
        lens_value, lens_provenance = _unwrap_design_field(
            raw.get("lens_mm"),
            label=f"camera_intents[{index}].lens_mm",
        )
        fov_value, _ = _unwrap_design_field(
            raw.get("fov_degrees"),
            label=f"camera_intents[{index}].fov_degrees",
        )
        position = _as_vector(
            position_value,
            label=f"camera_intents[{index}].position",
        )
        target = _as_vector(
            target_value,
            label=f"camera_intents[{index}].target",
        )
        rotation_value, _ = _unwrap_design_field(
            raw.get("rotation"),
            label=f"camera_intents[{index}].rotation",
        )
        movement_value, _ = _unwrap_design_field(
            raw.get("movement"),
            label=f"camera_intents[{index}].movement",
        )
        if fov_value is not None:
            if not isinstance(fov_value, Mapping):
                raise ValueError(
                    f"camera_intents[{index}].fov_degrees.value must be "
                    "an object with horizontal/vertical")
            fov_horizontal = fov_value.get("horizontal")
            if fov_horizontal is None:
                raise ValueError(
                    f"camera_intents[{index}] has no horizontal fov")
            fov_horizontal = float(fov_horizontal)
        else:
            fov_horizontal = None
        unresolved = [str(item) for item in (raw.get("unresolved") or [])]
        resolved = position is not None and target is not None
        cameras.append({
            "shot_id": shot_id,
            "position": position,
            "target": target,
            "lens": float(lens_value) if lens_value is not None else None,
            "fov_deg": fov_horizontal,
            "rotation": rotation_value,
            "movement": movement_value,
            "provenance": (
                position_provenance or target_provenance
                or lens_provenance or "plan_intent"),
            "resolved": resolved,
            "unresolved": unresolved,
            "unresolved_reason": (
                "" if resolved
                else "v2 camera fields unresolved: " + ",".join(unresolved)),
        })

    return {
        "schema_version": COARSE_REFERENCE_SCHEMA_VERSION,
        "scene_id": str(design.get("scene_id") or ""),
        "characters": characters,
        "props": props,
        "anchors": anchors,
        "camera_intents": cameras,
        "shots": [],
        "revisions": [],
        "shot_staging": shot_staging,
        "notes": notes,
        "source_design_schema_version": DESIGN_SCHEMA_VERSION,
        "source_design_revision": copy.deepcopy(design.get("revision")),
        "source_design_fingerprint": canonical_fingerprint(design),
        "fps": float(fps) if fps is not None else None,
    }


def validate_coarse_reference(doc: Any) -> List[str]:
    """轻量结构守卫：缺必需节/坏类型报 findings；通过返回空表。"""
    findings: List[str] = []
    if not isinstance(doc, Mapping):
        return ["粗编排参考必须是 Mapping"]
    if doc.get("schema_version") != COARSE_REFERENCE_SCHEMA_VERSION:
        findings.append(
            f"schema_version 必须为 {COARSE_REFERENCE_SCHEMA_VERSION!r}")
    for key in _REQUIRED_LIST_KEYS:
        if key not in doc:
            findings.append(f"缺必需键 {key}")
        elif not isinstance(doc[key], list):
            findings.append(f"{key} 必须是数组")
    for key in ("scene_id",):
        if key in doc and not isinstance(doc[key], str):
            findings.append(f"{key} 必须是字符串")
    if isinstance(doc.get("characters"), list):
        for i, char in enumerate(doc.get("characters") or []):
            if not isinstance(char, Mapping) or not char.get("name"):
                findings.append(f"characters[{i}] 缺 name")
            elif (char.get("position") is not None
                  and not _has_coord(char.get("position"))):
                findings.append(
                    f"characters[{i}].position 必须是坐标或 null")
    if isinstance(doc.get("camera_intents"), list):
        for i, cam in enumerate(doc.get("camera_intents") or []):
            if not isinstance(cam, Mapping) or not cam.get("shot_id"):
                findings.append(f"camera_intents[{i}] 缺 shot_id")
            else:
                unresolved = (
                    cam.get("resolved") is False
                    and bool(cam.get("unresolved")
                             or cam.get("unresolved_reason")))
                for key in ("position", "target"):
                    if not _has_coord(cam.get(key)) and not unresolved:
                        findings.append(f"camera_intents[{i}] 缺 {key}")
    staging = doc.get("shot_staging")
    if staging is not None:
        if not isinstance(staging, Mapping):
            findings.append("shot_staging 必须是对象")
        else:
            shot_ids = {
                str(shot.get("shot_id") or "")
                for shot in (doc.get("shots") or [])
                if isinstance(shot, Mapping)
            }
            character_names = {
                str(char.get("name") or "")
                for char in (doc.get("characters") or [])
                if isinstance(char, Mapping)
            }
            for shot_id, entities in staging.items():
                if str(shot_id) not in shot_ids:
                    findings.append(
                        f"shot_staging 引用未知 shot_id：{shot_id}")
                if not isinstance(entities, Mapping):
                    findings.append(
                        f"shot_staging.{shot_id} 必须是对象")
                    continue
                for name, entry in entities.items():
                    if str(name) not in character_names:
                        findings.append(
                            f"shot_staging.{shot_id} 引用未知角色：{name}")
                    if not isinstance(entry, Mapping):
                        findings.append(
                            f"shot_staging.{shot_id}.{name} 必须是对象")
                    elif not _has_coord(entry.get("position")):
                        findings.append(
                            f"shot_staging.{shot_id}.{name} 缺 position")
    return findings


def effective_shot_reference(
    doc: Mapping[str, Any], shot_id: str,
) -> Dict[str, Any]:
    """Resolve one shot's local staging without mutating the continuity base.

    ``characters[].position`` remains the world-continuity baseline used by
    shots without an overlay.  ``shot_staging[shot_id]`` overrides character
    position only for that shot.  Every preview, camera re-solve and
    measurement must consume this resolved document rather than mutating the
    global baseline.
    """
    result = copy.deepcopy(dict(doc))
    overlay = ((result.get("shot_staging") or {}).get(str(shot_id)) or {})
    if not isinstance(overlay, Mapping):
        raise ValueError(f"shot_staging.{shot_id} must be an object")
    by_name = {
        str(char.get("name") or ""): char
        for char in (result.get("characters") or [])
        if isinstance(char, dict)
    }
    for name, raw_entry in overlay.items():
        entry = dict(raw_entry or {})
        char = by_name.get(str(name))
        if char is None:
            raise ValueError(
                f"shot_staging.{shot_id} references unknown character {name}")
        position = entry.get("position")
        if not _has_coord(position):
            raise ValueError(
                f"shot_staging.{shot_id}.{name} has no position")
        char["position"] = copy.deepcopy(position)
        char["position_provenance"] = str(
            entry.get("provenance") or "agent_local_revision")
        char["position_reason"] = str(entry.get("reason") or "")
        char["effective_shot_id"] = str(shot_id)
    return result


def set_shot_character_position(
    doc: MutableMapping[str, Any],
    *,
    shot_id: str,
    name: str,
    position: Mapping[str, Any],
    provenance: str = "agent_local_revision",
    reason: str = "",
) -> Dict[str, float]:
    """Write one validated local staging overlay without touching continuity."""
    shot_id = str(shot_id or "")
    name = str(name or "")
    shot = next(
        (item for item in doc.get("shots") or []
         if isinstance(item, Mapping)
         and str(item.get("shot_id") or "") == shot_id),
        None,
    )
    if shot is None:
        raise ValueError(f"未知 shot_id：{shot_id}")
    declared = {str(item) for item in (shot.get("characters") or [])}
    framing = shot.get("framing_target")
    if isinstance(framing, Mapping) \
            and str(framing.get("kind") or "") == "character":
        declared.add(str(framing.get("ref") or ""))
    if name not in declared:
        raise ValueError(
            f"角色 {name} 不在 shot {shot_id} 的出场/拍对象声明中，"
            "禁止创建跨镜局部站位")
    if not any(
        str(item.get("name") or "") == name
        for item in doc.get("characters") or []
        if isinstance(item, Mapping)
    ):
        raise ValueError(f"未知角色实体：{name}")
    if not _has_coord(position):
        raise ValueError("character_position 处方缺 target_value 坐标")
    target = {
        "x": float(position.get("x", 0.0)),
        "y": float(position.get("y", 0.0)),
        "z": float(position.get("z", 0.0)),
    }
    staging = doc.setdefault("shot_staging", {})
    if not isinstance(staging, MutableMapping):
        raise ValueError("shot_staging 必须是对象")
    shot_overlay = staging.setdefault(shot_id, {})
    if not isinstance(shot_overlay, MutableMapping):
        raise ValueError(f"shot_staging.{shot_id} 必须是对象")
    shot_overlay[name] = {
        "position": target,
        "provenance": str(provenance or "agent_local_revision"),
        "reason": str(reason or ""),
    }
    return copy.deepcopy(target)


def coarse_reference_fingerprint(doc: Mapping[str, Any]) -> str:
    """整份参考 JSON 的指纹（审计/基线/修正留痕引用用）。"""
    return canonical_fingerprint(doc)


def coarse_reference_content_fingerprint(doc: Mapping[str, Any]) -> str:
    """**世界坐标内容**指纹：忽略 ``revisions[]`` 元数据段。

    revisions 会随修订轮数不断增长，把它算进指纹会让 fingerprint_after
    自我循环；基线/留痕对拍应使用内容指纹。
    """
    import copy

    content = copy.deepcopy(dict(doc))
    content.pop("revisions", None)
    return canonical_fingerprint(content)


__all__ = [
    "COARSE_REFERENCE_SCHEMA_VERSION",
    "LEGACY_DESIGN_SCHEMA_VERSION",
    "DESIGN_SCHEMA_VERSION",
    "MOTION_SPEED_M_S",
    "load_coarse_reference",
    "dump_coarse_reference",
    "coarse_reference_from_design",
    "validate_coarse_reference",
    "coarse_reference_fingerprint",
    "coarse_reference_content_fingerprint",
    "effective_shot_reference",
    "set_shot_character_position",
]
