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
from typing import Any, Dict, List, Mapping

from .audit import canonical_fingerprint

COARSE_REFERENCE_SCHEMA_VERSION = "coarse-world-reference/v1"

#: 必需节与类型（守卫用，单一真源）。
_REQUIRED_LIST_KEYS = (
    "characters", "props", "anchors", "camera_intents", "shots", "revisions",
)


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
                    if not isinstance(cam.get(key), Mapping):
                        findings.append(f"camera_intents[{i}] 缺 {key}")
    return findings


def coarse_reference_fingerprint(doc: Mapping[str, Any]) -> str:
    """整份参考 JSON 的指纹（审计/基线/修正留痕引用用）。"""
    return canonical_fingerprint(doc)


__all__ = [
    "COARSE_REFERENCE_SCHEMA_VERSION",
    "load_coarse_reference",
    "dump_coarse_reference",
    "validate_coarse_reference",
    "coarse_reference_fingerprint",
]
