"""Ticket 06：空间快照契约版本化、审计留痕与零 LLM 重放 TDD 测试。

钉死：设计快照 / 观测快照 / diff 报告三份 JSON Schema 与 DTO 产出一致
（合法实例通过 jsonschema 校验、非法实例被拒绝）；生成快照写审计事件
（含 kind/时间/指纹）；重放路径零 LLM 调用（设计从 brief+plan 确定性重建、
观测从 SpatialFrame dict 重建，产物逐位一致）。schema 定义在纯层契约模块。
"""

from __future__ import annotations

import json

import jsonschema
import pytest

from block_director.contracts.spatial_snapshot import (
    DESIGN_SCHEMA,
    DIFF_SCHEMA,
    OBSERVATION_SCHEMA,
    snapshot_audit_event,
)
from block_director.cinema.spatial_design import build_design_snapshot
from block_director.cinema.spatial_diff import build_diff_report
from block_director.cinema.spatial_observation import build_observation_snapshot
from block_director.cinema.spatial_digest import (
    SpatialCamera,
    SpatialElement,
    SpatialFrame,
)


def _design():
    return build_design_snapshot(
        brief={
            "gaze": [{"from": "米迦尔", "to": "伊恩", "scope": "all"}],
            "environment": [
                {"label": "生蚝摊", "direction": "left", "distance": "near",
                 "size": "m", "mood": ""},
            ],
            "props": [{"id": "银币", "kind": "coin", "owner": "偷盗者",
                       "state_changes": []}],
        },
        plan={
            "shot_id": "shot_001", "shot_type": "MS",
            "duration_frames": 120, "characters": ["米迦尔", "伊恩"],
            "actions": [
                {"action_type": "look_at", "character_id": "米迦尔",
                 "params": {"target": "伊恩"}},
            ],
            "camera": {"side": "front", "lens": 35.0},
            "gaze": [{"from": "米迦尔", "to": "伊恩"}],
        },
        cast_positions={"米迦尔": [0.0, 0.0, 0.0], "伊恩": [2.0, 0.0, 0.0]},
        scene_id="market")


def _observation():
    camera = SpatialCamera(
        position=(0.0, 0.0, 0.0), forward=(0.0, 0.0, -1.0),
        up=(0.0, 1.0, 0.0), lens_mm=18.0, sensor_width=36.0,
        sensor_height=24.0, sensor_fit="AUTO",
        render_width=1280, render_height=720)
    element = SpatialElement(
        id="米迦尔", kind="character",
        aabb_min=(-0.5, -0.5, 0.0), aabb_max=(0.5, 0.5, 1.7),
        center=(0.0, 0.0, 0.85), facing=(0.0, 1.0, 0.0),
        rotation=None, motion=None,
        gaze={"target_id": None, "direction": [0.0, 1.0, 0.0]})
    return build_observation_snapshot([
        SpatialFrame(frame=1, shot_id="shot_001", camera=camera,
                     elements=[element]),
    ])


def test_design_snapshot_passes_schema():
    jsonschema.validate(instance=_design(), schema=DESIGN_SCHEMA)


def test_observation_snapshot_passes_schema():
    jsonschema.validate(instance=_observation(), schema=OBSERVATION_SCHEMA)


def test_diff_report_passes_schema():
    report = build_diff_report(_design(), _observation())
    jsonschema.validate(instance=report, schema=DIFF_SCHEMA)


def test_invalid_instances_rejected():
    bad_design = dict(_design())
    del bad_design["schema_version"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=bad_design, schema=DESIGN_SCHEMA)

    bad_obs = dict(_observation())
    bad_obs["shots"] = "not-a-list"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=bad_obs, schema=OBSERVATION_SCHEMA)

    bad_diff = {"schema_version": "spatial-diff/v1", "items": [{"metric": 1}]}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=bad_diff, schema=DIFF_SCHEMA)


def test_snapshot_audit_event_shape():
    event = snapshot_audit_event("spatial_design_snapshot", _design())
    assert event["kind"] == "spatial_design_snapshot"
    assert event["schema_version"] == "spatial-design-snapshot/v1"
    assert event["fingerprint_sha256"]
    assert isinstance(event.get("created_at"), str)
    event_obs = snapshot_audit_event("spatial_observation_snapshot",
                                     _observation())
    assert event_obs["kind"] == "spatial_observation_snapshot"


def test_rebuild_design_is_deterministic_no_llm():
    """同一 brief+plan 两次重建逐位一致（重建是纯函数，零 LLM 调用）。"""
    first = json.dumps(_design(), sort_keys=True, ensure_ascii=False)
    second = json.dumps(_design(), sort_keys=True, ensure_ascii=False)
    assert first == second


def test_rebuild_observation_from_frame_dicts_is_deterministic():
    """观测快照可从 SpatialFrame dict（audit_log 的持久形状）零 LLM 复原。"""
    from block_director.cinema.spatial_digest import SpatialFrame as SF

    built = _observation()
    # audit 里持久化的是 SpatialFrame dict；从 dict 复原应逐位一致
    camera = SpatialCamera(
        position=(0.0, 0.0, 0.0), forward=(0.0, 0.0, -1.0),
        up=(0.0, 1.0, 0.0), lens_mm=18.0, sensor_width=36.0,
        sensor_height=24.0, sensor_fit="AUTO",
        render_width=1280, render_height=720)
    element = SpatialElement(
        id="米迦尔", kind="character",
        aabb_min=(-0.5, -0.5, 0.0), aabb_max=(0.5, 0.5, 1.7),
        center=(0.0, 0.0, 0.85), facing=(0.0, 1.0, 0.0),
        rotation=None, motion=None,
        gaze={"target_id": None, "direction": [0.0, 1.0, 0.0]})
    frames = [SF(frame=1, shot_id="shot_001", camera=camera,
                 elements=[element])]
    rebuilt = build_observation_snapshot(
        [SF.from_dict(frame.to_dict()) for frame in frames])
    assert json.dumps(rebuilt, sort_keys=True, ensure_ascii=False) == \
        json.dumps(built, sort_keys=True, ensure_ascii=False)
