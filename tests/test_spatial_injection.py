"""Ticket 05：设计摘要 / diff 块渲染与修复提示注入 TDD 测试。

钉死：计划提示可注入设计快照摘要（确定性渲染 + 长度上限整行追加）；修复
提示可追加「设计 vs 实测」diff 块；``build_repair_payload`` 不传 diff_block
时与现状逐字节一致（零形状差），传了才追加，且不污染既有 prompt 结构。
"""

from __future__ import annotations

from block_director.cinema.spatial_design import (
    build_design_snapshot,
    render_design_summary,
)
from block_director.cinema.spatial_diff import (
    build_diff_report,
    render_diff_block,
)


def _design():
    return {
        "schema_version": "spatial-design-snapshot/v1",
        "scene_id": "market",
        "characters": [
            {"name": "米迦尔", "position": {"x": 0.0, "y": 0.0, "z": 0.0},
             "facing": [0.0, 1.0, 0.0], "provenance": "plan_intent",
             "motion": None,
             "gaze": {"target_id": "伊恩", "direction": [1.0, 0.0, 0.0]}},
        ],
        "props": [],
        "anchors": [
            {"label": "生蚝摊", "position": [-2.0, 0.0, 0.0],
             "provenance": "algorithmic_measurement", "resolved": True},
        ],
        "camera_intents": [
            {"shot_id": "shot_001", "position": [5.0, -3.0, 1.6],
             "target": [0.0, 0.0, 1.3855], "lens": 35.0,
             "provenance": "algorithmic_measurement", "resolved": True},
        ],
        "notes": [],
    }


def _observed():
    return {
        "schema_version": "spatial-observation/v1",
        "shots": [
            {"shot_id": "shot_001", "samples": [
                {"frame": 1,
                 "camera": {"position": [5.3, -3.2, 1.6],
                            "provenance": "blender_geometry"},
                 "elements": [
                     {"id": "米迦尔", "kind": "character",
                      "center": [0.0, 0.0, 0.0],
                      "facing": [0.0, 1.0, 0.0], "rotation": None,
                      "motion": None,
                      "gaze": {"target_id": None,
                               "direction": [1.0, 0.0, 0.0]},
                      "provenance": "blender_geometry"},
                 ]},
            ]},
        ],
    }


def test_render_design_summary_contains_facts():
    text = render_design_summary(_design(), max_chars=2000)
    assert "米迦尔" in text
    assert "0.0" in text            # 坐标
    assert "生蚝摊" in text
    assert "shot_001" in text


def test_render_design_summary_respects_max_chars():
    text = render_design_summary(_design(), max_chars=40)
    assert len(text) <= 40


def test_render_diff_block_contains_expected_actual_threshold():
    report = build_diff_report(_design(), _observed())
    text = render_diff_block(report, max_chars=2000)
    assert "设计 vs 实测" in text
    assert "camera_position" in text
    assert "actual" in text and "threshold" in text


def test_render_diff_block_respects_max_chars():
    report = build_diff_report(_design(), _observed())
    text = render_diff_block(report, max_chars=50)
    assert len(text) <= 50


def test_repair_payload_unchanged_without_diff_block():
    """不传 diff_block 的修复提示与现状一致：本票只做加法。"""
    from block_director.layer5_orchestrator.repair import build_repair_payload

    audit, registry = _minimal_audit_and_registry()
    base = build_repair_payload(audit, registry, request_id="test-fixed")
    with_diff = build_repair_payload(audit, registry, diff_block="",
                                     request_id="test-fixed")
    assert base == with_diff


def test_repair_payload_appends_diff_block_when_given():
    from block_director.layer5_orchestrator.repair import build_repair_payload

    audit, registry = _minimal_audit_and_registry()
    payload = build_repair_payload(audit, registry, diff_block="【设计 vs 实测】ok")
    system = payload.messages[0].content
    assert "【设计 vs 实测】ok" in system


def _minimal_audit_and_registry():
    """够 `build_repair_payload` 用的最小替身（参照 test_dialogue_budget_prompt）。"""
    from block_director.contracts.audit import AuditError, AuditResult
    from block_director.contracts.enums import Severity

    class _Registry:
        def schemas_except(self, name):
            return []

        def schemas_only(self, *names):
            return []

    audit = AuditResult(errors=[
        AuditError(rule="R011", code="E_SDL_001", severity=Severity.ERROR,
                   target="shot_001", message="对白装不下")])
    return audit, _Registry()
