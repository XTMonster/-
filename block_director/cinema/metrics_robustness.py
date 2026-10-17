"""空间尺 10 · 鲁棒性与工程层 5 指标（Ticket 10）。

指标（阈值以 metric_registry.py 注册表为真源，本模块照抄口径）：
* pose_robustness   —— 姿态微扰后仍通过的核心指标比例，目标 ≥ 0.90；
* camera_robustness —— 相机采样误差/轨迹插值后的核心指标，目标 ≥ 0.90；
* label_safe_area   —— 关键视觉信息被覆盖比例，目标 = 0；
* visibility_stability —— 出画/遮挡帧占比，目标 ≤ 0.10；
* repair_locality   —— 非目标镜头破坏数，目标 = 0（联动 H6）。

本模块为纯层实现（不 import bpy）：微扰 harness 固定种子、只读采样，
用 dataclasses.replace 重建镜头副本重跑几何层核心指标，不改动任何既有
pass/fail 输出；处方方向只给方向与预期影响，不泄漏工具名/参数。
"""
from __future__ import annotations

import random
from dataclasses import dataclass, replace
from typing import Dict, List, Optional, Sequence, Set, Tuple

from ..contracts.tools import ACTION_TOOLS
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
from .metrics_geometry import evaluate as geometry_evaluate
from .metric_registry import METRICS_BY_NAME
from .prescription import validate_prescription


# --------------------------------------------------------------------------- #
# 阈值与常量（注册表口径）
# --------------------------------------------------------------------------- #
PERTURB_SEED = 20261017
POSE_JITTER = 0.02            # 姿态微扰：包围盒四边 ±0.02（NDC）
CAMERA_POS_NOISE = 0.05       # 相机位置噪声（NDC，三分量 ±0.05）
CAMERA_LENS_NOISE = 2.0       # 镜头焦距噪声（mm，±2.0）
CAMERA_STRIDE = 2             # 相机“实测”帧采样步长
CAMERA_PROJ_SCALE = 0.5       # 平移重投影系数
POSE_TARGET = 0.90
CAMERA_TARGET = 0.90
VISIBILITY_TARGET = 0.10
LABEL_PREFIX = "label_"

#: 微扰 harness 计数的几何层核心指标（样本盒只触发这三项）。
CORE_METRICS = ("edge_clearance", "screen_size", "horizon_stability")

#: 处方方向与预期影响（只给方向，不含工具名/参数；与注册表 repair_direction 同源）。
#: 污染词红线：direction/expected_effect 均不得出现工具名或“tool”。
_REPAIR: Dict[str, Tuple[str, Tuple[str, ...], Tuple[str, ...]]] = {
    "pose_robustness": (
        "加入姿态扰动回归样例并固定采样点，让核心测量不再对采样误差敏感",
        ("pose_robustness",),
        ("move_character", "reframe"),
    ),
    "camera_robustness": (
        "加密路径采样并平滑相机轨迹，让插值误差不再翻转构图测量",
        ("camera_robustness",),
        ("setup_camera", "move_camera"),
    ),
    "label_safe_area": (
        "调整标签布局并加入避让校验，让标签与网格不再压住关键视觉信息",
        ("label_safe_area",),
        ("place_character", "move_character", "setup_camera"),
    ),
    "visibility_stability": (
        "让主体绕开遮挡区并让机位提前跟随，稳定内容关键帧与动作关键帧的可见性",
        ("visibility_stability",),
        ("move_character", "move_camera"),
    ),
    "repair_locality": (
        "改用单镜修复并先记录基线，修复只作用于目标镜头且产出差异报告",
        ("repair_locality",),
        ("move_character", "move_camera", "reframe"),
    ),
}


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _warning(component: str, message: str,
             evidence: Tuple[int, ...]) -> Finding:
    """软失败项：WARNING + 「需人工复核」结尾，不产处方。"""
    return Finding(
        component=component,
        severity=Severity.WARNING,
        message=f"{message}，需人工复核",
        evidence_frames=evidence,
    )


def _measure(metric: str, raw: float, score: float,
             target: TargetInterval, evidence: Tuple[int, ...],
             confidence: float = 1.0) -> Measurement:
    return Measurement(
        metric=metric,
        raw_value=round(float(raw), 6),
        score=round(float(score), 6),
        target=target,
        evidence_frames=evidence,
        confidence=round(float(confidence), 6),
        evidence_grade="production",
    )


# --------------------------------------------------------------------------- #
# 微扰 harness（固定种子、只读采样）
# --------------------------------------------------------------------------- #
def _subject_boxes(shot: ShotSample, frame: FrameSample) -> List[SubjectBox]:
    """帧内全部主体的投影盒（跳过标签覆盖层主体）。"""
    out: List[SubjectBox] = []
    for item in frame.subjects:
        if item.subject_id.startswith(LABEL_PREFIX):
            continue
        out.append(item.box)
    return out


def _rebuild_shot(shot: ShotSample,
                  boxes_by_frame: Dict[int, List[SubjectBox]],
                  cameras_by_frame: Optional[Dict[int, FrameSample]] = None
                  ) -> ShotSample:
    """按帧重建镜头：替换投影盒，可选替换相机读数，其余字段原样保留。"""
    def rebuild(item: ProjectedSubject, box: SubjectBox) -> ProjectedSubject:
        return replace(item, box=box)

    def frame(n: int) -> FrameSample:
        original = next(f for f in shot.frames if f.frame == n)
        boxes = boxes_by_frame.get(n, _subject_boxes(shot, original))
        subjects = []
        index = 0
        for item in original.subjects:
            if item.subject_id.startswith(LABEL_PREFIX):
                subjects.append(item)
            else:
                subjects.append(rebuild(item, boxes[index]))
                index += 1
        base = replace(original, subjects=tuple(subjects))
        if cameras_by_frame is not None and n in cameras_by_frame:
            cam = cameras_by_frame[n]
            base = replace(base, camera_position=cam.camera_position,
                           lens=cam.lens, vfov_deg=cam.vfov_deg)
        return base

    content = ContentFrame(
        shot_id=shot.shot_id,
        frame_range=shot.frame_range,
        frames=tuple(frame(f.frame) for f in shot.content.frames),
    )
    actions: List[ActionFrame] = []
    for action in shot.actions:
        actions.append(ActionFrame(
            shot_id=action.shot_id,
            start=frame(action.start.frame),
            contacts=tuple(frame(f.frame) for f in action.contacts),
            reaction_end=frame(action.reaction_end.frame),
        ))
    return replace(shot, content=content, actions=tuple(actions))


def _geometry_outcome(shot: ShotSample, intent: Optional[IntentContract]
                      ) -> Tuple[Dict[str, bool], Dict[str, float], int]:
    """几何核心指标读数：metric -> 是否落在目标区间、原始值、测量总数。"""
    out = geometry_evaluate(shot, intent)
    passing: Dict[str, bool] = {}
    raw: Dict[str, float] = {}
    frames: Set[int] = set()
    for m in out.measurements:
        if m.metric not in CORE_METRICS:
            continue
        passing[m.metric] = bool(m.target.contains(m.raw_value))
        raw[m.metric] = m.raw_value
        frames.update(m.evidence_frames)
    return passing, raw, len(out.measurements)


def pose_perturb_harness(shot: ShotSample,
                         intent: Optional[IntentContract],
                         seed: int = PERTURB_SEED
                         ) -> Tuple[float, Tuple[str, ...], Tuple[int, ...]]:
    """姿态微扰 harness：每帧每主体四边各加 uniform(-jitter, jitter)。

    返回 (通过比例, 翻转指标名, 采样帧并集)。固定种子、只读采样；
    覆盖内容关键帧与动作关键帧的并集。
    """
    rng = random.Random(seed)
    baseline, _, _ = _geometry_outcome(shot, intent)
    sampled: Set[int] = set()
    boxes_by_frame: Dict[int, List[SubjectBox]] = {}
    for frame in shot.frames:
        boxes = []
        for box in _subject_boxes(shot, frame):
            boxes.append(SubjectBox(
                name=box.name,
                left=box.left + rng.uniform(-POSE_JITTER, POSE_JITTER),
                right=box.right + rng.uniform(-POSE_JITTER, POSE_JITTER),
                top=box.top + rng.uniform(-POSE_JITTER, POSE_JITTER),
                bottom=box.bottom + rng.uniform(-POSE_JITTER, POSE_JITTER),
                facing=box.facing,
            ))
        boxes_by_frame[frame.frame] = boxes
        sampled.add(frame.frame)
    rebuilt = _rebuild_shot(shot, boxes_by_frame)
    passing, _, _ = _geometry_outcome(rebuilt, intent)
    flipped = tuple(sorted(
        m for m in baseline if baseline[m] and not passing[m]))
    total = len(passing)
    passed = sum(1 for ok in passing.values() if ok)
    ratio = _clamp01(passed / total) if total else 0.0
    return ratio, flipped, tuple(sorted(sampled))


def camera_perturb_harness(shot: ShotSample,
                           intent: Optional[IntentContract],
                           seed: int = PERTURB_SEED
                           ) -> Tuple[float, Tuple[str, ...], Tuple[int, ...]]:
    """相机微扰 harness：按 stride 采样“实测”帧，其余帧线性插值。

    位置/焦距加噪声后按针孔模型重投影包围盒；只读采样、固定种子。
    返回 (通过比例, 翻转指标名, 采样帧并集)。
    """
    rng = random.Random(seed)
    baseline, _, _ = _geometry_outcome(shot, intent)
    frames = tuple(shot.frames)
    measured_idx = tuple(range(0, len(frames), CAMERA_STRIDE))
    measured: Dict[int, Tuple[float, float, float, float, float]] = {}
    for index in measured_idx:
        frame = frames[index]
        cam_x, cam_y, cam_z = frame.camera_position
        measured[index] = (
            cam_x + rng.uniform(-CAMERA_POS_NOISE, CAMERA_POS_NOISE),
            cam_y + rng.uniform(-CAMERA_POS_NOISE, CAMERA_POS_NOISE),
            cam_z + rng.uniform(-CAMERA_POS_NOISE, CAMERA_POS_NOISE),
            frame.lens + rng.uniform(-CAMERA_LENS_NOISE, CAMERA_LENS_NOISE),
            frame.vfov_deg,
        )

    def interp(a: Tuple[float, ...], b: Tuple[float, ...],
               t: float) -> Tuple[float, ...]:
        return tuple(a[i] + (b[i] - a[i]) * t for i in range(len(a)))

    def camera_for(index: int) -> Tuple[float, float, float, float, float]:
        lo, hi = measured_idx[0], measured_idx[-1]
        for i in range(len(measured_idx) - 1):
            if measured_idx[i] <= index <= measured_idx[i + 1]:
                lo, hi = measured_idx[i], measured_idx[i + 1]
                break
        if lo == hi:
            return measured[lo]
        t = (index - lo) / (hi - lo)
        return tuple(interp(measured[lo], measured[hi], t))  # type: ignore

    boxes_by_frame: Dict[int, List[SubjectBox]] = {}
    cameras_by_frame: Dict[int, FrameSample] = {}
    sampled: Set[int] = set()
    for index, frame in enumerate(frames):
        cam_x, cam_y, cam_z, lens, _ = camera_for(index)
        k = lens / 35.0
        shift_x = -cam_x * CAMERA_PROJ_SCALE
        shift_y = -cam_y * CAMERA_PROJ_SCALE
        boxes = []
        for box in _subject_boxes(shot, frame):
            boxes.append(SubjectBox(
                name=box.name,
                left=0.5 + (box.left - 0.5) * k - shift_x,
                right=0.5 + (box.right - 0.5) * k - shift_x,
                top=0.5 + (box.top - 0.5) * k - shift_y,
                bottom=0.5 + (box.bottom - 0.5) * k - shift_y,
                facing=box.facing,
            ))
        boxes_by_frame[frame.frame] = boxes
        cameras_by_frame[frame.frame] = replace(
            frame,
            camera_position=(cam_x, cam_y, cam_z),
            lens=lens,
        )
        sampled.add(frame.frame)
    rebuilt = _rebuild_shot(shot, boxes_by_frame, cameras_by_frame)
    passing, _, _ = _geometry_outcome(rebuilt, intent)
    flipped = tuple(sorted(
        m for m in baseline if baseline[m] and not passing[m]))
    total = len(passing)
    passed = sum(1 for ok in passing.values() if ok)
    ratio = _clamp01(passed / total) if total else 0.0
    return ratio, flipped, tuple(sorted(sampled))


# --------------------------------------------------------------------------- #
# 指标 worker：返回 (measurements, findings)
# --------------------------------------------------------------------------- #
def _covered_ratio(label_box: SubjectBox, subject_box: SubjectBox) -> float:
    """标签盒对被覆盖主体盒的覆盖比例：重叠面积 / 被覆盖主体面积。"""
    x_overlap = max(0.0, min(label_box.right, subject_box.right)
                    - max(label_box.left, subject_box.left))
    y_overlap = max(0.0, min(label_box.top, subject_box.top)
                    - max(label_box.bottom, subject_box.bottom))
    overlap_area = x_overlap * y_overlap
    subject_area = max(subject_box.width, 1e-9) * max(subject_box.height, 1e-9)
    return _clamp01(overlap_area / subject_area)


def _pose_robustness(
    shot: ShotSample, intent: Optional[IntentContract]
) -> Tuple[Tuple[Measurement, ...], Tuple[Finding, ...]]:
    ratio, flipped, sampled = pose_perturb_harness(shot, intent)
    target = TargetInterval(min_value=POSE_TARGET)
    if ratio >= POSE_TARGET and not flipped:
        measurement = _measure(
            "pose_robustness", ratio, ratio, target, sampled, 1.0)
        return (measurement,), ()
    if ratio < POSE_TARGET and len(flipped) >= 2:
        finding = Finding(
            component="pose_robustness",
            severity=Severity.ERROR,
            message=(
                f"姿态微扰后核心构图指标通过率 {ratio:.3f} 低于目标 "
                f"{POSE_TARGET:.2f}（固定种子 {PERTURB_SEED}、扰动幅度 "
                f"±{POSE_JITTER:.3f}），翻转指标 {flipped}，构图判定对姿态采样误差敏感"
            ),
            evidence_frames=sampled,
        )
        measurement = _measure(
            "pose_robustness", ratio, ratio, target, sampled, 1.0)
        return (measurement,), (finding,)
    if ratio >= POSE_TARGET:
        reason = (f"姿态微扰后整体通过率达标但核心指标 {flipped} 发生翻转，"
                  f"扰动敏感度判定两可")
    else:
        reason = (f"姿态微扰后通过率 {ratio:.3f} 略低于目标 {POSE_TARGET:.2f}"
                  f"且翻转指标 {flipped} 不足两个，是否构成系统性采样敏感两可")
    finding = _warning("pose_robustness", reason, sampled)
    measurement = _measure(
        "pose_robustness", ratio, ratio, target, sampled, 0.5)
    return (measurement,), (finding,)


def _camera_robustness(
    shot: ShotSample, intent: Optional[IntentContract]
) -> Tuple[Tuple[Measurement, ...], Tuple[Finding, ...]]:
    ratio, flipped, sampled = camera_perturb_harness(shot, intent)
    target = TargetInterval(min_value=CAMERA_TARGET)
    if ratio >= CAMERA_TARGET and not flipped:
        measurement = _measure(
            "camera_robustness", ratio, ratio, target, sampled, 1.0)
        return (measurement,), ()
    if ratio < CAMERA_TARGET and len(flipped) >= 2:
        finding = Finding(
            component="camera_robustness",
            severity=Severity.ERROR,
            message=(
                f"相机采样误差后核心构图指标通过率 {ratio:.3f} 低于目标 "
                f"{CAMERA_TARGET:.2f}（固定种子 {PERTURB_SEED}、扰动幅度："
                f"位置 ±{CAMERA_POS_NOISE:.2f}、焦距 ±{CAMERA_LENS_NOISE:.1f}mm），"
                f"翻转指标 {flipped}，插值误差翻转构图测量"
            ),
            evidence_frames=sampled,
        )
        measurement = _measure(
            "camera_robustness", ratio, ratio, target, sampled, 1.0)
        return (measurement,), (finding,)
    if ratio >= CAMERA_TARGET:
        reason = (f"相机采样误差后整体通过率达标但核心指标 {flipped} 发生翻转，"
                  f"插值敏感度判定两可")
    else:
        reason = (f"相机采样误差后通过率 {ratio:.3f} 略低于目标 "
                  f"{CAMERA_TARGET:.2f}且翻转指标 {flipped} 不足两个，"
                  f"是否构成系统性插值误差两可")
    finding = _warning("camera_robustness", reason, sampled)
    measurement = _measure(
        "camera_robustness", ratio, ratio, target, sampled, 0.5)
    return (measurement,), (finding,)


def _label_safe_area(
    shot: ShotSample,
) -> Tuple[Tuple[Measurement, ...], Tuple[Finding, ...]]:
    """标签/网格避让：覆盖角色 FATAL，仅覆盖次要道具 WARNING 两可。"""
    all_frames = tuple(f.frame for f in shot.frames)
    covered_char: List[int] = []
    covered_prop: List[int] = []
    worst = 0.0
    for frame in shot.frames:
        labels = [s for s in frame.subjects
                  if s.subject_id.startswith(LABEL_PREFIX)]
        if not labels:
            continue
        for label in labels:
            for subject in frame.subjects:
                if subject.subject_id.startswith(LABEL_PREFIX):
                    continue
                ratio = _covered_ratio(label.box, subject.box)
                if ratio <= 0.0:
                    continue
                worst = max(worst, ratio)
                if subject.kind == "character":
                    covered_char.append(frame.frame)
                else:
                    covered_prop.append(frame.frame)
    raw = round(worst, 6)
    score = round(1.0 - raw, 6)
    target = TargetInterval(max_value=0.0)
    if not covered_char and not covered_prop:
        measurement = _measure(
            "label_safe_area", 0.0, 1.0, target, all_frames, 1.0)
        return (measurement,), ()
    if covered_char:
        finding = Finding(
            component="label_safe_area",
            severity=Severity.FATAL,
            message=(
                f"标签/网格压住关键视觉信息（覆盖比例 {raw:.3f}，覆盖角色帧 "
                f"{sorted(set(covered_char))}），主体可读性受损"
            ),
            evidence_frames=tuple(sorted(set(covered_char + covered_prop))),
        )
        measurement = _measure(
            "label_safe_area", raw, score, target, all_frames, 1.0)
        return (measurement,), (finding,)
    finding = _warning(
        "label_safe_area",
        f"标签/网格压住次要信息（覆盖比例 {raw:.3f}，覆盖道具帧 "
        f"{sorted(set(covered_prop))}），是否遮挡关键信息两可",
        tuple(sorted(set(covered_prop))),
    )
    measurement = _measure(
        "label_safe_area", raw, score, target, all_frames, 0.5)
    return (measurement,), (finding,)


def _visibility_stability(
    shot: ShotSample,
) -> Tuple[Tuple[Measurement, ...], Tuple[Finding, ...]]:
    """出画/遮挡稳定性：反复出画 FATAL，单帧触动作 WARNING 两可。"""
    action_frames: Set[int] = set()
    for action in shot.actions:
        action_frames.add(action.start.frame)
        action_frames.update(f.frame for f in action.contacts)
        action_frames.add(action.reaction_end.frame)
    all_frames = tuple(f.frame for f in shot.frames)
    bad_frames: List[int] = []
    for frame in shot.frames:
        chars = [s for s in frame.subjects if s.kind == "character"]
        primary = max(chars, key=lambda s: s.box.height) if chars else None
        if primary is None:
            bad_frames.append(frame.frame)
        elif (primary.visible_ratio < 0.70
              or primary.box.inside_ratio() <= 0.0):
            bad_frames.append(frame.frame)
    raw = round(len(bad_frames) / len(all_frames), 6) if all_frames else 0.0
    score = round(1.0 - raw, 6)
    target = TargetInterval(max_value=VISIBILITY_TARGET)
    if raw <= VISIBILITY_TARGET:
        measurement = _measure(
            "visibility_stability", raw, score, target, all_frames, 1.0)
        return (measurement,), ()
    if len(bad_frames) >= 2:
        finding = Finding(
            component="visibility_stability",
            severity=Severity.FATAL,
            message=(
                f"主体在内容关键帧与动作关键帧反复出画/被遮挡（出画帧 "
                f"{sorted(set(bad_frames))}，占比 {raw:.3f}），动作可辨性受损"
            ),
            evidence_frames=tuple(sorted(set(bad_frames))),
        )
        measurement = _measure(
            "visibility_stability", raw, score, target, all_frames, 1.0)
        return (measurement,), (finding,)
    bad = bad_frames[0]
    if bad in action_frames:
        finding = _warning(
            "visibility_stability",
            f"主体仅在动作关键帧 {bad} 单帧出画/被遮挡，是否刻意留白两可",
            (bad,),
        )
        measurement = _measure(
            "visibility_stability", raw, score, target, all_frames, 0.5)
        return (measurement,), (finding,)
    finding = Finding(
        component="visibility_stability",
        severity=Severity.ERROR,
        message=(
            f"主体在非动作帧 {bad} 单帧出画/被遮挡，存在采样抖动"
        ),
        evidence_frames=(bad,),
    )
    measurement = _measure(
        "visibility_stability", raw, score, target, all_frames, 1.0)
    return (measurement,), (finding,)


def _repair_locality(
    sample: SequenceSample, intent: Optional[IntentContract]
) -> Tuple[Tuple[Measurement, ...], Tuple[Finding, ...]]:
    """修复局部性：非目标镜头出现几何失败项即破坏邻镜（联动 H6）。"""
    shots = sample.shots
    target_id = (intent.shot_id if intent is not None and intent.shot_id
                 else shots[0].shot_id)
    target_ids = {s.shot_id for s in shots if s.shot_id == target_id}
    non_target = [s for s in shots if s.shot_id not in target_ids]
    evidence: Set[int] = set()
    hard: List[str] = []
    soft: List[str] = []
    for shot in non_target:
        outcome = geometry_evaluate(shot, intent)
        evidence.update(f.frame for f in shot.frames)
        if any(f.severity in (Severity.FATAL, Severity.ERROR)
               for f in outcome.findings):
            hard.append(shot.shot_id)
        elif any(f.severity == Severity.WARNING
                 for f in outcome.findings):
            soft.append(shot.shot_id)
    ev = tuple(sorted(evidence))
    target = TargetInterval(max_value=0.0)
    raw = round(float(len(hard) + len(soft)), 6)
    denominator = max(len(non_target), 1)
    score = round(_clamp01(1.0 - (len(hard) + len(soft)) / denominator), 6)
    if not hard and not soft:
        measurement = _measure(
            "repair_locality", 0.0, 1.0, target, ev, 1.0)
        return (measurement,), ()
    if hard:
        finding = Finding(
            component="repair_locality",
            severity=Severity.FATAL,
            message=(
                f"修复动作破坏非目标镜头（受影响镜头 {sorted(set(hard))}，"
                f"共 {len(hard) + len(soft)} 镜），未记录基线或未限定修复范围"
            ),
            evidence_frames=ev,
            gate="H6",
        )
        measurement = _measure(
            "repair_locality", raw, score, target, ev, 1.0)
        return (measurement,), (finding,)
    finding = _warning(
        "repair_locality",
        f"非目标镜头 {sorted(set(soft))} 出现软性读数漂移，修复是否局部两可",
        ev,
    )
    measurement = _measure(
        "repair_locality", raw, score, target, ev, 0.5)
    return (measurement,), (finding,)


# --------------------------------------------------------------------------- #
# 公共接缝：evaluate / build_prescriptions / render_report
# --------------------------------------------------------------------------- #
def evaluate(sample: object,
             intent: Optional[IntentContract] = None) -> EvaluationOutput:
    """按采样粒度分派本层指标；几何层 finding 不向上传播。"""
    if isinstance(sample, SequenceSample):
        measurements, findings = _repair_locality(sample, intent)
        shot_id = sample.shots[0].shot_id
    elif isinstance(sample, ShotSample):
        has_label = any(
            s.subject_id.startswith(LABEL_PREFIX)
            for frame in sample.frames for s in frame.subjects)
        if has_label:
            measurements, findings = _label_safe_area(sample)
        else:
            pose_m, pose_f = _pose_robustness(sample, intent)
            camera_m, camera_f = _camera_robustness(sample, intent)
            vis_m, vis_f = _visibility_stability(sample)
            measurements = pose_m + camera_m + vis_m
            findings = pose_f + camera_f + vis_f
        shot_id = sample.shot_id
    else:
        raise TypeError(
            f"鲁棒性层只接受 ShotSample/SequenceSample：{type(sample)!r}")
    return EvaluationOutput(
        shot_id=shot_id,
        measurements=tuple(measurements),
        findings=tuple(findings),
        intent=intent,
    )


def build_prescriptions(output: EvaluationOutput) -> Tuple[Prescription, ...]:
    """只对失败分量（fatal/error）产处方；通过/两可不产。"""
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
    """渲染 LLM 可读读数；只含数值、方向与扰动参数，过 detect_pollution。"""
    lines = [f"镜头 {output.shot_id} 鲁棒性与工程层读数："]
    lines.append(
        f"- 扰动参数：固定种子 {PERTURB_SEED}，扰动幅度——姿态 ±{POSE_JITTER:.2f} "
        f"NDC、相机位置 ±{CAMERA_POS_NOISE:.2f} NDC、焦距 ±{CAMERA_LENS_NOISE:.1f} mm")
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


# --------------------------------------------------------------------------- #
# 三态样例（TDD 冻结）
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SampleCase:
    """一个三态样例：镜头采样/序列采样 + 意图 + 预期结论。"""

    name: str
    sample: object
    intent: Optional[IntentContract]
    expected: str


def _subject_box(subject_id: str, left: float, right: float, top: float,
                 bottom: float) -> SubjectBox:
    return SubjectBox(name=subject_id, left=left, right=right, top=top,
                      bottom=bottom, facing=1.0)


def _projected(subject_id: str, box: SubjectBox,
               kind: str = "character",
               visible_ratio: float = 1.0) -> ProjectedSubject:
    return ProjectedSubject(subject_id=subject_id, kind=kind, box=box,
                            visible_ratio=visible_ratio)


def _hero_box(left: float, right: float, top: float,
              bottom: float) -> ProjectedSubject:
    return _projected("hero", _subject_box("hero", left, right, top, bottom))


def _shot_11(subjects_by_frame: Dict[int, Tuple[ProjectedSubject, ...]],
             shot_id: str = "shot_001") -> ShotSample:
    """5 帧采样：内容关键帧 1/6/11，动作关键帧 3→6→9（帧 6 并集共用）。"""
    def frame(n: int) -> FrameSample:
        return FrameSample(frame=n, shot_id=shot_id,
                           subjects=subjects_by_frame.get(n, ()))

    content = ContentFrame(shot_id=shot_id, frame_range=(1, 11),
                           frames=(frame(1), frame(6), frame(11)))
    action = ActionFrame(shot_id=shot_id, start=frame(3),
                         contacts=(frame(6),), reaction_end=frame(9))
    return ShotSample(shot_id=shot_id, frame_range=(1, 11),
                      content=content, actions=(action,))


def _shot_5(subjects_by_frame: Dict[int, Tuple[ProjectedSubject, ...]],
            shot_id: str = "shot_001",
            frame_range: Tuple[int, int] = (1, 5)) -> ShotSample:
    """3 帧采样：内容关键帧 1/3/5，无动作。"""
    def frame(n: int) -> FrameSample:
        return FrameSample(frame=n, shot_id=shot_id,
                           subjects=subjects_by_frame.get(n, ()))

    first, last = frame_range
    middle = (first + last) // 2
    content = ContentFrame(shot_id=shot_id, frame_range=frame_range,
                           frames=(frame(first), frame(middle), frame(last)))
    return ShotSample(shot_id=shot_id, frame_range=frame_range,
                      content=content)


def _all_hero(shot: ShotSample, left: float, right: float, top: float,
              bottom: float, visible: Optional[float] = None
              ) -> Dict[int, Tuple[ProjectedSubject, ...]]:
    """把镜头全部采样帧换成同一 hero 盒（可选覆盖可见比例）。"""
    ratio = 1.0 if visible is None else visible
    subject = _hero_box(left, right, top, bottom) if visible is None else \
        _projected("hero", _subject_box("hero", left, right, top, bottom),
                   visible_ratio=ratio)
    return {f.frame: (subject,) for f in shot.frames}


_MS = IntentContract(shot_id="shot_001", shot_type="MS")

#: pose / camera / visibility 共用 5 帧结构（内容 1/6/11，动作 3/6/9）。
_pose_good = _shot_11(_all_hero(_shot_11({}), 0.15, 0.58, 0.93, 0.50))
_pose_bad = _shot_11(_all_hero(_shot_11({}), 0.04, 0.40, 0.93, 0.5475))
_pose_ambiguous = _shot_11(
    _all_hero(_shot_11({}), 0.15, 0.58, 0.93, 0.5475))
_camera_good = _shot_11(_all_hero(_shot_11({}), 0.15, 0.58, 0.90, 0.47))
_camera_bad = _shot_11(
    _all_hero(_shot_11({}), 0.0401, 0.40, 0.90, 0.5175))
_camera_ambiguous = _shot_11(
    _all_hero(_shot_11({}), 0.15, 0.58, 0.90, 0.5175))

_vis_good = _shot_11(_all_hero(_shot_11({}), 0.15, 0.58, 0.93, 0.50))
_vis_bad_frames = _all_hero(_shot_11({}), 0.15, 0.58, 0.93, 0.50)
_vis_bad_frames[1] = (_projected(
    "hero", _subject_box("hero", 0.15, 0.58, 0.93, 0.50),
    visible_ratio=0.4),)
_vis_bad_frames[6] = (_projected(
    "hero", _subject_box("hero", 0.15, 0.58, 0.93, 0.50),
    visible_ratio=0.4),)
_vis_bad_frames[9] = (_projected(
    "hero", _subject_box("hero", 0.15, 0.58, 0.93, 0.50),
    visible_ratio=0.4),)
_vis_bad = _shot_11(_vis_bad_frames)
_vis_amb_frames = _all_hero(_shot_11({}), 0.15, 0.58, 0.93, 0.50)
_vis_amb_frames[6] = (_projected(
    "hero", _subject_box("hero", 0.15, 0.58, 0.93, 0.50),
    visible_ratio=0.0),)
_vis_ambiguous = _shot_11(_vis_amb_frames)

#: label 三态（3 帧，无动作；label 覆盖层主体走 label_ 前缀）。
_label_good_frames = {
    n: (_hero_box(0.20, 0.60, 0.90, 0.40),
        _projected("label_hero", _subject_box(
            "label_hero", 0.70, 0.95, 0.98, 0.75), kind="prop"))
    for n in (1, 3, 5)
}
_label_bad_frames = {
    n: (_hero_box(0.20, 0.60, 0.90, 0.40),
        _projected("label_hero", _subject_box(
            "label_hero", 0.10, 0.70, 1.00, 0.30), kind="prop"))
    for n in (1, 3, 5)
}
_label_amb_frames = {
    n: (_projected("table", _subject_box(
        "table", 0.05, 0.25, 0.45, 0.25), kind="prop"),
        _projected("label_table", _subject_box(
            "label_table", 0.15, 0.35, 0.55, 0.35), kind="prop"))
    for n in (1, 3, 5)
}


def _repair_sample(shot_002_hero: ProjectedSubject) -> SequenceSample:
    shot_001 = _shot_5(
        {n: (_hero_box(0.10, 0.35, 0.95, 0.50),) for n in (1, 3, 5)},
        shot_id="shot_001")
    shot_002 = _shot_5(
        {n: (shot_002_hero,) for n in (6, 8, 10)},
        shot_id="shot_002", frame_range=(6, 10))
    return SequenceSample(shots=(shot_001, shot_002))


_repair_good_hero = _hero_box(0.10, 0.35, 0.95, 0.50)
_repair_bad_hero = _hero_box(-0.30, -0.10, 0.95, 0.50)
_repair_amb_hero = _hero_box(0.04, 0.34, 0.93, 0.48)

SAMPLES: Dict[str, Dict[str, SampleCase]] = {
    "pose_robustness": {
        "good": SampleCase("pose_robustness", _pose_good, _MS, "good"),
        "bad": SampleCase("pose_robustness", _pose_bad, _MS, "bad"),
        "ambiguous": SampleCase(
            "pose_robustness", _pose_ambiguous, _MS, "ambiguous"),
    },
    "camera_robustness": {
        "good": SampleCase("camera_robustness", _camera_good, _MS, "good"),
        "bad": SampleCase("camera_robustness", _camera_bad, _MS, "bad"),
        "ambiguous": SampleCase(
            "camera_robustness", _camera_ambiguous, _MS, "ambiguous"),
    },
    "label_safe_area": {
        "good": SampleCase("label_safe_area", _shot_5(_label_good_frames),
                           _MS, "good"),
        "bad": SampleCase("label_safe_area", _shot_5(_label_bad_frames),
                          _MS, "bad"),
        "ambiguous": SampleCase("label_safe_area", _shot_5(_label_amb_frames),
                                _MS, "ambiguous"),
    },
    "visibility_stability": {
        "good": SampleCase("visibility_stability", _vis_good, _MS, "good"),
        "bad": SampleCase("visibility_stability", _vis_bad, _MS, "bad"),
        "ambiguous": SampleCase(
            "visibility_stability", _vis_ambiguous, _MS, "ambiguous"),
    },
    "repair_locality": {
        "good": SampleCase(
            "repair_locality", _repair_sample(_repair_good_hero), _MS, "good"),
        "bad": SampleCase(
            "repair_locality", _repair_sample(_repair_bad_hero), _MS, "bad"),
        "ambiguous": SampleCase(
            "repair_locality", _repair_sample(_repair_amb_hero), _MS,
            "ambiguous"),
    },
}


__all__ = [
    "PERTURB_SEED", "SAMPLES", "build_prescriptions", "camera_perturb_harness",
    "evaluate", "pose_perturb_harness", "render_report",
]
