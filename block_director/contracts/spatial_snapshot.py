"""空间快照契约（Ticket 06）：设计 / 观测 / diff 三份 JSON Schema + 审计事件。

纯层（不 import bpy）。Schema 是三份快照产物的**单一真源形状**，与
``cinema.spatial_design`` / ``cinema.spatial_observation`` /
``cinema.spatial_diff`` 的产出一一对应；测试用 jsonschema 校验（生产侧
零运行时依赖——校验只在测试/交付验证里跑，与观测契约同口径）。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Mapping, Tuple

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


# --------------------------------------------------------------------------- #
# 并行实现契约（layer5_orchestrator.design_snapshot / observation_snapshot）
# --------------------------------------------------------------------------- #
#: 设计快照版本（并行层 DTO 用，与 ``DESIGN_SCHEMA`` 的 const 独立演进）。
DESIGN_SNAPSHOT_SCHEMA = "spatial-understanding-design/v1"

#: 观测快照版本（并行层 DTO 用）。
OBSERVATION_SNAPSHOT_SCHEMA = "spatial-understanding-observation/v1"

#: 设计/观测偏差阈值（唯一真源；``cinema.spatial_diff.REGISTRY`` 从这里派生，
#: 保证 diff 判定与设计快照 registry 块同源、阈值不散两处）。
DIFF_THRESHOLDS: Dict[str, float] = {
    "camera_position_m": 0.3,      # 机位落位偏差容忍（30 cm）
    "character_position_m": 0.3,   # 角色站位偏差容忍（30 cm）
    "heading_angle_deg": 30.0,     # 朝向夹角容忍（与 R001 轴线 30° 同口径）
    "gaze_angle_deg": 30.0,        # 视线夹角容忍
    "motion_displacement_m": 0.5,  # 运动路径首末位移偏差容忍
    "speed_delta_m_s": 0.5,        # 运动速度偏差容忍
}


class _SnapshotDTO:
    """版本化快照的薄 DTO：from_dict/to_dict 深度复制，serde 往返逐位一致。

    不引入 jsonschema 运行时依赖（零依赖红线）；顶层缺键/非 Mapping 直接
    报错（不吞异常），形状校验由测试与交付验证链负责。``to_dict`` 走 JSON
    往返，同时证明产物可序列化并归一化内嵌类型（tuple→list 等）。
    """

    _required: Tuple[str, ...] = ()

    def __init__(self, data: Dict[str, Any]) -> None:
        self._data = data

    @classmethod
    def from_dict(cls, data: Any) -> "_SnapshotDTO":
        if not isinstance(data, Mapping):
            raise TypeError(
                f"{cls.__name__}.from_dict 需要 Mapping，"
                f"得到 {type(data).__name__}")
        missing = [key for key in cls._required if key not in data]
        if missing:
            raise ValueError(f"{cls.__name__} 缺必需键: {missing}")
        return cls(dict(data))

    def to_dict(self) -> Dict[str, Any]:
        return json.loads(json.dumps(self._data, ensure_ascii=False))


class DesignSnapshot(_SnapshotDTO):
    """设计快照 DTO（并行层 builder 的返回类型）。"""

    _required = ("schema_version", "characters", "props", "anchors",
                 "camera_intents", "registry", "notes")


class ObservationSnapshot(_SnapshotDTO):
    """观测快照 DTO（并行层 builder 的返回类型）。"""

    _required = ("schema_version", "shots", "notes")


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


def validate_spatial_snapshot(snapshot: Any,
                              schema: Dict[str, Any]) -> List[str]:
    """轻量结构校验（Ticket 08，生产侧零 jsonschema 依赖）。

    校验器只做**结构守卫**：``schema_version`` 常量 + 必需键 + 已声明类型的
    顶层属性（array/object/string/integer/boolean）。完整的 jsonschema 校验
    由测试链与冒烟探针负责（``tests/test_spatial_snapshot_schema.py`` 已钉
    合法/非法实例）；本函数是交付写盘前的最后一层网，坏数据不静默、不造假。
    通过返回空表；发现任何问题返回一条条可读的 findings。
    """
    findings: List[str] = []
    if not isinstance(snapshot, Mapping):
        return ["快照必须是 Mapping"]
    props = schema.get("properties") or {}
    const = (props.get("schema_version") or {}).get("const")
    if const is not None and snapshot.get("schema_version") != const:
        findings.append(f"schema_version 必须为 {const!r}")
    for key in schema.get("required") or []:
        if key not in snapshot:
            findings.append(f"缺必需键 {key}")
    for key, prop in props.items():
        if key not in snapshot:
            continue
        declared = prop.get("type")
        value = snapshot[key]
        if declared == "array" and not isinstance(value, list):
            findings.append(f"{key} 必须是数组")
        elif declared == "object" and not isinstance(value, Mapping):
            findings.append(f"{key} 必须是对象")
        elif declared == "string" and not isinstance(value, str):
            findings.append(f"{key} 必须是字符串")
        elif declared == "integer" and not isinstance(value, int):
            findings.append(f"{key} 必须是整数")
        elif declared == "boolean" and not isinstance(value, bool):
            findings.append(f"{key} 必须是布尔")
    return findings


__all__ = ["DESIGN_SCHEMA", "OBSERVATION_SCHEMA", "DIFF_SCHEMA",
           "DESIGN_SNAPSHOT_SCHEMA", "OBSERVATION_SNAPSHOT_SCHEMA",
           "DIFF_THRESHOLDS", "DesignSnapshot", "ObservationSnapshot",
           "snapshot_audit_event", "validate_spatial_snapshot"]
