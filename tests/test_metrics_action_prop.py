"""Ticket 07 · 动作与因果层·姿态道具 2 指标的验收测试（TDD 先行）。

判据来自注册表 `metric_registry.py`（名称/阈值/严重度照抄）与 07 SPEC：
* 每指标 SAMPLES 三态齐全（good / bad / ambiguous）；
* 本票**无任何硬门联动**：bad 样例的 finding.gate 必须为 None（显式断言）；
* pose_phase_separation：四阶段（准备—发力—接触—反应）可区分阶段数/4 ≥ 0.75，
  bad（阶段混杂不可分）→ FATAL，一阶段缺失 → ERROR；
* prop_interaction_visibility：手—道具—目标三段接触可见比例 ≥ 0.80，
  bad（关键交互不可辨，如道具出画）→ FATAL；
* good：测量达标、无失败项、confidence == 1.0、无处方；
* ambiguous：confidence < 1.0，无 fatal/error，至多 warning 以
  「需人工复核」结尾，不产处方；
* 处方过 validate_prescription、allowed_tools ⊆ ACTION_TOOLS、
  render_report 过 detect_pollution；全部评估确定性可复现。
"""
from __future__ import annotations

import pytest

from block_director.cinema.evaluation_protocol import Severity
from block_director.cinema.metric_registry import METRICS_BY_NAME
from block_director.cinema.metrics_action_prop import (
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
    "pose_phase_separation",
    "prop_interaction_visibility",
)

#: 注册表硬门联动（本票两条目均为空，bad 的 gate 必须显式为 None）
GATED = {name: tuple(METRICS_BY_NAME[name].links_to_gates)
         for name in METRICS}

#: bad 样例应判定的严重度（注册表 severity 口径：阶段混杂不可分 / 关键交互不可辨）
BAD_SEVERITY = {
    "pose_phase_separation": Severity.FATAL,
    "prop_interaction_visibility": Severity.FATAL,
}


@pytest.mark.parametrize("metric", METRICS)
def test_registry_entries_have_no_gate_links(metric: str) -> None:
    """注册表真源：两条目 links_to_gates 均为空（本票无硬门联动）。"""
    spec = METRICS_BY_NAME[metric]
    assert spec.links_to_gates == ()
    assert spec.granularity == "Shot"
    assert spec.layer == "action"


@pytest.mark.parametrize("metric", METRICS)
def test_samples_three_states_complete(metric: str) -> None:
    assert set(SAMPLES[metric]) == {"good", "bad", "ambiguous"}
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
    assert not [p for p in build_prescriptions(out) if p.component == metric]


@pytest.mark.parametrize("metric", METRICS)
def test_good_triggers_no_hard_gate(metric: str) -> None:
    case = SAMPLES[metric]["good"]
    out = evaluate(case.sample, case.intent)
    assert all(f.gate is None for f in out.findings)


@pytest.mark.parametrize("metric", METRICS)
def test_bad_finding_and_prescription(metric: str) -> None:
    case = SAMPLES[metric]["bad"]
    out = evaluate(case.sample, case.intent)
    findings = [f for f in out.findings if f.component == metric]
    assert findings, f"{metric} bad 样例应产生失败项"
    finding = findings[0]
    assert finding.severity == BAD_SEVERITY[metric]
    # 本票无硬门联动：即使 severity == FATAL，gate 也必须显式为 None。
    assert finding.gate is None
    assert GATED[metric] == ()
    prescriptions = [p for p in build_prescriptions(out)
                     if p.component == metric]
    assert prescriptions, f"{metric} bad 样例应产生处方"
    for p in prescriptions:
        ok, why = validate_prescription(p)
        assert ok, why
        assert set(p.allowed_tools) <= set(ACTION_TOOLS)
        assert p.expected_effect
        assert p.direction


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
        assert finding.gate is None
    assert not [p for p in build_prescriptions(out) if p.component == metric]


@pytest.mark.parametrize("metric", METRICS)
def test_bad_render_report_is_clean(metric: str) -> None:
    case = SAMPLES[metric]["bad"]
    out = evaluate(case.sample, case.intent)
    prescriptions = build_prescriptions(out)
    report = render_report(out, prescriptions)
    assert report
    assert detect_pollution(report) is None


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


def test_pose_phase_missing_phase_is_error() -> None:
    """注册表口径：一阶段缺失 -> ERROR（非混杂不可分的 FATAL）。"""
    from block_director.cinema.composition import SubjectBox
    from block_director.cinema.evaluation_protocol import (
        ContentFrame,
        FrameSample,
        ProjectedSubject,
        ShotSample,
    )

    def box(subject_id, left, right, top, bottom, facing):
        return SubjectBox(name=subject_id, left=left, right=right,
                          top=top, bottom=bottom, facing=facing)

    def projected(subject_id, b, kind="character", visible=1.0):
        return ProjectedSubject(subject_id=subject_id, kind=kind, box=b,
                                visible_ratio=visible)

    hero_small = projected("hero", box("hero", 0.30, 0.50, 0.85, 0.65, 1.0))
    hero_large = projected("hero", box("hero", 0.28, 0.62, 0.95, 0.55, 1.0))
    hero_recoil = projected("hero", box("hero", 0.35, 0.55, 0.80, 0.60, -1.0))
    frames = tuple(
        FrameSample(frame=n, shot_id="shot_001", subjects=subjects)
        for n, subjects in ((1, (hero_small,)),
                            (4, (hero_large,)),
                            (7, (hero_large,)),
                            (13, (hero_recoil,))))
    content = ContentFrame.from_shot(
        shot_id="shot_001", frame_range=(1, 13), frames=frames)
    # 无任何动作关键帧：接触阶段代表帧缺失（一阶段缺失）。
    shot = ShotSample(shot_id="shot_001", frame_range=(1, 13),
                      content=content)
    out = evaluate(shot)
    finding = next(f for f in out.findings
                   if f.component == "pose_phase_separation")
    assert finding.severity == Severity.ERROR
    assert finding.gate is None


def test_prop_interaction_good_covers_three_segments() -> None:
    """手—道具—目标三段关系在 good 样例中独立可断言。"""
    case = SAMPLES["prop_interaction_visibility"]["good"]
    out = evaluate(case.sample, case.intent)
    measurement = next(
        m for m in out.measurements
        if m.metric == "prop_interaction_visibility")
    assert measurement.raw_value >= 0.8
    assert not [f for f in out.findings
                if f.component == "prop_interaction_visibility"]
