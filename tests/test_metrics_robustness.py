"""Ticket 10 · 鲁棒性与工程层 5 指标的验收测试（TDD 先行）。

判据来自注册表 `metric_registry.py`（阈值照抄）与公共接缝 SPEC：
* pose_robustness / camera_robustness —— 微扰 harness 重跑几何层核心指标，
  good 通过比例 ≥ 0.90 且无核心指标翻转；bad 大面积翻转（≥2 核心指标）
  ERROR；ambiguous 个别翻转或非关键翻转 WARNING；
* label_safe_area —— 关键视觉信息被覆盖比例 = 0，覆盖角色 FATAL、
  覆盖次要信息 WARNING；
* visibility_stability —— 出画/遮挡帧占比 ≤ 0.10，反复出画 FATAL、
  单次短时出画 ERROR、单次且触动作关键帧 WARNING；
* repair_locality —— 非目标镜头破坏数 = 0，破坏邻镜且未记录 FATAL
  （联动 H6），局部受影响 WARNING；
* 全部 evidence_grade = "production"；good 无硬门；ambiguous 不产处方；
* render_report 必须过 detect_pollution；扰动参数（种子/幅度）进入 bad
  判词与渲染报告。
"""
from __future__ import annotations

import pytest

from block_director.cinema.evaluation_protocol import (
    SequenceSample,
    Severity,
    ShotSample,
)
from block_director.cinema.metrics_geometry import evaluate as geometry_evaluate
from block_director.cinema.metrics_robustness import (
    PERTURB_SEED,
    SAMPLES,
    build_prescriptions,
    camera_perturb_harness,
    evaluate,
    pose_perturb_harness,
    render_report,
)
from block_director.cinema.prescription import (
    detect_pollution,
    validate_prescription,
)
from block_director.contracts.tools import ACTION_TOOLS

METRICS = (
    "pose_robustness",
    "camera_robustness",
    "label_safe_area",
    "visibility_stability",
    "repair_locality",
)

#: 注册表硬门映射（links_to_gates）
GATED = {"repair_locality": "H6"}

#: bad 样例应判定的严重度（注册表 severity 口径）
BAD_SEVERITY = {
    "pose_robustness": Severity.ERROR,
    "camera_robustness": Severity.ERROR,
    "label_safe_area": Severity.FATAL,
    "visibility_stability": Severity.FATAL,
    "repair_locality": Severity.FATAL,
}


def _harness_for(metric: str):
    if metric == "pose_robustness":
        return pose_perturb_harness
    if metric == "camera_robustness":
        return camera_perturb_harness
    raise AssertionError(f"只有扰动指标有 harness：{metric}")


@pytest.mark.parametrize("metric", METRICS)
def test_samples_three_states_complete(metric: str) -> None:
    keys = set(SAMPLES[metric])
    assert {"good", "bad", "ambiguous"} <= keys
    assert keys == {"good", "bad", "ambiguous"}
    for state in ("good", "bad", "ambiguous"):
        case = SAMPLES[metric][state]
        assert case.name == metric
        assert case.expected == state


def test_sample_granularity() -> None:
    """repair_locality 是 Sequence 粒度；其余四指标是 Shot 粒度。"""
    for metric in METRICS:
        for state in ("good", "bad", "ambiguous"):
            sample = SAMPLES[metric][state].sample
            if metric == "repair_locality":
                assert isinstance(sample, SequenceSample)
            else:
                assert isinstance(sample, ShotSample)


@pytest.mark.parametrize("metric", METRICS)
def test_good_measurement_in_target_without_finding(metric: str) -> None:
    case = SAMPLES[metric]["good"]
    out = evaluate(case.sample, case.intent)
    measurement = next(m for m in out.measurements if m.metric == metric)
    assert 0.0 <= measurement.score <= 1.0
    assert measurement.confidence == 1.0
    assert measurement.evidence_frames
    assert measurement.evidence_grade == "production"
    assert measurement.target.contains(measurement.raw_value)
    assert not [f for f in out.findings if f.component == metric]
    assert not [p for p in build_prescriptions(out) if p.component == metric]


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


def test_bad_repair_locality_triggers_h6_fatal() -> None:
    case = SAMPLES["repair_locality"]["bad"]
    out = evaluate(case.sample, case.intent)
    finding = next(f for f in out.findings
                   if f.component == "repair_locality")
    assert finding.gate == "H6"
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
    assert "种子" in report
    assert "幅度" in report


@pytest.mark.parametrize("metric", ("pose_robustness", "camera_robustness"))
def test_perturb_harness_covers_content_and_action_frames(metric: str) -> None:
    """微扰采样必须覆盖内容关键帧与动作关键帧（两类并集）。"""
    harness = _harness_for(metric)
    for state in ("good", "bad", "ambiguous"):
        case = SAMPLES[metric][state]
        shot = case.sample
        assert isinstance(shot, ShotSample)
        content_frames = {f.frame for f in shot.content.frames}
        action_frames: set[int] = set()
        for action in shot.actions:
            action_frames.add(action.start.frame)
            action_frames.update(f.frame for f in action.contacts)
            action_frames.add(action.reaction_end.frame)
        ratio, flipped, sampled = harness(shot, case.intent, PERTURB_SEED)
        assert 0.0 <= ratio <= 1.0
        assert content_frames <= set(sampled)
        assert action_frames <= set(sampled)


@pytest.mark.parametrize("metric", ("pose_robustness", "camera_robustness"))
def test_perturb_harness_deterministic(metric: str) -> None:
    """同一输入同一种子，harness 两次调用逐项一致。"""
    harness = _harness_for(metric)
    for state in ("good", "bad", "ambiguous"):
        case = SAMPLES[metric][state]
        shot = case.sample
        assert isinstance(shot, ShotSample)
        first = harness(shot, case.intent, PERTURB_SEED)
        second = harness(shot, case.intent, PERTURB_SEED)
        assert first == second


@pytest.mark.parametrize("metric", ("pose_robustness", "camera_robustness"))
def test_perturb_harness_leaves_core_output_unchanged(metric: str) -> None:
    """harness 只读采样并自建 Measurement，核心层输出逐字段不变。"""
    harness = _harness_for(metric)
    for state in ("good", "bad", "ambiguous"):
        case = SAMPLES[metric][state]
        shot = case.sample
        assert isinstance(shot, ShotSample)
        before = geometry_evaluate(shot, case.intent).to_dict()
        harness(shot, case.intent, PERTURB_SEED)
        after = geometry_evaluate(shot, case.intent).to_dict()
        assert before == after


@pytest.mark.parametrize("metric", ("pose_robustness", "camera_robustness"))
def test_bad_finding_records_perturbation(metric: str) -> None:
    """bad 判词必须记录扰动参数（种子/幅度），保证可复现。"""
    case = SAMPLES[metric]["bad"]
    out = evaluate(case.sample, case.intent)
    finding = next(f for f in out.findings if f.component == metric)
    assert "种子" in finding.message
    assert "幅度" in finding.message


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
