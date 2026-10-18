"""Ticket 08：空间理解快照的运行链接线 TDD 测试（纯层，无 bpy）。

并行线程已交付纯层转换器/装配器/对照器与 schema（Ticket 01-07）；本文件钉住
把它们**接进运行链**的四条缝（缺数据一律零形状差，不发明产品）：

* 计划提示（``planner.build_plan_payload(design=...)``）：有 design 才注入
  设计摘要，没有时提示与现状逐字节一致；
* 交付参数（``driver.spatial_delivery_args``）：从驱动状态折出 export 的三份
  快照参数，缺省全部 ``None``（交付层一个键都不多写）；
* 零 LLM 重放（``replay.extract_spatial_snapshots``）：从审计日志的事件
  payload 复原三份快照，缺事件如实标 ``None``、多事件取最后一条；
* 结构校验（``contracts.spatial_snapshot.validate_spatial_snapshot``）：
  生产侧零 jsonschema 依赖，schema_version 常量 + 必需键，坏版本/缺键报错。
"""

from __future__ import annotations

from block_director.cinema.spatial_design import build_design_snapshot
from block_director.contracts.spatial_snapshot import (
    DESIGN_SCHEMA,
    DIFF_SCHEMA,
    OBSERVATION_SCHEMA,
    validate_spatial_snapshot,
)


def _design():
    return build_design_snapshot(
        brief={
            "gaze": [{"from": "米迦尔", "to": "伊恩", "scope": "all"}],
            "environment": [
                {"label": "生蚝摊", "direction": "left", "distance": "near",
                 "size": "m", "mood": ""},
            ],
        },
        plan={
            "shot_id": "shot_001", "shot_type": "MS", "duration_frames": 120,
            "characters": ["米迦尔", "伊恩"],
            "camera": {"side": "front", "lens": 35.0},
            "gaze": [{"from": "米迦尔", "to": "伊恩"}],
        },
        cast_positions={"米迦尔": [0.0, 0.0, 0.0],
                        "伊恩": [2.0, 0.0, 0.0]},
        scene_id="market")


def _records():
    return [
        {"kind": "spatial_design_snapshot",
         "data": {"payload": _design()}},
        {"kind": "spatial_observation_snapshot",
         "data": {"payload": {"schema_version": "spatial-observation/v1",
                              "shots": []}}},
        {"kind": "spatial_diff_report",
         "data": {"payload": {"schema_version": "spatial-diff/v1",
                              "items": []}}},
    ]


def test_plan_payload_unchanged_without_design():
    """不传 design 的计划提示与现状逐字节一致（Ticket 05 零形状差）。"""
    from block_director.layer5_orchestrator.planner import build_plan_payload

    base = build_plan_payload("剧本", request_id="t1")
    no_design = build_plan_payload("剧本", request_id="t1", design=None)
    empty = build_plan_payload("剧本", request_id="t1", design={})
    assert base == no_design == empty


def test_plan_payload_injects_design_summary_when_given():
    """给了 design 就注入确定性渲染的设计摘要（上限 1200 字符）。"""
    from block_director.cinema.spatial_design import render_design_summary
    from block_director.layer5_orchestrator.planner import build_plan_payload

    design = _design()
    block = render_design_summary(design, max_chars=1200)
    assert "空间设计快照" in block
    assert len(block) <= 1200

    payload = build_plan_payload("剧本", request_id="t2", design=design)
    system = payload.messages[0].content
    assert "空间设计快照" in system
    assert "米迦尔" in system
    assert "shot_001" in system


def test_spatial_delivery_args_maps_driver_state():
    """驱动内存三份快照 → export_project 的参数；缺省全部 None。"""
    from block_director.layer5_orchestrator.driver import spatial_delivery_args

    class _Driver:
        _spatial_design = {"schema_version": "spatial-design-snapshot/v1"}
        _spatial_observation = {"schema_version": "spatial-observation/v1"}
        _spatial_diff = {"schema_version": "spatial-diff/v1"}

    args = spatial_delivery_args(_Driver())
    assert args["spatial_design"]["schema_version"] == \
        "spatial-design-snapshot/v1"
    assert args["spatial_observation"]["schema_version"] == \
        "spatial-observation/v1"
    assert args["spatial_diff"]["schema_version"] == "spatial-diff/v1"

    class _Empty:
        pass

    assert spatial_delivery_args(_Empty()) == {
        "spatial_design": None, "spatial_observation": None,
        "spatial_diff": None}


def test_extract_spatial_snapshots_from_records():
    """重放从审计事件 payload 零 LLM 复原三份快照。"""
    from block_director.layer9_persistence.replay import (
        extract_spatial_snapshots,
    )

    snapshots = extract_spatial_snapshots(_records())
    assert snapshots["design"]["schema_version"] == \
        "spatial-design-snapshot/v1"
    assert snapshots["observation"]["schema_version"] == \
        "spatial-observation/v1"
    assert snapshots["diff"]["schema_version"] == "spatial-diff/v1"


def test_extract_spatial_snapshots_absent_is_none():
    from block_director.layer9_persistence.replay import (
        extract_spatial_snapshots,
    )

    assert extract_spatial_snapshots([]) == {
        "design": None, "observation": None, "diff": None}


def test_extract_spatial_snapshots_takes_last_event():
    """同一 kind 多事件时取最后一条（与 plan_received 同口径）。"""
    from block_director.layer9_persistence.replay import (
        extract_spatial_snapshots,
    )

    records = _records()
    records.append({
        "kind": "spatial_design_snapshot",
        "data": {"payload": {
            "schema_version": "spatial-design-snapshot/v1",
            "characters": [{"name": "末版"}], "props": [], "anchors": [],
            "camera_intents": [], "notes": []}}})
    assert extract_spatial_snapshots(records)["design"]["characters"][0][
        "name"] == "末版"


def test_validate_spatial_snapshot_accepts_good_payload():
    assert validate_spatial_snapshot(_design(), DESIGN_SCHEMA) == []


def test_validate_spatial_snapshot_rejects_bad_version_and_missing_keys():
    design = dict(_design())
    design["schema_version"] = "spatial-design-snapshot/v9"
    problems = validate_spatial_snapshot(design, DESIGN_SCHEMA)
    assert problems and "schema_version" in problems[0]

    missing = dict(_design())
    del missing["characters"]
    assert validate_spatial_snapshot(missing, DESIGN_SCHEMA)

    bad_diff = {"schema_version": "spatial-diff/v1", "items": "not-a-list"}
    assert validate_spatial_snapshot(bad_diff, DIFF_SCHEMA)
    del bad_diff["schema_version"]
    assert validate_spatial_snapshot(bad_diff, DIFF_SCHEMA)


def test_validate_spatial_snapshot_rejects_non_mapping():
    assert validate_spatial_snapshot(None, DESIGN_SCHEMA)
    assert validate_spatial_snapshot("数据", OBSERVATION_SCHEMA)
