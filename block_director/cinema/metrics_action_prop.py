"""空间尺 07 · 动作与因果层·姿态道具 2 指标（Ticket 07）。

指标（阈值以 metric_registry.py 注册表为真源，本模块照抄口径）：
* pose_phase_separation —— 姿态阶段切分可辨度：四阶段（准备—发力—接触—反应）
  中「可区分的阶段数 / 4」，目标 ≥ 0.75（至少 3 阶段可辨）；
  阶段混杂不可分 → fatal；一阶段缺失 → error；本指标无硬门联动。
* prop_interaction_visibility —— 手—道具—目标三段接触可见比例，目标 ≥ 0.80；
  关键交互不可辨（如道具出画）→ fatal；部分缺失 → error；本指标无硬门联动。

本模块为纯层实现（不 import bpy），输入是 evaluation_protocol 的采样对象；
样例均为 demo 输入（evidence_grade="demo"），输出统一 Measurement /
Finding / Prescription / EvaluationOutput。粒度固定 Shot（只接受 ShotSample）。

与 06 的边界：06 管接触因果（action_readability / cause_effect_visibility /
contact_point_visibility / reaction_legibility），本票只管姿态阶段切分与
道具交互可见性；同名概念不重复实现，本模块不 import 06。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

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
    Severity,
    ShotSample,
    TargetInterval,
    middle_frame,
)
from .prescription import validate_prescription


# --------------------------------------------------------------------------- #
# 阈值与常量（注册表口径）
# --------------------------------------------------------------------------- #
#: pose_phase_separation 目标下限：可区分阶段数 / 4 ≥ 0.75（至少 3 阶段）。
POSE_TARGET = 0.75

#: prop_interaction_visibility 目标下限：三段接触可见比例 ≥ 0.80。
PROP_TARGET = 0.80

#: 阈值边界两可带的半宽（判定 ambiguous 用）。
TARGET_EPS = 0.002

#: 姿态签名各维度的可辨容差：投影盒高差 / 朝向差 / 接触主体有无。
HEIGHT_EPS = 0.05
FACING_EPS = 0.5

#: 处方方向与预期影响（只给方向，不含工具名/参数；措辞过 detect_pollution）。
_REPAIR: Dict[str, Tuple[str, Tuple[str, ...], Tuple[str, ...]]] = {
    "pose_phase_separation": (
        "拆阶段补采样并拉开相邻阶段姿态差异：为发力与接触阶段补足动作关键帧采样，"
        "让准备与发力姿态区分可见",
        ("姿态阶段可辨度", "动作节奏"),
        ("move_character", "character_action", "move_camera", "reframe"),
    ),
    "prop_interaction_visibility": (
        "移近道具入画并错开接触遮挡：让手、道具与受作用目标的三段接触保持可见，"
        "必要时换侧机位",
        ("道具交互可见度", "接触链完整性"),
        ("move_character", "character_action",
         "interact_with", "move_camera", "reframe"),
    ),
}


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _boundary(value: float, boundary: float, eps: float) -> bool:
    """value 是否落在 boundary ± eps 的两可带上。"""
    return abs(float(value) - boundary) <= eps


def _ambiguous_warning(component: str, message_body: str,
                       evidence: Tuple[int, ...]) -> Finding:
    """结构性两可的三态输出：WARNING + 「需人工复核」结尾，不产处方。"""
    return Finding(
        component=component,
        severity=Severity.WARNING,
        message=f"{message_body}需人工复核",
        evidence_frames=evidence,
    )


# --------------------------------------------------------------------------- #
# pose_phase_separation：四阶段姿态切分可辨度
# --------------------------------------------------------------------------- #
def _largest_character(frame: FrameSample) -> Optional[ProjectedSubject]:
    """帧内最大的角色投影作手/主体（id 升序决胜，确定性）。"""
    chars = [s for s in frame.subjects if s.kind == "character"]
    if not chars:
        return None
    return max(chars, key=lambda s: (s.box.height, s.subject_id))


def _phase_signature(frame: FrameSample) -> Tuple[float, float, bool]:
    """阶段姿态签名：`(投影盒高, 朝向, 是否有接触主体)`。

    demo 口径：姿态可区分度用主体投影盒大小 / 位移方向（facing）/
    接触主体有无量化，相邻阶段差异超过容差才算可辨。
    """
    char = _largest_character(frame)
    has_contact = (
        any(s.kind == "prop" for s in frame.subjects)
        or sum(1 for s in frame.subjects if s.kind == "character") >= 2
    )
    if char is None:
        return (0.0, 0.0, has_contact)
    return (float(char.box.height), float(char.box.facing), has_contact)


def _signatures_differ(a: Tuple[float, float, bool],
                       b: Tuple[float, float, bool]) -> bool:
    """两个阶段签名是否差异足够大（任一维度超过容差即可辨）。"""
    if abs(a[0] - b[0]) > HEIGHT_EPS:
        return True
    if abs(a[1] - b[1]) > FACING_EPS:
        return True
    return a[2] != b[2]


def _nearest_frame(frames_by_number: Dict[int, FrameSample],
                   canonical: int) -> Optional[FrameSample]:
    """取采样帧中离规范帧号最近的一帧（同距离取更小帧号，确定性）。"""
    candidates = [f for _, f in sorted(frames_by_number.items())]
    if not candidates:
        return None
    return min(candidates, key=lambda f: (abs(f.frame - canonical), f.frame))


def _phase_representatives(
        shot: ShotSample) -> Tuple[Tuple[str, Optional[FrameSample]], ...]:
    """四阶段代表帧：准备/发力/接触/反应。

    有动作关键帧时用「动作起点 / 起点与接触帧中点 / 接触帧 / 反应结束帧」；
    无动作关键帧时退化为「首帧 / 中帧 / 缺失 / 末帧」（接触阶段缺失）。
    """
    frames_by_number: Dict[int, FrameSample] = {
        f.frame: f for f in shot.frames}
    first, last = shot.frame_range
    if shot.actions:
        action = shot.actions[0]
        start = action.start.frame
        first_contact = action.contacts[0].frame
        reaction_end = action.reaction_end.frame
        effort_canonical = (start + first_contact) // 2
        return (
            ("prepare", frames_by_number.get(start)),
            ("effort", _nearest_frame(frames_by_number, effort_canonical)),
            ("contact", frames_by_number.get(first_contact)),
            ("reaction", frames_by_number.get(reaction_end)),
        )
    middle = middle_frame(first, last)
    return (
        ("prepare", frames_by_number.get(first)),
        ("effort", frames_by_number.get(middle)),
        ("contact", None),
        ("reaction", frames_by_number.get(last)),
    )


def _pose_phase_separation(
        shot: ShotSample) -> Tuple[Tuple[Measurement, ...],
                                   Tuple[Finding, ...]]:
    representatives = _phase_representatives(shot)
    signatures: List[Optional[Tuple[float, float, bool]]] = [
        _phase_signature(frame) if frame is not None else None
        for _, frame in representatives
    ]
    missing = [name for name, frame in representatives if frame is None]

    # 可区分的阶段段数：相邻签名差异足够大的边界 + 1（离散计数，确定性）。
    distinct = 0
    previous: Optional[Tuple[float, float, bool]] = None
    for signature in signatures:
        if signature is None:
            continue
        if previous is None or _signatures_differ(previous, signature):
            distinct += 1
        previous = signature

    raw = round(distinct / 4.0, 6)
    evidence = tuple(sorted({f.frame for f in shot.frames}))
    ambiguous = (
        distinct == 3 and not missing and bool(shot.actions)
        and _boundary(raw, POSE_TARGET, TARGET_EPS)
    )
    measurement = Measurement(
        metric="pose_phase_separation",
        raw_value=raw,
        score=raw,
        target=TargetInterval(min_value=POSE_TARGET),
        evidence_frames=evidence,
        confidence=0.5 if ambiguous else 1.0,
        evidence_grade="demo",
    )

    findings: List[Finding] = []
    if distinct < 3:
        findings.append(Finding(
            component="pose_phase_separation",
            severity=Severity.FATAL,
            message=(f"动作过密或采样不足，四阶段姿态混杂不可分"
                     f"（可辨 {distinct}/4 阶段）"),
            evidence_frames=evidence,
        ))
    elif missing:
        findings.append(Finding(
            component="pose_phase_separation",
            severity=Severity.ERROR,
            message=(f"姿态阶段缺失：{ '、'.join(missing) } 无对应采样帧"
                     f"（可辨 {distinct}/4 阶段）"),
            evidence_frames=evidence,
        ))
    elif ambiguous:
        findings.append(_ambiguous_warning(
            "pose_phase_separation",
            "发力与准备两阶段姿态相似，但镜头节奏暗示发力仍可推断，"
            "判定是否算可辨两可，",
            evidence,
        ))
    return (measurement,), tuple(findings)


# --------------------------------------------------------------------------- #
# prop_interaction_visibility：手—道具—目标三段接触可见比例
# --------------------------------------------------------------------------- #
def _main_prop(frame: FrameSample) -> Optional[ProjectedSubject]:
    """帧内面积最大的道具投影（id 升序决胜，确定性）。"""
    props = [s for s in frame.subjects if s.kind == "prop"]
    if not props:
        return None
    return max(props, key=lambda s: (s.box.height * s.box.width,
                                     s.subject_id))


def _target_subject(frame: FrameSample,
                    hand: Optional[ProjectedSubject],
                    prop: Optional[ProjectedSubject]) -> Optional[ProjectedSubject]:
    """受作用目标：除手与主道具外的道具优先，否则其余角色，否则 None。"""
    hand_id = hand.subject_id if hand is not None else None
    prop_id = prop.subject_id if prop is not None else None
    candidates = [s for s in frame.subjects
                  if s.subject_id not in (hand_id, prop_id)]
    props = [s for s in candidates if s.kind == "prop"]
    if props:
        return max(props, key=lambda s: (s.box.height * s.box.width,
                                         s.subject_id))
    chars = [s for s in candidates if s.kind == "character"]
    if chars:
        return max(chars, key=lambda s: (s.box.height, s.subject_id))
    return None


def _prop_interaction_visibility(
        shot: ShotSample) -> Tuple[Tuple[Measurement, ...],
                                   Tuple[Finding, ...]]:
    contact_frames = shot.contact_frames
    if not contact_frames:
        contact_frames = shot.frames
    # 无任何道具主体的镜头不属于道具交互样例（本层互斥语义同 geometry
    # depth_separation：不足 2 主体时不产该指标测量），直接跳过。
    if not any(s.kind == "prop"
               for frame in contact_frames for s in frame.subjects):
        return (), ()
    ratios: List[float] = []
    evidence: List[int] = []
    zero_frames: List[int] = []
    for frame in contact_frames:
        hand = _largest_character(frame)
        prop = _main_prop(frame)
        target = _target_subject(frame, hand, prop)
        segments = (
            hand.visible_ratio if hand is not None else 0.0,
            prop.visible_ratio if prop is not None else 0.0,
            target.visible_ratio if target is not None else 0.0,
        )
        ratios.extend(segments)
        evidence.append(frame.frame)
        if any(ratio <= 0.0 for ratio in segments):
            zero_frames.append(frame.frame)
    if not ratios:
        return (), ()
    raw = round(sum(ratios) / len(ratios), 6)
    evidence_tuple = tuple(sorted(set(evidence)))
    ambiguous = (
        raw >= PROP_TARGET and _boundary(raw, PROP_TARGET, TARGET_EPS)
    )
    measurement = Measurement(
        metric="prop_interaction_visibility",
        raw_value=raw,
        score=raw,
        target=TargetInterval(min_value=PROP_TARGET),
        evidence_frames=evidence_tuple,
        confidence=0.5 if ambiguous else 1.0,
        evidence_grade="demo",
    )

    findings: List[Finding] = []
    if raw < PROP_TARGET:
        if zero_frames:
            findings.append(Finding(
                component="prop_interaction_visibility",
                severity=Severity.FATAL,
                message=(f"关键交互不可辨：道具出画或接触被完全遮挡"
                         f"（帧 {sorted(set(zero_frames))}），"
                         "手—道具—目标三段接触断裂"),
                evidence_frames=evidence_tuple,
            ))
        else:
            findings.append(Finding(
                component="prop_interaction_visibility",
                severity=Severity.ERROR,
                message=(f"手—道具—目标三段接触部分缺失"
                         f"（可见比例 {raw:.3f} < {PROP_TARGET}）"),
                evidence_frames=evidence_tuple,
            ))
    elif ambiguous:
        findings.append(_ambiguous_warning(
            "prop_interaction_visibility",
            "手与道具接触点被身体遮挡但道具轨迹清晰，判定是否可辨两可，",
            evidence_tuple,
        ))
    return (measurement,), tuple(findings)


# --------------------------------------------------------------------------- #
# 公共接缝：evaluate / build_prescriptions / render_report / SAMPLES
# --------------------------------------------------------------------------- #
def evaluate(sample: object,
             intent: Optional[IntentContract] = None) -> EvaluationOutput:
    """对本层全部适用指标产出测量与失败项（§8/§11.1 公共接缝）。

    本层粒度固定 Shot，只接受 ShotSample。
    """
    if not isinstance(sample, ShotSample):
        raise TypeError(
            f"动作层只接受 ShotSample（粒度 Shot）：{type(sample)!r}")
    measurements: List[Measurement] = []
    findings: List[Finding] = []
    for worker in (_pose_phase_separation, _prop_interaction_visibility):
        ms, fs = worker(sample)
        measurements.extend(ms)
        findings.extend(fs)
    return EvaluationOutput(
        shot_id=sample.shot_id,
        measurements=tuple(measurements),
        findings=tuple(findings),
        intent=intent,
    )


def build_prescriptions(output: EvaluationOutput) -> Tuple[Prescription, ...]:
    """只对失败分量（fatal/error）产处方；通过的分量不产。"""
    out: List[Prescription] = []
    for finding in output.findings:
        if finding.severity not in (Severity.FATAL, Severity.ERROR):
            continue
        if finding.component not in _REPAIR:
            continue
        direction, effects, allowed = _REPAIR[finding.component]
        measurement = next(
            (m for m in output.measurements
             if m.metric == finding.component), None)
        if measurement is None:
            continue
        prescription = Prescription(
            component=finding.component,
            severity=finding.severity,
            current=round(float(measurement.raw_value), 6),
            target=measurement.target,
            allowed_tools=tuple(allowed),
            direction=direction,
            expected_effect=effects,
        )
        ok, _ = validate_prescription(prescription)
        if ok:
            out.append(prescription)
    return tuple(out)


def render_report(output: EvaluationOutput,
                  prescriptions: Sequence[Prescription]) -> str:
    """渲染 LLM 可读读数；只含数值、方向与预期影响，过 detect_pollution。"""
    lines = [f"镜头 {output.shot_id} 动作层读数："]
    if output.intent is not None:
        lines.append(f"- 声明意图：{output.intent.intent or '（未声明）'}")
    for m in output.measurements:
        lines.append(
            f"- {m.metric}：原始 {m.raw_value:.3f}，归一化 {m.score:.3f}，"
            f"目标 {m.target.to_dict()}，证据帧 {m.evidence_frames}，"
            f"置信度 {m.confidence:.2f}")
    for f in output.findings:
        gate = f"（硬门 {f.gate}）" if f.gate else ""
        lines.append(f"- 失败项：{f.component}[{f.severity.value}]{gate} "
                     f"{f.message}，证据帧 {f.evidence_frames}")
    for p in prescriptions:
        lines.append(f"- 修复方向（{p.component}）：{p.direction}")
        if p.expected_effect:
            lines.append(f"  预期影响：{'、'.join(p.expected_effect)}")
    if not prescriptions:
        lines.append("- 无失败分量（全部达标）")
    return "\n".join(lines)


@dataclass(frozen=True)
class SampleCase:
    """一个三态样例：镜头采样 + 意图 + 预期结论。"""

    name: str
    sample: object
    intent: Optional[IntentContract]
    expected: str


# --------------------------------------------------------------------------- #
# 三态样例 fixture（Ticket 07：打斗四阶段 + 手—道具—目标交互）
# --------------------------------------------------------------------------- #
def _box(name: str, left: float, right: float, top: float, bottom: float,
         facing: float = 0.0) -> SubjectBox:
    return SubjectBox(name=name, left=left, right=right, top=top,
                      bottom=bottom, facing=facing)


def _proj(subject_id: str, b: SubjectBox, kind: str = "character",
          visible: float = 1.0) -> ProjectedSubject:
    return ProjectedSubject(subject_id=subject_id, kind=kind, box=b,
                            visible_ratio=visible)


def _frame(number: int, shot_id: str,
           subjects: Tuple[ProjectedSubject, ...]) -> FrameSample:
    return FrameSample(frame=number, shot_id=shot_id, subjects=subjects)


def _shot(shot_id: str, frame_range: Tuple[int, int],
          by_frame: Dict[int, Tuple[ProjectedSubject, ...]],
          with_action: bool = True) -> ShotSample:
    first, last = frame_range
    numbers = sorted(by_frame)
    if len(numbers) < 3:
        raise ValueError("fixture 内容关键帧至少 3 帧")
    frames = tuple(_frame(n, shot_id, by_frame[n]) for n in numbers)
    content = ContentFrame.from_shot(shot_id=shot_id,
                                     frame_range=frame_range,
                                     frames=frames)
    by_number = {f.frame: f for f in frames}
    actions: Tuple[ActionFrame, ...] = ()
    if with_action:
        start, contact, reaction_end = numbers[0], numbers[len(numbers) // 2], numbers[-1]
        actions = (ActionFrame(
            shot_id=shot_id,
            start=by_number[start],
            contacts=(by_number[contact],),
            reaction_end=by_number[reaction_end],
        ),)
    return ShotSample(shot_id=shot_id, frame_range=frame_range,
                      content=content, actions=actions)


# -- pose_phase_separation 三态 ------------------------------------------------- #
_HERO_SMALL = _proj("hero", _box("hero", 0.30, 0.50, 0.85, 0.65, 1.0))
_HERO_LARGE = _proj("hero", _box("hero", 0.28, 0.62, 0.95, 0.55, 1.0))
_HERO_MID = _proj("hero", _box("hero", 0.30, 0.60, 0.90, 0.55, 1.0))
_HERO_SAME = _proj("hero", _box("hero", 0.30, 0.60, 0.90, 0.50, 1.0))
_HERO_RECOIL = _proj("hero", _box("hero", 0.35, 0.55, 0.80, 0.60, -1.0))
_VICTIM = _proj("victim", _box("victim", 0.48, 0.60, 0.55, 0.25))

_POSE_GOOD = _shot("shot_001", (1, 13), {
    1: (_HERO_SMALL,),
    4: (_HERO_LARGE,),
    7: (_HERO_MID, _VICTIM),
    10: (_HERO_MID, _VICTIM),
    13: (_HERO_RECOIL,),
})

_POSE_BAD = _shot("shot_001", (1, 13), {
    1: (_HERO_SAME,),
    4: (_HERO_SAME,),
    7: (_HERO_SAME,),
    10: (_HERO_SAME,),
    13: (_HERO_SAME,),
})

_POSE_AMBIGUOUS = _shot("shot_001", (1, 13), {
    1: (_HERO_SMALL,),
    4: (_proj("hero", _box("hero", 0.30, 0.50, 0.85, 0.65, 1.0)),),
    7: (_HERO_MID, _VICTIM),
    10: (_HERO_MID, _VICTIM),
    13: (_HERO_RECOIL,),
})

# -- prop_interaction_visibility 三态 ------------------------------------------ #
_HAND = _proj("hero", _box("hero", 0.35, 0.55, 0.85, 0.55, 1.0))
_PROP_ON = _proj("prop", _box("prop", 0.45, 0.55, 0.55, 0.45), kind="prop")
_PROP_OFF = _proj("prop", _box("prop", -0.55, -0.45, 0.55, 0.45),
                  kind="prop", visible=0.0)
_TARGET_ON = _proj("target", _box("target", 0.55, 0.65, 0.55, 0.45),
                   kind="prop")
_TARGET_PARTIAL = _proj("target", _box("target", 0.55, 0.65, 0.55, 0.45),
                        kind="prop", visible=0.4)

_PROP_GOOD = _shot("shot_002", (1, 9), {
    1: (_HAND, _PROP_ON, _TARGET_ON),
    5: (_HAND, _PROP_ON, _TARGET_ON),
    9: (_HAND, _PROP_ON, _TARGET_ON),
})

_PROP_BAD = _shot("shot_002", (1, 9), {
    1: (_HAND, _PROP_ON, _TARGET_ON),
    5: (_HAND, _PROP_OFF, _TARGET_ON),
    9: (_HAND, _PROP_ON, _TARGET_ON),
})

_PROP_AMBIGUOUS = _shot("shot_002", (1, 9), {
    # 四阶段各自可辨（准备—发力—接触—反应），让 pose 指标走 good；
    # 仅接触帧的手—道具—目标三段停在 0.80 边界，构成 prop 的 ambiguous。
    1: (_HERO_SMALL,),
    3: (_HERO_LARGE,),
    5: (_HAND, _PROP_ON, _TARGET_PARTIAL),
    9: (_HERO_RECOIL,),
})


SAMPLES: Dict[str, Dict[str, SampleCase]] = {
    "pose_phase_separation": {
        "good": SampleCase(
            "pose_phase_separation", _POSE_GOOD,
            IntentContract(shot_id="shot_001", intent="打斗分阶段：准备—发力—接触—反应"),
            "good"),
        "bad": SampleCase(
            "pose_phase_separation", _POSE_BAD, None, "bad"),
        "ambiguous": SampleCase(
            "pose_phase_separation", _POSE_AMBIGUOUS, None, "ambiguous"),
    },
    "prop_interaction_visibility": {
        "good": SampleCase(
            "prop_interaction_visibility", _PROP_GOOD,
            IntentContract(shot_id="shot_002", intent="抓取/推物：手—道具—目标三段接触"),
            "good"),
        "bad": SampleCase(
            "prop_interaction_visibility", _PROP_BAD, None, "bad"),
        "ambiguous": SampleCase(
            "prop_interaction_visibility", _PROP_AMBIGUOUS, None, "ambiguous"),
    },
}


__all__ = [
    "SampleCase", "SAMPLES", "evaluate", "build_prescriptions",
    "render_report",
]
