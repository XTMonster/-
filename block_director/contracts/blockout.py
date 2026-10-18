"""Blockout 契约（Ticket 02）：清单/分镜表/报告/审批四份 Schema + 审批状态机。

纯层（不 import bpy）。Schema 文件在 ``contracts/blockout/schema/``，是
BlockoutManifest / ShotTable / BlockoutReport / BlockoutApproval 四类产物的
**单一真源形状**；测试链用 jsonschema 校验，生产侧零运行时依赖（与
``contracts/spatial_ruler/schema/`` 同口径）。

审批状态机：``draft -> camera-approved -> frozen``。已批准机位/走位被修改
（manifest 的 cameras 段与批准基准指纹不一致）时产生
``E_BLOCKOUT_APPROVAL_REQUIRED`` finding，不静默放行。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from .audit import canonical_fingerprint

BLOCKOUT_MANIFEST_SCHEMA_VERSION = "blockout-manifest/v1"
BLOCKOUT_SHOT_TABLE_SCHEMA_VERSION = "blockout-shot-table/v1"
BLOCKOUT_REPORT_SCHEMA_VERSION = "blockout-report/v1"
BLOCKOUT_APPROVAL_SCHEMA_VERSION = "blockout-approval/v1"

#: 与 ``cinema/blockout.py`` 同源用的别名（清单版本单一真源）。
MANIFEST_VERSION = BLOCKOUT_MANIFEST_SCHEMA_VERSION

#: 审批状态机的合法迁移表（单一真源）。
APPROVAL_TRANSITIONS: Dict[str, List[str]] = {
    "draft": ["camera-approved"],
    "camera-approved": ["frozen"],
    "frozen": [],
}

#: 审批必需 finding 的 check_id（spec §实现决策：不可静默改）。
E_BLOCKOUT_APPROVAL_REQUIRED = "E_BLOCKOUT_APPROVAL_REQUIRED"


def _schema_dir() -> Path:
    return Path(__file__).resolve().parent / "blockout" / "schema"


def blockout_manifest_schema() -> Dict[str, Any]:
    """载入清单 Schema（manifest 结构单一真源）。"""
    return json.loads(
        (_schema_dir() / "blockout-manifest.v1.schema.json")
        .read_text(encoding="utf-8"))


def validate_blockout_manifest(manifest: Any) -> List[str]:
    """轻量结构守卫（生产零 jsonschema 依赖）：缺必需节/坏类型报 findings。

    通过返回空表；发现任何问题返回一条条可读的 findings。完整 jsonschema
    校验由测试链负责（``tests/test_blockout_contracts.py``）。
    """
    findings: List[str] = []
    if not isinstance(manifest, Mapping):
        return ["manifest 必须是 Mapping"]
    if manifest.get("schema_version") != BLOCKOUT_MANIFEST_SCHEMA_VERSION:
        findings.append(
            f"schema_version 必须为 {BLOCKOUT_MANIFEST_SCHEMA_VERSION!r}")
    for key in ("primitives", "cameras", "shot_table", "asset_registry",
                "scene_prop_ids", "checkpoints", "notes"):
        if key not in manifest:
            findings.append(f"缺必需键 {key}")
        elif not isinstance(manifest[key], list):
            findings.append(f"{key} 必须是数组")
    for key in ("scene_id",):
        if key in manifest and not isinstance(manifest[key], str):
            findings.append(f"{key} 必须是字符串")
    return findings


# --------------------------------------------------------------------------
# 指纹（与 ``snapshot_audit_event`` 同口径的可复现规范序列化）

def camera_fingerprint(manifest: Any) -> str:
    """只对 cameras 段取指纹——审批门关心的是"机位/走位是否被改"。

    改角色站位/道具不触发 camera-approved 变更门（那是另一层审批）；
    改 position/target/lens/fov/movements/起止帧都会反映在指纹里。
    """
    cameras = (manifest or {}).get("cameras") or []
    return canonical_fingerprint(cameras)


def manifest_fingerprint(manifest: Any) -> str:
    """整份 manifest 的指纹（审计/报告引用用）。"""
    return canonical_fingerprint(manifest)


def _camera_signature(cameras: Any) -> str:
    camera_rows = cameras or []
    if isinstance(camera_rows, Mapping):
        camera_rows = list(camera_rows.values())
    return canonical_fingerprint(camera_rows)


# --------------------------------------------------------------------------
# 审批状态机

def approval_state_machine(
    checkpoint_id: str,
    scope: str,
    shot_id: Optional[str],
    current_state: str,
    manifest: Any,
    *,
    approved_by: str,
    target_state: str = "camera-approved",
    approved_at: str = "",
) -> Dict[str, Any]:
    """在清单上推进审批状态，产出一条审批记录（纯层、确定性）。

    ``scope`` 为 ``global`` / ``shot``；``target_state`` 只允许一次前进一格
    （draft -> camera-approved -> frozen），冻结后不可再批准。非法迁移抛
    ``ValueError``（不静默放行）。
    """
    allowed = APPROVAL_TRANSITIONS.get(str(current_state), [])
    if target_state not in allowed:
        raise ValueError(
            f"非法审批迁移：{current_state!r} -> {target_state!r}"
            f"（允许：{allowed or '无'}）")
    cameras = (manifest or {}).get("cameras") or []
    return {
        "schema_version": BLOCKOUT_APPROVAL_SCHEMA_VERSION,
        "checkpoint_id": str(checkpoint_id),
        "scope": str(scope),
        "shot_id": shot_id,
        "state": str(target_state),
        "manifest_fingerprint": manifest_fingerprint(manifest),
        "cameras_fingerprint": _camera_signature(cameras),
        "approved_at": str(approved_at or "deterministic-replay"),
        "approved_by": str(approved_by),
    }


def approval_required_findings(
    approval_record: Mapping[str, Any],
    candidate: Any,
) -> List[Dict[str, Any]]:
    """frozen/已批准基准被改机位或走位 -> 审批必需 finding（不静默放行）。

    只比对 cameras 段指纹；未变化返回空表。检查对象既可以是整份 manifest，
    也可以是 cameras 数组。
    """
    if str(approval_record.get("state")) not in (
            "camera-approved", "frozen"):
        return []
    if isinstance(candidate, Mapping) and "cameras" in candidate:
        cameras = candidate.get("cameras") or []
    else:
        cameras = candidate or []
    baseline = approval_record.get("cameras_fingerprint") or ""
    if not baseline or _camera_signature(cameras) == baseline:
        return []
    return [{
        "check_id": E_BLOCKOUT_APPROVAL_REQUIRED,
        "severity": "error",
        "message": (
            "已批准机位/走位被修改，必须重新走 camera-approved 审批流程"),
        "checkpoint_id": approval_record.get("checkpoint_id"),
        "shot_id": approval_record.get("shot_id"),
    }]


# --------------------------------------------------------------------------
# 审计事件（指纹 + 完整 payload，重放零 LLM）

def blockout_audit_event(kind: str, snapshot: Any) -> Dict[str, Any]:
    """构造一条 blockout 审计事件（kind / 版本 / 指纹 / payload）。

    ``kind`` 闭集：``blockout_manifest_generated`` /
    ``blockout_report_generated`` / ``blockout_approval_recorded``。
    指纹用可复现的规范序列化（sort_keys），同一产物两次事件指纹一致；
    payload 随事件走，重放可确定性复原，无需 LLM。
    """
    version = ""
    if isinstance(snapshot, Mapping):
        version = str(snapshot.get("schema_version") or "")
    return {
        "kind": str(kind),
        "schema_version": version,
        "fingerprint_sha256": canonical_fingerprint(snapshot),
        "created_at": "deterministic-replay",
        "payload": snapshot,
    }


__all__ = [
    "BLOCKOUT_MANIFEST_SCHEMA_VERSION",
    "BLOCKOUT_SHOT_TABLE_SCHEMA_VERSION",
    "BLOCKOUT_REPORT_SCHEMA_VERSION",
    "BLOCKOUT_APPROVAL_SCHEMA_VERSION",
    "APPROVAL_TRANSITIONS",
    "E_BLOCKOUT_APPROVAL_REQUIRED",
    "blockout_manifest_schema",
    "validate_blockout_manifest",
    "camera_fingerprint",
    "manifest_fingerprint",
    "approval_state_machine",
    "approval_required_findings",
    "blockout_audit_event",
]
