"""空间快照契约（Ticket 06）：设计 / 观测 / diff 三份 JSON Schema + 审计事件。

纯层（不 import bpy）。Schema 是三份快照产物的**单一真源形状**，与
``cinema.spatial_design`` / ``cinema.spatial_observation`` /
``cinema.spatial_diff`` 的产出一一对应；测试用 jsonschema 校验（生产侧
零运行时依赖——校验只在测试/交付验证里跑，与观测契约同口径）。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict

DESIGN_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Spatial Design Snapshot",
    "type": "object",
    "required": ["schema_version", "characters", "props", "anchors",
                 "camera_intents", "notes"],
    "properties": {
        "schema_version": {"const": "spatial-design-snapshot/v1"},
        "scene_id": {"type": "string"},
        "characters": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string"},
                    "position": {"type": ["object", "null"]},
                    "facing": {"type": ["array", "null"]},
                    "rotation": {"type": ["object", "null"]},
                    "motion": {"type": ["object", "null"]},
                    "gaze": {"type": ["object", "null"]},
                    "provenance": {"type": "string"},
                },
                "additionalProperties": True,
            },
        },
        "props": {"type": "array"},
        "anchors": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["label", "resolved"],
                "properties": {
                    "label": {"type": "string"},
                    "position": {"type": ["array", "null"]},
                    "provenance": {"type": "string"},
                    "resolved": {"type": "boolean"},
                },
                "additionalProperties": True,
            },
        },
        "camera_intents": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["shot_id"],
                "properties": {
                    "shot_id": {"type": "string"},
                    "position": {"type": ["array", "null"]},
                    "provenance": {"type": "string"},
                },
                "additionalProperties": True,
            },
        },
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": True,
}

OBSERVATION_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Spatial Observation Snapshot",
    "type": "object",
    "required": ["schema_version", "shots"],
    "properties": {
        "schema_version": {"const": "spatial-observation/v1"},
        "shots": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["shot_id", "samples"],
                "properties": {
                    "shot_id": {"type": "string"},
                    "samples": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["frame"],
                            "properties": {
                                "frame": {"type": "integer"},
                                "camera": {"type": "object"},
                                "elements": {"type": "array"},
                            },
                            "additionalProperties": True,
                        },
                    },
                },
                "additionalProperties": True,
            },
        },
    },
    "additionalProperties": True,
}

DIFF_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Spatial Diff Report",
    "type": "object",
    "required": ["schema_version", "items"],
    "properties": {
        "schema_version": {"const": "spatial-diff/v1"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["metric", "subject", "verdict"],
                "properties": {
                    "metric": {"type": "string"},
                    "subject": {"type": ["string", "null"]},
                    "expected": {},
                    "actual": {"type": ["number", "null"]},
                    "threshold": {"type": "number"},
                    "verdict": {"enum": ["pass", "fail", "unresolved"]},
                    "unit": {"type": "string"},
                },
                "additionalProperties": True,
            },
        },
    },
    "additionalProperties": True,
}


def snapshot_audit_event(kind: str, snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """构造一条快照审计事件（kind / 版本 / 指纹 / 时间）。

    ``kind`` 闭集：``spatial_design_snapshot`` / ``spatial_observation_snapshot``
    / ``spatial_diff_report``。指纹用可复现的规范序列化（sort_keys），同一
    快照两次事件指纹一致，可重放对拍。
    """
    payload = json.dumps(snapshot, sort_keys=True, ensure_ascii=False,
                         default=str).encode("utf-8")
    fingerprint = hashlib.sha256(payload).hexdigest()
    return {
        "kind": str(kind),
        "schema_version": str(snapshot.get("schema_version") or ""),
        "fingerprint_sha256": fingerprint,
        "created_at": "deterministic-replay",   # 真实运行由调用方盖时间戳
    }


__all__ = ["DESIGN_SCHEMA", "OBSERVATION_SCHEMA", "DIFF_SCHEMA",
           "snapshot_audit_event"]
