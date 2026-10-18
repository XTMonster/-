"""空间理解/设计快照 Ticket 01：空间 DTO 扩展的纯层 serde 测试。

钉死：``SpatialElement`` 新增 ``rotation`` / ``motion`` / ``gaze`` 可空字段、
``SpatialCamera`` 新增 ``rotation`` 可空字段——旧字段全保留、None 时输出键为
None（与既有 ``facing`` 同口径）、``from_dict`` 对缺失新键给 None（旧 JSON
仍可读）；dict 化 → JSON → from_dict 逐位一致（空值与满值两种样本）。

本文件不 import bpy；DTO 模块用 AST 对拍断言不 import bpy（红线保持）。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from block_director.cinema.spatial_digest import (
    SpatialCamera,
    SpatialElement,
    SpatialFrame,
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


def _element(rotation=None, motion=None, gaze=None):
    return SpatialElement(
        id="char_a",
        kind="character",
        aabb_min=(-0.5, -0.5, -10.5),
        aabb_max=(0.5, 0.5, -9.5),
        center=(0.0, 0.0, -10.0),
        facing=(0.0, 0.0, -1.0),
        rotation=rotation,
        motion=motion,
        gaze=gaze,
    )


def test_dto_pure_layer_never_imports_bpy():
    source = ROOT / "block_director" / "cinema" / "spatial_digest.py"
    assert _no_bpy_import(source)


def test_spatial_element_full_fields_round_trip_through_json():
    rotation = {"quaternion": [1.0, 0.0, 0.0, 0.0],
                "euler": [0.0, 0.0, 0.0], "order": "XYZ"}
    motion = {"frames": [1, 13, 25],
              "waypoints": [[0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                            [0.0, 2.0, 0.0]],
              "speed_m_s": [1.0, 1.0]}
    gaze = {"target_id": "char_b", "direction": [0.0, 1.0, 0.0]}
    frame = SpatialFrame(
        frame=7, shot_id="shot_001",
        camera=_camera(rotation=dict(rotation)),
        elements=[_element(rotation=dict(rotation), motion=dict(motion),
                           gaze=dict(gaze))],
    )
    restored = SpatialFrame.from_dict(
        json.loads(json.dumps(frame.to_dict())))
    assert restored.to_dict() == frame.to_dict()


def test_spatial_element_empty_fields_round_trip_through_json():
    """None 字段时：键仍输出（值为 None），from_dict 还原为 None。"""
    frame = SpatialFrame(frame=7, shot_id="shot_001",
                         camera=_camera(), elements=[_element()])
    text = frame.to_dict()
    element = text["elements"][0]
    assert element["rotation"] is None
    assert element["motion"] is None
    assert element["gaze"] is None
    assert text["camera"]["rotation"] is None
    restored = SpatialFrame.from_dict(json.loads(json.dumps(text)))
    assert restored.to_dict() == text
    assert restored.elements[0].rotation is None
    assert restored.elements[0].motion is None
    assert restored.elements[0].gaze is None
    assert restored.camera.rotation is None


def test_from_dict_missing_new_keys_yields_none():
    """旧 JSON（没有新键）仍可读：新字段一律 None，旧字段原样保留。"""
    old = {
        "frame": 7,
        "shot_id": "shot_001",
        "camera": _camera().to_dict(),
        "elements": [_element().to_dict()],
    }
    restored = SpatialFrame.from_dict(old)
    assert restored.camera.rotation is None
    assert restored.elements[0].rotation is None
    assert restored.elements[0].motion is None
    assert restored.elements[0].gaze is None
    assert restored.elements[0].facing == (0.0, 0.0, -1.0)
    assert restored.elements[0].center == (0.0, 0.0, -10.0)


def test_old_fields_still_serialize_unchanged():
    element = _element()
    data = element.to_dict()
    assert data["id"] == "char_a"
    assert data["kind"] == "character"
    assert data["aabb_min"] == [-0.5, -0.5, -10.5]
    assert data["aabb_max"] == [0.5, 0.5, -9.5]
    assert data["center"] == [0.0, 0.0, -10.0]
    assert data["facing"] == [0.0, 0.0, -1.0]
    camera = _camera().to_dict()
    assert camera["position"] == [0.0, 0.0, 0.0]
    assert camera["forward"] == [0.0, 0.0, -1.0]
    assert camera["up"] == [0.0, 1.0, 0.0]
    assert camera["lens_mm"] == 18.0
    assert camera["sensor_fit"] == "AUTO"
    assert camera["render_width"] == 1280
    assert camera["render_height"] == 720


def test_spatial_digest_still_serializes_with_optional_new_fields():
    """spatial_digest 对带新字段的元素保持判定不变（加法兼容）。"""
    from block_director.cinema.spatial_digest import spatial_digest

    frame = SpatialFrame(
        frame=7, shot_id="shot_001", camera=_camera(),
        elements=[_element(gaze={"target_id": "char_b",
                                 "direction": [0.0, 1.0, 0.0]})],
    )
    digest = spatial_digest([frame], collision_margin=0.2)
    text = json.dumps(digest, ensure_ascii=False)
    assert json.loads(text)["frames"][0]["elements"][0]["id"] == "char_a"
