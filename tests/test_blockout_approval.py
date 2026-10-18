"""Ticket 05：Blockout 审批记录落盘/读回与审批门（纯层，不 import bpy）。

钉死：审批记录列表落盘确定性（两次逐位一致）、读回与写入一致、追加一条
审批记录顺序保留、分镜表 JSON 与 manifest.shot_table 逐位一致、已批准
（camera-approved/frozen）基准被改机位/走位 -> E_BLOCKOUT_APPROVAL_REQUIRED
finding 且 blocked=True、未改 -> 空表不阻塞。全部纯层，无 bpy。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _manifest(cameras=None) -> dict:
    return {
        "schema_version": "blockout-manifest/v1",
        "scene_id": "scene_01",
        "primitives": [],
        "cameras": cameras or [{
            "shot_id": "S01", "camera_id": "cam_S01",
            "position": [3.0, -4.0, 1.6], "target": [0.0, 0.0, 1.2],
            "lens_mm": 35.0, "fov_deg": 39.6,
            "movements": [], "start_frame": 1, "end_frame": 48,
            "provenance": "algorithmic_measurement", "resolved": True,
        }],
        "shot_table": [{
            "shot_id": "S01", "order": 1, "start_frame": 1, "end_frame": 48,
            "camera_id": "cam_S01", "character_ids": ["米迦尔"],
            "prop_ids": [], "transition_overlap_frames": 0,
            "enter_exit": {"enter": [], "exit": []},
            "downstream_map": {"reference_video": "S01.mp4"},
        }],
        "asset_registry": [],
        "scene_prop_ids": [],
        "checkpoints": [
            {"id": "scene_01_blockout.blend", "scope": "global",
             "shot_id": None},
            {"id": "scene_s01_blockout.blend", "scope": "shot",
             "shot_id": "S01"},
        ],
        "notes": [],
    }


def _record(state="camera-approved") -> dict:
    return {
        "schema_version": "blockout-approval/v1",
        "checkpoint_id": "scene_01_blockout.blend",
        "scope": "global",
        "shot_id": None,
        "state": state,
        "manifest_fingerprint": "0123456789abcdef",
        "cameras_fingerprint": "fedcba9876543210",
        "approved_at": "2026-10-18T00:00:00+08:00",
        "approved_by": "blockout-gate",
    }


def test_module_is_pure_no_bpy():
    source = ROOT / "block_director" / "cinema" / "blockout_approval.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any("bpy" in (alias.name or "") for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            assert "bpy" not in (node.module or "")


def test_write_read_roundtrip_deterministic(tmp_path):
    from block_director.cinema.blockout_approval import (
        read_approval_records,
        write_approval_records,
    )

    records = [_record()]
    first = write_approval_records(records, tmp_path)
    second = write_approval_records(records, tmp_path)
    assert first == second
    assert read_approval_records(tmp_path) == records
    #: 分镜表与 manifest 逐位一致
    from block_director.cinema.blockout_approval import write_shot_table
    rows = write_shot_table(_manifest(), tmp_path)
    assert rows == _manifest()["shot_table"]
    path = tmp_path / "shot_table.json"
    assert json.loads(path.read_text(encoding="utf-8")) == rows


def test_append_approval_keeps_order_and_state_machine(tmp_path):
    from block_director.cinema.blockout_approval import (
        append_approval,
        read_approval_records,
    )

    manifest = _manifest()
    record = append_approval(
        [], manifest, tmp_path, checkpoint_id="scene_01_blockout.blend",
        scope="global", shot_id=None, current_state="draft",
        approved_by="blockout-gate")
    assert record["state"] == "camera-approved"
    record2 = append_approval(
        [record], manifest, tmp_path,
        checkpoint_id="scene_01_blockout.blend", scope="global",
        shot_id=None, current_state=record["state"], approved_by="blockout-gate",
        target_state="frozen")
    assert record2["state"] == "frozen"
    records = read_approval_records(tmp_path)
    assert [r["state"] for r in records] == ["camera-approved", "frozen"]

    #: 非法迁移：frozen 不能回退
    with pytest.raises(ValueError):
        append_approval(
            records, manifest, tmp_path,
            checkpoint_id="scene_01_blockout.blend", scope="global",
            shot_id=None, current_state="frozen",
            approved_by="x", target_state="camera-approved")


def test_gate_blocks_when_camera_changed_after_approval(tmp_path):
    from block_director.cinema.blockout_approval import (
        E_BLOCKOUT_APPROVAL_REQUIRED,
        append_approval,
        gate_findings,
    )

    manifest = _manifest()
    record = append_approval(
        [], manifest, tmp_path, checkpoint_id="scene_01_blockout.blend",
        scope="global", shot_id=None, current_state="draft",
        approved_by="blockout-gate")

    #: 未改 -> 不阻塞
    gate = gate_findings([record], manifest)
    assert gate["blocked"] is False and gate["findings"] == []

    #: 改机位 -> 阻塞 + finding
    tampered = json.loads(json.dumps(manifest))
    tampered["cameras"][0]["position"] = [9.0, 9.0, 9.0]
    gate = gate_findings([record], tampered)
    assert gate["blocked"] is True
    assert any(f["check_id"] == E_BLOCKOUT_APPROVAL_REQUIRED
               for f in gate["findings"])

    #: frozen 后改同样阻塞（任一已批准状态都触发门）
    frozen = append_approval(
        [record], manifest, tmp_path,
        checkpoint_id="scene_01_blockout.blend", scope="global",
        shot_id=None, current_state=record["state"],
        approved_by="blockout-gate", target_state="frozen")
    gate = gate_findings([frozen], tampered)
    assert gate["blocked"] is True
    assert gate["findings"]


def test_gate_empty_records_or_missing_file_no_block(tmp_path):
    from block_director.cinema.blockout_approval import (
        gate_findings,
        read_approval_records,
    )

    assert read_approval_records(tmp_path) == []
    gate = gate_findings([], _manifest())
    assert gate["blocked"] is False and gate["findings"] == []
