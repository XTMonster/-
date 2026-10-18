"""Ticket 02：前向空间设计转换器（brief -> 设计快照）TDD 测试。

钉死：把理解剧本后的散文语义（SceneBrief space/environment/gaze/props）与
计划意图（站位/动作/机位）确定性转换成版本化「空间设计快照」：每角色
position/rotation/motion/gaze/facing + provenance；每物品 position/rotation/
motion/owner/parent/kind；锚点经求解器解出 label->坐标（解不出如实记，
不伪造精确解）；每镜机位设计值。本文件不 import bpy；实现模块用 AST 对拍
不 import bpy（红线保持）。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from block_director.cinema.spatial_design import build_design_snapshot

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


def _brief():
    """合成 SceneBrief 形状：散文语义层（与 contracts/brief.py 字段一致）。"""
    return {
        "speakers": [
            {"speaker": "米迦尔", "listener": "伊恩"},
            {"speaker": "伊恩", "listener": "米迦尔"},
        ],
        "gaze": [
            {"from": "米迦尔", "to": "伊恩", "scope": "all"},
        ],
        "beats": [],
        "space": [
            {"character": "米迦尔", "relative_to": "伊恩",
             "relation": "side_by_side", "distance_class": "near"},
        ],
        "environment": [
            {"label": "生蚝摊", "direction": "left", "distance": "near",
             "size": "m", "mood": ""},
            {"label": "银币摊", "direction": "right", "distance": "mid",
             "size": "m", "mood": ""},
        ],
        "arc": {},
        "props": [
            {"id": "银币", "kind": "coin", "owner": "偷盗者",
             "state_changes": [{"to": "双手捧着"}]},
        ],
        "notes": [],
    }


def _plan():
    """合成计划形状（ShotPlan.to_dict 的 dict 版本，够转换器消费的字段）。"""
    return {
        "shot_id": "shot_001",
        "intent": "建立",
        "shot_type": "MS",
        "duration_frames": 120,
        "order": 1,
        "characters": ["米迦尔", "伊恩"],
        "actions": [
            {"action_type": "walk_to", "character_id": "伊恩",
             "params": {"target_position": [2.0, -1.0, 0.0]}},
            {"action_type": "look_at", "character_id": "米迦尔",
             "params": {"target": "伊恩"}},
        ],
        "dialogues": [],
        "prompt": "",
        "camera": {"side": "front", "lens": 35.0},
        "axis_note": "",
        "continuity_in": "",
        "gaze": [{"from": "米迦尔", "to": "伊恩"}],
        "vfx": [],
        "composition": {},
        "rule_justifications": [],
        "responsibility": None,
    }


def _cast_positions():
    """角色站位声明（plan_intent 源：initial_location）。"""
    return {
        "米迦尔": [0.0, 0.0, 0.0],
        "伊恩": [2.0, 0.0, 0.0],
        "偷盗者": [4.0, 1.0, 0.0],
    }


def test_design_converter_pure_layer_never_imports_bpy():
    source = ROOT / "block_director" / "cinema" / "spatial_design.py"
    assert _no_bpy_import(source)


def test_character_full_fields_enter_snapshot():
    snap = build_design_snapshot(
        brief=_brief(), plan=_plan(), cast_positions=_cast_positions(),
        scene_id="market")
    assert snap["schema_version"].startswith("spatial-design-snapshot/")
    chars = {item["name"]: item for item in snap["characters"]}
    assert "米迦尔" in chars and "伊恩" in chars
    mika = chars["米迦尔"]
    # 站位声明直接入位（不脑补），来源 plan_intent
    assert mika["position"]["x"] == 0.0
    assert mika["provenance"] == "plan_intent"
    assert mika["unit"]["position"] == "m"
    # 视线：brief + plan 都说米迦尔看伊恩；目标站位已知 -> 方向向量可算
    assert mika["gaze"]["target_id"] == "伊恩"
    direction = mika["gaze"]["direction"]
    assert direction is not None and len(direction) == 3
    # 旋转与 facing 有结构、可空
    assert mika["rotation"] is None or isinstance(mika["rotation"], dict)
    ian = chars["伊恩"]
    # 运动意图：walk_to target -> motion 路径/终点
    assert ian["motion"]["end"] == [2.0, -1.0, 0.0]
    assert ian["motion"]["provenance"] == "plan_intent"


def test_anchor_resolved_via_solver():
    snap = build_design_snapshot(
        brief=_brief(), plan=_plan(), cast_positions=_cast_positions(),
        scene_id="market")
    anchors = {item["label"]: item for item in snap["anchors"]}
    assert "生蚝摊" in anchors and "银币摊" in anchors
    oyster = anchors["生蚝摊"]
    # 锚点坐标来自求解器（algorithmic_measurement），不是模型猜
    assert oyster["provenance"] == "algorithmic_measurement"
    assert len(oyster["position"]) == 3
    assert all(isinstance(v, (int, float)) for v in oyster["position"])


def test_anchor_unresolved_is_honest_not_fake():
    brief = _brief()
    brief["environment"] = [
        # direction 取闭集外（非法语义）-> 转换器无法确定落位，必须如实记
        {"label": "神秘物件", "direction": "diagonal", "distance": "near",
         "size": "m", "mood": ""},
    ]
    snapshot = build_design_snapshot(
        brief=brief, plan=_plan(), cast_positions=_cast_positions(),
        scene_id="market")
    # 非法语义不能伪造"精确解"：标 resolved=False + 留痕。
    anchor = snapshot["anchors"][0]
    assert anchor["label"] == "神秘物件"
    assert anchor["resolved"] is False
    assert anchor.get("unresolved_reason")
    reasons = [note for note in snapshot["notes"] if "神秘物件" in note]
    assert reasons, "未解析锚点必须留痕，不许静默伪造"


def test_camera_intent_from_framing():
    snap = build_design_snapshot(
        brief=_brief(), plan=_plan(), cast_positions=_cast_positions(),
        scene_id="market")
    cams = {item["shot_id"]: item for item in snap["camera_intents"]}
    assert "shot_001" in cams
    cam = cams["shot_001"]
    # 机位来自 framing 求解（algorithmic_measurement）：position/target/lens 齐
    assert cam["provenance"] == "algorithmic_measurement"
    assert len(cam["position"]) == 3 and len(cam["target"]) == 3
    assert cam["lens"] > 0.0
    assert cam["fov_deg"] > 0.0


def test_empty_shot_is_valid_snapshot():
    plan = dict(_plan())
    plan["characters"] = []
    plan["actions"] = []
    snap = build_design_snapshot(
        brief={}, plan=plan, cast_positions={}, scene_id="empty")
    assert snap["characters"] == []
    assert snap["camera_intents"]  # 空镜仍有机位设计（建立/留白/转场）


def test_deterministic_two_builds_identical():
    first = build_design_snapshot(
        brief=_brief(), plan=_plan(), cast_positions=_cast_positions(),
        scene_id="market")
    second = build_design_snapshot(
        brief=_brief(), plan=_plan(), cast_positions=_cast_positions(),
        scene_id="market")
    assert json.dumps(first, sort_keys=True, ensure_ascii=False) == \
        json.dumps(second, sort_keys=True, ensure_ascii=False)


def test_plan_character_without_position_is_honest():
    """角色在计划里但无站位声明：不脑补坐标，记 note 且 position 可空/缺省显式。"""
    plan = dict(_plan())
    plan["characters"] = ["神秘人"]
    cast = dict(_cast_positions())
    cast.pop("神秘人", None)
    snap = build_design_snapshot(
        brief=_brief(), plan=plan, cast_positions=cast, scene_id="market")
    names = [item["name"] for item in snap["characters"]]
    assert "神秘人" in names
    notes = [note for note in snap["notes"] if "神秘人" in note]
    assert notes, "计划里无站位的角色必须留痕，不得静默落默认坐标"
