"""Ticket 01：Blockout 清单生成器（纯层，不 import bpy）。

钉死：空间设计快照 -> BlockoutManifest 确定性转换——体块（human scale、
形状/尺寸/颜色占位、asset 引用、provenance）、相机先行（位置/目标/镜头/
运动轨迹/帧范围）、分镜表（shot_id/起止帧/相机/角色/道具/转场重叠/出入画/
下游映射）、共享资产登记去重、检查点声明；未解析锚点不落坐标；空镜合法；
同一输入两次构建逐位一致。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from block_director.contracts.plan import Plan, ShotPlan

ROOT = Path(__file__).resolve().parents[1]


def _design() -> dict:
    """手工构造的设计快照（独立真源：期望值手算，不与实现同源）。"""
    return {
        "schema_version": "spatial-design-snapshot/v1",
        "scene_id": "dock_market",
        "characters": [
            {
                "name": "米迦尔",
                "position": {"x": -0.9, "y": 0.0, "z": 0.0},
                "facing": [0.0, 1.0, 0.0],
                "rotation": None, "motion": None, "gaze": None,
                "provenance": "plan_intent",
            },
            {
                "name": "伊恩",
                "position": {"x": 0.9, "y": 0.0, "z": 0.0},
                "facing": [0.0, 1.0, 0.0],
                "rotation": None, "motion": None, "gaze": None,
                "provenance": "plan_intent",
            },
        ],
        "props": [
            {"id": "生蚝摊", "kind": "stall", "owner": None, "parent": None,
             "position": [2.5, 1.0, 0.0], "rotation": None, "motion": None,
             "provenance": "script_declaration"},
            {"id": "钱袋", "kind": "prop", "owner": "贵妇", "parent": None,
             "position": None, "rotation": None, "motion": None,
             "provenance": "plan_intent"},
        ],
        "anchors": [
            {"label": "入口", "position": [0.0, 6.0, 0.0], "provenance":
             "algorithmic_measurement", "resolved": True},
            {"label": "幽灵摊位", "position": None, "provenance": "plan_intent",
             "resolved": False, "unresolved_reason": "方向非法"},
        ],
        "camera_intents": [
            {"shot_id": "shot_001", "position": [-0.9, 4.66, 0.62],
             "target": [-0.9, 0.0, 1.0], "lens": 35.0, "fov_deg": 54.4,
             "provenance": "algorithmic_measurement", "resolved": True},
            {"shot_id": "shot_002", "position": [0.9, 5.0, 0.8],
             "target": [0.9, 0.0, 1.0], "lens": 35.0, "fov_deg": 54.4,
             "provenance": "algorithmic_measurement", "resolved": True},
        ],
        "notes": ["测试设计快照"],
    }


def _plan() -> Plan:
    return Plan(shots=[
        ShotPlan(
            shot_id="shot_001", intent="双人对话", shot_type="MS",
            duration_frames=24, order=1, characters=["米迦尔", "伊恩"],
            actions=[{"type": "enter_from", "start_frame": 1, "end_frame": 4,
                      "params": {"from": [-3.0, 0.0, 0.0]}}],
            camera={"side": "front", "lens": 35,
                    "movements": [{"type": "push_in", "amount": 0.4,
                                   "start_frame": 1, "end_frame": 24}]},
        ),
        ShotPlan(
            shot_id="shot_002", intent="空镜：市场通道", shot_type="MS",
            duration_frames=12, order=2, characters=[],
            camera={"lens": 35},
        ),
    ])


def _build(design=None, plan=None) -> dict:
    from block_director.cinema.blockout import build_blockout_manifest

    manifest = build_blockout_manifest(
        design=design if design is not None else _design(),
        plan=plan if plan is not None else _plan())
    return manifest


def test_blockout_module_is_pure_no_bpy():
    source = ROOT / "block_director" / "cinema" / "blockout.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any("bpy" in (alias.name or "")
                           for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            assert "bpy" not in (node.module or "")


def test_two_builds_are_byte_identical():
    first = json.dumps(_build(), ensure_ascii=False, sort_keys=True)
    second = json.dumps(_build(), ensure_ascii=False, sort_keys=True)
    assert first == second


def test_human_scale_character_blocks():
    manifest = _build()
    characters = [p for p in manifest["primitives"] if p["kind"] == "character"]
    assert {p["source"]["id"] for p in characters} == {"米迦尔", "伊恩"}
    for block in characters:
        #: human scale：角色体块高度 ∈ [1.5, 2.0] m，脚底锚定
        assert 1.5 <= block["size"]["z"] <= 2.0
        assert block["z_anchor"] == "foot"
        assert block["position"]["x"] == pytest.approx(
            _design()["characters"][0]["position"]["x"] if
            block["source"]["id"] == "米迦尔" else 0.9, abs=1e-3)


def test_cameras_come_first_with_movements_and_frames():
    manifest = _build()
    cameras = {c["shot_id"]: c for c in manifest["cameras"]}
    assert set(cameras) == {"shot_001", "shot_002"}
    cam = cameras["shot_001"]
    assert cam["position"] == [-0.9, 4.66, 0.62]
    assert cam["lens_mm"] == 35.0
    assert cam["provenance"] == "algorithmic_measurement"
    #: 相机运动轨迹来自计划意图（不脑补）
    assert cam["movements"] == [
        {"type": "push_in", "amount": 0.4,
         "start_frame": 1, "end_frame": 24}]
    #: 帧范围来自计划帧调度（shot_001 占 1..24，shot_002 接 25..36）
    assert cam["start_frame"] == 1 and cam["end_frame"] == 24
    assert cameras["shot_002"]["start_frame"] == 25
    assert cameras["shot_002"]["end_frame"] == 36


def test_shot_table_fields_complete_and_match_plan():
    manifest = _build()
    table = {s["shot_id"]: s for s in manifest["shot_table"]}
    row = table["shot_001"]
    assert row["order"] == 1
    assert row["start_frame"] == 1 and row["end_frame"] == 24
    assert row["camera_id"] == "cam_shot_001"
    assert row["character_ids"] == ["米迦尔", "伊恩"]
    assert "transition_overlap_frames" in row
    assert row["enter_exit"]["enter"] == ["enter_from"]
    assert row["downstream_map"]["reference_video"] == "shot_001.mp4"
    assert table["shot_002"]["character_ids"] == []


def test_unresolved_anchor_not_placed():
    manifest = _build()
    anchor_ids = [p["id"] for p in manifest["primitives"]
                  if p["kind"] == "anchor"]
    assert "anchor_幽灵摊位" not in anchor_ids
    assert "anchor_入口" in anchor_ids


def test_empty_shot_is_legal():
    manifest = _build()
    row = next(s for s in manifest["shot_table"] if s["shot_id"] == "shot_002")
    assert row["character_ids"] == []
    assert row["camera_id"] == "cam_shot_002"


def test_asset_registry_dedups_shared_props():
    manifest = _build()
    registry = {a["asset_id"]: a for a in manifest["asset_registry"]}
    assert "stall_生蚝摊" in registry
    #: 同一资产只登记一次；未落坐标的钱袋不进资产表
    stall_ids = [a for a in manifest["asset_registry"]
                 if a["kind"] == "stall"]
    assert len(stall_ids) == 1
    prop_ids = {a["asset_id"] for a in manifest["asset_registry"]}
    assert "prop_钱袋" not in prop_ids


def test_checkpoints_declared_global_and_per_shot():
    manifest = _build()
    checkpoint_ids = {c["id"] for c in manifest["checkpoints"]}
    assert "scene_01_blockout.blend" in checkpoint_ids
    assert "scene_s01_blockout.blend" in checkpoint_ids
    assert "scene_s02_blockout.blend" in checkpoint_ids
