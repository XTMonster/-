"""Ticket 04：设计 vs 实测对照器与阈值 registry TDD 测试。

钉死：对同一镜的「设计快照」与「观测快照」做确定性对照，产出结构化偏差
报告：位置偏差（欧氏距离）、朝向夹角、视线夹角、运动路径偏差；所有阈值收进
registry（一处定义，无魔法数字），各项带 expected/actual/threshold/verdict；
设计值缺失/未解析时如实标记，不脑补。本文件不 import bpy；实现模块用 AST
对拍不 import bpy（红线保持）。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

from block_director.cinema.spatial_diff import (
    DIFF_SNAPSHOT_SCHEMA,
    REGISTRY,
    build_diff_report,
)

ROOT = Path(__file__).resolve().parents[1]


def _no_bpy_import(module: Path) -> bool:
    tree = ast.parse(module.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any("bpy" in (alias.name or "") for alias in node.names):
                return False
        if isinstance(node, ast.ImportFrom):
            if "bpy" in (node.module or ""):
                return False
    return True


def _design():
    return {
        "schema_version": "spatial-design-snapshot/v1",
        "scene_id": "market",
        "characters": [
            {
                "name": "米迦尔",
                "position": {"x": 0.0, "y": 0.0, "z": 0.0},
                "rotation": None,
                "facing": [0.0, 1.0, 0.0],
                "motion": None,
                "gaze": {"target_id": "伊恩", "direction": [1.0, 0.0, 0.0]},
            },
        ],
        "props": [],
        "anchors": [],
        "camera_intents": [
            {
                "shot_id": "shot_001",
                "position": [5.0, -3.0, 1.6],
                "target": [0.0, 0.0, 1.3855],
                "lens": 35.0,
                "fov_deg": 54.4,
                "provenance": "algorithmic_measurement",
                "resolved": True,
            },
        ],
        "shots": [{
            "shot_id": "shot_001",
            "characters": ["米迦尔"],
        }],
        "notes": [],
    }


def _observed(hero_center=(0.0, 0.0, 0.0)):
    hx, hy, hz = hero_center
    return {
        "schema_version": "spatial-observation/v1",
        "shots": [
            {
                "shot_id": "shot_001",
                "samples": [
                    {
                        "frame": 1,
                        "camera": {"position": [5.3, -3.2, 1.6],
                                   "provenance": "blender_geometry",
                                   "unit": {"position": "m"}},
                        "elements": [
                            {
                                "id": "米迦尔", "kind": "character",
                                "center": list(hero_center),
                                "aabb_min": [hx - 0.5, hy - 0.5, 0.0],
                                "aabb_max": [hx + 0.5, hy + 0.5, 1.7],
                                "facing": [0.0, 1.0, 0.0],
                                "rotation": None, "motion": None,
                                "gaze": {"target_id": None,
                                         "direction": [1.0, 0.0, 0.0]},
                                "provenance": "blender_geometry",
                            },
                        ],
                    },
                ],
            },
        ],
    }


def test_spatial_diff_pure_layer_never_imports_bpy():
    assert _no_bpy_import(ROOT / "block_director" / "cinema"
                          / "spatial_diff.py")


def test_registry_is_single_source_of_thresholds():
    # 对照器内部不得硬编码阈值数字；一切阈值从 registry 读
    assert "camera_position_m" in REGISTRY
    assert "character_position_m" in REGISTRY
    assert "heading_angle_deg" in REGISTRY
    assert "gaze_angle_deg" in REGISTRY
    assert "motion_displacement_m" in REGISTRY
    assert REGISTRY["camera_position_m"] > 0.0


def test_camera_and_character_position_diff_numeric():
    hero_drift = (0.25, 0.0, 0.0)   # 设计 (0,0,0)，实测 (0.25,0,0)
    report = build_diff_report(_design(), _observed(hero_center=hero_drift))
    assert report["schema_version"] == DIFF_SNAPSHOT_SCHEMA
    items = {item["metric"]: item for item in report["items"]}
    cam = items["camera_position"]
    # 设计 (5,-3,1.6) vs 实测 (5.3,-3.2,1.6) -> sqrt(0.09+0.04)=0.360555
    assert cam["expected"] == [5.0, -3.0, 1.6]
    assert abs(cam["actual"] - 0.3606) < 1e-3
    assert cam["threshold"] == REGISTRY["camera_position_m"]
    assert cam["verdict"] in ("pass", "fail")
    assert cam["unit"] == "m"
    char = items["character_position"]
    # 设计脚底中心 (0,0,0) vs 实测 AABB 的脚底中心
    # ((xmin+xmax)/2, (ymin+ymax)/2, zmin) = (0.25,0,0)
    assert abs(char["actual"] - 0.25) < 1e-6
    assert char["subject"] == "米迦尔"


def test_heading_and_gaze_angle_diff():
    observed = _observed()
    observed["shots"][0]["samples"][0]["elements"][0]["facing"] = \
        [1.0, 0.0, 0.0]   # 设计 facing +Y vs 实测 +X -> 90°
    report = build_diff_report(_design(), observed)
    items = {item["metric"]: item for item in report["items"]}
    heading = items["heading_angle"]
    assert abs(heading["actual"] - 90.0) < 1e-6
    assert heading["threshold"] == REGISTRY["heading_angle_deg"]
    # gaze 方向一致 -> 夹角 0
    gaze = items["gaze_angle"]
    assert abs(gaze["actual"] - 0.0) < 1e-6


def test_heading_and_gaze_use_the_shots_expected_direction():
    design = _design()
    character = design["characters"][0]
    character["facing"] = [0.0, 1.0, 0.0]
    character["facing_by_shot"] = [{
        "shot_id": "shot_001",
        "direction": [1.0, 0.0, 0.0],
    }]
    character["gaze"] = {
        "target_id": "伊恩",
        "direction": [0.0, 1.0, 0.0],
    }
    character["gaze_by_shot"] = [{
        "shot_id": "shot_001",
        "target_id": "伊恩",
        "direction": [1.0, 0.0, 0.0],
    }]

    observed = _observed()
    observed["shots"][0]["samples"][0]["elements"][0]["facing"] = \
        [1.0, 0.0, 0.0]
    report = build_diff_report(design, observed)
    items = {item["metric"]: item for item in report["items"]}

    assert items["heading_angle"]["actual"] == 0.0
    assert items["gaze_angle"]["actual"] == 0.0


def test_design_missing_character_marks_unresolved():
    design = _design()
    design["characters"] = []   # 设计层没这个角色（不该脑补）
    report = build_diff_report(design, _observed())
    items = {item["metric"]: item for item in report["items"]}
    assert "character_position" in items
    assert items["character_position"]["verdict"] == "unresolved"


def test_only_characters_declared_for_the_shot_are_compared():
    design = _design()
    design["characters"].append({
        "name": "伊恩",
        "position": {"x": 2.0, "y": 0.0, "z": 0.0},
        "facing": [0.0, 1.0, 0.0],
        "gaze": None,
    })

    report = build_diff_report(design, _observed())
    character_subjects = {
        item["subject"] for item in report["items"]
        if item["metric"] == "character_position"
    }

    assert character_subjects == {"米迦尔"}


def test_report_deterministic_and_json_serializable():
    first = json.dumps(build_diff_report(_design(), _observed()),
                       sort_keys=True, ensure_ascii=False)
    second = json.dumps(build_diff_report(_design(), _observed()),
                        sort_keys=True, ensure_ascii=False)
    assert first == second


def test_character_position_uses_foot_center_anchor():
    """位置比较用脚底中心，而不是 AABB 角点或包围盒中心。"""
    observed = _observed()
    observed["shots"][0]["samples"][0]["elements"][0]["aabb_min"] = \
        [0.25, -0.5, 0.0]
    observed["shots"][0]["samples"][0]["elements"][0]["aabb_max"] = \
        [0.75, 0.5, 1.7]   # 脚底中心 (0.5, 0, 0)，盒中心在 z=0.85
    report = build_diff_report(_design(), observed)
    items = {item["metric"]: item for item in report["items"]}
    char = items["character_position"]
    # 设计脚底中心 (0,0,0) vs 实测脚底中心 (0.5,0,0) -> 0.5
    # 用 aabb_min 角点会错得 0.559，用盒中心会错得 0.984
    assert abs(char["actual"] - 0.5) < 1e-9
