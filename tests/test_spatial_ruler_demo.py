"""空间尺最小可运行 demo 的测试（纯层，不 import bpy）。

演示"AI 怎么通过算法读懂空间"：
1. 用 `evaluate_composition` 得到六分量构图报告（纯几何）；
2. `build_prescriptions` 把失败分量变成**可执行处方**（tool + tool_args）；
3. `validate_args` 证明处方参数真的能被现有工具接受；
4. `render_ruler_report` 把它渲染成 LLM 可读的"尺子读数"。

本文件是 spec（.scratch/spatial-ruler/spec.md）阶段 A 的第一个落地切片：
全部纯层、确定性、零依赖、不碰 Blender、不花模型额度。
"""

from __future__ import annotations

from typing import Any, Dict

from block_director.cinema.composition import (
    CompositionReport,
    SubjectBox,
    evaluate_composition,
)
from block_director.cinema.prescription import (
    Prescription,
    build_prescriptions,
    render_ruler_report,
)
from block_director.layer5_orchestrator.tool_schema import validate_args


# --------------------------------------------------------------------------- #
# 工具 schema 的轻量替身（demo 不 import bpy；正式实现走 tool_registry）
# --------------------------------------------------------------------------- #
ACTION_TOOL_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "move_camera": {
        "type": "object", "additionalProperties": False,
        "required": ["movement_type", "start_frame", "end_frame"],
        "properties": {
            "camera_id": {"type": "string"},
            "movement_type": {"type": "string", "enum": ["dolly_in", "dolly_out",
                                                         "truck_left", "truck_right",
                                                         "pan"]},
            "amount": {"type": "number", "minimum": 0, "maximum": 180},
            "start_frame": {"type": "integer", "minimum": 1},
            "end_frame": {"type": "integer", "minimum": 1},
        },
    },
    "move_character": {
        "type": "object", "additionalProperties": False,
        "required": ["character_id", "target_position", "start_frame", "end_frame"],
        "properties": {
            "character_id": {"type": "string"},
            "target_position": {"type": "array", "minItems": 3, "maxItems": 3,
                                "items": {"type": "number"}},
            "speed": {"type": "string", "enum": ["walk", "run"]},
            "start_frame": {"type": "integer", "minimum": 1},
            "end_frame": {"type": "integer", "minimum": 1},
        },
    },
    "reframe": {
        "type": "object", "additionalProperties": False,
        "properties": {
            "shot_id": {"type": "string"},
            "shot_type": {"type": "string", "enum": ["MS"]},
            "lens": {"type": "number", "minimum": 8, "maximum": 300},
        },
    },
}


def _prescriptions_pass_schema(prescriptions: List[Prescription]) -> bool:
    """每个处方的 tool_args 都必须通过该工具的 schema（spec 契约硬约束）。"""
    for p in prescriptions:
        schema = ACTION_TOOL_SCHEMAS.get(p.tool)
        if schema is None:
            return False
        if validate_args(schema, p.tool_args):
            return False
    return True


# --------------------------------------------------------------------------- #
# 测试
# --------------------------------------------------------------------------- #
def _good_box(**overrides) -> SubjectBox:
    values = dict(name="小明", left=0.24, right=0.42, top=1.0 - 0.07,
                  bottom=0.35, facing=1.0)
    values.update(overrides)
    return SubjectBox(**values)


def test_ruler_reports_failed_component():
    """失败构图应产生"当前值 + 建议工具"的可读读数。"""
    report = evaluate_composition([_good_box(top=0.60)])  # 头顶留白过多
    prescriptions = build_prescriptions(report)
    text = render_ruler_report(report, prescriptions)
    assert report.items["headroom"].score < 1.0
    assert any(p.component == "headroom" for p in prescriptions)
    assert "建议执行" in text
    assert "当前" in text and "目标" in text


def test_prescription_tool_args_are_executable():
    """处方参数必须能通过对应工具的 schema 校验（spec 契约硬约束）。"""
    report = evaluate_composition([_good_box(top=0.60)])
    prescriptions = build_prescriptions(report)
    assert prescriptions
    assert _prescriptions_pass_schema(prescriptions)


def test_passing_components_produce_no_prescription():
    """通过的分量不生成处方（零形状差，golden 不漂移）。"""
    report = evaluate_composition([_good_box()])
    assert report.passed
    assert build_prescriptions(report) == []


def test_ruler_demo_is_deterministic():
    """同一输入两次渲染逐字节相同（确定性，RK-17 精神）。"""
    report = evaluate_composition([_good_box(top=0.60)])
    prescriptions = build_prescriptions(report)
    first = render_ruler_report(report, prescriptions)
    second = render_ruler_report(evaluate_composition([_good_box(top=0.60)]),
                                 build_prescriptions(report))
    assert first == second
