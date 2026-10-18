"""Ticket 06：Blockout 全局回放一致性审查（纯层，不 import bpy）。

钉死：五维结论（空间连续/出入画/相机方向/光照方向/转场）齐全；发现的问题
以 finding 形式可归因到分镜与帧；180° 轴线侧别静默翻转 -> E_BLOCKOUT_AXIS_FLIP；
转场帧缺口 -> E_BLOCKOUT_TRANSITION_GAP；出场角色无体块 ->
E_BLOCKOUT_MISSING_CAST_BLOCK；出入画声明与出场冲突 ->
E_BLOCKOUT_ENTER_EXIT_MISMATCH；错误 finding -> verdict fail；同一输入两次
构建逐位一致。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _manifest() -> dict:
    """两镜双人对话：shot_001 正面、shot_002 越轴（无中性镜桥接）。"""
    return {
        "schema_version": "blockout-manifest/v1",
        "scene_id": "scene_01",
        "primitives": [
            {"id": "char_米迦尔", "kind": "character", "shape": "box",
             "position": {"x": -0.9, "y": 0.0, "z": 0.0},
             "size": {"x": 0.5, "y": 0.5, "z": 1.7},
             "color": "#8f8f8f", "z_anchor": "foot",
             "asset_ref": None, "provenance": "plan_intent",
             "source": {"type": "character", "id": "米迦尔"}},
            {"id": "char_伊恩", "kind": "character", "shape": "box",
             "position": {"x": 0.9, "y": 0.0, "z": 0.0},
             "size": {"x": 0.5, "y": 0.5, "z": 1.7},
             "color": "#8f8f8f", "z_anchor": "foot",
             "asset_ref": None, "provenance": "plan_intent",
             "source": {"type": "character", "id": "伊恩"}},
        ],
        "cameras": [
            {"shot_id": "S01", "camera_id": "cam_S01",
             "position": [0.0, 5.0, 1.6], "target": [0.0, 0.0, 1.0],
             "lens_mm": 35.0, "fov_deg": 54.4, "movements": [],
             "start_frame": 1, "end_frame": 24,
             "provenance": "algorithmic_measurement", "resolved": True},
            #: 相机从 y=+5 移到 y=-5：相对 A→B（-0.9→0.9 沿 x）侧别翻转
            {"shot_id": "S02", "camera_id": "cam_S02",
             "position": [0.0, -5.0, 1.6], "target": [0.0, 0.0, 1.0],
             "lens_mm": 35.0, "fov_deg": 54.4, "movements": [],
             "start_frame": 25, "end_frame": 48,
             "provenance": "algorithmic_measurement", "resolved": True},
        ],
        "shot_table": [
            {"shot_id": "S01", "order": 1, "start_frame": 1, "end_frame": 24,
             "camera_id": "cam_S01", "character_ids": ["米迦尔", "伊恩"],
             "prop_ids": [], "transition_overlap_frames": 0,
             "enter_exit": {"enter": [], "exit": []},
             "downstream_map": {"reference_video": "S01.mp4"}},
            {"shot_id": "S02", "order": 2, "start_frame": 25, "end_frame": 48,
             "camera_id": "cam_S02", "character_ids": ["米迦尔", "伊恩"],
             "prop_ids": [], "transition_overlap_frames": 0,
             "enter_exit": {"enter": [], "exit": []},
             "downstream_map": {"reference_video": "S02.mp4"}},
        ],
        "asset_registry": [],
        "scene_prop_ids": [],
        "checkpoints": [],
        "notes": [],
    }


def test_module_is_pure_no_bpy():
    source = ROOT / "block_director" / "cinema" / "blockout_sequence.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any("bpy" in (alias.name or "") for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            assert "bpy" not in (node.module or "")


def test_five_dimensions_present_and_axis_flip_detected():
    from block_director.cinema.blockout_sequence import (
        E_BLOCKOUT_AXIS_FLIP,
        build_blockout_sequence_review,
    )

    review = build_blockout_sequence_review(
        manifest=_manifest(), manifest_fingerprint="fp1")
    assert review["schema_version"] == "blockout-sequence-review/v1"
    assert set(review["dimensions"]) == {
        "spatial_continuity", "enter_exit", "camera_direction",
        "lighting_direction", "transition"}
    assert review["verdict"] == "fail"
    axis = [f for f in review["findings"]
            if f["check_id"] == E_BLOCKOUT_AXIS_FLIP]
    assert len(axis) == 1
    assert axis[0]["shot_id"] == "S02"
    assert axis[0]["frame"] == 25
    axis_check = [c for c in review["checks"]
                  if c["dimension"] == "camera_direction"]
    assert axis_check[0]["verdict"] == "fail"


def test_clean_two_shot_sequence_passes():
    from block_director.cinema.blockout_sequence import (
        build_blockout_sequence_review,
    )

    manifest = _manifest()
    #: 两镜同侧机位 -> 无越轴，全 pass
    manifest["cameras"][1]["position"] = [0.0, 5.0, 2.2]
    manifest["cameras"][1]["target"] = [0.0, 0.0, 1.0]
    review = build_blockout_sequence_review(manifest=manifest)
    assert review["verdict"] == "pass"
    assert all(c["verdict"] == "pass" for c in review["checks"])


def test_transition_gap_finding_attributable_to_shot_and_frame():
    from block_director.cinema.blockout_sequence import (
        E_BLOCKOUT_TRANSITION_GAP,
        build_blockout_sequence_review,
    )

    manifest = _manifest()
    #: S02 起于 30（S01 止于 24，中间 5 帧无人声明；重叠声明 0）
    manifest["cameras"][1]["start_frame"] = 30
    manifest["cameras"][1]["end_frame"] = 53
    manifest["shot_table"][1]["start_frame"] = 30
    manifest["shot_table"][1]["end_frame"] = 53
    review = build_blockout_sequence_review(manifest=manifest)
    gaps = [f for f in review["findings"]
            if f["check_id"] == E_BLOCKOUT_TRANSITION_GAP]
    assert len(gaps) == 1
    assert gaps[0]["shot_id"] == "S02"
    assert gaps[0]["frame"] == 30
    assert review["verdict"] == "fail"


def test_overlap_frames_cover_the_gap():
    from block_director.cinema.blockout_sequence import (
        E_BLOCKOUT_TRANSITION_GAP,
        build_blockout_sequence_review,
    )

    manifest = _manifest()
    manifest["cameras"][1]["start_frame"] = 27
    manifest["cameras"][1]["end_frame"] = 50
    manifest["shot_table"][1]["start_frame"] = 27
    manifest["shot_table"][1]["end_frame"] = 50
    #: 重叠声明 3 帧（24 止 -> 27 起，声明 3 = 覆盖）
    manifest["shot_table"][0]["transition_overlap_frames"] = 3
    manifest["shot_table"][1]["transition_overlap_frames"] = 3
    review = build_blockout_sequence_review(manifest=manifest)
    gaps = [f for f in review["findings"]
            if f["check_id"] == E_BLOCKOUT_TRANSITION_GAP]
    assert gaps == []
    #: 但 S02 仍越轴 -> 整体还是 fail（转场本身绿）
    transition_check = [c for c in review["checks"]
                        if c["dimension"] == "transition"]
    assert transition_check[0]["verdict"] == "pass"


def test_missing_cast_block_and_enter_exit_mismatch():
    from block_director.cinema.blockout_sequence import (
        E_BLOCKOUT_ENTER_EXIT_MISMATCH,
        E_BLOCKOUT_MISSING_CAST_BLOCK,
        build_blockout_sequence_review,
    )

    manifest = _manifest()
    #: 入画声明贵妇且不在本镜出场
    manifest["shot_table"][0]["enter_exit"] = {"enter": ["贵妇"], "exit": []}
    review = build_blockout_sequence_review(manifest=manifest)
    missing = [f for f in review["findings"]
               if f["check_id"] == E_BLOCKOUT_MISSING_CAST_BLOCK]
    mismatch = [f for f in review["findings"]
                if f["check_id"] == E_BLOCKOUT_ENTER_EXIT_MISMATCH]
    assert missing          #: 入画角色无体块
    assert mismatch         #: 入画声明不在本镜出场
    spatial = [c for c in review["checks"]
               if c["dimension"] == "spatial_continuity"]
    assert spatial[0]["verdict"] == "fail"
    assert review["verdict"] == "fail"


def test_deterministic_two_builds_byte_identical():
    from block_director.cinema.blockout_sequence import (
        build_blockout_sequence_review,
    )

    first = json.dumps(
        build_blockout_sequence_review(manifest=_manifest()),
        ensure_ascii=False, sort_keys=True)
    second = json.dumps(
        build_blockout_sequence_review(manifest=_manifest()),
        ensure_ascii=False, sort_keys=True)
    assert first == second
