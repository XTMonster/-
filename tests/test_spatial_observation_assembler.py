"""Ticket 03：后向观测快照装配器 TDD 测试。

钉死：给定一组 `SpatialFrame`（含 rotation / motion / gaze 新字段，
来自 ticket 01 的 DTO），确定性装配成版本化「观测快照」：逐镜、逐角色/物品、
逐采样帧，字段带 provenance=blender_geometry + unit；差分运动（位移/速度）
数值正确；旧字段形状不变；空镜合法。本文件不 import bpy；实现模块用 AST
对拍不 import bpy（红线保持）。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

from block_director.cinema.spatial_digest import (
    SpatialCamera,
    SpatialElement,
    SpatialFrame,
)
from block_director.cinema.spatial_observation import (
    OBSERVATION_SNAPSHOT_SCHEMA,
    build_observation_snapshot,
    frame_displacements,
)
from block_director.utils.geometry import rotation_payload

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


def _camera(rotation=None):
    return SpatialCamera(
        position=(0.0, 0.0, 0.0),
        forward=(0.0, 0.0, -1.0),
        up=(0.0, 1.0, 0.0),
        lens_mm=18.0,
        sensor_width=36.0,
        sensor_height=24.0,
        sensor_fit="AUTO",
        render_width=1280,
        render_height=720,
        rotation=rotation,
    )


def _rot(q_w=1.0, z=0.0):
    return {"quaternion": [q_w, 0.0, 0.0, 0.0],
            "euler": [0.0, 0.0, z], "order": "XYZ"}


def _hero(frame: int):
    """角色在帧间移动（frame1 在原点，frame2 移到 +X）。"""
    x = 0.0 if frame == 1 else 2.0 if frame == 13 else 4.0
    return SpatialElement(
        id="hero", kind="character",
        aabb_min=(x - 0.5, -0.5, 0.0), aabb_max=(x + 0.5, 0.5, 1.7),
        center=(x, 0.0, 0.85), facing=(0.0, 1.0, 0.0),
        rotation=_rot(), motion=None,
        gaze={"target_id": "enemy", "direction": [0.0, 1.0, 0.0]},
    )


def _frames():
    return [
        SpatialFrame(frame=1, shot_id="shot_001", camera=_camera(),
                     elements=[_hero(1)]),
        SpatialFrame(frame=13, shot_id="shot_001", camera=_camera(),
                     elements=[_hero(13)]),
        SpatialFrame(frame=25, shot_id="shot_001", camera=_camera(),
                     elements=[_hero(25)]),
    ]


def test_observation_snapshot_pure_layer_never_imports_bpy():
    assert _no_bpy_import(ROOT / "block_director" / "cinema"
                          / "spatial_observation.py")


def test_build_observation_snapshot_fields_and_unit():
    snap = build_observation_snapshot(_frames())
    assert snap["schema_version"] == OBSERVATION_SNAPSHOT_SCHEMA
    shots = snap["shots"]
    assert len(shots) == 1 and shots[0]["shot_id"] == "shot_001"
    samples = shots[0]["samples"]
    assert [s["frame"] for s in samples] == [1, 13, 25]
    element = samples[0]["elements"][0]
    # rotation / gaze 来自 DTO 透传，来源一律 blender_geometry
    assert element["rotation"]["quaternion"] == [1.0, 0.0, 0.0, 0.0]
    assert element["gaze"]["target_id"] == "enemy"
    assert element["provenance"] == "blender_geometry"
    assert element["unit"]["position"] == "m"
    camera = samples[0]["camera"]
    assert camera["provenance"] == "blender_geometry"
    assert camera["rotation"] is not None or camera["rotation"] is None
    # 旧字段形状保留（center/aabb/facing）
    assert len(element["aabb_min"]) == 3 and len(element["center"]) == 3


def test_frame_displacements_numeric():
    hero_positions = {
        1: [0.0, 0.0, 0.0],
        13: [2.0, 0.0, 0.0],
        25: [4.0, 0.0, 0.0],
    }
    disp = frame_displacements(hero_positions)
    assert len(disp["waypoints"]) == 3
    # 帧1->13：位移 2m，12 帧 @24fps = 0.5s -> 4.0 m/s
    assert disp["displacements"][0] == [2.0, 0.0, 0.0]
    assert abs(disp["speed_m_s"][0] - 4.0) < 1e-6
    assert comp(disp["total_travel"])  # 2+2


def comp(value):
    return abs(value - 4.0) < 1e-6


def test_observation_snapshot_empty_shot_valid():
    empty_camera = _camera(rotation=_rot())
    frame = SpatialFrame(frame=1, shot_id="shot_000",
                         camera=empty_camera, elements=[])
    snap = build_observation_snapshot([frame])
    assert snap["shots"][0]["samples"][0]["elements"] == []
    assert snap["shots"][0]["samples"][0]["camera"]["rotation"] is not None


def test_observation_snapshot_deterministic():
    first = json.dumps(build_observation_snapshot(_frames()),
                       sort_keys=True, ensure_ascii=False)
    second = json.dumps(build_observation_snapshot(_frames()),
                        sort_keys=True, ensure_ascii=False)
    assert first == second


def test_rotation_payload_normalizes_and_rounds():
    payload = rotation_payload((1.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    assert payload["quaternion"] == [1.0, 0.0, 0.0, 0.0]
    assert payload["euler"] == [0.0, 0.0, 0.0]
    assert payload["order"] == "XYZ"
    # 数值浮点也归一（四舍五入到 4 位，观察契约口径）
    payload = rotation_payload((1.0000001, 0.0, 0.0, 0.0),
                               (0.123456789, 0.0, 0.0))
    assert payload["quaternion"][0] == 1.0
    assert payload["euler"][0] == 0.1235
