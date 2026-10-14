"""Ticket 05 · 视线与注意力层 5 指标的验收测试（TDD 先行）。

判据来自注册表 `metric_registry.py`（阈值照抄）与公共接缝 SPEC：
* 每指标 SAMPLES 三态齐全（good / bad / ambiguous）；
* good：测量达标、无该指标失败项、不触发硬门、confidence == 1.0；
* bad：失败项严重度与硬门符合注册表，处方过 validate_prescription、
  allowed_tools ⊆ ACTION_TOOLS，render_report 过 detect_pollution；
* ambiguous：confidence < 1.0，无 fatal/error，至多 warning 以
  「需人工复核」结尾，不产处方；
* 全部评估确定性可复现。
"""
from __future__ import annotations

import pytest

from block_director.cinema.evaluation_protocol import (
    SequenceSample,
    Severity,
)
from block_director.cinema.metrics_attention import (
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
    "gaze_target_visibility",
    "eyeline_consistency",
    "attention_priority",
    "focus_competition",
    "beat_coverage",
)

#: 注册表硬门映射（links_to_gates）
GATED = {"gaze_target_visibility": "H4"}

#: bad 样例应判定的严重度（注册表 severity 口径）
BAD_SEVERITY = {
    "gaze_target_visibility": Severity.FATAL,
    "eyeline_consistency": Severity.FATAL,
    "attention_priority": Severity.FATAL,
    "focus_competition": Severity.ERROR,
    "beat_coverage": Severity.FATAL,
}


@pytest.mark.parametrize("metric", METRICS)
def test_samples_three_states_complete(metric: str) -> None:
    keys = set(SAMPLES[metric])
    assert {"good", "bad", "ambiguous"} <= keys
    # 视线层只要求三态，不允许额外变体漂移。
    assert keys == {"good", "bad", "ambiguous"}
    for state in ("good", "bad", "ambiguous"):
        case = SAMPLES[metric][state]
        assert case.name == metric
        assert case.expected == state


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


def test_bad_gaze_target_triggers_h4_fatal() -> None:
    case = SAMPLES["gaze_target_visibility"]["bad"]
    out = evaluate(case.sample, case.intent)
    finding = next(f for f in out.findings
                   if f.component == "gaze_target_visibility")
    assert finding.gate == "H4"
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


def test_eyeline_sample_is_sequence() -> None:
    """对切/序列粒度必须用 SequenceSample（公共接缝 §8）。"""
    assert isinstance(SAMPLES["eyeline_consistency"]["good"].sample,
                      SequenceSample)


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
