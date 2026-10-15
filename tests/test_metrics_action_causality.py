"""Ticket 06 · 动作与因果层·接触因果 4 指标的验收测试（TDD 先行）。

判据来自注册表 `metric_registry.py`（阈值照抄）与公共接缝 SPEC：
* 每指标 SAMPLES 三态齐全（good / bad / ambiguous）；
* good：测量达标、无该指标失败项、不触发硬门、confidence == 1.0；
* bad：失败项严重度与硬门符合注册表，处方过 validate_prescription、
  allowed_tools ⊆ ACTION_TOOLS，render_report 过 detect_pollution；
* ambiguous：confidence < 1.0，无 fatal/error，至多 warning 以
  「需人工复核」结尾，不产处方；
* 打斗 fixture 同时覆盖攻击者/受击者/接触点/反应姿态，报告含
  「动作层读数」与「因果层读数」两个独立小节（issue 06 验收）；
* 全部评估确定性可复现。
"""
from __future__ import annotations

import pytest

from block_director.cinema.composition import SubjectBox
from block_director.cinema.evaluation_protocol import (
    ActionFrame,
    ContentFrame,
    FrameSample,
    ProjectedSubject,
    Severity,
    ShotSample,
)
from block_director.cinema.metrics_action_causality import (
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
    "action_readability",
    "cause_effect_visibility",
    "contact_point_visibility",
    "reaction_legibility",
)

#: 注册表硬门映射（links_to_gates）：前三项联动 H2，reaction 无硬门。
GATED = {
    "action_readability": "H2",
    "cause_effect_visibility": "H2",
    "contact_point_visibility": "H2",
}


def _subj(sid, l, r, t, b, kind="character", vis=1.0, facing=1):
    return ProjectedSubject(sid, SubjectBox(sid, l, r, t, b, facing=facing),
                            kind=kind, visible_ratio=vis)


def _mk_frame(n, vis, shot_id):
    subs = (
        _subj("hero", 0.20, 0.50, 0.90, 0.30, vis=vis.get("hero", 1.0)),
        _subj("enemy", 0.50, 0.70, 0.55, 0.05, facing=-1,
              vis=vis.get("enemy", 1.0)),
        _subj("fist", 0.40, 0.46, 0.75, 0.35, kind="prop",
              vis=vis.get("fist", 1.0)),
    )
    return FrameSample(n, subs, shot_id=shot_id)


def _mk_shot(vis4=None, vis5=None, shot_id="shot_001"):
    """5 帧打斗样例：帧范围 (1,5)、内容帧 (1,3,5)、动作帧 (2,4,5)。"""
    vis = {1: {}, 2: {}, 3: {}, 4: vis4 or {}, 5: vis5 or {}}
    frames = {n: _mk_frame(n, vis[n], shot_id) for n in (1, 2, 3, 4, 5)}
    content = ContentFrame.from_shot(shot_id, (1, 5),
                                     (frames[1], frames[3], frames[5]))
    action = ActionFrame(shot_id, frames[2], (frames[4],), frames[5])
    return ShotSample(shot_id, (1, 5), content, (action,))

#: bad 样例应判定的严重度（注册表 severity 口径：任一元素不可辨 / 因果链
#: 断裂 / 接触点不可辨 / 结果姿态完全不可见 → fatal）。
BAD_SEVERITY = {
    "action_readability": Severity.FATAL,
    "cause_effect_visibility": Severity.FATAL,
    "contact_point_visibility": Severity.FATAL,
    "reaction_legibility": Severity.FATAL,
}


@pytest.mark.parametrize("metric", METRICS)
def test_samples_three_states_complete(metric: str) -> None:
    keys = set(SAMPLES[metric])
    assert {"good", "bad", "ambiguous"} <= keys
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


@pytest.mark.parametrize("metric", ("action_readability",
                                    "cause_effect_visibility",
                                    "contact_point_visibility"))
def test_bad_triggers_h2_fatal(metric: str) -> None:
    case = SAMPLES[metric]["bad"]
    out = evaluate(case.sample, case.intent)
    finding = next(f for f in out.findings if f.component == metric)
    assert finding.gate == "H2"
    assert finding.severity == Severity.FATAL


def test_reaction_legibility_bad_has_no_hard_gate() -> None:
    case = SAMPLES["reaction_legibility"]["bad"]
    out = evaluate(case.sample, case.intent)
    finding = next(f for f in out.findings
                   if f.component == "reaction_legibility")
    assert finding.severity == Severity.FATAL
    assert finding.gate is None


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


@pytest.mark.parametrize("state", ("good", "bad", "ambiguous"))
@pytest.mark.parametrize("metric", METRICS)
def test_render_report_is_clean(metric: str, state: str) -> None:
    case = SAMPLES[metric][state]
    out = evaluate(case.sample, case.intent)
    prescriptions = build_prescriptions(out)
    report = render_report(out, prescriptions)
    assert report
    assert detect_pollution(report) is None


@pytest.mark.parametrize("metric,vis4,vis5,exp_gate", [
    ("action_readability", None, {"enemy": 0.1}, "H2"),
    ("cause_effect_visibility", None, {"enemy": 0.4}, "H2"),
    ("contact_point_visibility", {"fist": 0.5}, None, "H2"),
    ("reaction_legibility", None, {"enemy": 0.5}, None),
])
def test_partial_error_finding_gate(metric, vis4, vis5, exp_gate) -> None:
    """error（部分缺失，非 fatal）分支的 gate 也按注册表 links_to_gates 填。"""
    shot = _mk_shot(vis4=vis4, vis5=vis5)
    out = evaluate(shot, None)
    findings = [f for f in out.findings if f.component == metric]
    assert findings, f"{metric} error 样例应产生失败项"
    finding = findings[0]
    assert finding.severity == Severity.ERROR
    assert finding.gate == exp_gate


def test_fight_fixture_covers_roles_and_contact() -> None:
    """打斗 fixture 同时覆盖攻击者/受击者/接触点/反应姿态（issue 06）。"""
    case = SAMPLES["action_readability"]["good"]
    seen_attacker = seen_victim = seen_contact = False
    reaction_has_victim = False
    for action in case.sample.actions:
        for frame in (action.start, *action.contacts):
            ids = {s.subject_id for s in frame.subjects}
            kinds = {s.kind for s in frame.subjects}
            seen_attacker = seen_attacker or "hero" in ids
            seen_victim = seen_victim or "enemy" in ids
            seen_contact = seen_contact or ("fist" in ids and "prop" in kinds)
        reaction_has_victim = reaction_has_victim or "enemy" in {
            s.subject_id for s in action.reaction_end.subjects}
    assert seen_attacker and seen_victim and seen_contact
    assert reaction_has_victim


def test_fight_report_has_two_independent_sections() -> None:
    """打斗样例报告含「动作层读数」与「因果层读数」独立小节。"""
    case = SAMPLES["action_readability"]["bad"]
    out = evaluate(case.sample, case.intent)
    report = render_report(out, build_prescriptions(out))
    assert "动作层读数：" in report
    assert "因果层读数：" in report
    action_section = report.split("因果层读数：")[0]
    assert "action_readability" in action_section
    assert "contact_point_visibility" in action_section
    assert "reaction_legibility" in action_section
    cause_section = report.split("因果层读数：")[1]
    assert "cause_effect_visibility" in cause_section
    # 两个小节不合并成一个总分：因果层没有动作层的总分行。
    assert "总分" not in cause_section.split("失败项")[0]


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
