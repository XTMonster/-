"""连续性层 6 指标的纯 Python demo 实现（Ticket 08）。

六个指标全部以「镜头序列」为输入（相邻镜头按剪辑顺序排列）：
* axis_continuity            —— 越轴（银幕左右序翻转且无豁免）联动 H3；
* motion_vector_continuity   —— 相邻镜主导角色运动向量方向承接；
* scale_continuity           —— 相邻镜景别跳级是否有叙事意图；
* eyeline_match              —— 对切互看方向与视线高度匹配；
* screen_direction           —— 银幕方向一致镜头对占比；
* temporal_readability       —— 动作—结果剪辑顺序可解释。

三态口径：good（达标无失败项）、bad（按注册表严重度 + 处方）、
ambiguous（临界两可：warning + 需人工复核，不产处方）。

**轴线判据与 ``axis.py`` 真源同源**：银幕左右序状态机、朝向符号、景别档位
一律 import 自 ``axis.py``，禁止另抄一份。
纯 Python、无 bpy。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .axis import (
    facing_sign_of,
    flipped_screen_directions,
    screen_order_violation,
    shot_size_index,
    update_order,
)
from .axis import ScreenOrderState, ScreenSample
from .composition import SubjectBox
from .evaluation_protocol import (
    ActionFrame,
    ContentFrame,
    EvaluationOutput,
    Finding,
    FrameSample,
    IntentContract,
    Measurement,
    middle_frame,
    Prescription,
    ProjectedSubject,
    SequenceSample,
    Severity,
    ShotSample,
    TargetInterval,
)
from .prescription import validate_prescription
from ..contracts.tools import ACTION_TOOLS

#: 六项指标（注册表顺序）
METRICS = (
    "axis_continuity",
    "motion_vector_continuity",
    "scale_continuity",
    "eyeline_match",
    "screen_direction",
    "temporal_readability",
)

#: 达标/边界常量
BOUNDARY_EPS = 1e-4
MOTION_TARGET = 0.90
SCALE_TARGET = 0.90
EYELINE_TARGET = 0.90
SCREEN_TARGET = 0.95
TEMPORAL_TARGET = 0.90

#: 头部单位（用于视线高度差的归一化）
HEAD_UNIT = 0.10

#: 画面高度占比 -> 景别（与 axis.SHOT_SIZE_ORDER 同源，bpy 侧按真源口径投影）
_SIZE_BY_HEIGHT = (
    (0.85, "ECU"),
    (0.60, "CU"),
    (0.42, "MCU"),
    (0.30, "MS"),
    (0.20, "MLS"),
    (0.12, "LS"),
)

#: 转场意图词：镜头声明里出现即视为「已交代转场」
TRANSITION_WORDS = ("转场", "反向", "回头", "反打")

#: 银幕方向「已声明换侧」的词
SCREEN_DECLARED_WORDS = ("回头", "反打")

#: 时间跳变声明词（temporal_readability 豁免）
TIME_JUMP_WORDS = ("时间跳变",)

#: 每指标处方：方向（全中文，不含工具名/参数）、预期影响、工具白名单
_REPAIR = {
    "axis_continuity": (
        "回到已确立的轴侧，或把这次左右互换声明为越轴意图并在中间"
        "插入中性机位交代",
        ("银幕左右序恢复连续",),
        ("move_camera", "move_character"),
    ),
    "motion_vector_continuity": (
        "保持相邻镜头运动方向承接，或声明转场意图后再反向",
        ("运动方向连续或意图明确",),
        ("move_camera", "move_character"),
    ),
    "scale_continuity": (
        "对齐相邻镜头景别至同档，或为跳级声明叙事意图",
        ("景别衔接自然或意图明确",),
        ("reframe", "move_camera"),
    ),
    "eyeline_match": (
        "统一视线锚点与机位高度，让互看关系成立且视线高度匹配",
        ("互看方向与高度匹配",),
        ("move_camera", "move_character", "reframe"),
    ),
    "screen_direction": (
        "保持动作接续画面方向一致，或先交代换侧意图再反向",
        ("银幕方向连续或意图明确",),
        ("move_camera", "move_character"),
    ),
    "temporal_readability": (
        "把结果剪辑点到动作接触之后，或补过程帧并声明时间跳变",
        ("动作—结果顺序可解释",),
        ("move_character", "character_action"),
    ),
}

#: 节拍因果序（temporal_readability 判据：动作先于结果）
CAUSAL_ORDER = {"动作": 0, "结果": 1}


# --------------------------------------------------------------------------- #
# 公共 helper
# --------------------------------------------------------------------------- #
def _shots_of(sample: object) -> Tuple[ShotSample, ...]:
    """把 SequenceSample / ShotSample 归一为镜头元组（本层全部为序列粒度）。"""
    if isinstance(sample, ShotSample):
        return (sample,)
    if isinstance(sample, SequenceSample):
        return sample.shots
    raise TypeError(
        f"连续性层只接受 SequenceSample/ShotSample：{type(sample)!r}")


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _cx(box: SubjectBox) -> float:
    return (box.left + box.right) / 2.0


def _cy(box: SubjectBox) -> float:
    return (box.top + box.bottom) / 2.0


def _content_first(shot: ShotSample) -> FrameSample:
    return shot.content.frames[0]


def _content_last(shot: ShotSample) -> FrameSample:
    return shot.content.frames[-1]


def _content_mid(shot: ShotSample) -> FrameSample:
    """规范中帧（内容关键帧可能多于 3 帧，不能直接用索引 1）。"""
    number = middle_frame(*shot.frame_range)
    for frame in shot.content.frames:
        if frame.frame == number:
            return frame
    raise ValueError(f"镜头 {shot.shot_id} 内容关键帧缺少规范中帧 {number}")


def _dominant_subject(frame: FrameSample) -> Optional[ProjectedSubject]:
    """帧内主导角色：包围盒高度最大，同高取 subject_id 最小；无角色取任一主体。"""
    subjects = [s for s in frame.subjects if s.kind == "character"]
    if not subjects:
        subjects = list(frame.subjects)
    if not subjects:
        return None
    max_height = max(s.box.height for s in subjects)
    tallest = [s for s in subjects if s.box.height == max_height]
    return min(tallest, key=lambda s: str(s.subject_id))


def _shot_size_of(height: float) -> str:
    """画面高度占比 -> 景别档名（_SIZE_BY_HEIGHT 第一档 >= 命中）。"""
    value = float(height)
    for threshold, shot_type in _SIZE_BY_HEIGHT:
        if value >= threshold:
            return shot_type
    return "ELS"


def _has_any(intent: Optional[IntentContract], words: Sequence[str]) -> bool:
    """意图文本/运镜声明里是否命中任一豁免词。"""
    if intent is None:
        return False
    text = f"{intent.intent or ''} {' '.join(intent.camera_movements or ())}"
    return any(word in text for word in words)


def _has_intent_text(intent: Optional[IntentContract]) -> bool:
    return intent is not None and bool((intent.intent or "").strip())


def _vector_angle_deg(a: Sequence[float], b: Sequence[float]) -> float:
    """2D 向量夹角（度）；任一零向量视为 0°（无承接信息不判反转）。"""
    ax, ay = float(a[0]), float(a[1])
    bx, by = float(b[0]), float(b[1])
    na, nb = math.hypot(ax, ay), math.hypot(bx, by)
    if na < 1e-9 or nb < 1e-9:
        return 0.0
    cos_value = max(-1.0, min(1.0, (ax * bx + ay * by) / (na * nb)))
    return math.degrees(math.acos(cos_value))


def _evidence_frames(shots: Sequence[ShotSample],
                     numbers: Sequence[int]) -> Tuple[int, ...]:
    return tuple(sorted(set(int(n) for n in numbers)))


# --------------------------------------------------------------------------- #
# 指标 worker：返回 (measurements, findings)
# --------------------------------------------------------------------------- #
def _axis_continuity(shots: Sequence[ShotSample],
                     intent: Optional[IntentContract]
                     ) -> Tuple[Tuple[Measurement, ...], Tuple[Finding, ...]]:
    """相邻镜头银幕左右序翻转（越轴）联动 H3。"""
    states: List[ScreenOrderState] = []
    evidence: List[int] = []
    for shot in shots:
        mid = _content_mid(shot)
        samples = tuple(
            ScreenSample(
                character_id=item.subject_id,
                screen_x=_cx(item.box),
                facing_x=item.box.facing,
            )
            for item in mid.subjects
        )
        states.append(update_order(ScreenOrderState(), samples))
        evidence.append(mid.frame)
    pairs = len(states) - 1
    violations = 0
    for prev, cur in zip(states, states[1:]):
        if screen_order_violation(prev, cur, bridge_ok=False) is not None:
            violations += 1
    raw = violations / pairs if pairs else 0.0
    declared = intent is not None and bool(intent.axis_side)
    ambiguous = violations > 0 and declared
    measurement = Measurement(
        metric="axis_continuity",
        raw_value=round(raw, 6),
        score=round(1.0 - raw, 6),
        target=TargetInterval(max_value=0.0),
        evidence_frames=tuple(sorted(set(evidence))),
        confidence=0.5 if ambiguous else 1.0,
        evidence_grade="demo",
    )
    findings: List[Finding] = []
    if violations and declared:
        findings.append(Finding(
            component="axis_continuity",
            severity=Severity.WARNING,
            message=("已声明越轴意图但相邻镜头缺少中性桥接交代，"
                     "是否算有效越轴需人工复核"),
            evidence_frames=tuple(sorted(set(evidence))),
        ))
    elif violations:
        findings.append(Finding(
            component="axis_continuity",
            severity=Severity.FATAL,
            message=f"相邻镜头银幕左右序翻转（越轴 {violations} 处）且无意图声明",
            evidence_frames=tuple(sorted(set(evidence))),
            gate="H3",
        ))
    return (measurement,), tuple(findings)


def _motion_vector_continuity(
        shots: Sequence[ShotSample],
        intent: Optional[IntentContract]
        ) -> Tuple[Tuple[Measurement, ...], Tuple[Finding, ...]]:
    """相邻镜头主导角色运动向量方向承接。"""
    vectors: List[Tuple[float, float]] = []
    evidence: List[int] = []
    for shot in shots:
        first = _content_first(shot)
        last = _content_last(shot)
        a = _dominant_subject(first)
        b = _dominant_subject(last)
        evidence.extend((first.frame, last.frame))
        if a is None or b is None:
            vectors.append((0.0, 0.0))
            continue
        vectors.append((
            _cx(b.box) - _cx(a.box),
            _cy(b.box) - _cy(a.box),
        ))
    worst = max(
        (_vector_angle_deg(prev, cur)
         for prev, cur in zip(vectors, vectors[1:])),
        default=0.0,
    )
    raw = 1.0 - worst / 180.0
    declared_transition = _has_any(intent, TRANSITION_WORDS)
    ambiguous = 45.0 < worst <= 90.0
    measurement = Measurement(
        metric="motion_vector_continuity",
        raw_value=round(raw, 6),
        score=round(raw, 6),
        target=TargetInterval(min_value=MOTION_TARGET),
        evidence_frames=tuple(sorted(set(evidence))),
        confidence=0.5 if ambiguous else 1.0,
        evidence_grade="demo",
    )
    findings: List[Finding] = []
    if worst > 90.0 and not declared_transition:
        findings.append(Finding(
            component="motion_vector_continuity",
            severity=Severity.FATAL,
            message=(f"相邻镜头主导运动方向急剧反转"
                     f"（夹角 {worst:.1f}°）且无转场交代"),
            evidence_frames=tuple(sorted(set(evidence))),
        ))
    elif ambiguous:
        findings.append(Finding(
            component="motion_vector_continuity",
            severity=Severity.WARNING,
            message="相邻镜头运动方向接近垂直，承接是否成立需人工复核",
            evidence_frames=tuple(sorted(set(evidence))),
        ))
    return (measurement,), tuple(findings)


def _scale_continuity(shots: Sequence[ShotSample],
                      intent: Optional[IntentContract]
                      ) -> Tuple[Tuple[Measurement, ...], Tuple[Finding, ...]]:
    """相邻镜头景别跳级是否有叙事意图。"""
    sizes: List[str] = []
    evidence: List[int] = []
    for shot in shots:
        mid = _content_mid(shot)
        subject = _dominant_subject(mid)
        evidence.append(mid.frame)
        if subject is None:
            sizes.append("")
            continue
        sizes.append(_shot_size_of(subject.box.height))
    pairs = len(sizes) - 1
    jumps = 0
    diff_one = 0
    for prev, cur in zip(sizes, sizes[1:]):
        if not prev or not cur:
            continue
        diff = abs(shot_size_index(prev) - shot_size_index(cur))
        if diff >= 2:
            jumps += 1
        elif diff == 1:
            diff_one += 1
    declared = _has_intent_text(intent)
    raw = 1.0 - (jumps / pairs if pairs else 0.0)
    ambiguous = diff_one > 0 and not declared
    measurement = Measurement(
        metric="scale_continuity",
        raw_value=round(raw, 6),
        score=round(raw, 6),
        target=TargetInterval(min_value=SCALE_TARGET),
        evidence_frames=tuple(sorted(set(evidence))),
        confidence=0.5 if ambiguous else 1.0,
        evidence_grade="demo",
    )
    findings: List[Finding] = []
    if jumps > 0 and not declared:
        findings.append(Finding(
            component="scale_continuity",
            severity=Severity.ERROR,
            message=(f"相邻镜头景别跳级（差 ≥2 档，共 {jumps} 处）"
                     "且未声明叙事意图"),
            evidence_frames=tuple(sorted(set(evidence))),
        ))
    elif ambiguous:
        findings.append(Finding(
            component="scale_continuity",
            severity=Severity.WARNING,
            message="相邻镜头景别单档变化且未声明意图，是否算有意递进需人工复核",
            evidence_frames=tuple(sorted(set(evidence))),
        ))
    return (measurement,), tuple(findings)


def _eyeline_match(shots: Sequence[ShotSample],
                   intent: Optional[IntentContract]
                   ) -> Tuple[Tuple[Measurement, ...], Tuple[Finding, ...]]:
    """对切互看方向与视线高度匹配。"""
    evidence = _evidence_frames(
        shots, (frame.frame for shot in shots for frame in shot.frames))
    if len(shots) < 2:
        mid = _content_mid(shots[0])
        return (Measurement(
            metric="eyeline_match",
            raw_value=1.0,
            score=1.0,
            target=TargetInterval(min_value=EYELINE_TARGET),
            evidence_frames=(mid.frame,),
            confidence=0.9,
            evidence_grade="demo",
        ),), ()
    first = _content_mid(shots[0])
    second = _content_mid(shots[1])
    a = _dominant_subject(first)
    b = _dominant_subject(second)
    if a is None or b is None:
        return (Measurement(
            metric="eyeline_match",
            raw_value=0.0,
            score=0.0,
            target=TargetInterval(min_value=EYELINE_TARGET),
            evidence_frames=evidence,
            confidence=1.0,
            evidence_grade="demo",
        ),), (Finding(
            component="eyeline_match",
            severity=Severity.FATAL,
            message="对切镜头主导角色缺失，互看关系不可判定",
            evidence_frames=evidence,
        ),)
    sign_a = facing_sign_of(a.box.facing)
    sign_b = facing_sign_of(b.box.facing)
    mutual = sign_a != 0 and sign_b != 0 and sign_a != sign_b
    ratio = 0.0
    ambiguous = False
    raw = 1.0
    if mutual:
        ratio = abs(_cy(a.box) - _cy(b.box)) / HEAD_UNIT
        tilt = _has_any(intent, ("俯仰",))
        if ratio > 1.5:
            raw = 0.0
        elif ratio >= 1.0:
            ambiguous = True
            if not tilt:
                raw = 0.0
    else:
        raw = 0.0
    measurement = Measurement(
        metric="eyeline_match",
        raw_value=round(raw, 6),
        score=round(raw, 6),
        target=TargetInterval(min_value=EYELINE_TARGET),
        evidence_frames=evidence,
        confidence=0.5 if ambiguous else 1.0,
        evidence_grade="demo",
    )
    findings: List[Finding] = []
    if not mutual:
        findings.append(Finding(
            component="eyeline_match",
            severity=Severity.FATAL,
            message="对切镜头互看关系断裂（两镜主导角色朝向同侧或不可判定）",
            evidence_frames=evidence,
        ))
    elif ratio > 1.5:
        findings.append(Finding(
            component="eyeline_match",
            severity=Severity.ERROR,
            message=f"对切视线高度差过大（{ratio:.2f} 个头部单位）",
            evidence_frames=evidence,
        ))
    elif ambiguous:
        findings.append(Finding(
            component="eyeline_match",
            severity=Severity.WARNING,
            message="对切视线高度差处于临界且声明俯仰意图，是否匹配需人工复核",
            evidence_frames=evidence,
        ))
    return (measurement,), tuple(findings)


def _screen_direction(shots: Sequence[ShotSample],
                      intent: Optional[IntentContract]
                      ) -> Tuple[Tuple[Measurement, ...], Tuple[Finding, ...]]:
    """银幕方向一致镜头对占比。"""
    signs: List[int] = []
    evidence: List[int] = []
    for shot in shots:
        first = _content_first(shot)
        last = _content_last(shot)
        a = _dominant_subject(first)
        b = _dominant_subject(last)
        evidence.extend((first.frame, last.frame))
        if a is None or b is None:
            signs.append(0)
            continue
        dx = _cx(b.box) - _cx(a.box)
        if abs(dx) <= BOUNDARY_EPS:
            sign = facing_sign_of(_dominant_subject(_content_mid(shot)).box.facing
                                  if _dominant_subject(_content_mid(shot))
                                  else 0.0)
        else:
            sign = 1 if dx > 0.0 else -1
        signs.append(sign)
    pairs = len(signs) - 1
    consistent = sum(
        1 for prev, cur in zip(signs, signs[1:]) if prev == cur)
    raw = consistent / pairs if pairs else 1.0
    declared = _has_any(intent, SCREEN_DECLARED_WORDS)
    ambiguous = raw < 1.0 and declared
    measurement = Measurement(
        metric="screen_direction",
        raw_value=round(raw, 6),
        score=round(raw, 6),
        target=TargetInterval(min_value=SCREEN_TARGET),
        evidence_frames=tuple(sorted(set(evidence))),
        confidence=0.5 if ambiguous else 1.0,
        evidence_grade="demo",
    )
    findings: List[Finding] = []
    if raw < 1.0 and declared:
        findings.append(Finding(
            component="screen_direction",
            severity=Severity.WARNING,
            message="银幕方向换侧已声明意图但缺少中间交代，是否算有效换侧需人工复核",
            evidence_frames=tuple(sorted(set(evidence))),
        ))
    elif raw < 1.0:
        findings.append(Finding(
            component="screen_direction",
            severity=Severity.FATAL,
            message="相邻镜头银幕方向反向且未声明换侧意图",
            evidence_frames=tuple(sorted(set(evidence))),
        ))
    return (measurement,), tuple(findings)


def _temporal_readability(
        shots: Sequence[ShotSample],
        intent: Optional[IntentContract]
        ) -> Tuple[Tuple[Measurement, ...], Tuple[Finding, ...]]:
    """动作—结果剪辑顺序可解释。"""
    evidence = _evidence_frames(
        shots, (frame.frame for shot in shots for frame in shot.frames))
    beats = intent.beats if intent is not None else ()
    if intent is None or len(beats) != len(shots):
        mid = _content_mid(shots[0])
        return (Measurement(
            metric="temporal_readability",
            raw_value=1.0,
            score=1.0,
            target=TargetInterval(min_value=TEMPORAL_TARGET),
            evidence_frames=(mid.frame,),
            confidence=0.9,
            evidence_grade="demo",
        ),), ()
    missing = [shot.shot_id for shot in shots
               if not shot.actions or not shot.contact_frames]
    if missing:
        return (Measurement(
            metric="temporal_readability",
            raw_value=0.0,
            score=0.0,
            target=TargetInterval(min_value=TEMPORAL_TARGET),
            evidence_frames=evidence,
            confidence=1.0,
            evidence_grade="demo",
        ),), (Finding(
            component="temporal_readability",
            severity=Severity.ERROR,
            message=f"声明了节拍但镜头缺少动作接触帧（{missing}）",
            evidence_frames=evidence,
        ),)
    orders = [CAUSAL_ORDER.get(str(beat), 2) for beat in beats]
    falling = all(a >= b for a, b in zip(orders, orders[1:])) and any(
        a > b for a, b in zip(orders, orders[1:]))
    declared_jump = _has_any(intent, TIME_JUMP_WORDS)
    if falling and not declared_jump:
        return (Measurement(
            metric="temporal_readability",
            raw_value=0.0,
            score=0.0,
            target=TargetInterval(min_value=TEMPORAL_TARGET),
            evidence_frames=evidence,
            confidence=1.0,
            evidence_grade="demo",
        ),), (Finding(
            component="temporal_readability",
            severity=Severity.FATAL,
            message="动作—结果剪辑顺序倒置（结果先于动作）且未声明时间跳变",
            evidence_frames=evidence,
        ),)
    if falling and declared_jump:
        return (Measurement(
            metric="temporal_readability",
            raw_value=1.0,
            score=1.0,
            target=TargetInterval(min_value=TEMPORAL_TARGET),
            evidence_frames=evidence,
            confidence=0.5,
            evidence_grade="demo",
        ),), (Finding(
            component="temporal_readability",
            severity=Severity.WARNING,
            message="结果先于动作但已声明时间跳变，是否算有意倒叙需人工复核",
            evidence_frames=evidence,
        ),)
    return (Measurement(
        metric="temporal_readability",
        raw_value=1.0,
        score=1.0,
        target=TargetInterval(min_value=TEMPORAL_TARGET),
        evidence_frames=evidence,
        confidence=1.0,
        evidence_grade="demo",
    ),), ()


# --------------------------------------------------------------------------- #
# 公共接缝：evaluate / build_prescriptions / render_report / SAMPLES
# --------------------------------------------------------------------------- #
def evaluate(sample: object,
             intent: Optional[IntentContract] = None) -> EvaluationOutput:
    """对本层全部六项指标产出测量与失败项（§8/§11.1 公共接缝）。"""
    shots = _shots_of(sample)
    measurements: List[Measurement] = []
    findings: List[Finding] = []
    for worker in (
        _axis_continuity,
        _motion_vector_continuity,
        _scale_continuity,
        _eyeline_match,
        _screen_direction,
        _temporal_readability,
    ):
        ms, fs = worker(shots, intent)
        measurements.extend(ms)
        findings.extend(fs)
    shot_id = shots[0].shot_id if shots else ""
    return EvaluationOutput(
        shot_id=shot_id,
        measurements=tuple(measurements),
        findings=tuple(findings),
        intent=intent,
    )


def build_prescriptions(output: EvaluationOutput) -> Tuple[Prescription, ...]:
    """只对失败分量（fatal/error）产处方；通过/两可的分量不产。"""
    out: List[Prescription] = []
    for finding in output.findings:
        if finding.severity not in (Severity.FATAL, Severity.ERROR):
            continue
        if finding.component not in _REPAIR:
            continue
        measurement = next(
            (m for m in output.measurements
             if m.metric == finding.component), None)
        if measurement is None:
            continue
        direction, effects, allowed = _REPAIR[finding.component]
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
    lines = [f"镜头 {output.shot_id} 连续性层读数："]
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
    """一个三态样例：镜头序列采样 + 意图 + 预期结论。"""

    name: str
    sample: object
    intent: Optional[IntentContract]
    expected: str


# --------------------------------------------------------------------------- #
# 三态样例（demo 级，可复现）
# --------------------------------------------------------------------------- #
def _projected(subject_id: str, cx: float, cy: float, height: float,
               facing: float) -> ProjectedSubject:
    """角色投影盒：盒宽固定 0.04，中心 (cx, cy)，高 height，朝向 facing。"""
    hw = 0.02
    return ProjectedSubject(
        subject_id=subject_id,
        kind="character",
        box=SubjectBox(name=subject_id, left=cx - hw, right=cx + hw,
                       top=cy + height / 2.0, bottom=cy - height / 2.0,
                       facing=facing),
        visible_ratio=1.0,
    )


def _frame(shot_id: str, n: int,
           subjects: Tuple[ProjectedSubject, ...]) -> FrameSample:
    return FrameSample(frame=n, shot_id=shot_id, subjects=subjects)


def _content_shot(shot_id: str, frame_range: Tuple[int, int],
                  subjects_by_frame: Dict[int, Tuple[ProjectedSubject, ...]]
                  ) -> ShotSample:
    """按 帧号->投影 字典构造内容关键帧（须覆盖首/中/末）。"""
    numbers = tuple(sorted(subjects_by_frame))
    frames = tuple(_frame(shot_id, n, subjects_by_frame[n])
                   for n in numbers)
    content = ContentFrame.from_shot(shot_id, frame_range, frames)
    return ShotSample(shot_id=shot_id, frame_range=frame_range,
                      content=content)


def _hero_motion(first_x: float, last_x: float, facing: float,
                 shot_id: str, frame_range: Tuple[int, int],
                 cy: float = 0.52, height: float = 0.40) -> ShotSample:
    """单角色横向运动镜头：首/中/末帧中心沿首->末插值。"""
    first, last = frame_range
    mid_x = (first_x + last_x) / 2.0
    return _content_shot(shot_id, frame_range, {
        first: (_projected("hero", first_x, cy, height, facing),),
        middle_frame(first, last):
            (_projected("hero", mid_x, cy, height, facing),),
        last: (_projected("hero", last_x, cy, height, facing),),
    })


def _hero_static(cx: float, cy: float, height: float, facing: float,
                 shot_id: str, frame_range: Tuple[int, int]) -> ShotSample:
    first, last = frame_range
    subject = (_projected("hero", cx, cy, height, facing),)
    return _content_shot(shot_id, frame_range, {
        first: subject,
        middle_frame(first, last): subject,
        last: subject,
    })


def _action_shot(shot_id: str, frame_range: Tuple[int, int],
                 cx: float = 0.50, cy: float = 0.52,
                 height: float = 0.40, facing: float = 1.0) -> ShotSample:
    """动作镜头：内容帧 首/中/末 + 动作帧 起点/接触/反应。"""
    first, last = frame_range
    subject = (_projected("hero", cx, cy, height, facing),)
    content = ContentFrame.from_shot(
        shot_id, frame_range,
        (_frame(shot_id, first, subject),
         _frame(shot_id, middle_frame(first, last), subject),
         _frame(shot_id, last, subject)))
    actions = (ActionFrame(
        shot_id=shot_id,
        start=_frame(shot_id, first + 1, subject),
        contacts=(_frame(shot_id, first + 2, subject),),
        reaction_end=_frame(shot_id, first + 3, subject),
    ),)
    return ShotSample(shot_id=shot_id, frame_range=frame_range,
                      content=content, actions=actions)


def _sequence(shots: Sequence[ShotSample]) -> SequenceSample:
    return SequenceSample(shots=tuple(shots))


def _dialogue_pair() -> SequenceSample:
    """双人对切：左右序稳定、互看成立、视线同高（axis/eyeline good）。"""
    shot1 = _content_shot("shot_001", (1, 5), {
        1: (_projected("hero", 0.28, 0.52, 0.55, 1.0),
            _projected("enemy", 0.70, 0.52, 0.30, -1.0)),
        3: (_projected("hero", 0.30, 0.52, 0.55, 1.0),
            _projected("enemy", 0.70, 0.52, 0.30, -1.0)),
        5: (_projected("hero", 0.32, 0.52, 0.55, 1.0),
            _projected("enemy", 0.70, 0.52, 0.30, -1.0)),
    })
    shot2 = _content_shot("shot_002", (6, 10), {
        6: (_projected("enemy", 0.68, 0.52, 0.55, -1.0),
            _projected("hero", 0.30, 0.52, 0.30, 1.0)),
        8: (_projected("enemy", 0.70, 0.52, 0.55, -1.0),
            _projected("hero", 0.30, 0.52, 0.30, 1.0)),
        10: (_projected("enemy", 0.72, 0.52, 0.55, -1.0),
             _projected("hero", 0.30, 0.52, 0.30, 1.0)),
    })
    return _sequence((shot1, shot2))


def _dialogue_flipped_pair() -> SequenceSample:
    """双人越轴：第二镜左右序翻转、运动与银幕方向反向（axis bad）。"""
    shot1 = _content_shot("shot_001", (1, 5), {
        1: (_projected("hero", 0.28, 0.52, 0.55, 1.0),
            _projected("enemy", 0.70, 0.52, 0.30, -1.0)),
        3: (_projected("hero", 0.30, 0.52, 0.55, 1.0),
            _projected("enemy", 0.70, 0.52, 0.30, -1.0)),
        5: (_projected("hero", 0.32, 0.52, 0.55, 1.0),
            _projected("enemy", 0.70, 0.52, 0.30, -1.0)),
    })
    shot2 = _content_shot("shot_002", (6, 10), {
        6: (_projected("enemy", 0.32, 0.52, 0.55, -1.0),
            _projected("hero", 0.70, 0.52, 0.30, 1.0)),
        8: (_projected("enemy", 0.30, 0.52, 0.55, -1.0),
            _projected("hero", 0.70, 0.52, 0.30, 1.0)),
        10: (_projected("enemy", 0.28, 0.52, 0.55, -1.0),
             _projected("hero", 0.70, 0.52, 0.30, 1.0)),
    })
    return _sequence((shot1, shot2))


def _chase_continuous() -> SequenceSample:
    """单角色同向追逐：运动方向一致、银幕方向一致（motion/screen good）。"""
    shot1 = _hero_motion(0.30, 0.50, 1.0, "shot_001", (1, 5))
    shot2 = _hero_motion(0.50, 0.70, -1.0, "shot_002", (6, 10))
    return _sequence((shot1, shot2))


def _chase_reversed() -> SequenceSample:
    """单角色反向追逐：运动与银幕方向均反向（motion/screen bad）。"""
    shot1 = _hero_motion(0.30, 0.50, 1.0, "shot_001", (1, 5))
    shot2 = _hero_motion(0.50, 0.30, 1.0, "shot_002", (6, 10))
    return _sequence((shot1, shot2))


def _corner_turn() -> SequenceSample:
    """直角转弯：相邻运动方向恰 90°，承接两可（motion ambiguous）。"""
    shot1 = _hero_motion(0.30, 0.50, 1.0, "shot_001", (1, 5))
    shot2 = _content_shot("shot_002", (6, 10), {
        6: (_projected("hero", 0.50, 0.52, 0.40, 1.0),),
        8: (_projected("hero", 0.50, 0.62, 0.40, 1.0),),
        10: (_projected("hero", 0.50, 0.72, 0.40, 1.0),),
    })
    return _sequence((shot1, shot2))


def _scale_step() -> SequenceSample:
    """景别单档递进（MCU->MS），是否有意取决于意图（scale good/ambiguous）。"""
    shot1 = _hero_static(0.50, 0.52, 0.50, 1.0, "shot_001", (1, 5))
    shot2 = _hero_static(0.50, 0.52, 0.34, 1.0, "shot_002", (6, 10))
    return _sequence((shot1, shot2))


def _scale_jump() -> SequenceSample:
    """景别大幅跳级（ECU->ELS，差 6 档）且无意图（scale bad）。"""
    shot1 = _hero_static(0.50, 0.52, 0.90, 1.0, "shot_001", (1, 5))
    shot2 = _hero_static(0.50, 0.52, 0.08, 1.0, "shot_002", (6, 10))
    return _sequence((shot1, shot2))


def _single_hero_same_facing() -> SequenceSample:
    """单角色两镜朝向同侧：互看关系断裂（eyeline bad）。"""
    shot1 = _hero_static(0.50, 0.52, 0.40, 1.0, "shot_001", (1, 5))
    shot2 = _hero_static(0.50, 0.52, 0.40, 1.0, "shot_002", (6, 10))
    return _sequence((shot1, shot2))


def _eyeline_tilt() -> SequenceSample:
    """两镜朝向异号但视线高度差恰 1 个头单位（eyeline ambiguous）。"""
    shot1 = _hero_static(0.50, 0.42, 0.40, -1.0, "shot_001", (1, 5))
    shot2 = _hero_static(0.50, 0.52, 0.40, 1.0, "shot_002", (6, 10))
    return _sequence((shot1, shot2))


def _action_pair() -> SequenceSample:
    """两镜动作镜头：结果先于动作由 beats 声明决定（temporal 三态共用）。"""
    shot1 = _action_shot("shot_001", (1, 5))
    shot2 = _action_shot("shot_002", (6, 10))
    return _sequence((shot1, shot2))


SAMPLES: Dict[str, Dict[str, SampleCase]] = {
    "axis_continuity": {
        "good": SampleCase("axis_continuity", _dialogue_pair(), None, "good"),
        "bad": SampleCase(
            "axis_continuity", _dialogue_flipped_pair(), None, "bad"),
        "ambiguous": SampleCase(
            "axis_continuity", _dialogue_flipped_pair(),
            IntentContract(shot_id="shot_001", intent="反打越轴",
                           axis_side="positive"),
            "ambiguous"),
    },
    "motion_vector_continuity": {
        "good": SampleCase(
            "motion_vector_continuity", _chase_continuous(), None, "good"),
        "bad": SampleCase(
            "motion_vector_continuity", _chase_reversed(), None, "bad"),
        "ambiguous": SampleCase(
            "motion_vector_continuity", _corner_turn(),
            IntentContract(shot_id="shot_001", intent="承接转弯"),
            "ambiguous"),
    },
    "scale_continuity": {
        "good": SampleCase(
            "scale_continuity", _scale_step(),
            IntentContract(shot_id="shot_001", intent="景别递进强调反应"),
            "good"),
        "bad": SampleCase(
            "scale_continuity", _scale_jump(), None, "bad"),
        "ambiguous": SampleCase(
            "scale_continuity", _scale_step(),
            IntentContract(shot_id="shot_001", intent=""),
            "ambiguous"),
    },
    "eyeline_match": {
        "good": SampleCase(
            "eyeline_match", _dialogue_pair(), None, "good"),
        "bad": SampleCase(
            "eyeline_match", _single_hero_same_facing(), None, "bad"),
        "ambiguous": SampleCase(
            "eyeline_match", _eyeline_tilt(),
            IntentContract(shot_id="shot_001", intent="俯仰视线呼应"),
            "ambiguous"),
    },
    "screen_direction": {
        "good": SampleCase(
            "screen_direction", _chase_continuous(), None, "good"),
        "bad": SampleCase(
            "screen_direction", _chase_reversed(), None, "bad"),
        "ambiguous": SampleCase(
            "screen_direction", _chase_reversed(),
            IntentContract(shot_id="shot_001", intent="反打换侧"),
            "ambiguous"),
    },
    "temporal_readability": {
        "good": SampleCase(
            "temporal_readability", _action_pair(),
            IntentContract(shot_id="shot_001", beats=("动作", "结果")),
            "good"),
        "bad": SampleCase(
            "temporal_readability", _action_pair(),
            IntentContract(shot_id="shot_001", beats=("结果", "动作")),
            "bad"),
        "ambiguous": SampleCase(
            "temporal_readability", _action_pair(),
            IntentContract(shot_id="shot_001", beats=("结果", "动作"),
                           intent="时间跳变闪回"),
            "ambiguous"),
    },
}


__all__ = [
    "SampleCase", "SAMPLES", "evaluate", "build_prescriptions",
    "render_report",
]
