"""动作与因果层·接触因果 4 指标的纯 Python demo 实现（Ticket 06）。

四个指标全部以「动作关键帧」序列为输入（起手 -> 接触 -> 反应结束）：
* action_readability        —— 起手、路径、接触、收势四段轮廓是否分别可辨；
* cause_effect_visibility   —— 发起、受力、结果三段是否连续可见（因果链）；
* contact_point_visibility  —— 接触点（道具/肢体）在接触帧是否可辨；
* reaction_legibility       —— 受击方反应结束帧的结果姿态是否完整可见。

三态口径：good（达标无失败项）、bad（fatal 硬门/无硬门 + 处方）、
ambiguous（临界两可：warning + 需人工复核，不产处方）。
打斗 fixture 固定角色：hero=攻击者、enemy=受击者、fist=接触道具。
纯 Python、无 bpy。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from .composition import SubjectBox
from .evaluation_protocol import (
    ActionFrame,
    ContentFrame,
    EvaluationOutput,
    Finding,
    FrameSample,
    IntentContract,
    Measurement,
    Prescription,
    ProjectedSubject,
    SequenceSample,
    Severity,
    ShotSample,
    TargetInterval,
)
from .prescription import validate_prescription
from ..contracts.tools import ACTION_TOOLS

#: 四个指标的达标下界（照抄注册表 metric_registry.py 口径）。
ACTION_TARGET = 0.80
CAUSE_TARGET = 0.85
CONTACT_TARGET = 0.70
REACTION_TARGET = 0.70

#: 临界两可带：raw 恰在目标值 ± BOUNDARY_EPS 内判 ambiguous。
BOUNDARY_EPS = 1e-4

#: 打斗 fixture 的角色/道具 id（issue 06 验收）。
ATTACKER = "hero"
VICTIM = "enemy"
CONTACT_PROP = "fist"

#: 每指标处方：方向（全中文，不含工具名/参数，防污染）、预期影响、工具白名单。
_REPAIR = {
    "action_readability": (
        "拆分动作关键帧并靠近主体：让起手、路径、接触、收势四段轮廓分别可辨",
        ("动作四段轮廓分别可辨",),
        ("move_camera", "move_character", "reframe"),
    ),
    "cause_effect_visibility": (
        "补结果镜头并保持发起与受力同框：让发起、受力、结果三段连续可见",
        ("发起、受力、结果三段连续可见",),
        ("move_camera", "move_character"),
    ),
    "contact_point_visibility": (
        "换侧机位并错开站位：让接触点与肢体轮廓分离可辨",
        ("接触点与肢体轮廓分离可辨",),
        ("move_camera", "move_character"),
    ),
    "reaction_legibility": (
        "延长反应停留并移开前景遮挡：让结果姿态完整可见",
        ("结果姿态完整可见",),
        ("move_camera", "move_character", "character_action"),
    ),
}

_ACTION_METRICS = (
    "action_readability",
    "contact_point_visibility",
    "reaction_legibility",
)
_CAUSE_METRIC = "cause_effect_visibility"


def _shots_of(sample):
    if isinstance(sample, ShotSample):
        return (sample,)
    if isinstance(sample, SequenceSample):
        return sample.shots
    raise TypeError(type(sample))


def _clamp(v):
    return max(0.0, min(1.0, float(v)))


def _mean(values):
    return sum(float(v) for v in values) / len(values) if values else 0.0


def _vis(frame, sid):
    s = frame.subject(sid)
    return s.visible_ratio if s is not None else 0.0


def _tri(component, raw, target, evidence, gate, boundary_desc, fatal_msg,
         fatal=False):
    """三态分级：fatal(任一元素不可辨/整条读数归零) / error / boundary-ambiguous。

    ``raw`` 已 round(…, 6)。ambiguous 时 confidence=0.5 且 WARNING 以
    「需人工复核」结尾、不产处方（severity 不在 fatal/error 集合）。
    """
    if fatal or raw <= 0.0:
        fs = (Finding(component, Severity.FATAL, fatal_msg,
                      tuple(evidence), gate),)
        conf = 1.0
    elif raw < target:
        fs = (Finding(component, Severity.ERROR,
                      f"{component}读数低于目标 {target:.2f}",
                      tuple(evidence), gate),)
        conf = 1.0
    elif abs(raw - target) <= BOUNDARY_EPS:
        fs = (Finding(component, Severity.WARNING,
                      f"{boundary_desc}需人工复核", tuple(evidence)),)
        conf = 0.5
    else:
        fs = ()
        conf = 1.0
    m = Measurement(component, float(raw), _clamp(raw),
                    TargetInterval(min_value=target), tuple(evidence), conf,
                    "demo")
    return m, fs


def _no_action(metric, target, shot):
    ev = tuple(f.frame for f in shot.content.frames)
    m = Measurement(metric, 0.0, 0.0, TargetInterval(min_value=target),
                    ev, 0.0, "demo")
    f = (Finding(metric, Severity.WARNING, "缺少动作关键帧，需人工复核", ev),)
    return m, f


def _readability(shot):
    if not shot.actions:
        return _no_action("action_readability", ACTION_TARGET, shot)
    ev = []
    elems = []
    for action in shot.actions:
        ev.extend((action.start.frame,
                   *(c.frame for c in action.contacts),
                   action.reaction_end.frame))
        elems.extend((
            _vis(action.start, ATTACKER),
            _mean([_vis(c, ATTACKER) for c in action.contacts]),
            _mean([_vis(c, CONTACT_PROP) for c in action.contacts]),
            _vis(action.reaction_end, VICTIM),
        ))
    fatal = any(v <= 0.0 for v in elems)
    raw = round(_mean(elems), 6)
    return _tri("action_readability", raw, ACTION_TARGET, sorted(set(ev)),
                "H2", "动作路径处于临界可辨，",
                "动作路径或主体关键帧完全不可辨", fatal)


def _cause(shot):
    if not shot.actions:
        return _no_action("cause_effect_visibility", CAUSE_TARGET, shot)
    ev = []
    elems = []
    for action in shot.actions:
        ev.extend((action.start.frame,
                   *(c.frame for c in action.contacts),
                   action.reaction_end.frame))
        elems.extend((
            _vis(action.start, ATTACKER),
            _mean([min(_vis(c, CONTACT_PROP), _vis(c, VICTIM))
                   for c in action.contacts]),
            _vis(action.reaction_end, VICTIM),
        ))
    fatal = any(v <= 0.0 for v in elems)
    raw = round(_mean(elems), 6)
    return _tri("cause_effect_visibility", raw, CAUSE_TARGET,
                sorted(set(ev)), "H2", "因果链处于临界连续，",
                "因果链断裂，发起、受力或结果完全不可见", fatal)


def _contact(shot):
    if not shot.actions:
        return _no_action("contact_point_visibility", CONTACT_TARGET, shot)
    ev = []
    vals = []
    for action in shot.actions:
        for c in action.contacts:
            ev.append(c.frame)
            vals.append(_vis(c, CONTACT_PROP))
    fatal = any(v <= 0.0 for v in vals)
    raw = round(_mean(vals), 6)
    return _tri("contact_point_visibility", raw, CONTACT_TARGET,
                sorted(set(ev)), "H2", "接触点处于临界可辨，",
                "接触点完全不可辨", fatal)


def _reaction(shot):
    if not shot.actions:
        return _no_action("reaction_legibility", REACTION_TARGET, shot)
    ev = []
    vals = []
    for action in shot.actions:
        ev.append(action.reaction_end.frame)
        vals.append(_vis(action.reaction_end, VICTIM))
    fatal = any(v <= 0.0 for v in vals)
    raw = round(_mean(vals), 6)
    return _tri("reaction_legibility", raw, REACTION_TARGET,
                sorted(set(ev)), None, "结果姿态处于临界可见，",
                "结果姿态完全不可见", fatal)


def evaluate(sample, intent=None):
    ms = []
    fs = []
    for shot in _shots_of(sample):
        for worker in (_readability, _cause, _contact, _reaction):
            m, f = worker(shot)
            ms.append(m)
            fs.extend(f)
    return EvaluationOutput(_shots_of(sample)[0].shot_id, tuple(ms),
                            tuple(fs), intent)


def build_prescriptions(output):
    out = []
    for f in output.findings:
        if (f.severity not in (Severity.FATAL, Severity.ERROR)
                or f.component not in _REPAIR):
            continue
        m = next((x for x in output.measurements
                  if x.metric == f.component), None)
        if not m:
            continue
        d, e, a = _REPAIR[f.component]
        p = Prescription(f.component, f.severity, m.raw_value, m.target,
                         a, d, e)
        if validate_prescription(p)[0]:
            out.append(p)
    return tuple(out)


def _has_actions(output):
    return not any(f.message.startswith("缺少动作关键帧")
                   for f in output.findings)


def render_report(output, prescriptions):
    """LLM 可读读数：动作层（readability/contact/reaction）与因果层两节。

    绝不渲染 allowed_tools / 工具名 / 参数（detect_pollution 红线）；
    无动作关键帧时退化为单节常规读数。
    """
    lines = []
    if not _has_actions(output):
        lines.append(f"镜头 {output.shot_id} 动作与因果层读数：")
        if output.intent:
            lines.append(f"- 声明意图：{output.intent.intent or '（未声明）'}")
        for m in output.measurements:
            lines.append(_line_measurement(m))
        for f in output.findings:
            lines.append(_line_finding(f))
        return "\n".join(lines)

    lines.append(f"镜头 {output.shot_id} 动作层读数：")
    if output.intent:
        lines.append(f"- 声明意图：{output.intent.intent or '（未声明）'}")
    action_ms = [m for m in output.measurements if m.metric in _ACTION_METRICS]
    for m in action_ms:
        lines.append(_line_measurement(m))
    for f in output.findings:
        if f.component in _ACTION_METRICS:
            lines.append(_line_finding(f))
    for p in prescriptions:
        if p.component in _ACTION_METRICS:
            lines.append(_line_prescription(p))

    lines.append("因果层读数：")
    for m in output.measurements:
        if m.metric == _CAUSE_METRIC:
            lines.append(_line_measurement(m))
    for f in output.findings:
        if f.component == _CAUSE_METRIC:
            lines.append(_line_finding(f))
    for p in prescriptions:
        if p.component == _CAUSE_METRIC:
            lines.append(_line_prescription(p))
    return "\n".join(lines)


def _line_measurement(m):
    return (f"- {m.metric}：原始 {m.raw_value:.3f}，归一化 {m.score:.3f}，"
            f"目标 {m.target.to_dict()}，证据帧 {m.evidence_frames}，"
            f"置信度 {m.confidence:.2f}")


def _line_finding(f):
    return (f"- 失败项：{f.component}[{f.severity.value}] {f.message}，"
            f"证据帧 {f.evidence_frames}")


def _line_prescription(p):
    lines = [f"- 修复方向（{p.component}）：{p.direction}"]
    if p.expected_effect:
        lines.append(f"  预期影响：{'、'.join(p.expected_effect)}")
    return "\n".join(lines)


@dataclass(frozen=True)
class SampleCase:
    name: str
    sample: object
    intent: Optional[IntentContract]
    expected: str


def _p(sid, l, r, t, b, kind="character", vis=1.0, facing=1):
    return ProjectedSubject(sid, SubjectBox(sid, l, r, t, b, facing=facing),
                            kind=kind, visible_ratio=vis)


def _frame(n, vis, shot_id):
    subs = (
        _p("hero", 0.20, 0.50, 0.90, 0.30, vis=vis.get("hero", 1.0)),
        _p("enemy", 0.50, 0.70, 0.55, 0.05, facing=-1,
           vis=vis.get("enemy", 1.0)),
        _p("fist", 0.40, 0.46, 0.75, 0.35, kind="prop",
           vis=vis.get("fist", 1.0)),
    )
    return FrameSample(n, subs, shot_id=shot_id)


def _fight_shot(frame_vis, shot_id="shot_001"):
    """打斗 fixture：帧范围 (1,5)，内容帧 (1,3,5)，动作帧 (2,4,5)。"""
    f1 = _frame(1, frame_vis.get(1, {}), shot_id)
    f2 = _frame(2, frame_vis.get(2, {}), shot_id)
    f3 = _frame(3, frame_vis.get(3, {}), shot_id)
    f4 = _frame(4, frame_vis.get(4, {}), shot_id)
    f5 = _frame(5, frame_vis.get(5, {}), shot_id)
    content = ContentFrame.from_shot(shot_id, (1, 5), (f1, f3, f5))
    action = ActionFrame(shot_id, f2, (f4,), f5)
    return ShotSample(shot_id, (1, 5), content, (action,))


_INTENT = IntentContract("shot_001", intent="突袭打斗", subject="hero",
                         props=("fist",))

_GOOD = _fight_shot({})
_R_BAD = _fight_shot({4: {"hero": 0.0}})
_C_BAD = _fight_shot({5: {"enemy": 0.0}})
_RX_BAD = _fight_shot({5: {"enemy": 0.0}})
_CT_BAD = _fight_shot({4: {"fist": 0.0}})
_R_AMB = _fight_shot({5: {"enemy": 0.2}})
_C_AMB = _fight_shot({5: {"enemy": 0.55}})
_CT_AMB = _fight_shot({4: {"fist": 0.7}})
_RX_AMB = _fight_shot({5: {"enemy": 0.7}})

SAMPLES = {
    "action_readability": {
        "good": SampleCase("action_readability", _GOOD, _INTENT, "good"),
        "bad": SampleCase("action_readability", _R_BAD, _INTENT, "bad"),
        "ambiguous": SampleCase("action_readability", _R_AMB, _INTENT,
                                "ambiguous"),
    },
    "cause_effect_visibility": {
        "good": SampleCase("cause_effect_visibility", _GOOD, _INTENT, "good"),
        "bad": SampleCase("cause_effect_visibility", _C_BAD, _INTENT, "bad"),
        "ambiguous": SampleCase("cause_effect_visibility", _C_AMB, _INTENT,
                                "ambiguous"),
    },
    "contact_point_visibility": {
        "good": SampleCase("contact_point_visibility", _GOOD, _INTENT,
                           "good"),
        "bad": SampleCase("contact_point_visibility", _CT_BAD, _INTENT,
                          "bad"),
        "ambiguous": SampleCase("contact_point_visibility", _CT_AMB, _INTENT,
                                "ambiguous"),
    },
    "reaction_legibility": {
        "good": SampleCase("reaction_legibility", _GOOD, _INTENT, "good"),
        "bad": SampleCase("reaction_legibility", _RX_BAD, _INTENT, "bad"),
        "ambiguous": SampleCase("reaction_legibility", _RX_AMB, _INTENT,
                                "ambiguous"),
    },
}

__all__ = [
    "SampleCase",
    "SAMPLES",
    "evaluate",
    "build_prescriptions",
    "render_report",
]
