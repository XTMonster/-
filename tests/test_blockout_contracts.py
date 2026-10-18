"""Ticket 02：Blockout 契约与审计（Schema + 审批状态机 + 零 LLM 重放）。

纯层验收（不 import bpy）：

- 四份 Schema（manifest / shot_table / report / approval）与 Ticket 01 产出
  逐位对应；合法样例经 jsonschema 校验通过；
- 审批状态机 draft -> camera-approved -> frozen：已批准机位/走位被改后
  必须产生 E_BLOCKOUT_APPROVAL_REQUIRED finding，不静默放行；
- 审计事件指纹可复现：同一 manifest/报告两次事件指纹一致；replay 无 LLM。
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "block_director" / "contracts" / "blockout" / "schema"

MANIFEST_SCHEMA_NAME = "blockout-manifest.v1.schema.json"
SHOT_TABLE_SCHEMA_NAME = "blockout-shot-table.v1.schema.json"
REPORT_SCHEMA_NAME = "blockout-report.v1.schema.json"
APPROVAL_SCHEMA_NAME = "blockout-approval.v1.schema.json"

#: 独立真源样例（Ticket 01 产出形状的字面量，不从实现反推）。
MANIFEST_EXAMPLE = {
    "schema_version": "blockout-manifest/v1",
    "scene_id": "scene_01",
    "primitives": [{
        "id": "char_米迦尔", "kind": "character", "shape": "box",
        "position": {"x": 0.0, "y": 0.0, "z": 0.0},
        "size": {"x": 0.5, "y": 0.5, "z": 1.7},
        "color": "#8f8f8f", "z_anchor": "foot",
        "asset_ref": None, "provenance": "plan_intent",
        "source": {"type": "character", "id": "米迦尔"},
    }],
    "cameras": [{
        "shot_id": "S01", "camera_id": "cam_S01",
        "position": [3.0, -4.0, 1.6], "target": [0.0, 0.0, 1.2],
        "lens_mm": 35.0, "fov_deg": 39.6,
        "movements": [], "start_frame": 1, "end_frame": 48,
        "provenance": "algorithmic_measurement", "resolved": True,
    }],
    "shot_table": [{
        "shot_id": "S01", "order": 1, "start_frame": 1, "end_frame": 48,
        "camera_id": "cam_S01", "character_ids": ["米迦尔"], "prop_ids": [],
        "transition_overlap_frames": 0,
        "enter_exit": {"enter": [], "exit": []},
        "downstream_map": {"reference_video": "S01.mp4"},
    }],
    "asset_registry": [],
    "scene_prop_ids": [],
    "checkpoints": [
        {"id": "scene_01_blockout.blend", "scope": "global", "shot_id": None},
        {"id": "scene_s01_blockout.blend", "scope": "shot", "shot_id": "S01"},
    ],
    "notes": [],
}

SHOT_TABLE_EXAMPLE = MANIFEST_EXAMPLE["shot_table"][0]

REPORT_EXAMPLE = {
    "schema_version": "blockout-report/v1",
    "manifest_fingerprint": "0123456789abcdef",
    "verdict": "pass",
    "findings": [],
    "checks": [],
    "notes": [],
}

APPROVAL_EXAMPLE = {
    "schema_version": "blockout-approval/v1",
    "checkpoint_id": "scene_01_blockout.blend",
    "scope": "global",
    "shot_id": None,
    "state": "camera-approved",
    "manifest_fingerprint": "0123456789abcdef",
    "cameras_fingerprint": "fedcba9876543210",
    "approved_at": "2026-10-18T00:00:00+08:00",
    "approved_by": "blockout-gate",
}


def _load(name: str) -> dict:
    path = SCHEMA_DIR / name
    assert path.exists(), f"缺少 schema 文件：{path}"
    return json.loads(path.read_text(encoding="utf-8"))


def test_manifest_schema_file_present_and_validates_example():
    schema = _load(MANIFEST_SCHEMA_NAME)
    assert schema["$schema"].startswith("https://json-schema.org/")
    assert schema["properties"]["schema_version"]["const"] == (
        "blockout-manifest/v1")
    jsonschema.validate(instance=MANIFEST_EXAMPLE, schema=schema)


def test_shot_table_schema_file_present_and_validates_example():
    schema = _load(SHOT_TABLE_SCHEMA_NAME)
    assert schema["properties"]["schema_version"]["const"] == (
        "blockout-shot-table/v1")
    jsonschema.validate(instance=SHOT_TABLE_EXAMPLE, schema=schema)


def test_report_schema_file_present_and_validates_example():
    schema = _load(REPORT_SCHEMA_NAME)
    assert schema["properties"]["schema_version"]["const"] == (
        "blockout-report/v1")
    jsonschema.validate(instance=REPORT_EXAMPLE, schema=schema)


def test_approval_schema_file_present_and_validates_example():
    schema = _load(APPROVAL_SCHEMA_NAME)
    assert schema["properties"]["schema_version"]["const"] == (
        "blockout-approval/v1")
    jsonschema.validate(instance=APPROVAL_EXAMPLE, schema=schema)


def test_manifest_schema_rejects_missing_required_sections():
    schema = _load(MANIFEST_SCHEMA_NAME)
    bad = dict(MANIFEST_EXAMPLE)
    del bad["shot_table"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=bad, schema=schema)


def test_real_ticket01_manifest_output_passes_schema():
    """防漂移守卫：Ticket 01 的真实产出一律过新增清单 Schema。

    独立真源是 ``test_blockout_manifest._build()``（已提交的 Ticket 01 测试
    构造）；若清单生成器输出形状漂移，这里立即红——Schema 不是纸面契约。
    """
    from tests.test_blockout_manifest import _build

    manifest = _build()
    jsonschema.validate(
        instance=manifest, schema=_load(MANIFEST_SCHEMA_NAME))


# ---------------------------------------------------------------------------
# 审批状态机（纯层）

def test_approval_state_machine_transitions():
    from block_director.contracts.blockout import (
        approval_required_findings,
        approval_state_machine,
        camera_fingerprint,
        validate_blockout_manifest,
    )

    manifest = dict(MANIFEST_EXAMPLE)
    # draft -> camera-approved -> frozen 合法
    record = approval_state_machine(
        "scene_01_blockout.blend", "global", None, "draft",
        manifest, approved_by="blockout-gate")
    assert record["state"] == "camera-approved"
    record = approval_state_machine(
        record["checkpoint_id"], record["scope"], record["shot_id"],
        record["state"], manifest, approved_by="blockout-gate",
        target_state="frozen")
    assert record["state"] == "frozen"

    # 冻结后改机位 -> 审批必需 finding（不静默放行）
    tampered = json.loads(json.dumps(manifest))
    tampered["cameras"][0]["position"] = [9.0, 9.0, 9.0]
    findings = approval_required_findings(record, tampered)
    assert findings
    assert all(item["check_id"] == "E_BLOCKOUT_APPROVAL_REQUIRED"
               for item in findings)

    # 未改 -> 无 finding
    assert approval_required_findings(record, manifest) == []

    # 非法迁移：frozen 不能回到已批准状态
    with pytest.raises(ValueError):
        approval_state_machine(
            record["checkpoint_id"], record["scope"], record["shot_id"],
            "frozen", manifest, approved_by="x",
            target_state="camera-approved")

    # 指纹确定性：同一 manifest 两次一致
    assert camera_fingerprint(manifest) == camera_fingerprint(manifest)

    # manifest 结构校验：坏数据要报 findings（validate 走轻量守卫）
    bad = dict(manifest)
    del bad["primitives"]
    assert validate_blockout_manifest(bad)


# ---------------------------------------------------------------------------
# 审计事件指纹与重放

def test_audit_event_fingerprint_deterministic_and_replay_without_llm():
    from block_director.contracts.blockout import blockout_audit_event

    event_a = blockout_audit_event(
        "blockout_manifest_generated", MANIFEST_EXAMPLE)
    event_b = blockout_audit_event(
        "blockout_manifest_generated", MANIFEST_EXAMPLE)
    assert event_a["fingerprint_sha256"] == event_b["fingerprint_sha256"]
    assert event_a["schema_version"] == "blockout-manifest/v1"

    # 事件随 payload 走（重放需要它做确定性复原）
    assert event_a["payload"]["shot_table"][0]["shot_id"] == "S01"


def test_replay_extracts_blockout_manifest_and_approval_without_llm():
    from block_director.contracts.blockout import blockout_audit_event
    from block_director.layer9_persistence.replay import (
        extract_blockout_approvals,
        extract_blockout_manifest,
    )

    records = [
        {"kind": "plan_received", "data": {"plan": {"shots": []}}},
        {"kind": "blockout_manifest_generated",
         "data": blockout_audit_event(
             "blockout_manifest_generated", MANIFEST_EXAMPLE)},
        {"kind": "blockout_approval_recorded",
         "data": blockout_audit_event(
             "blockout_approval_recorded", APPROVAL_EXAMPLE)},
    ]
    manifest = extract_blockout_manifest(records)
    assert manifest is not None
    assert manifest["schema_version"] == "blockout-manifest/v1"
    approvals = extract_blockout_approvals(records)
    assert len(approvals) == 1
    assert approvals[0]["checkpoint_id"] == "scene_01_blockout.blend"
