"""空间理解/设计快照 Ticket 03：后向观测快照装配（SpatialFrame -> 观测快照）。

钉死：相机/元素回读 rotation、gaze（方向 + 计划目标映射）；运动差分（帧间
位移/速度/路径，``blender_geometry``）；旧字段 position/aabb/center/facing
保持原形状；空镜合法；两帧 delta<=0 不产生 NaN；同一输入两次装配逐位一致；
模块纯层（不 import bpy）。
"""

from __future__ import annotations

import ast
import json
import math
from pathlib import Path

import pytest

from block_director.cinema.spatial_digest import (
    SpatialCamera,
    SpatialElement,
    SpatialFrame,
)
from block_director.contracts.plan import FPS, Plan, ShotPlan

ROOT = Path(__file__).resolve().parents[1]


def _camera(pos=(0.0, 0.0, 2.0)):
    return SpatialCamera(
        position=pos, forward=(0.0, 0.0, -1.0), up=(0.0, 1.0, 0.0),
        lens_mm=50.0, sensor_width=36.0, sensor_height=24.0,
        sensor_fit="AUTO", render_width=1280, render_height=720,
        rotation={"quaternion": [1.0, 0.0, 0.0, 0.0],
                  "euler": [0.0, 0.0, 0.0], "order": "XYZ"},
    )


def _element(element_id, center, facing=None, gaze=None):
    return SpatialElement(
        id=element_id, kind="character", aabb_min=[-0.5, -0.5, 0.0],
        aabb_max=[0.5, 0.5, 1.8], center=center, facing=facing,
        rotation={"quaternion": [1.0, 0.0, 0.0, 0.0],
                  "euler": [0.0, 0.0, 0.0], "order": "XYZ"},
        gaze=gaze,
    )


def _frames():
    return [
        SpatialFrame(frame=1, shot_id="shot_001", camera=_camera(),
                     elements=[_element("米迦尔", (0.0, 0.0, 0.0),
                                        facing=(0.0, 1.0, 0.0),
                                        gaze={"target_id": None,
                                              "direction": [0.0, 1.0, 0.0]})]),
        SpatialFrame(frame=13, shot_id="shot_001", camera=_camera(),
                     elements=[_element("米迦尔", (0.0, 2.0, 0.0),
                                        facing=(0.0, 1.0, 0.0),
                                        gaze={"target_id": None,
                                              "direction": [0.0, 1.0, 0.0]})]),
        SpatialFrame(frame=25, shot_id="shot_001", camera=_camera(),
                     elements=[_element("米迦尔", (0.0, 4.0, 0.0),
                                        facing=(0.0, 1.0, 0.0),
                                        gaze={"target_id": None,
                                              "direction": [0.0, 1.0, 0.0]})]),
    ]


def _plan():
    return Plan(shots=[
        ShotPlan(shot_id="shot_001", intent="test", shot_type="MS",
                 duration_frames=24, order=1, characters=["米迦尔"],
                 gaze=[{"from": "米迦尔", "to": "伊恩"}]),
    ])


def _build(frames=None, plan=None):
    from block_director.layer5_orchestrator.observation_snapshot import (
        build_observation_snapshot,
    )

    return build_observation_snapshot(frames=frames or _frames(), plan=plan,
                                      run_id="obs-run")


def test_observation_snapshot_module_is_pure_no_bpy():
    source = ROOT / "block_director" / "layer5_orchestrator" \
        / "observation_snapshot.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any("bpy" in (alias.name or "")
                           for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            assert "bpy" not in (node.module or "")


def test_schema_version_and_shot_structure():
    data = _build().to_dict()
    assert data["schema_version"] == "spatial-understanding-observation/v1"
    assert len(data["shots"]) == 1
    shot = data["shots"][0]
    assert shot["shot_id"] == "shot_001"
    assert [f["frame"] for f in shot["frames"]] == [1, 13, 25]
    assert len(shot["motion"]) == 1


def test_camera_and_element_fields_wrapped_blender_geometry():
    data = _build().to_dict()
    shot = data["shots"][0]
    frame = shot["frames"][0]
    camera = frame["camera"]
    assert camera["position"]["value"] == [0.0, 0.0, 2.0]
    assert camera["position"]["unit"] == "m"
    assert camera["position"]["provenance"] == "blender_geometry"
    assert camera["rotation"]["value"]["quaternion"] == [1.0, 0.0, 0.0, 0.0]
    assert camera["rotation"]["provenance"] == "blender_geometry"
    assert camera["lens_mm"]["value"] == 50.0
    assert camera["fov_degrees"]["value"]["horizontal"] > 0.0
    element = frame["elements"][0]
    assert element["id"] == "米迦尔"
    assert element["kind"] == "character"
    assert element["position"]["value"] == [0.0, 0.0, 0.0]
    assert element["position"]["provenance"] == "blender_geometry"
    assert element["aabb"]["min"] == [-0.5, -0.5, 0.0]
    assert element["aabb"]["max"] == [0.5, 0.5, 1.8]
    assert element["facing"]["value"] == [0.0, 1.0, 0.0]
    assert element["facing"]["provenance"] == "blender_geometry"
    assert element["rotation"]["value"]["euler"] == [0.0, 0.0, 0.0]
    assert element["gaze"]["direction"]["value"] == [0.0, 1.0, 0.0]
    assert element["gaze"]["direction"]["provenance"] == "blender_geometry"


def test_motion_diff_uses_independent_worked_math():
    data = _build().to_dict()
    motion = data["shots"][0]["motion"][0]
    assert motion["subject_id"] == "米迦尔"
    #: 帧 1→13→25（FPS=24，每段 12 帧 = 0.5 s），位移 2 m/段 ⇒ 4 m/s。
    segment = 12.0 / FPS
    expected_speed = pytest.approx(2.0 / segment, abs=1e-3)
    assert motion["displacement_m"] == pytest.approx([2.0, 2.0], abs=1e-3)
    assert motion["speed_m_s"] == pytest.approx(
        [expected_speed.expected, expected_speed.expected], abs=1e-3)
    assert motion["total_displacement_m"] == pytest.approx(4.0, abs=1e-3)
    #: pytest.approx 不支持嵌套结构，路径逐点断言（值已四舍五入，精确比较）。
    assert motion["path"] == [[0.0, 0.0, 0.0], [0.0, 2.0, 0.0],
                              [0.0, 4.0, 0.0]]


def test_gaze_target_mapped_from_plan():
    data = _build(plan=_plan()).to_dict()
    element = data["shots"][0]["frames"][0]["elements"][0]
    assert element["gaze"]["target_id"] == "伊恩"


def test_gaze_target_stays_none_without_plan():
    data = _build(plan=None).to_dict()
    element = data["shots"][0]["frames"][0]["elements"][0]
    assert element["gaze"]["target_id"] is None


def test_empty_shot_produces_legal_snapshot():
    frames = [
        SpatialFrame(frame=1, shot_id="shot_empty", camera=_camera(),
                     elements=[]),
        SpatialFrame(frame=13, shot_id="shot_empty", camera=_camera(),
                     elements=[]),
    ]
    data = _build(frames=frames).to_dict()
    shot = data["shots"][0]
    assert shot["shot_id"] == "shot_empty"
    assert shot["frames"][0]["elements"] == []
    assert shot["motion"] == []


def test_single_frame_produces_motion_without_segments():
    frames = [SpatialFrame(frame=1, shot_id="shot_001", camera=_camera(),
                           elements=[_element("米迦尔", (0.0, 0.0, 0.0))])]
    data = _build(frames=frames).to_dict()
    assert data["shots"][0]["motion"] == []


def test_zero_frame_delta_never_produces_nan():
    frames = [
        SpatialFrame(frame=1, shot_id="shot_001", camera=_camera(),
                     elements=[_element("米迦尔", (0.0, 0.0, 0.0))]),
        SpatialFrame(frame=1, shot_id="shot_001", camera=_camera(),
                     elements=[_element("米迦尔", (0.0, 2.0, 0.0))]),
    ]
    data = _build(frames=frames).to_dict()
    shot = data["shots"][0]
    frame_values = [f["frame"] for f in shot["frames"]]
    assert frame_values == [1]
    #: 同帧重复被去重成单帧 → 无运动段，且全 JSON 无 NaN。
    assert shot["motion"] == []
    assert not any(
        isinstance(item, float) and math.isnan(item)
        for item in json.loads(json.dumps(data, allow_nan=True)
                               ).get("shots", []))


def test_two_builds_are_byte_identical():
    first = json.dumps(_build().to_dict(), ensure_ascii=False, sort_keys=True)
    second = json.dumps(_build().to_dict(), ensure_ascii=False, sort_keys=True)
    assert first == second


def test_observation_snapshot_serde_round_trip():
    from block_director.contracts.spatial_snapshot import (
        ObservationSnapshot,
    )

    built = _build()
    restored = ObservationSnapshot.from_dict(
        json.loads(json.dumps(built.to_dict())))
    assert restored.to_dict() == built.to_dict()
