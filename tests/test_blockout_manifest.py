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
                    "movements": [{"type": "dolly_in", "amount": 0.4,
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


def test_character_local_staging_becomes_auditable_shot_positions():
    design = _design()
    design["shots"] = [
        {"shot_id": "shot_001", "order": 1, "duration_frames": 24,
         "characters": ["米迦尔", "伊恩"], "actions": []},
        {"shot_id": "shot_002", "order": 2, "duration_frames": 12,
         "characters": ["米迦尔"], "actions": []},
    ]
    design["shot_staging"] = {
        "shot_001": {
            "米迦尔": {
                "position": {"x": 1.25, "y": 0.5, "z": 0.0},
                "provenance": "agent_local_revision",
                "reason": "第一镜双人构图错开",
            },
        },
    }

    manifest = _build(design=design)
    michael = next(
        primitive for primitive in manifest["primitives"]
        if primitive["kind"] == "character"
        and primitive["source"]["id"] == "米迦尔")

    assert michael["position"] == {"x": -0.9, "y": 0.0, "z": 0.0}
    assert michael["shot_positions"] == [
        {
            "shot_id": "shot_001",
            "position": {"x": 1.25, "y": 0.5, "z": 0.0},
            "start_frame": 1,
            "end_frame": 24,
            "provenance": "agent_local_revision",
            "reason": "第一镜双人构图错开",
        },
        {
            "shot_id": "shot_002",
            "position": {"x": -0.9, "y": 0.0, "z": 0.0},
            "start_frame": 25,
            "end_frame": 36,
            "provenance": "plan_intent",
            "reason": "",
        },
    ]
    ian = next(
        primitive for primitive in manifest["primitives"]
        if primitive["kind"] == "character"
        and primitive["source"]["id"] == "伊恩")
    assert ian["shot_positions"] == [
        {
            "shot_id": "shot_001",
            "position": {"x": 0.9, "y": 0.0, "z": 0.0},
            "start_frame": 1,
            "end_frame": 24,
            "provenance": "plan_intent",
            "reason": "",
        },
    ]


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
        {"type": "dolly_in", "amount": 0.4,
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


def test_design_shots_priority_drives_shot_table():
    """R10：design.shots[]（参考世界 JSON 语义层）优先决定分镜表。"""
    design = _design()
    design["shots"] = [
        {"shot_id": "shot_001", "order": 1, "duration_frames": 30,
         "intent": "开场", "characters": ["米迦尔"], "actions": []},
        {"shot_id": "shot_002", "order": 2, "duration_frames": 18,
         "intent": "空镜", "characters": [], "actions": []},
    ]
    manifest = _build(design=design)
    rows = {s["shot_id"]: s for s in manifest["shot_table"]}
    assert rows["shot_001"]["start_frame"] == 1
    assert rows["shot_001"]["end_frame"] == 30       # 跟随 design，非 plan 的 24
    assert rows["shot_002"]["start_frame"] == 31
    assert rows["shot_002"]["end_frame"] == 48       # 跟随 design 的 18 帧


def test_routes_derived_from_design_motion_by_shot():
    """R10：manifest.routes 从角色 motion_by_shot 确定性派生（walk_path actual）。"""
    design = _design()
    design["characters"][0]["motion_by_shot"] = [{
        "shot_id": "shot_001", "start": [-0.9, 0.0, 0.0],
        "end": [2.0, 1.0, 0.0], "speed_m_s": 1.0,
    }]
    manifest = _build(design=design)
    routes = {r["character"]: r for r in manifest["routes"]}
    assert routes["米迦尔"]["end"] == [2.0, 1.0, 0.0]
    assert routes["米迦尔"]["shot_id"] == "shot_001"
    assert routes["米迦尔"]["speed_m_s"] == 1.0


def test_manifest_with_routes_passes_schema():
    import json

    import jsonschema

    manifest = _build()
    manifest["routes"] = [{
        "character": "米迦尔", "shot_id": "shot_001",
        "start": [-0.9, 0.0, 0.0], "end": [2.0, 1.0, 0.0],
        "speed_m_s": 1.0, "provenance": "plan_intent",
    }]
    schema = json.loads((
        ROOT / "block_director" / "contracts" / "blockout" / "schema"
        / "blockout-manifest.v1.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(instance=manifest, schema=schema)


def test_coin_kind_aliases_do_not_fall_back_to_default_block_size():
    """真实 brief 的 ``kind="货币"`` 必须有硬币尺度，不能落默认 0.9×1.2。

    final16 真跑把银币标成 ``kind=货币``；旧尺寸表只认 ``prop`` 等少数
    英文键，于是银币成了 0.9×0.9×1.2 的巨块，在 shot_002/003 挡住
    偷盗者的手/脸。该测试从公开 manifest 边界验证中文与英文别名。
    """
    design = _design()
    design["props"] = [
        {"id": "银币", "kind": "货币", "owner": "偷盗者", "parent": None,
         "position": [0.22, 0.25, 0.91], "rotation": None, "motion": None,
         "provenance": "plan_intent"},
        {"id": "纪念币", "kind": "coin", "owner": "米迦尔", "parent": None,
         "position": [-0.22, 0.25, 0.91], "rotation": None, "motion": None,
         "provenance": "plan_intent"},
    ]
    manifest = _build(design=design)
    props = {p["source"]["id"]: p for p in manifest["primitives"]
             if p["kind"] == "prop"}

    assert set(props) == {"银币", "纪念币"}
    for prop in props.values():
        assert prop["size"]["x"] <= 0.2
        assert prop["size"]["y"] <= 0.2
        assert prop["size"]["z"] <= 0.1


def test_free_text_coin_kind_resolves_by_explicit_longest_alias():
    """final12 的 ``kind="银币化为金子"`` 必须命中“银币”别名。

    该输入不是闭集 kind，而是 Stage S 对状态变化的自由文本描述。尺寸档
    解析只允许显式别名命中：返回命中的别名与规范化档位供审计，不能靠
    模糊相似度猜。
    """
    from block_director.cinema.blockout import resolve_prop_kind

    resolved = resolve_prop_kind("银币化为金子")

    assert resolved.raw_kind == "银币化为金子"
    assert resolved.canonical_kind == "coin"
    assert resolved.matched_alias == "银币"
    assert resolved.match_mode == "alias"
    assert resolved.size == (0.12, 0.12, 0.03)


def test_exact_coin_kind_wins_before_alias_matching():
    from block_director.cinema.blockout import resolve_prop_kind

    resolved = resolve_prop_kind("货币")

    assert resolved.canonical_kind == "货币"
    assert resolved.matched_alias == ""
    assert resolved.match_mode == "exact"
    assert resolved.size == (0.12, 0.12, 0.03)


def test_unmatched_prop_kind_stays_auditable_fallback():
    from block_director.cinema.blockout import (
        DEFAULT_BLOCK_SIZE,
        resolve_prop_kind,
    )

    resolved = resolve_prop_kind("未知机械装置")

    assert resolved.canonical_kind == "prop"
    assert resolved.matched_alias == ""
    assert resolved.match_mode == "fallback"
    assert resolved.size == DEFAULT_BLOCK_SIZE


def test_manifest_records_free_text_kind_resolution():
    """别名归一化必须进入 manifest notes，保留原文、命中词和档位。"""
    design = _design()
    design["props"] = [
        {"id": "银币-金子", "kind": "银币化为金子", "owner": "偷盗者",
         "parent": None, "position": [0.22, 0.25, 0.91], "rotation": None,
         "motion": None, "provenance": "algorithmic_measurement"},
    ]

    manifest = _build(design=design)
    prop = next(p for p in manifest["primitives"] if p["kind"] == "prop")
    asset = next(a for a in manifest["asset_registry"]
                 if a["asset_id"] == prop["asset_ref"])

    assert prop["size"] == {"x": 0.12, "y": 0.12, "z": 0.03}
    assert asset["kind"] == "coin"
    assert any(
        "银币化为金子" in note and "银币" in note and "coin" in note
        for note in manifest["notes"])
