"""空间尺最小可运行 demo 的测试（纯层，不 import bpy）。

演示"AI 怎么通过算法读懂空间"：
1. 用 `evaluate_composition` 得到六分量构图报告（纯几何）；
2. `build_prescriptions` 把失败分量变成**方向处方**（component / severity /
   current / target / allowed_tools / direction / expected_effect，
   不含 tool / tool_args——处方化裁决，防止尺子泄漏修复答案）；
3. `validate_prescription` 证明处方方向合法、allowed_tools 在工具闭集内；
4. 正式的 `render_ruler_report`（Ticket 03c，落在 prescription.py 真源）
   只渲染数值与方向，渲染结果必须通过 `detect_pollution`
   （不泄漏工具名/参数/"建议执行"）；demo 与打斗 demo 都调用它，不再各自占位。

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
    render_ruler_report,
    validate_prescription,
)


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


def test_ruler_report_never_leaks_tools_params_or_suggestion():
    """渲染读数不得含工具名/参数名/参数值/"建议执行"（03c 污染负例）。"""
    report = evaluate_composition([_good_box(top=0.60)])
    prescriptions = build_prescriptions(report)
    assert prescriptions
    text = render_ruler_report(report, prescriptions)
    assert detect_pollution(text) is None
    lowered = text.lower()
    for token in ("move_camera", "move_character", "reframe",
                  "setup_camera", "character_action", "dolly_in",
                  "delta_x", "delta_y", "camera_z", "建议执行",
                  "建议调用", "lens=", "amount="):
        assert token not in lowered, token


def test_ruler_report_is_imported_from_prescription_true_source():
    """正式渲染归属 prescription.py（03c），demo 不应再自带占位实现。"""
    from block_director.cinema import prescription as pkg_prescription
    from tools import spatial_ruler_demo as demo
    assert pkg_prescription.render_ruler_report is render_ruler_report
    # demo 模块内部不应再有名为 render_ruler_report 的本地函数定义。
    assert "render_ruler_report" not in vars(demo) or (
        vars(demo).get("render_ruler_report") is pkg_prescription.render_ruler_report)


def test_fight_tight_frame_render_is_unpolluted():
    """打斗 demo 最紧帧（重叠+头部被挡）渲染同样不得泄漏修复答案。"""
    report = evaluate_composition(
        [SubjectBox(name="hero", left=0.29, right=0.65, top=1.05,
                    bottom=0.05, facing=1.0),
         SubjectBox(name="villain", left=0.35, right=0.71, top=1.05,
                    bottom=0.05, facing=-1.0)],
        occluded={"hero": True, "villain": False})
    prescriptions = build_prescriptions(report)
    assert prescriptions, "打斗最紧帧应产生处方"
    text = render_ruler_report(report, prescriptions)
    assert detect_pollution(text) is None
    lowered = text.lower()
    for token in ("move_camera", "move_character", "reframe",
                  "建议执行", "建议调用", "delta_x"):
        assert token not in lowered, token
