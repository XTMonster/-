"""空间理解/设计快照 Ticket 02：前向设计转换器（brief+plan+cast -> 设计快照）。

钉死：坐标/旋转/运动/视线/锚点/机位正确入位且 provenance 诚实——角色站位来自
计划动作或 cast（``plan_intent``）；锚点经 ``solve_anchor_positions`` 解算
（``algorithmic_measurement``）、解不出照实记 ``unresolved`` 且**不带 position**
（不采用求解器缺省环坐标）；机位来自 framing 求解器（``algorithmic_measurement``）；
空镜产出合法快照；同一输入两次转换逐位一致；DTO serde 往返一致；纯层不 import bpy。
"""

from __future__ import annotations

import ast
import json
import math
from pathlib import Path

import pytest

from block_director.contracts.brief import SceneBrief
from block_director.contracts.plan import Plan, ShotPlan

ROOT = Path(__file__).resolve().parents[1]


def _plan() -> Plan:
    return Plan(
        shots=[
            ShotPlan(
                shot_id="shot_001",
                intent="米迦尔走向银币摊",
                shot_type="MS",
                duration_frames=24,
                order=1,
                characters=["米迦尔"],
                actions=[{
                    "type": "walk_to",
                    "start_frame": 1,
                    "end_frame": 24,
                    "params": {"from": [0.0, 0.0, 0.0],
                               "to": [2.0, 0.0, 0.0],
                               "speed": "walk"},
                }],
                camera={"side": "front", "lens": 50},
                gaze=[{"from": "米迦尔", "to": "伊恩"}],
            ),
            ShotPlan(
                shot_id="shot_002",
                intent="空镜：银币摊",
                shot_type="MS",
                duration_frames=12,
                order=2,
                characters=[],
                camera={"lens": 35},
            ),
        ],
        environment={
            "anchors": [
                {"name": "生蚝摊", "relation": "left_of 米迦尔 2m"},
                {"name": "幽灵摊位", "relation": "behind 幽灵"},
            ],
        },
    )


def _brief() -> SceneBrief:
    return SceneBrief(
        gaze=[{"from": "米迦尔", "to": "伊恩", "scope": "all"}],
        props=[{"id": "摊位_01", "kind": "prop", "owner": "米迦尔"}],
    )


def _cast():
    return {
        "米迦尔": {"position": [0.0, 0.0, 0.0], "facing": [0.0, 1.0, 0.0]},
        "伊恩": {"position": [2.0, 2.0, 0.0], "facing": [0.0, 1.0, 0.0]},
    }


def _build():
    from block_director.layer5_orchestrator.design_snapshot import (
        build_design_snapshot,
    )

    return build_design_snapshot(brief=_brief(), plan=_plan(), cast=_cast(),
                                 run_id="test-run")


def test_design_snapshot_module_is_pure_no_bpy():
    source = ROOT / "block_director" / "layer5_orchestrator" \
        / "design_snapshot.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any("bpy" in (alias.name or "")
                           for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            assert "bpy" not in (node.module or "")


def test_schema_version_and_structure():
    snapshot = _build()
    data = snapshot.to_dict()
    assert data["schema_version"] == "spatial-understanding-design/v1"
    assert data["run_context"]["run_id"] == "test-run"
    assert data["shot_ids"] == ["shot_001", "shot_002"]
    assert {c["id"] for c in data["characters"]} == {"米迦尔"}
    assert {p["id"] for p in data["props"]} == {"摊位_01"}
    assert {a["label"] for a in data["anchors"]} == {"生蚝摊", "幽灵摊位"}
    assert [c["shot_id"] for c in data["camera_intents"]] == \
        ["shot_001", "shot_002"]


def test_character_position_facing_motion_gaze_provenance():
    data = _build().to_dict()
    char = next(c for c in data["characters"] if c["id"] == "米迦尔")
    assert char["position"] == {
        "value": [0.0, 0.0, 0.0], "unit": "m", "provenance": "plan_intent"}
    assert char["facing"] == {
        "value": [0.0, 1.0, 0.0], "unit": "none", "provenance": "plan_intent"}
    motion = char["motion"]
    assert motion["action_type"] == "walk_to"
    assert motion["from"] == [0.0, 0.0, 0.0]
    assert motion["to"] == [2.0, 0.0, 0.0]
    assert motion["speed"] == "walk"
    assert motion["start_frame"] == 1
    assert motion["end_frame"] == 24
    assert motion["provenance"] == "plan_intent"
    gaze = char["gaze"]
    assert gaze["target_id"] == "伊恩"
    assert gaze["provenance"] == "plan_intent"
    expected = (1.0 / math.sqrt(2.0), 1.0 / math.sqrt(2.0), 0.0)
    assert gaze["direction"]["value"] == pytest.approx(list(expected), abs=1e-3)


def test_anchor_resolved_via_solver_algorithmic():
    data = _build().to_dict()
    anchor = next(a for a in data["anchors"] if a["label"] == "生蚝摊")
    assert anchor["status"] == "resolved"
    assert anchor["position"]["value"] == pytest.approx(
        [-2.0, 0.0, 0.0], abs=1e-3)
    assert anchor["position"]["provenance"] == "algorithmic_measurement"
    assert anchor["position"]["unit"] == "m"


def test_anchor_unresolved_is_honest_without_position():
    data = _build().to_dict()
    anchor = next(a for a in data["anchors"] if a["label"] == "幽灵摊位")
    assert anchor["status"] == "unresolved"
    assert anchor["position"] is None
    assert anchor["reason"]
    assert "position" in anchor.get("unresolved", [])


def test_camera_intent_shot_001_from_framing_solver():
    from block_director.cinema.framing import (
        ASPECT_16_9,
        SENSOR_WIDTH,
        vertical_fov,
    )

    data = _build().to_dict()
    intent = next(c for c in data["camera_intents"]
                  if c["shot_id"] == "shot_001")
    assert intent["lens_mm"]["value"] == 50
    assert intent["lens_mm"]["provenance"] == "plan_intent"
    assert intent["position"]["provenance"] == "algorithmic_measurement"
    #: 目标点在主体正上方轴线（x/y 与主体一致），z 为求解器的设计对准高度。
    assert intent["target"]["value"][:2] == pytest.approx([0.0, 0.0],
                                                          abs=1e-3)
    assert intent["target"]["value"][2] > 0.0
    assert intent["rotation"]["provenance"] == "algorithmic_measurement"
    expected_v = math.degrees(vertical_fov(50.0, SENSOR_WIDTH, ASPECT_16_9))
    expected_h = math.degrees(2.0 * math.atan(
        SENSOR_WIDTH / (2.0 * 50.0)))
    assert intent["fov_degrees"]["value"]["vertical"] == pytest.approx(
        expected_v, abs=1e-3)
    assert intent["fov_degrees"]["value"]["horizontal"] == pytest.approx(
        expected_h, abs=1e-3)


def test_empty_shot_produces_legal_camera_intent():
    data = _build().to_dict()
    intent = next(c for c in data["camera_intents"]
                  if c["shot_id"] == "shot_002")
    assert intent["lens_mm"]["value"] == 35
    assert intent["position"] is None
    assert "position" in intent["unresolved"]
    #: 空镜不贡献角色条目（shot_001 的角色不被误带到空镜）。
    assert all(c["shot_id"] != "shot_002" for c in data["characters"])


def test_prop_without_position_is_unresolved_but_has_owner_kind():
    data = _build().to_dict()
    prop = next(p for p in data["props"] if p["id"] == "摊位_01")
    assert prop["kind"] == "prop"
    assert prop["owner"] == "米迦尔"
    assert prop["position"] is None
    assert "position" in prop["unresolved"]


def test_two_conversions_are_byte_identical():
    first = _build().to_dict()
    second = _build().to_dict()
    assert json.dumps(first, ensure_ascii=False, sort_keys=True) == \
        json.dumps(second, ensure_ascii=False, sort_keys=True)


def test_design_snapshot_serde_round_trip():
    from block_director.contracts.spatial_snapshot import DesignSnapshot

    original = _build()
    restored = DesignSnapshot.from_dict(
        json.loads(json.dumps(original.to_dict())))
    assert restored.to_dict() == original.to_dict()
