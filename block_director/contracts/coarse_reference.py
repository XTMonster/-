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
            elif not isinstance(char.get("position"), Mapping):
                findings.append(f"characters[{i}] 缺 position（坐标必须可追溯）")
    if isinstance(doc.get("camera_intents"), list):
        for i, cam in enumerate(doc.get("camera_intents") or []):
            if not isinstance(cam, Mapping) or not cam.get("shot_id"):
                findings.append(f"camera_intents[{i}] 缺 shot_id")
            else:
                for key in ("position", "target"):
                    if not _has_coord(cam.get(key)):
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
    "load_coarse_reference",
    "dump_coarse_reference",
    "validate_coarse_reference",
    "coarse_reference_fingerprint",
    "coarse_reference_content_fingerprint",
    "effective_shot_reference",
    "set_shot_character_position",
]
