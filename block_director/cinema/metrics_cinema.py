"""空间尺 09 · 摄影意图层 5 指标（Ticket 09）。

指标（阈值以 metric_registry.py 注册表为真源，本模块照抄口径）：
* perspective_fit        —— 透视特征（焦距带 + 主体尺度）与声明景别的一致性；
* camera_path_clearance  —— 相机运动路径与主体/障碍的安全间距（H5 联动）；
* reveal_progression     —— 画面信息面积随内容关键帧逐步揭示的进程；
* movement_intent_match  —— 实际运镜轨迹与声明运镜的贴合度（复用
  camera_motion.movement_samples 的展开口径，不另写运镜几何）；
* spatial_orientation    —— 关键空间参照物（地标/门/道具）在内容关键帧中的
  持续可辨性。

本模块为纯层实现（不 import bpy）。输入是 evaluation_protocol 的采样对象，
样例均为 demo 输入（evidence_grade="demo"），输出统一 Measurement /
Finding / Prescription / EvaluationOutput。处方只给方向与预期影响，不含
工具名/参数（render_report 输出必须通过 detect_pollution）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from ..contracts.enums import MOVEMENT_TYPES
from ..contracts.tools import ACTION_TOOLS
from .camera_motion import (
    DEFAULT_AMOUNTS,
    DOLLY_ZOOMS,
    HANDHELD,
    ORBITS,
    ROTATIONS,
    SUBJECT_TRACKING,
    TRANSLATIONS,
    ZOOMS,
    movement_samples,
)
from .composition import SubjectBox
from .evaluation_protocol import (
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
from .metric_registry import METRICS_BY_NAME
from .prescription import validate_prescription


# --------------------------------------------------------------------------- #
# 阈值与常量（注册表口径）
# --------------------------------------------------------------------------- #
#: perspective_fit 目标下限（0-1 组合分）。
PERSPECTIVE_TARGET = 0.80

#: camera_path_clearance 安全间距（米）与分级。
PATH_CLEARANCE_MIN = 0.20
PATH_CLEARANCE_TIGHT = 0.35
PATH_BOUNDARY_EPS = 0.002

#: reveal_progression 揭示进程目标下限（0-1）。
REVEAL_TARGET = 0.80

#: movement_intent_match 目标下限（0-1 贴合度）。
INTENT_MATCH_TARGET = 0.80

#: spatial_orientation 目标下限（可见帧占比）。
ORIENTATION_TARGET = 0.80

#: 焦距带（mm）：wide / normal / tele（左闭右开，超界按最接近带处理）。
LENS_BANDS = ((18.0, 28.0), (28.0, 50.0), (50.0, 135.0))

#: 声明景别 -> 期望焦距带（band 0=wide / 1=normal / 2=tele）。
SHOT_TYPE_BAND: Dict[str, int] = {
    "CU": 2,
    "MS": 1,
    "WS": 0,
}

#: 声明景别 -> (期望主体高度区间, 区间中点)。
SHOT_TYPE_HEIGHT: Dict[str, Tuple[Tuple[float, float], float]] = {
    "CU": ((0.60, 1.00), 0.80),
    "MS": ((0.30, 0.60), 0.45),
    "WS": ((0.00, 0.30), 0.15),
}

#: 处方方向与预期影响（只给方向，不含工具名/参数；与注册表 repair_direction
#: 同源，render_report 渲染后必须通过 detect_pollution）。
_REPAIR: Dict[str, Tuple[str, Tuple[str, ...], Tuple[str, ...]]] = {
    "perspective_fit": (
        "修正机位距离与焦距选择：让透视特征回到与声明景别一致的区间",
        ("perspective_fit",),
        ("move_camera", "reframe"),
    ),
    "camera_path_clearance": (
        "抬高或外移相机路径：绕开主体与障碍物，保持安全间距",
        ("camera_path_clearance",),
        ("move_camera",),
    ),
    "reveal_progression": (
        "增加运镜逐步揭示：让新信息随内容关键帧持续进入画面",
        ("reveal_progression",),
        ("move_camera",),
    ),
    "movement_intent_match": (
        "按声明运镜重写实际轨迹：跟拍需要真正跟随主体移动，"
        "推拉保持同一方向持续推进",
        ("movement_intent_match",),
        ("move_camera",),
    ),
    "spatial_orientation": (
        "纳入地标并稳定朝向：让关键空间参照物在内容关键帧中持续可辨",
        ("spatial_orientation",),
        ("move_camera",),
    ),
}


# --------------------------------------------------------------------------- #
# 小工具（纯计算）
# --------------------------------------------------------------------------- #
Vector3 = Tuple[float, float, float]


def _length(v: Sequence[float]) -> float:
    return math.sqrt(sum(float(x) ** 2 for x in v))


def _normalize(v: Sequence[float]) -> Vector3:
    length = _length(v)
    if length < 1e-9:
        return (0.0, 0.0, 0.0)
    return (float(v[0]) / length, float(v[1]) / length,
            float(v[2]) / length)


def _cross(a: Sequence[float], b: Sequence[float]) -> Vector3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _distance(a: Sequence[float], b: Sequence[float]) -> float:
    return _length(tuple(float(x) - float(y) for x, y in zip(a, b)))


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _boundary(value: float, boundary: float, eps: float) -> bool:
    return abs(float(value) - boundary) <= eps


def _ambiguous_warning(component: str, boundary_desc: str,
                       evidence: Tuple[int, ...]) -> Finding:
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


def _project_world(frame: FrameSample, ndc_x: float, ndc_y: float,
                   depth: float = 3.0) -> Vector3:
    """把 NDC 坐标点投到世界系 depth 固定平面（demo 投影口径）。"""
    forward = _normalize(frame.camera_forward)
    right = _cross(forward, (0.0, 0.0, 1.0))
    if _length(right) < 1e-9:
        right = (1.0, 0.0, 0.0)
    else:
        right = _normalize(right)
    up = _cross(right, forward)
    half_span = depth * math.tan(math.radians(frame.vfov_deg) / 2.0)
    width = 2.0 * half_span * frame.aspect
    height = 2.0 * half_span
    return (
        frame.camera_position[0] + forward[0] * depth
        + right[0] * (ndc_x - 0.5) * width
        + up[0] * (ndc_y - 0.5) * height,
        frame.camera_position[1] + forward[1] * depth
        + right[1] * (ndc_x - 0.5) * width
        + up[1] * (ndc_y - 0.5) * height,
        frame.camera_position[2] + forward[2] * depth
        + right[2] * (ndc_x - 0.5) * width
        + up[2] * (ndc_y - 0.5) * height,
    )


def _lens_band(lens: float) -> int:
    """焦距带编号：0=wide / 1=normal / 2=tele。"""
    for index, (low, high) in enumerate(LENS_BANDS):
        if low <= float(lens) < high:
            return index
    value = float(lens)
    if value < LENS_BANDS[0][0]:
        return 0
    return len(LENS_BANDS) - 1


def _parse_movement(raw: str) -> Optional[Tuple[str, float]]:
    """解析 \"type\" 或 \"type:amount\"；非法/未知返回 None。"""
    text = str(raw or "").strip()
    if not text:
        return None
    if ":" in text:
        name, amount = text.split(":", 1)
        name = name.strip()
        try:
            amount = float(amount.strip())
        except ValueError:
            return None
    else:
        name, amount = text.strip(), 0.0
    if name not in MOVEMENT_TYPES:
        return None
    if amount == 0.0:
        amount = float(DEFAULT_AMOUNTS.get(name, 1.0))
    return name, amount


def _declared_movement(intent: Optional[IntentContract],
                       ) -> Optional[Tuple[str, float]]:
    if intent is None or not intent.camera_movements:
        return None
    return _parse_movement(intent.camera_movements[0])


def _declared_target(frame: FrameSample) -> Vector3:
    pos = tuple(float(v) for v in frame.camera_position)
    forward = _normalize(frame.camera_forward)
    return (pos[0] + forward[0] * 3.0, pos[1] + forward[1] * 3.0,
            pos[2] + forward[2] * 3.0)


# --------------------------------------------------------------------------- #
# 指标 worker：返回 (measurements, findings)
# --------------------------------------------------------------------------- #
def _perspective_fit(shot: ShotSample,
                     intent: Optional[IntentContract]) -> Tuple[
                         Tuple[Measurement, ...], Tuple[Finding, ...]]:
    declared = (intent.shot_type if intent is not None else "") or ""
    band_target = SHOT_TYPE_BAND.get(declared)
    height_spec = SHOT_TYPE_HEIGHT.get(declared, SHOT_TYPE_HEIGHT["MS"])
    height_mid = height_spec[1]
    unknown_shot_type = band_target is None
    band_target = SHOT_TYPE_BAND.get(declared, 1)

    frame_scores: list[float] = []
    evidence: list[int] = []
    for frame in shot.frames:
        lens = float(frame.lens)
        lens_match = 1.0 if unknown_shot_type else (
            1.0 - min(2.0, abs(_lens_band(lens) - band_target)) / 2.0)
        box = _primary_subject(frame)
        if box is None:
            continue
        height_match = 1.0 - min(1.0, abs(box.height - height_mid) / 0.5)
        frame_scores.append(0.5 * lens_match + 0.5 * height_match)
        evidence.append(frame.frame)
    if not frame_scores:
        return (), ()

    raw = round(min(frame_scores), 6)
    evidence_frames = tuple(sorted(set(evidence)))
    base_frame = shot.frames[0]
    box = _primary_subject(base_frame)
    special_wide_cu = (
        declared == "CU"
        and _lens_band(float(base_frame.lens)) == 0
        and box is not None
        and (box.left <= 0.12 or box.right >= 0.88)
    )
    ambiguous = (not special_wide_cu
                 and PERSPECTIVE_TARGET <= raw <= PERSPECTIVE_TARGET + 0.10)
    confidence = 0.5 if (special_wide_cu or ambiguous
                         or unknown_shot_type) else 1.0
    measurement = Measurement(
        metric="perspective_fit",
        raw_value=raw,
        score=round(raw, 6),
        target=TargetInterval(min_value=PERSPECTIVE_TARGET),
        evidence_frames=evidence_frames,
        confidence=confidence,
        evidence_grade="demo",
    )
    findings: list[Finding] = []
    if special_wide_cu:
        findings.append(_ambiguous_warning(
            "perspective_fit",
            "广角近景主体边缘畸变明显，是否符合情绪意图两可，",
            evidence_frames,
        ))
    elif raw < PERSPECTIVE_TARGET:
        findings.append(Finding(
            component="perspective_fit",
            severity=Severity.ERROR,
            message=(f"透视特征与声明景别不符（组合分 {raw:.3f} < "
                     f"{PERSPECTIVE_TARGET}），焦距与主体尺度偏离意图"),
            evidence_frames=evidence_frames,
        ))
    elif ambiguous:
        findings.append(_ambiguous_warning(
            "perspective_fit",
            f"透视特征恰在景别匹配临界附近（{raw:.2f}），"
            "是否属有意风格化两可，",
            evidence_frames,
        ))
    elif unknown_shot_type:
        findings.append(_ambiguous_warning(
            "perspective_fit",
            "未声明景别，已按中性焦距与中景尺度测量，判定是否适用两可，",
            evidence_frames,
        ))
    return (measurement,), tuple(findings)


def _camera_path_clearance(
        shot: ShotSample,
        intent: Optional[IntentContract]) -> Tuple[
            Tuple[Measurement, ...], Tuple[Finding, ...]]:
    declared = _declared_movement(intent)
    if declared is None:
        return (), ()
    movement, amount = declared
    if not shot.frames:
        return (), ()
    base = shot.frames[0]
    last = shot.frames[-1]
    if last.frame <= base.frame:
        return (), ()

    # 障碍点：各内容帧全部主体的中心 + 4 角，按首帧相机参数投影到 depth=3。
    obstacles: list[Vector3] = []
    for frame in shot.frames:
        for subject in frame.subjects:
            box = subject.box
            corners = (
                (box.left, box.top), (box.right, box.top),
                (box.left, box.bottom), (box.right, box.bottom),
                (box.center_x, box.center_y),
            )
            obstacles.extend(
                _project_world(base, ndc_x, ndc_y) for ndc_x, ndc_y in corners)

    subject_path = None
    if movement in SUBJECT_TRACKING:
        centers = [_primary_subject(f) for f in shot.frames]
        if not any(c is not None for c in centers):
            return (), ()
        subject_path = [
            _project_world(base, c.center_x, c.center_y)
            for c in centers if c is not None
        ]

    samples = movement_samples(
        tuple(float(v) for v in base.camera_position),
        _declared_target(base),
        movement,
        amount,
        base.frame,
        last.frame,
        samples=5,
        lens=float(base.lens),
        subject_path=subject_path,
        seed=0,
    )
    distances: list[float] = []
    path_frames: list[int] = []
    for item in samples:
        pos = tuple(float(v) for v in item["position"])
        distances.append(min(_distance(pos, ob) for ob in obstacles))
        path_frames.append(int(item["frame"]))
    if not distances:
        return (), ()
    raw = round(min(distances), 6)
    evidence_frames = tuple(sorted(set(path_frames)))
    score = _clamp01(raw / PATH_CLEARANCE_MIN)
    on_boundary = _boundary(raw, PATH_CLEARANCE_MIN, PATH_BOUNDARY_EPS)
    measurement = Measurement(
        metric="camera_path_clearance",
        raw_value=raw,
        score=round(score, 6),
        target=TargetInterval(min_value=PATH_CLEARANCE_MIN),
        evidence_frames=evidence_frames,
        confidence=0.5 if on_boundary else 1.0,
        evidence_grade="demo",
    )
    findings: list[Finding] = []
    if raw < PATH_CLEARANCE_MIN and not on_boundary:
        findings.append(Finding(
            component="camera_path_clearance",
            severity=Severity.FATAL,
            message=(f"相机路径穿过主体（最近间距 {raw:.3f} 米 < "
                     f"{PATH_CLEARANCE_MIN} 米），机位与角色重叠"),
            evidence_frames=evidence_frames,
            gate="H5",
        ))
    elif on_boundary:
        findings.append(_ambiguous_warning(
            "camera_path_clearance",
            "相机路径恰在安全间距边界且主体快速移动，是否可接受两可，",
            evidence_frames,
        ))
    elif raw < PATH_CLEARANCE_TIGHT:
        findings.append(Finding(
            component="camera_path_clearance",
            severity=Severity.ERROR,
            message=(f"相机路径贴主体过近（最近间距 {raw:.3f} 米，"
                     "尚未穿模）"),
            evidence_frames=evidence_frames,
        ))
    return (measurement,), tuple(findings)


def _clipped_union_area(boxes: Sequence[SubjectBox]) -> float:
    """多个 NDC 盒 clip 到 [0,1] 后的精确矩形并集面积。"""
    clipped: list[Tuple[float, float, float, float]] = []
    for box in boxes:
        left = max(0.0, min(1.0, float(box.left)))
        right = max(0.0, min(1.0, float(box.right)))
        bottom = max(0.0, min(1.0, float(box.bottom)))
        top = max(0.0, min(1.0, float(box.top)))
        if right - left <= 1e-12 or top - bottom <= 1e-12:
            continue
        clipped.append((left, right, bottom, top))
    if not clipped:
        return 0.0
    xs = sorted({x for left, right, _, _ in clipped for x in (left, right)})
    total = 0.0
    for index in range(len(xs) - 1):
        x0, x1 = xs[index], xs[index + 1]
        if x1 - x0 <= 1e-12:
            continue
        spans = [(bottom, top) for left, right, bottom, top in clipped
                 if left <= x0 + 1e-12 and right >= x1 - 1e-12]
        if not spans:
            continue
        spans.sort()
        merged_height = 0.0
        cur_bottom, cur_top = spans[0]
        for bottom, top in spans[1:]:
            if bottom <= cur_top:
                cur_top = max(cur_top, top)
            else:
                merged_height += cur_top - cur_bottom
                cur_bottom, cur_top = bottom, top
        merged_height += cur_top - cur_bottom
        total += (x1 - x0) * merged_height
    return total


def _reveal_progression(shot: ShotSample) -> Tuple[
        Tuple[Measurement, ...], Tuple[Finding, ...]]:
    areas: list[float] = []
    evidence: list[int] = []
    for frame in shot.frames:
        boxes = [subject.box for subject in frame.subjects]
        areas.append(_clipped_union_area(boxes))
        evidence.append(frame.frame)
    if not areas:
        return (), ()
    first, last = areas[0], areas[-1]
    delta = last - first
    if len(areas) > 1 and all(
            areas[i] < areas[i + 1] for i in range(len(areas) - 1)) \
            and delta >= 0.04:
        raw = 1.0
        state = "good"
    elif max(areas) - min(areas) <= 1e-9:
        raw = 0.0
        state = "bad"
    else:
        raw = 0.5
        state = "ambiguous"
    measurement = Measurement(
        metric="reveal_progression",
        raw_value=round(raw, 6),
        score=round(raw, 6),
        target=TargetInterval(min_value=REVEAL_TARGET),
        evidence_frames=tuple(sorted(set(evidence))),
        confidence=0.5 if state == "ambiguous" else 1.0,
        evidence_grade="demo",
    )
    findings: list[Finding] = []
    if state == "bad":
        findings.append(Finding(
            component="reveal_progression",
            severity=Severity.ERROR,
            message=(f"信息面积恒定无揭示进程（各帧 {raw:.3f}），"
                     "画面没有随内容关键帧打开新信息"),
            evidence_frames=tuple(sorted(set(evidence))),
        ))
    elif state == "ambiguous":
        findings.append(_ambiguous_warning(
            "reveal_progression",
            "揭示进程中途停滞、信息面积未持续增长，是否属有意留白两可，",
            tuple(sorted(set(evidence))),
        ))
    return (measurement,), tuple(findings)


def _movement_intent_match(
        shot: ShotSample,
        intent: Optional[IntentContract]) -> Tuple[
            Tuple[Measurement, ...], Tuple[Finding, ...]]:
    declared = _declared_movement(intent)
    if declared is None:
        return (), ()
    movement, amount = declared
    if not shot.frames:
        return (), ()
    base = shot.frames[0]
    last = shot.frames[-1]
    if last.frame <= base.frame:
        return (), ()

    subject_path = None
    if movement in SUBJECT_TRACKING:
        centers = [_primary_subject(f) for f in shot.frames]
        if not any(c is not None for c in centers):
            measurement = Measurement(
                metric="movement_intent_match",
                raw_value=0.0,
                score=0.0,
                target=TargetInterval(min_value=INTENT_MATCH_TARGET),
                evidence_frames=(),
                confidence=1.0,
                evidence_grade="demo",
            )
            finding = Finding(
                component="movement_intent_match",
                severity=Severity.ERROR,
                message="跟拍声明缺少可用主体路径，无法核验实际轨迹",
                evidence_frames=(),
            )
            return (measurement,), (finding,)
        subject_path = [
            _project_world(base, c.center_x, c.center_y)
            for c in centers if c is not None
        ]

    samples = movement_samples(
        tuple(float(v) for v in base.camera_position),
        _declared_target(base),
        movement,
        amount,
        base.frame,
        last.frame,
        samples=len(shot.frames),
        lens=float(base.lens),
        subject_path=subject_path,
        seed=0,
    )
    declared_by_frame: Dict[int, Dict[str, object]] = {
        int(item["frame"]): item for item in samples
    }
    compare_position = movement not in ROTATIONS and movement not in ZOOMS
    compare_look_at = movement in ROTATIONS
    compare_lens = movement in ZOOMS

    def _declared_value(index: int, frame: int,
                        key: str) -> Optional[object]:
        if frame in declared_by_frame:
            return declared_by_frame[frame][key]
        if 0 <= index < len(samples):
            return samples[index][key]
        return None

    def _actual_value(frame: FrameSample, key: str) -> object:
        if key == "position":
            return tuple(float(v) for v in frame.camera_position)
        if key == "look_at":
            pos = tuple(float(v) for v in frame.camera_position)
            forward = _normalize(frame.camera_forward)
            return (pos[0] + forward[0] * 3.0,
                    pos[1] + forward[1] * 3.0,
                    pos[2] + forward[2] * 3.0)
        if key == "lens":
            return float(frame.lens)
        raise KeyError(key)

    errors: list[float] = []
    valid = 0
    for index, frame in enumerate(shot.frames):
        if compare_position:
            key = "position"
        elif compare_look_at:
            key = "look_at"
        else:
            key = "lens"
        declared = _declared_value(index, frame.frame, key)
        if declared is None:
            continue
        actual = _actual_value(frame, key)
        if key == "lens":
            errors.append(abs(float(actual) - float(declared)))
        else:
            errors.append(_distance(actual, declared))  # type: ignore[arg-type]
        valid += 1
    if valid == 0:
        return (), ()

    first_key = ("look_at" if compare_look_at else
                 "lens" if compare_lens else "position")
    first_declared = samples[0][first_key]
    last_declared = samples[-1][first_key]
    if first_key == "lens":
        span = abs(float(last_declared) - float(first_declared))
    else:
        span = _distance(last_declared, first_declared)  # type: ignore[arg-type]
    if span <= 1e-9:
        raw = 1.0 if max(errors, default=0.0) <= 1e-9 else 0.0
    else:
        raw = 1.0 - sum(errors) / (span * valid)
    raw = _clamp01(raw)
    score = round(raw, 6)
    evidence_frames = tuple(sorted({f.frame for f in shot.frames}))
    ambiguous = INTENT_MATCH_TARGET <= raw <= INTENT_MATCH_TARGET + 0.10
    measurement = Measurement(
        metric="movement_intent_match",
        raw_value=score,
        score=score,
        target=TargetInterval(min_value=INTENT_MATCH_TARGET),
        evidence_frames=evidence_frames,
        confidence=0.5 if ambiguous else 1.0,
        evidence_grade="demo",
    )
    findings: list[Finding] = []
    if raw < INTENT_MATCH_TARGET:
        findings.append(Finding(
            component="movement_intent_match",
            severity=Severity.ERROR,
            message=(f"实际运镜与声明轨迹不符（贴合度 {raw:.3f} < "
                     f"{INTENT_MATCH_TARGET}），运动被写成错误轨迹"),
            evidence_frames=evidence_frames,
        ))
    elif ambiguous:
        findings.append(_ambiguous_warning(
            "movement_intent_match",
            "实际运镜与声明节奏存在差异（快推 vs 缓推），"
            "是否属有意变化两可，",
            evidence_frames,
        ))
    return (measurement,), tuple(findings)


def _spatial_orientation(shot: ShotSample) -> Tuple[
        Tuple[Measurement, ...], Tuple[Finding, ...]]:
    visible_frames: list[int] = []
    total = 0
    for frame in shot.frames:
        landmarks = [
            subject for subject in frame.subjects
            if subject.kind == "prop"
            or "landmark" in str(subject.subject_id).lower()
            or "door" in str(subject.subject_id).lower()
        ]
        total += 1
        if not landmarks:
            continue
        main = max(landmarks, key=lambda s: (s.box.height, s.subject_id))
        if (float(main.visible_ratio) >= 0.5
                and main.box.inside_ratio() > 0.05):
            visible_frames.append(frame.frame)
    if total == 0:
        return (), ()
    raw = round(len(visible_frames) / float(total), 6)
    ambiguous = 0.0 < raw < ORIENTATION_TARGET
    measurement = Measurement(
        metric="spatial_orientation",
        raw_value=raw,
        score=raw,
        target=TargetInterval(min_value=ORIENTATION_TARGET),
        evidence_frames=tuple(sorted(set(f.frame for f in shot.frames))),
        confidence=0.5 if ambiguous else 1.0,
        evidence_grade="demo",
    )
    findings: list[Finding] = []
    if raw == 0.0:
        findings.append(Finding(
            component="spatial_orientation",
            severity=Severity.ERROR,
            message="空间完全无法建立：内容关键帧中缺少可辨的空间参照物",
            evidence_frames=tuple(sorted(set(f.frame for f in shot.frames))),
        ))
    elif ambiguous:
        findings.append(_ambiguous_warning(
            "spatial_orientation",
            f"空间参照物只在部分内容关键帧可辨（占比 {raw:.3f}），"
            "是否属有意模糊空间两可，",
            tuple(sorted(set(f.frame for f in shot.frames))),
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
    raise TypeError(f"摄影意图层只接受 ShotSample/SequenceSample：{type(sample)!r}")


def evaluate(sample: object,
             intent: Optional[IntentContract] = None) -> EvaluationOutput:
    """对本层全部适用指标产出测量与失败项（公共接缝，与几何层同形）。"""
    shots = _shots_of(sample)
    measurements: list[Measurement] = []
    findings: list[Finding] = []
    for shot in shots:
        workers = (
            _perspective_fit(shot, intent),
            _camera_path_clearance(shot, intent),
            _reveal_progression(shot),
            _movement_intent_match(shot, intent),
            _spatial_orientation(shot),
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
    """渲染 LLM 可读读数；只含数值、方向与预期影响，过 detect_pollution。

    只打印声明的景别（shot_type），**绝不打印 camera_movements**——
    运镜名（dolly_in/track_right 等）是污染 token。
    """
    lines = [f"镜头 {output.shot_id} 摄影意图层读数："]
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


def _subject_box(subject_id: str, left: float, right: float, top: float,
                 bottom: float) -> SubjectBox:
    return SubjectBox(name=subject_id, left=left, right=right, top=top,
                      bottom=bottom)


def _projected(subject_id: str, box: SubjectBox,
               kind: str = "character",
               visible_ratio: float = 1.0) -> ProjectedSubject:
    return ProjectedSubject(subject_id=subject_id, kind=kind, box=box,
                            visible_ratio=visible_ratio)


def _hero(left: float, right: float, top: float, bottom: float
          ) -> ProjectedSubject:
    return _projected("hero", _subject_box("hero", left, right, top, bottom))


def _extra(subject_id: str, left: float, right: float, top: float,
           bottom: float) -> ProjectedSubject:
    return _projected(
        subject_id, _subject_box(subject_id, left, right, top, bottom))


def _prop(subject_id: str, left: float, right: float, top: float,
          bottom: float, visible_ratio: float = 1.0) -> ProjectedSubject:
    return _projected(
        subject_id, _subject_box(subject_id, left, right, top, bottom),
        kind="prop", visible_ratio=visible_ratio)


def _frame(n: int, subjects: Sequence[ProjectedSubject],
           shot_id: str = "shot_001",
           position: Sequence[float] = (0.0, 0.0, 0.0),
           lens: float = 35.0) -> FrameSample:
    return FrameSample(
        frame=n, shot_id=shot_id, subjects=tuple(subjects),
        camera_position=tuple(float(v) for v in position), lens=lens)


def _shot(frames: Sequence[FrameSample], shot_id: str = "shot_001",
          frame_range: Tuple[int, int] = (1, 5)) -> ShotSample:
    content = ContentFrame.from_shot(shot_id, frame_range, tuple(frames))
    return ShotSample(shot_id=shot_id, frame_range=frame_range,
                      content=content)


# —— perspective_fit：CU 声明下按焦距带 + 主体高度评分 ——
_cu_good = _hero(0.20, 0.40, 0.95, 0.15)       # 特写尺度（高 0.80）
_cu_bad = _hero(0.35, 0.45, 0.45, 0.25)        # 矮小主体（高 0.20）≠ CU
_cu_wide_edge = _hero(0.08, 0.92, 0.95, 0.15)  # 广角近景、主体贴边 -> 风格两可


def _perspective_frames(box: ProjectedSubject,
                        lens: float) -> ShotSample:
    return _shot(tuple(_frame(n, (box,), lens=lens) for n in (1, 3, 5)))


# —— camera_path_clearance / movement_intent_match：主体静态、相机按轨迹 ——
_path_hero = _hero(0.40, 0.60, 0.70, 0.30)


def _positioned_frames(
        positions: Sequence[Sequence[float]]) -> ShotSample:
    return _shot(tuple(
        _frame(n, (_path_hero,), position=pos)
        for n, pos in zip((1, 3, 5), positions)))


# —— reveal_progression：并集面积随内容关键帧严格递增 ——
_reveal_h1 = _hero(0.25, 0.45, 0.90, 0.45)
_reveal_h2 = _hero(0.55, 0.85, 0.95, 0.30)
_reveal_e2 = _extra("extra", 0.45, 0.75, 0.60, 0.05)
_reveal_p3 = _prop("table", 0.10, 0.40, 0.55, 0.25)


def _reveal_good() -> ShotSample:
    return _shot((
        _frame(1, (_reveal_h1,)),
        _frame(3, (_reveal_h2, _reveal_e2)),
        _frame(5, (_reveal_h2, _reveal_e2, _reveal_p3)),
    ))


def _reveal_ambiguous() -> ShotSample:
    return _shot((
        _frame(1, (_reveal_h1,)),
        _frame(3, (_reveal_h2, _reveal_e2)),
        _frame(5, (_reveal_h2, _reveal_e2)),
    ))


# —— spatial_orientation：门作为空间参照物 ——
_door = _prop("door", 0.20, 0.45, 0.85, 0.15)
_door_occluded = _prop("door", 0.20, 0.45, 0.85, 0.15,
                       visible_ratio=0.3)


SAMPLES: Dict[str, Dict[str, SampleCase]] = {
    "perspective_fit": {
        "good": SampleCase(
            "perspective_fit", _perspective_frames(_cu_good, 85.0),
            IntentContract(shot_id="shot_001", shot_type="CU"),
            "good"),
        "bad": SampleCase(
            "perspective_fit", _perspective_frames(_cu_bad, 24.0),
            IntentContract(shot_id="shot_001", shot_type="CU"),
            "bad"),
        "ambiguous": SampleCase(
            "perspective_fit", _perspective_frames(_cu_wide_edge, 24.0),
            IntentContract(shot_id="shot_001", shot_type="CU"),
            "ambiguous"),
    },
    "camera_path_clearance": {
        "good": SampleCase(
            "camera_path_clearance",
            _positioned_frames(((0, 0, 0), (1, 0, 0), (2, 0, 0))),
            IntentContract(shot_id="shot_001",
                           camera_movements=("track_right:2.0",)),
            "good"),
        "bad": SampleCase(
            "camera_path_clearance",
            _positioned_frames(((0, 0, 0), (0, 0, -1.5), (0, 0, -3.0))),
            IntentContract(shot_id="shot_001",
                           camera_movements=("dolly_in:3.0",)),
            "bad"),
        "ambiguous": SampleCase(
            "camera_path_clearance",
            _positioned_frames(((0, 0, 0), (0, 0, -1.4), (0, 0, -2.8))),
            IntentContract(shot_id="shot_001",
                           camera_movements=("dolly_in:2.8",)),
            "ambiguous"),
    },
    "reveal_progression": {
        "good": SampleCase(
            "reveal_progression", _reveal_good(), None, "good"),
        "bad": SampleCase(
            "reveal_progression",
            _positioned_frames(((0, 0, 0), (0, 0, 0), (0, 0, 0))),
            None, "bad"),
        "ambiguous": SampleCase(
            "reveal_progression", _reveal_ambiguous(), None, "ambiguous"),
    },
    "movement_intent_match": {
        "good": SampleCase(
            "movement_intent_match",
            _positioned_frames(((0, 0, 0), (0, 0, -1), (0, 0, -2))),
            IntentContract(shot_id="shot_001",
                           camera_movements=("dolly_in:2.0",)),
            "good"),
        "bad": SampleCase(
            "movement_intent_match",
            _positioned_frames(((0, 0, 0), (0, 0, 0), (0, 0, 0))),
            IntentContract(shot_id="shot_001",
                           camera_movements=("dolly_in:2.0",)),
            "bad"),
        "ambiguous": SampleCase(
            "movement_intent_match",
            _positioned_frames(((0, 0, 0), (0, 0, -0.3), (0, 0, -2.0))),
            IntentContract(shot_id="shot_001",
                           camera_movements=("dolly_in:2.0",)),
            "ambiguous"),
    },
    "spatial_orientation": {
        "good": SampleCase(
            "spatial_orientation",
            _shot((_frame(1, (_door,)), _frame(3, (_door,)),
                   _frame(5, (_door,)))),
            None, "good"),
        "bad": SampleCase(
            "spatial_orientation",
            _positioned_frames(((0, 0, 0), (0, 0, 0), (0, 0, 0))),
            None, "bad"),
        "ambiguous": SampleCase(
            "spatial_orientation",
            _shot((_frame(1, (_door,)), _frame(3, (_door_occluded,)),
                   _frame(5, (_door,)))),
            None, "ambiguous"),
    },
}


__all__ = [
    "SampleCase", "SAMPLES", "evaluate", "build_prescriptions",
    "render_report",
]


# --------------------------------------------------------------------------- #
# 公共接缝：evaluate / build_prescriptions / render_report / SAMPLES
# --------------------------------------------------------------------------- #
def _shot_of(sample: object) -> ShotSample:
    """输入可能是镜头采样或镜头序列采样；统一取出本层评估的单镜。"""
    if isinstance(sample, SequenceSample):
        return sample.shots[0]
    if not isinstance(sample, ShotSample):
        raise TypeError(f"不支持的采样类型：{type(sample).__name__}")
    return sample


def evaluate(sample: object,
             intent: Optional[IntentContract] = None) -> EvaluationOutput:
    """对本层全部五项指标产出测量与失败项（公共接缝）。"""
    shot = _shot_of(sample)
    measurements: List[Measurement] = []
    findings: List[Finding] = []
    workers = (
        lambda: _perspective_fit(shot, intent),
        lambda: _camera_path_clearance(shot, intent),
        lambda: _reveal_progression(shot),
        lambda: _movement_intent_match(shot, intent),
        lambda: _spatial_orientation(shot),
    )
    for worker in workers:
        ms, fs = worker()
        measurements.extend(ms)
        findings.extend(fs)
    return EvaluationOutput(
        shot_id=shot.shot_id,
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
        current = (float(measurement.raw_value)
                   if measurement is not None else 0.0)
        target = (measurement.target if measurement is not None
                  else TargetInterval(min_value=0.0))
        direction, effects, allowed = _REPAIR[finding.component]
        prescription = Prescription(
            component=finding.component,
            severity=finding.severity,
            current=round(current, 6),
            target=target,
            allowed_tools=tuple(allowed),
            direction=direction,
            expected_effect=effects,
        )
        ok, why = validate_prescription(prescription)
        if not ok:
            raise RuntimeError(
                f"处方校验失败：{finding.component}（{why}）")
        out.append(prescription)
    return tuple(out)


def render_report(output: EvaluationOutput,
                  prescriptions: Sequence[Prescription]) -> str:
    """渲染 LLM 可读读数；只含数值、方向与预期影响，过 detect_pollution。

    不渲染 camera_movements 与 allowed_tools（工具名即污染源）。
    """
    lines = [f"镜头 {output.shot_id} 摄影意图层读数："]
    if output.intent is not None:
        lines.append(f"- 声明景别：{output.intent.shot_type or '（未声明）'}")
    for m in output.measurements:
        lines.append(
            f"- {m.metric}：原始 {m.raw_value:.3f}，归一化 {m.score:.3f}，"
            f"目标 {m.target.to_dict()}，证据帧 {m.evidence_frames}，"
            f"置信度 {m.confidence:.2f}，证据等级 {m.evidence_grade}")
    for f in output.findings:
        gate = f"（硬门 {f.gate}）" if f.gate else ""
        lines.append(f"- 失败项：{f.component}[{f.severity.value}]{gate} "
                     f"{f.message}，证据帧 {f.evidence_frames}")
    for p in prescriptions:
        lines.append(f"- 修复方向（{p.component}）：{p.direction}")
        if p.expected_effect:
            lines.append(f"  预期影响：{'、'.join(p.expected_effect)}")
    if not prescriptions:
        lines.append("- 无失败分量（全部达标或仅提示）")
    return "\n".join(lines)


@dataclass(frozen=True)
class SampleCase:
    """一个三态样例：镜头采样 + 意图 + 预期结论。"""

    name: str
    sample: ShotSample
    intent: Optional[IntentContract]
    expected: str


# --------------------------------------------------------------------------- #
# 三态样例（demo 级，可复现）
# --------------------------------------------------------------------------- #
def _projected(subject_id: str, cx: float, cy: float, height: float,
               kind: str = "character", visible: float = 1.0,
               width: float = 0.04) -> ProjectedSubject:
    """投影主体：盒宽固定 width，中心 (cx, cy)，高 height。"""
    hw = width / 2.0
    return ProjectedSubject(
        subject_id=subject_id,
        box=SubjectBox(name=subject_id,
                       left=round(cx - hw, 6),
                       right=round(cx + hw, 6),
                       top=round(cy + height / 2.0, 6),
                       bottom=round(cy - height / 2.0, 6)),
        kind=kind,
        visible_ratio=visible,
    )


def _frame(number: int, camera_position: Sequence[float],
           subjects: Sequence[ProjectedSubject], lens: float = 50.0,
           shot_id: str = "") -> FrameSample:
    """内容帧：相机默认看向 -z，固定 vfov/aspect/roll。"""
    return FrameSample(
        frame=number,
        subjects=tuple(subjects),
        camera_position=tuple(float(v) for v in camera_position),
        camera_forward=(0.0, 0.0, -1.0),
        camera_up=(0.0, 1.0, 0.0),
        vfov_deg=35.0,
        aspect=16.0 / 9.0,
        lens=float(lens),
        roll_deg=0.0,
        shot_id=shot_id,
    )


def _content_shot(shot_id: str,
                  frames: Sequence[FrameSample]) -> ShotSample:
    """把内容关键帧包装成镜头采样（帧号严格递增，首/中/末覆盖）。"""
    first, last = int(frames[0].frame), int(frames[-1].frame)
    return ShotSample(
        shot_id=shot_id,
        frame_range=(first, last),
        content=ContentFrame.from_shot(shot_id, (first, last), frames),
    )


def _shot(shot_id: str,
          subjects_per_frame: Sequence[Sequence[ProjectedSubject]],
          positions: Optional[Sequence[Sequence[float]]] = None,
          lens: float = 50.0) -> ShotSample:
    """三帧（1/3/5）镜头采样；positions 缺省时固定 (0,0,5)。"""
    positions = positions or ((0.0, 0.0, 5.0),) * 3
    frames = [
        _frame(n, positions[i], subjects, lens=lens, shot_id=shot_id)
        for i, (n, subjects) in enumerate(zip((1, 3, 5), subjects_per_frame))
    ]
    return _content_shot(shot_id, frames)


def _intent(shot_id: str, shot_type: str = "",
            movements: Sequence[str] = ()) -> IntentContract:
    return IntentContract(
        shot_id=shot_id,
        shot_type=shot_type,
        camera_movements=tuple(movements),
    )


def _perspective_samples() -> Dict[str, SampleCase]:
    """透视特征三态：焦距带 + 主体尺度 vs 声明景别。"""
    good_hero = _projected("hero", 0.5, 0.5, 0.45)
    bad_hero = _projected("hero", 0.5, 0.5, 0.08)
    amb_hero = _projected("hero", 0.10, 0.5, 0.62)
    return {
        "good": SampleCase(
            name="perspective_fit",
            sample=_shot("pf_good",
                         ((good_hero,), (good_hero,), (good_hero,)),
                         lens=40),
            intent=_intent("pf_good", "MS"),
            expected="good",
        ),
        "bad": SampleCase(
            name="perspective_fit",
            sample=_shot("pf_bad",
                         ((bad_hero,), (bad_hero,), (bad_hero,)),
                         lens=200),
            intent=_intent("pf_bad", "MS"),
            expected="bad",
        ),
        "ambiguous": SampleCase(
            name="perspective_fit",
            sample=_shot("pf_amb",
                         ((amb_hero,), (amb_hero,), (amb_hero,)),
                         lens=20),
            intent=_intent("pf_amb", "CU"),
            expected="ambiguous",
        ),
    }


def _camera_path_samples() -> Dict[str, SampleCase]:
    """相机路径安全间距三态：track 平移安全 / dolly 穿主体 / 边界两可。"""
    hero = _projected("hero", 0.5, 0.5, 0.4)
    subjects = (hero,)
    track_positions = ((0.0, 0.0, 5.0), (1.5, 0.0, 5.0), (3.0, 0.0, 5.0))
    dolly_bad = ((0.0, 0.0, 5.0), (0.0, 0.0, 3.5), (0.0, 0.0, 2.0))
    dolly_amb = ((0.0, 0.0, 5.0), (0.0, 0.0, 3.6), (0.0, 0.0, 2.2))
    return {
        "good": SampleCase(
            name="camera_path_clearance",
            sample=_shot("cp_good",
                         (subjects, subjects, subjects),
                         positions=track_positions, lens=40),
            intent=_intent("cp_good", "MS", ("track_right:3.0",)),
            expected="good",
        ),
        "bad": SampleCase(
            name="camera_path_clearance",
            sample=_shot("cp_bad",
                         (subjects, subjects, subjects),
                         positions=dolly_bad, lens=40),
            intent=_intent("cp_bad", "MS", ("dolly_in:3.0",)),
            expected="bad",
        ),
        "ambiguous": SampleCase(
            name="camera_path_clearance",
            sample=_shot("cp_amb",
                         (subjects, subjects, subjects),
                         positions=dolly_amb, lens=40),
            intent=_intent("cp_amb", "MS", ("dolly_in:2.8",)),
            expected="ambiguous",
        ),
    }


def _reveal_samples() -> Dict[str, SampleCase]:
    """揭示进程三态：并集信息面积逐帧严格递增 / 恒定 / 停滞两可。"""
    hero_good = _projected("hero", 0.3, 0.5, 0.45, width=0.2)
    letter = _projected("letter", 0.7, 0.65, 0.3,
                        kind="prop", width=0.3)
    table = _projected("table", 0.75, 0.25, 0.2,
                       kind="prop", width=0.4)
    hero_bad = _projected("hero", 0.5, 0.5, 0.4, width=0.4)
    hero_amb = _projected("hero", 0.5, 0.5, 0.3, width=0.3)
    hero_amb5 = _projected("hero", 0.5, 0.5, 0.4, width=0.3)
    return {
        "good": SampleCase(
            name="reveal_progression",
            sample=_shot("rv_good",
                         ((hero_good,), (hero_good, letter),
                          (hero_good, letter, table)), lens=40),
            intent=_intent("rv_good", "MS"),
            expected="good",
        ),
        "bad": SampleCase(
            name="reveal_progression",
            sample=_shot("rv_bad",
                         ((hero_bad,), (hero_bad,), (hero_bad,)), lens=40),
            intent=_intent("rv_bad", "MS"),
            expected="bad",
        ),
        "ambiguous": SampleCase(
            name="reveal_progression",
            sample=_shot("rv_amb",
                         ((hero_amb,), (hero_amb,), (hero_amb5,)), lens=40),
            intent=_intent("rv_amb", "MS"),
            expected="ambiguous",
        ),
    }


def _movement_samples() -> Dict[str, SampleCase]:
    """运镜意图贴合三态：同轨达标 / 反向错误轨迹 / 快缓两可。"""
    good_hero = _projected("hero", 0.7, 0.5, 0.45)
    center_hero = _projected("hero", 0.5, 0.5, 0.45)
    dolly_good = ((0.0, 0.0, 5.0), (0.0, 0.0, 3.5), (0.0, 0.0, 2.0))
    dolly_bad = ((0.0, 0.0, 5.0), (0.0, 0.0, 6.5), (0.0, 0.0, 8.0))
    dolly_amb = ((0.0, 0.0, 5.0), (0.0, 0.0, 3.2), (0.0, 0.0, 1.4))
    return {
        "good": SampleCase(
            name="movement_intent_match",
            sample=_shot("mv_good",
                         ((good_hero,), (good_hero,), (good_hero,)),
                         positions=dolly_good, lens=40),
            intent=_intent("mv_good", "MS", ("dolly_in:3.0",)),
            expected="good",
        ),
        "bad": SampleCase(
            name="movement_intent_match",
            sample=_shot("mv_bad",
                         ((center_hero,), (center_hero,), (center_hero,)),
                         positions=dolly_bad, lens=40),
            intent=_intent("mv_bad", "MS", ("dolly_in:3.0",)),
            expected="bad",
        ),
        "ambiguous": SampleCase(
            name="movement_intent_match",
            sample=_shot("mv_amb",
                         ((center_hero,), (center_hero,), (center_hero,)),
                         positions=dolly_amb, lens=40),
            intent=_intent("mv_amb", "MS", ("dolly_in:3.0",)),
            expected="ambiguous",
        ),
    }


def _spatial_samples() -> Dict[str, SampleCase]:
    """空间参照物三态：地标全帧可辨 / 无参照物 / 部分帧可辨两可。"""
    hero = _projected("hero", 0.3, 0.5, 0.45, width=0.2)
    door = _projected("door_main", 0.80, 0.50, 0.80,
                      kind="prop", visible=1.0, width=0.20)
    door_amb = _projected("door_main", 0.80, 0.50, 0.80,
                          kind="prop", visible=0.4, width=0.20)
    door_amb5 = _projected("door_main", 0.80, 0.50, 0.80,
                           kind="prop", visible=0.9, width=0.20)
    return {
        "good": SampleCase(
            name="spatial_orientation",
            sample=_shot("sp_good",
                         ((hero, door), (hero, door), (hero, door)),
                         lens=40),
            intent=_intent("sp_good", "MS"),
            expected="good",
        ),
        "bad": SampleCase(
            name="spatial_orientation",
            sample=_shot("sp_bad",
                         ((hero,), (hero,), (hero,)), lens=40),
            intent=_intent("sp_bad", "MS"),
            expected="bad",
        ),
        "ambiguous": SampleCase(
            name="spatial_orientation",
            sample=_shot("sp_amb",
                         ((hero, door_amb), (hero, door_amb),
                          (hero, door_amb5)), lens=40),
            intent=_intent("sp_amb", "MS"),
            expected="ambiguous",
        ),
    }


SAMPLES: Dict[str, Dict[str, SampleCase]] = {
    "perspective_fit": _perspective_samples(),
    "camera_path_clearance": _camera_path_samples(),
    "reveal_progression": _reveal_samples(),
    "movement_intent_match": _movement_samples(),
    "spatial_orientation": _spatial_samples(),
}


__all__ = [
    "SampleCase",
    "SAMPLES",
    "evaluate",
    "build_prescriptions",
    "render_report",
]
