"""空间尺最小可运行 demo 的测试（纯层，不 import bpy）。

演示"AI 怎么通过算法读懂空间"：
1. 用 `evaluate_composition` 得到六分量构图报告（纯几何）；
2. `build_prescriptions` 把失败分量变成**方向处方**（component / severity /
   current / target / allowed_tools / direction / expected_effect，
   不含 tool / tool_args——处方化裁决，防止尺子泄漏修复答案）；
3. `validate_prescription` 证明处方方向合法、allowed_tools 在工具闭集内；
4. demo 的 `render_ruler_report` 只渲染数值与方向，渲染结果必须通过
   `detect_pollution`（不泄漏工具名/参数/“建议执行”）。

本文件是 spec（.scratch/spatial-ruler/spec.md）阶段 A 的第一个落地切片：
全部纯层、确定性、零依赖、不碰 Blender、不花模型额度。
"""

from __future__ import annotations

from block_director.cinema.composition import (
    CompositionReport,
    SubjectBox,
    evaluate_composition,
)
from block_director.cinema.prescription import (
    build_prescriptions,
    detect_pollution,
    validate_prescription,
)
from tools.spatial_ruler_demo import render_ruler_report


def _prescriptions_are_directional(prescriptions) -> bool:
    """每个处方都必须通过方向校验，且渲染结果不得泄漏修复答案。"""
    for p in prescriptions:
        ok, why = validate_prescription(p)
        if not ok:
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
    """失败构图应产生"当前值 + 目标 + 修复方向"的可读读数。"""
    report = evaluate_composition([_good_box(top=0.60)])  # 头顶留白过多
    prescriptions = build_prescriptions(report)
    text = render_ruler_report(report, prescriptions)
    assert report.items["headroom"].score < 1.0
    assert any(p.component == "headroom" for p in prescriptions)
    assert "当前" in text and "目标" in text
    assert "修复方向" in text


def test_prescription_directions_are_valid_and_unpolluted():
    """处方只给方向：通过方向校验，渲染读数不泄漏工具名/参数/建议执行。"""
    report = evaluate_composition([_good_box(top=0.60)])
    prescriptions = build_prescriptions(report)
    assert prescriptions
    assert _prescriptions_are_directional(prescriptions)
    text = render_ruler_report(report, prescriptions)
    assert detect_pollution(text) is None


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
