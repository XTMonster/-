"""Ticket 08 · 连续性层 6 指标的验收测试（TDD 先行）。

判据来自注册表 `metric_registry.py`（阈值照抄）与公共接缝 SPEC：
* 每指标 SAMPLES 三态齐全（good / bad / ambiguous）；
* good：测量达标、无该指标失败项、不触发硬门、confidence == 1.0；
* bad：失败项严重度与硬门符合注册表（axis_continuity 联动 H3），处方过
  validate_prescription、allowed_tools ⊆ ACTION_TOOLS；
* ambiguous：confidence < 1.0，无 fatal/error，至多 warning 以「需人工复核」
  结尾，不产处方；
* 轴线/银幕左右序/朝向符号判据必须与 `axis.py` 真源同源（禁止另抄一份）；
* 全部评估确定性可复现。
"""
from __future__ import annotations

import pytest

import block_director.cinema.metrics_continuity as metrics_continuity
from block_director.cinema import axis
from block_director.cinema.evaluation_protocol import (
    SequenceSample,
    Severity,
)
from block_director.cinema.metrics_continuity import (
    SAMPLES,
    build_prescriptions,
    evaluate,
    render_report,
)
from block_director.cinema.prescription import (
    detect_pollution,
    validate_prescription,
)
from block_director.contracts.tools import ACTION_TOOLS

METRICS = (
    "axis_continuity",
    "motion_vector_continuity",
    "scale_continuity",
    "eyeline_match",
    "screen_direction",
    "temporal_readability",
)

#: 注册表硬门映射（links_to_gates）
GATED = {"axis_continuity": "H3"}

#: bad 样例应判定的严重度（注册表 severity 口径）
BAD_SEVERITY = {
    "axis_continuity": Severity.FATAL,
    "motion_vector_continuity": Severity.FATAL,
    "scale_continuity": Severity.ERROR,
    "eyeline_match": Severity.FATAL,
    "screen_direction": Severity.FATAL,
    "temporal_readability": Severity.FATAL,
}


@pytest.mark.parametrize("metric", METRICS)
def test_samples_three_states_complete(metric: str) -> None:
    keys = set(SAMPLES[metric])
    assert {"good", "bad", "ambiguous"} <= keys
    # 连续性层只要求三态，不允许额外变体漂移。
    assert keys == {"good", "bad", "ambiguous"}
    for state in ("good", "bad", "ambiguous"):
        case = SAMPLES[metric][state]
        assert case.name == metric
        assert case.expected == state


def test_all_samples_are_sequences() -> None:
    """连续性层全部指标为 Sequence 粒度：样例必须是 SequenceSample。"""
    for metric in METRICS:
        for case in SAMPLES[metric].values():
            assert isinstance(case.sample, SequenceSample)


def test_axis_sources_are_reused() -> None:
    """轴线/银幕左右序/朝向符号判据必须与 axis.py 真源同源。"""
    assert metrics_continuity.screen_order_violation is axis.screen_order_violation
    assert metrics_continuity.update_order is axis.update_order
    assert metrics_continuity.shot_size_index is axis.shot_size_index
    assert metrics_continuity.flipped_screen_directions is (
        axis.flipped_screen_directions)


@pytest.mark.parametrize("metric", METRICS)
def test_good_measurement_in_target_without_finding(metric: str) -> None:
    case = SAMPLES[metric]["good"]
    out = evaluate(case.sample, case.intent)
    measurement = next(m for m in out.measurements if m.metric == metric)
    assert 0.0 <= measurement.score <= 1.0
    assert measurement.confidence == 1.0
    assert measurement.evidence_frames
    assert measurement.evidence_grade == "demo"
    assert measurement.target.contains(measurement.raw_value)
    assert not [f for f in out.findings if f.component == metric]


@pytest.mark.parametrize("metric", METRICS)
def test_bad_finding_and_prescription(metric: str) -> None:
    case = SAMPLES[metric]["bad"]
    out = evaluate(case.sample, case.intent)
    findings = [f for f in out.findings if f.component == metric]
    assert findings, f"{metric} bad 样例应产生失败项"
    finding = findings[0]
    assert finding.severity == BAD_SEVERITY[metric]
    if metric in GATED:
        assert finding.gate == GATED[metric]
    else:
        assert finding.gate is None
    prescriptions = [p for p in build_prescriptions(out)
                     if p.component == metric]
    assert prescriptions, f"{metric} bad 样例应产生处方"
    for p in prescriptions:
        ok, why = validate_prescription(p)
        assert ok, why
        assert set(p.allowed_tools) <= set(ACTION_TOOLS)
        assert p.expected_effect
        assert p.direction


def test_bad_axis_triggers_h3_fatal() -> None:
    case = SAMPLES["axis_continuity"]["bad"]
    out = evaluate(case.sample, case.intent)
    finding = next(f for f in out.findings
                   if f.component == "axis_continuity")
    assert finding.gate == "H3"
    assert finding.severity == Severity.FATAL


@pytest.mark.parametrize("metric", METRICS)
def test_good_triggers_no_hard_gate(metric: str) -> None:
    case = SAMPLES[metric]["good"]
    out = evaluate(case.sample, case.intent)
    assert all(f.gate is None for f in out.findings)


@pytest.mark.parametrize("metric", METRICS)
def test_ambiguous_soft_and_prescription_free(metric: str) -> None:
    case = SAMPLES[metric]["ambiguous"]
    out = evaluate(case.sample, case.intent)
    measurement = next(m for m in out.measurements if m.metric == metric)
    assert measurement.confidence < 1.0
    for finding in out.findings:
        if finding.component != metric:
            continue
        assert finding.severity not in (Severity.FATAL, Severity.ERROR)
        if finding.severity == Severity.WARNING:
            assert finding.message.endswith("需人工复核")
    assert not [p for p in build_prescriptions(out) if p.component == metric]


@pytest.mark.parametrize("metric", METRICS)
def test_bad_render_report_is_clean(metric: str) -> None:
    case = SAMPLES[metric]["bad"]
    out = evaluate(case.sample, case.intent)
    prescriptions = build_prescriptions(out)
    report = render_report(out, prescriptions)
    assert report
    assert detect_pollution(report) is None


def test_bad_chase_covers_direction_and_vector() -> None:
    """追逐 bad：屏幕方向反向 + 运动向量无承接，双指标都判 FATAL。"""
    case = SAMPLES["motion_vector_continuity"]["bad"]
    out = evaluate(case.sample, case.intent)
    mv = next(f for f in out.findings
              if f.component == "motion_vector_continuity")
    sd = next(f for f in out.findings
              if f.component == "screen_direction")
    assert mv.severity == Severity.FATAL
    assert sd.severity == Severity.FATAL


def test_bad_eyeline_covers_mutual_break() -> None:
    """对切 bad：互看关系断裂（同一镜两人朝向同号）判 FATAL。"""
    case = SAMPLES["eyeline_match"]["bad"]
    out = evaluate(case.sample, case.intent)
    finding = next(f for f in out.findings
                   if f.component == "eyeline_match")
    assert finding.severity == Severity.FATAL


@pytest.mark.parametrize("metric", METRICS)
def test_evaluate_deterministic(metric: str) -> None:
    for state in ("good", "bad", "ambiguous"):
        case = SAMPLES[metric][state]
        first = evaluate(case.sample, case.intent).to_dict()
        second = evaluate(case.sample, case.intent).to_dict()
        assert first == second


@pytest.mark.parametrize("metric", METRICS)
def test_render_report_deterministic(metric: str) -> None:
    case = SAMPLES[metric]["bad"]
    out = evaluate(case.sample, case.intent)
    prescriptions = build_prescriptions(out)
    assert render_report(out, prescriptions) == render_report(
        out, prescriptions)
