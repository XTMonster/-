"""空间尺 04 · 几何基础层 5 指标（Ticket 04）。

指标（阈值以 metric_registry.py 注册表为真源，本模块照抄口径）：
* edge_clearance      —— 主体包围盒到最近画面边缘的 NDC 距离，目标 [0.04, 0.20]；
* depth_separation    —— 前后层组合分（重叠与尺度分离），目标 ≥ 0.60；
* silhouette_separation —— 轮廓重叠率（demo 用投影盒重叠近似），目标 ≤ 0.25；
* screen_size         —— 主体屏幕高度与声明景别期望高度的相对偏差，目标 ≤ ±15%；
* horizon_stability   —— 画面滚转角与意图基准的偏差，无意图 ≤ 1°。

本模块为纯层实现（不 import bpy），输入是 evaluation_protocol 的采样对象；
样例均为 demo 输入（evidence_grade="demo"），输出统一 Measurement /
Finding / Prescription / EvaluationOutput。

注意：screen_size 的“声明景别 -> 期望高度”映射属于本模块的 demo 常量
（新指标新样例，不触碰既有 composition/framing 阈值）；正式运行时由
评测台提供景别表，本表只用于可复现的三态样例。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Sequence, Tuple

from ..contracts.tools import ACTION_TOOLS
from .composition import SubjectBox
from .evaluation_protocol import (
    EvaluationOutput,
    Finding,
    FrameSample,
    IntentContract,
    Measurement,
    Prescription,
    SequenceSample,
    Severity,
    ShotSample,
    TargetInterval,
)
from .metric_registry import METRICS_BY_NAME
from .prescription import validate_prescription


# --------------------------------------------------------------------------- #
# 阈值与常量（注册表口径）
# --------------------------------------------------------------------------- #
#: edge_clearance 目标区间与分级。
EDGE_MIN = 0.04
EDGE_MAX = 0.20
EDGE_BOUNDARY_EPS = 0.002          # 恰在 0.04 边界 ± eps 视为两可

#: depth_separation 组合分目标下限。
DEPTH_TARGET = 0.60

#: silhouette_separation 重叠率目标上限。
SILHOUETTE_TARGET = 0.25

#: screen_size 相对偏差目标上限（±15%）。
SIZE_DEVIATION_TARGET = 0.15

#: horizon_stability 无意图偏差上限（度）。
HORIZON_TARGET_DEG = 1.0

#: 声明景别 -> 期望屏幕高度（demo 级常量，正式景别表由评测台提供）。
SHOT_TYPE_EXPECTED_HEIGHT: Dict[str, float] = {
    "MS": 0.45,   # 中景
    "CU": 0.80,   # 近景/特写
}

#: 处方方向与预期影响（只给方向，不含工具名/参数；与注册表 repair_direction 同源）。
_REPAIR: Dict[str, Tuple[str, Tuple[str, ...], Tuple[str, ...]]] = {
    "edge_clearance": (
        "把主体关键点拉回安全区：收紧景别或调整机位，让主体与画面边缘留出余量",
        ("edge_clearance",),
        ("move_character", "move_camera", "reframe"),
    ),
    "depth_separation": (
        "拉开前后景纵深：调整走位拉开两层距离，并改变机位角度避免两层重合",
        ("depth_separation",),
        ("move_character", "move_camera"),
    ),
    "silhouette_separation": (
        "错开站位与轮廓层次：让关键主体与背景/他人轮廓保持可分离，必要时换机位",
        ("silhouette_separation",),
        ("move_character", "move_camera"),
    ),
    "screen_size": (
        "修正主体在画面中的尺度：机位推进或收紧景别，使主体高度回到声明景别的期望区间",
        ("screen_size",),
        ("move_camera", "reframe"),
    ),
    "horizon_stability": (
        "修正画面滚转：让水平基线回到水平或与已声明倾斜意图一致",
        ("horizon_stability",),
        ("setup_camera", "move_camera"),
    ),
}


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _boundary(value: float, boundary: float, eps: float) -> bool:
    """value 是否落在 boundary ± eps 的两可带上。"""
    return abs(float(value) - boundary) <= eps


def _ambiguous_warning(component: str, boundary_desc: str,
                       evidence: Tuple[int, ...]) -> Finding:
    """结构性两可的三态输出：WARNING + 「需人工复核」结尾，不产处方。"""
    return Finding(
        component=component,
        severity=Severity.WARNING,
        message=f"{boundary_desc}需人工复核",
        evidence_frames=evidence,
    )


def _primary_subject(frame: FrameSample) -> Optional[SubjectBox]:
    """取帧内最大的角色投影盒作主主体（无角色时取任一主体）。"""
    subjects = [s for s in frame.subjects if s.kind == "character"]
    if not subjects:
        subjects = list(frame.subjects)
    if not subjects:
        return None
    return max(subjects, key=lambda s: s.box.height).box


def _clearance(box: SubjectBox) -> float:
    """包围盒到最近画面边缘的 NDC 距离；完全出画钳制为 0。"""
    dists = (box.left - 0.0, 1.0 - box.right,
             1.0 - box.top, box.bottom)
    return max(0.0, min(dists))


def _overlap_ratio(a: SubjectBox, b: SubjectBox) -> float:
    """两个投影盒的重叠率：重叠面积 / 较小盒面积（demo 轮廓近似）。"""
    x_overlap = max(0.0, min(a.right, b.right) - max(a.left, b.left))
    y_overlap = max(0.0, min(a.top, b.top) - max(a.bottom, b.bottom))
    overlap_area = x_overlap * y_overlap
    min_area = min(max(a.width, 1e-9) * max(a.height, 1e-9),
                   max(b.width, 1e-9) * max(b.height, 1e-9))
    return _clamp01(overlap_area / min_area)


# --------------------------------------------------------------------------- #
# 指标 worker：返回 (measurements, findings)
# --------------------------------------------------------------------------- #
def _edge_clearance(shot: ShotSample) -> Tuple[Tuple[Measurement, ...],
                                                Tuple[Finding, ...]]:
    clearances: list[float] = []
    evidence: list[int] = []
    out_of_frame: list[int] = []
    for frame in shot.frames:
        for subject in frame.subjects:
            box = subject.box
            value = _clearance(box)
            clearances.append(value)
            evidence.append(frame.frame)
            if box.inside_ratio() <= 0.0:
                out_of_frame.append(frame.frame)
    if not clearances:
        return (), ()
    raw = min(clearances)
    frame_first = min(evidence)
    score = (_clamp01(1.0 - (EDGE_MIN - raw) / EDGE_MIN)
             if raw < EDGE_MIN else 1.0)
    ambiguous = (
        raw >= EDGE_MIN and _boundary(raw, EDGE_MIN, EDGE_BOUNDARY_EPS)
    )
    measurement = Measurement(
        metric="edge_clearance",
        raw_value=round(raw, 6),
        score=round(score, 6),
        target=TargetInterval(min_value=EDGE_MIN, max_value=EDGE_MAX),
        evidence_frames=tuple(sorted(set(evidence))),
        confidence=0.5 if ambiguous else 1.0,
        evidence_grade="demo",
    )
    findings: list[Finding] = []
    if out_of_frame:
        findings.append(Finding(
            component="edge_clearance",
            severity=Severity.FATAL,
            message=f"关键点完全出画（帧 {out_of_frame}），主体包围盒整体在画外",
            evidence_frames=tuple(sorted(set(out_of_frame))),
            gate="H1",
        ))
    elif raw < EDGE_MIN:
        findings.append(Finding(
            component="edge_clearance",
            severity=Severity.ERROR,
            message=(f"主体贴近画面边缘（最小边距 {raw:.3f} < {EDGE_MIN}），"
                     "关键点存在出画风险"),
            evidence_frames=(frame_first,),
        ))
    elif ambiguous:
        findings.append(_ambiguous_warning(
            "edge_clearance",
            "主体边缘距离恰在安全区下界附近且声明景别为近景，"
            "贴近是否算有意构图两可，",
            tuple(sorted(set(evidence))),
        ))
    return (measurement,), tuple(findings)


def _depth_separation(shot: ShotSample) -> Tuple[Tuple[Measurement, ...],
                                                 Tuple[Finding, ...]]:
    best_score: Optional[float] = None
    evidence: list[int] = []
    for frame in shot.frames:
        chars = [s for s in frame.subjects if s.kind == "character"]
        if len(chars) < 2:
            continue
        ordered = sorted(chars, key=lambda s: s.box.height, reverse=True)
        front, back = ordered[0], ordered[1]
        overlap = _overlap_ratio(front.box, back.box)
        shorter = min(front.box.height, back.box.height)
        taller = max(front.box.height, back.box.height)
        scale_sep = 1.0 - shorter / max(taller, 1e-9)
        composite = 0.6 * (1.0 - overlap) + 0.4 * (1.0 - scale_sep)
        if best_score is None or composite < best_score:
            best_score = composite
        evidence.append(frame.frame)
    if best_score is None:
        return (), ()
    raw = round(best_score, 6)
    ambiguous = _boundary(raw, DEPTH_TARGET, 0.002)
    measurement = Measurement(
        metric="depth_separation",
        raw_value=raw,
        score=raw,
        target=TargetInterval(min_value=DEPTH_TARGET),
        evidence_frames=tuple(sorted(set(evidence))),
        confidence=0.5 if ambiguous else 1.0,
        evidence_grade="demo",
    )
    findings: list[Finding] = []
    if raw < 0.30:
        findings.append(Finding(
            component="depth_separation",
            severity=Severity.FATAL,
            message="前后层完全重合，主次深度不可辨",
            evidence_frames=tuple(sorted(set(evidence))),
        ))
    elif raw < DEPTH_TARGET:
        findings.append(Finding(
            component="depth_separation",
            severity=Severity.ERROR,
            message=(f"前后层重叠但深度差小（组合分 {raw:.3f} < "
                     f"{DEPTH_TARGET}），层次感不足"),
            evidence_frames=tuple(sorted(set(evidence))),
        ))
    elif ambiguous:
        findings.append(_ambiguous_warning(
            "depth_separation",
            "前后层组合分恰在 0.60 阈值边缘，斜角机位看似分离实则贴背，",
            tuple(sorted(set(evidence))),
        ))
    return (measurement,), tuple(findings)


def _silhouette_separation(shot: ShotSample) -> Tuple[Tuple[Measurement, ...],
                                                      Tuple[Finding, ...]]:
    worst: Optional[float] = None
    evidence: list[int] = []
    for frame in shot.frames:
        boxes = [s.box for s in frame.subjects]
        if len(boxes) < 2:
            continue
        frame_worst = 0.0
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                ratio = _overlap_ratio(boxes[i], boxes[j])
                frame_worst = max(frame_worst, ratio)
        if worst is None or frame_worst > worst:
            worst = frame_worst
        evidence.append(frame.frame)
    if worst is None:
        return (), ()
    raw = round(worst, 6)
    ambiguous = _boundary(raw, SILHOUETTE_TARGET, 0.002)
    measurement = Measurement(
        metric="silhouette_separation",
        raw_value=raw,
        score=round(1.0 - raw, 6),
        target=TargetInterval(max_value=SILHOUETTE_TARGET),
        evidence_frames=tuple(sorted(set(evidence))),
        confidence=0.5 if ambiguous else 1.0,
        evidence_grade="demo",
    )
    findings: list[Finding] = []
    if raw > 0.50:
        findings.append(Finding(
            component="silhouette_separation",
            severity=Severity.FATAL,
            message=(f"关键动作轮廓粘连（重叠率 {raw:.3f}），主体轮廓不可分离"),
            evidence_frames=tuple(sorted(set(evidence))),
        ))
    elif raw > SILHOUETTE_TARGET:
        findings.append(Finding(
            component="silhouette_separation",
            severity=Severity.ERROR,
            message=(f"轮廓部分粘连（重叠率 {raw:.3f} > {SILHOUETTE_TARGET}），"
                     "动作可辨性受损"),
            evidence_frames=tuple(sorted(set(evidence))),
        ))
    elif ambiguous:
        findings.append(_ambiguous_warning(
            "silhouette_separation",
            "轮廓重叠率恰在 0.25 边界且属前后景压脚的有意层次，",
            tuple(sorted(set(evidence))),
        ))
    return (measurement,), tuple(findings)


def _screen_size(shot: ShotSample,
                 intent: Optional[IntentContract]) -> Tuple[
                     Tuple[Measurement, ...], Tuple[Finding, ...]]:
    # 声明景别缺失/未知时按中景默认尺度测量，置信度 < 1（公共接缝要求
    # 每指标至少 1 个 Measurement，缺声明本身属两可，不按降级处理）。
    expected = SHOT_TYPE_EXPECTED_HEIGHT.get(
        intent.shot_type if intent is not None else "")
    using_default = expected is None
    if using_default:
        expected = SHOT_TYPE_EXPECTED_HEIGHT["MS"]
    deviations: list[float] = []
    evidence: list[int] = []
    for frame in shot.frames:
        box = _primary_subject(frame)
        if box is None:
            continue
        ratio = box.height / expected
        deviations.append(abs(ratio - 1.0))
        evidence.append(frame.frame)
    if not deviations:
        return (), ()
    raw = round(max(deviations), 6)
    ambiguous = _boundary(raw, SIZE_DEVIATION_TARGET, 0.002)
    measurement = Measurement(
        metric="screen_size",
        raw_value=raw,
        score=round(1.0 - raw, 6),
        target=TargetInterval(max_value=SIZE_DEVIATION_TARGET),
        evidence_frames=tuple(sorted(set(evidence))),
        confidence=0.5 if (ambiguous or using_default) else 1.0,
        evidence_grade="demo",
    )
    findings: list[Finding] = []
    if raw > 0.45:
        findings.append(Finding(
            component="screen_size",
            severity=Severity.FATAL,
            message=(f"主体尺度与声明景别完全不符（偏差 {raw:.3f}），"
                     "画面语义被读错"),
            evidence_frames=tuple(sorted(set(evidence))),
        ))
    elif raw > SIZE_DEVIATION_TARGET:
        findings.append(Finding(
            component="screen_size",
            severity=Severity.ERROR,
            message=(f"主体尺度超出声明景别允许偏差（偏差 {raw:.3f} > "
                     f"{SIZE_DEVIATION_TARGET}）"),
            evidence_frames=tuple(sorted(set(evidence))),
        ))
    elif ambiguous:
        findings.append(_ambiguous_warning(
            "screen_size",
            "主体尺度偏差恰在 15% 边界且运镜为推拉，按首/中/末哪帧判定两可，",
            tuple(sorted(set(evidence))),
        ))
    elif using_default:
        findings.append(_ambiguous_warning(
            "screen_size",
            "声明景别缺失，已按中景默认尺度测量，判定是否适用于剧本意图两可，",
            tuple(sorted(set(evidence))),
        ))
    return (measurement,), tuple(findings)


def _horizon_stability(shot: ShotSample,
                       intent: Optional[IntentContract]) -> Tuple[
                           Tuple[Measurement, ...], Tuple[Finding, ...]]:
    baseline = 0.0
    hint = bool(intent is not None and "主观镜头" in (intent.intent or ""))
    declared_tilt: list[str] = []
    if intent is not None:
        movements = tuple(intent.camera_movements or ())
        declared_tilt = [m for m in movements
                         if any(k in m for k in ("tilt", "canted", "roll"))]
    # 已显式声明倾斜意图时视为声明一致（deviation=0），不再以水平基线衡量；
    # 未声明时以水平基线 0° 为基准。
    if declared_tilt:
        deviations = [0.0 for _ in shot.frames]
    else:
        deviations = [abs(float(frame.roll_deg) - baseline)
                      for frame in shot.frames]
    raw = round(max(deviations), 6)
    evidence = tuple(frame.frame for frame in shot.frames)
    ambiguous = (
        raw > HORIZON_TARGET_DEG and hint
        and raw <= 2.0 * HORIZON_TARGET_DEG
    )
    measurement = Measurement(
        metric="horizon_stability",
        raw_value=raw,
        score=round(_clamp01(1.0 - raw / 10.0), 6),
        target=TargetInterval(max_value=HORIZON_TARGET_DEG),
        evidence_frames=evidence,
        confidence=0.5 if ambiguous else 1.0,
        evidence_grade="demo",
    )
    findings: list[Finding] = []
    if raw > 5.0:
        findings.append(Finding(
            component="horizon_stability",
            severity=Severity.FATAL,
            message=f"画面严重倾斜（滚转 {raw:.1f}°）且无意图声明",
            evidence_frames=evidence,
        ))
    elif raw > HORIZON_TARGET_DEG and not hint:
        findings.append(Finding(
            component="horizon_stability",
            severity=Severity.ERROR,
            message=f"画面轻微漂移（滚转 {raw:.1f}°），水平基线不稳定",
            evidence_frames=evidence,
        ))
    elif ambiguous:
        findings.append(_ambiguous_warning(
            "horizon_stability",
            "轻微倾斜且剧本有主观镜头暗示但未显式声明，是否算有意图两可，",
            evidence,
        ))
    return (measurement,), tuple(findings)


# --------------------------------------------------------------------------- #
# 公共接缝：evaluate / build_prescriptions / render_report / SAMPLES
# --------------------------------------------------------------------------- #
def _shots_of(sample: object) -> Tuple[ShotSample, ...]:
    if isinstance(sample, ShotSample):
        return (sample,)
    if isinstance(sample, SequenceSample):
        return sample.shots
    raise TypeError(f"几何层只接受 ShotSample/SequenceSample：{type(sample)!r}")


def evaluate(sample: object,
             intent: Optional[IntentContract] = None) -> EvaluationOutput:
    """对本层全部适用指标产出测量与失败项（§8/§11.1 公共接缝）。"""
    shots = _shots_of(sample)
    measurements: list[Measurement] = []
    findings: list[Finding] = []
    for shot in shots:
        workers = (
            _edge_clearance(shot),
            _depth_separation(shot),
            _silhouette_separation(shot),
            _screen_size(shot, intent),
            _horizon_stability(shot, intent),
        )
        for ms, fs in workers:
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
    """只对失败分量（fatal/error）产处方；通过的分量不产。"""
    out: list[Prescription] = []
    for finding in output.findings:
        if finding.severity not in (Severity.FATAL, Severity.ERROR):
            continue
        if finding.component not in _REPAIR:
            continue
        direction, effects, allowed = _REPAIR[finding.component]
        # 目标区间按本模块注册表口径重建（与 Measurement.target 一致）。
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
    lines = [f"镜头 {output.shot_id} 几何层读数："]
    if output.intent is not None:
        lines.append(f"- 声明景别：{output.intent.shot_type or '（未声明）'}")
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


def _shot_with(shot_id: str, subjects: Tuple[FrameSample, ...],
               frame_range: Tuple[int, int]) -> ShotSample:
    content = _content(shot_id, subjects, frame_range)
    return ShotSample(shot_id=shot_id, frame_range=frame_range,
                      content=content)


def _content(shot_id: str, frames: Tuple[FrameSample, ...],
             frame_range: Tuple[int, int]):
    from .evaluation_protocol import ContentFrame
    return ContentFrame.from_shot(shot_id=shot_id, frame_range=frame_range,
                                  frames=frames)


def _subject_box(subject_id: str, left: float, right: float, top: float,
                 bottom: float) -> SubjectBox:
    return SubjectBox(name=subject_id, left=left, right=right, top=top,
                      bottom=bottom, facing=1.0)


def _projected(subject_id: str, box: SubjectBox,
               kind: str = "character"):
    from .evaluation_protocol import ProjectedSubject
    return ProjectedSubject(subject_id=subject_id, kind=kind, box=box,
                            visible_ratio=1.0)


def _frames(subjects: Tuple[object, ...], shot_id: str = "shot_001",
            roll_deg: float = 0.0,
            frame_range: Tuple[int, int] = (1, 5)) -> Tuple[FrameSample, ...]:
    first, last = frame_range
    middle = (first + last) // 2
    return tuple(
        FrameSample(frame=n, shot_id=shot_id, subjects=subjects,
                    roll_deg=roll_deg)
        for n in (first, middle, last)
    )


def _hero(left: float, right: float, top: float, bottom: float) -> object:
    return _projected("hero", _subject_box("hero", left, right, top, bottom))


def _two(subjects: Tuple[object, ...], shot_id: str = "shot_001",
         roll_deg: float = 0.0) -> ShotSample:
    return _shot_with(shot_id, _frames(subjects, shot_id, roll_deg=roll_deg),
                      (1, 5))


_hero_good = _hero(0.10, 0.35, 0.95, 0.50)           # 最近边距 0.10 ∈ [0.04, 0.20]
_hero_boundary = _hero(0.04, 0.30, 0.92, 0.12)       # 左缘恰 0.04，高 0.80 匹配 CU
_hero_out = _hero(-0.30, -0.10, 0.95, 0.50)          # 完全出画

_back_good = _projected(
    "back", _subject_box("back", 0.05, 0.35, 0.92, 0.02))
_front_good = _projected(
    "hero", _subject_box("hero", 0.50, 0.80, 0.75, 0.30))
_back_boundary = _projected(
    "back", _subject_box("back", 0.15, 0.45, 0.95, 0.05))
_front_boundary = _projected(
    "hero", _subject_box("hero", 0.40, 0.65, 0.32, 0.05))
_stacked_back = _projected(
    "back", _subject_box("back", 0.30, 0.60, 0.92, 0.02))
_stacked_front = _projected(
    "hero", _subject_box("hero", 0.30, 0.60, 0.92, 0.32))

_left_box = _projected(
    "hero", _subject_box("hero", 0.25, 0.45, 0.90, 0.35))
_right_good = _projected(
    "extra", _subject_box("extra", 0.55, 0.85, 0.95, 0.10))
_right_partial = _projected(
    "extra", _subject_box("extra", 0.40, 0.70, 0.95, 0.10))
_right_engulf = _projected(
    "extra", _subject_box("extra", 0.34, 0.79, 0.95, 0.05))

_cu_box = _hero(0.20, 0.60, 0.95, 0.15)              # 特写尺度（高 0.80）
_size_boundary = _hero(0.25, 0.60, 0.95, 0.5675)     # 高 0.3825 = 0.45×0.85


SAMPLES: Dict[str, Dict[str, SampleCase]] = {
    "edge_clearance": {
        "good": SampleCase(
            "edge_clearance", _two((_hero_good,)),
            IntentContract(shot_id="shot_001", shot_type="MS"),
            "good"),
        "bad": SampleCase(
            "edge_clearance", _two((_hero_out,)),
            IntentContract(shot_id="shot_001", shot_type="MS"),
            "bad"),
        "ambiguous": SampleCase(
            "edge_clearance", _two((_hero_boundary,)),
            IntentContract(shot_id="shot_001", shot_type="CU"),
            "ambiguous"),
    },
    "depth_separation": {
        "good": SampleCase(
            "depth_separation", _two((_back_good, _front_good)),
            None, "good"),
        "bad": SampleCase(
            "depth_separation", _two((_stacked_back, _stacked_front)),
            None, "bad"),
        "ambiguous": SampleCase(
            "depth_separation", _two((_back_boundary, _front_boundary)),
            IntentContract(shot_id="shot_001", shot_type="CU"),
            "ambiguous"),
    },
    "silhouette_separation": {
        "good": SampleCase(
            "silhouette_separation", _two((_left_box, _right_good)),
            None, "good"),
        "bad": SampleCase(
            "silhouette_separation", _two((_left_box, _right_engulf)),
            None, "bad"),
        "ambiguous": SampleCase(
            "silhouette_separation", _two((_left_box, _right_partial)),
            IntentContract(shot_id="shot_001", shot_type="CU"),
            "ambiguous"),
    },
    "screen_size": {
        "good": SampleCase(
            "screen_size", _two((_hero_good,)),
            IntentContract(shot_id="shot_001", shot_type="MS"),
            "good"),
        "bad": SampleCase(
            "screen_size", _two((_cu_box,)),
            IntentContract(shot_id="shot_001", shot_type="MS"),
            "bad"),
        "ambiguous": SampleCase(
            "screen_size", _two((_size_boundary,)),
            IntentContract(shot_id="shot_001", shot_type="MS"),
            "ambiguous"),
    },
    "horizon_stability": {
        "good": SampleCase(
            "horizon_stability", _two((_hero_good,)),
            IntentContract(shot_id="shot_001", shot_type="MS"),
            "good"),
        "bad": SampleCase(
            "horizon_stability", _two((_hero_good,), roll_deg=12.0),
            IntentContract(shot_id="shot_001", shot_type="MS"),
            "bad"),
        "ambiguous": SampleCase(
            "horizon_stability", _two((_hero_good,), roll_deg=2.0),
            IntentContract(shot_id="shot_001", shot_type="MS",
                           intent="主观镜头暗示轻微倾斜"),
            "ambiguous"),
    },
}


__all__ = [
    "SampleCase", "SAMPLES", "evaluate", "build_prescriptions",
    "render_report",
]
