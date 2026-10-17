"""纯层视锥度量与告警检测（v1.6 B2，FR-C1–C4；TDD §4.1）。

输入：``List[FrameSample]``（bpy 侧 ``layer3_engine/frustum_sampler.py`` 产出）。
输出：``List[GuardWarning]``——**只报现象**（数值证据 + 声明意图 + 修复提示），
改不改由 LLM / 修复回路决定。阈值一律来自 ``GuardConfig``（config.guard 的运行时形），
函数体内不写死阈值。禁止 import bpy / mathutils。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..contracts.guard import (
    BODY_HEIGHT_BANDS,
    HEAD_HEIGHT_BANDS,
    Confidence,
    GuardWarning,
    Severity,
)
from .anchor import DEFAULT_PROFILE as _PROFILE
from .composition import HEADROOM_IDEAL, THIRDS, SubjectBox

#: 头球直径占全身高的比例——由冻结几何推导（ADR-0007），不另抄常量。
HEAD_FRACTION = _PROFILE.head_d / _PROFILE.total_height


@dataclass
class FrameSample:
    """单帧单主体的投影结果。``box`` 是**全身**包围盒（NDC，(0,0) 左下，可越界）。"""
    frame: int
    subject: str
    box: SubjectBox
    visible_ratio: float = 1.0
    behind_camera: bool = False
    shot_id: str = ""
    #: 本帧被外来遮挡物挡掉的采样点类别归因：``{"角色:char_002": 0.33}`` 等
    #: （占本帧 9 个采样点的比例；纯层回退：缺字段按空 dict 处理）。
    occlusion_by_class: Dict[str, float] = field(default_factory=dict)
    #: 本帧角色×角色碰撞对（卡 V11 由 ``frustum_sampler.sample_shot`` 填）：
    #: ``[{"pair": [a, b], "gap": float}, ...]``；同一帧会复制到每个主体的样本上，
    #: 消费方按 ``(frame, pair)`` 去重。
    collisions: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class DeclaredShot:
    """计划对这一镜的声明（意图比对的输入）。"""
    shot_id: str
    shot_type: str = ""
    subject: str = ""
    intent: str = ""
    #: 剧本声明的离场帧（0 ＝ 未声明离场 ⇒ 持续出画是"计划外"）
    declared_exit_frame: int = 0
    front_occlusion_declared: bool = False
    #: 声明了改变景别的运镜（推/拉/变焦）⇒ 镜内景别变化是设计，不报 size_drift
    size_change_declared: bool = False


@dataclass
class ShotSummary:
    """镜头间检查的单镜摘要。"""
    shot_id: str
    subject_ratio: float
    camera_angle_deg: float
    duration_frames: int = 0


@dataclass
class GuardConfig:
    """``config.guard`` 的运行时形；用 :func:`guard_config_from` 从 AppConfig 构造。"""
    edge_clip_max: float = 0.10
    lead_room_min: float = 0.05
    sustain_frames: int = 12
    size_drift: float = 0.15
    jump_ratio: float = 0.25
    jump_cut_angle_deg: float = 30.0
    jump_cut_size_diff: float = 0.10
    occlusion_warn: float = 0.20
    sample_step: int = 4
    #: 动作/字幕安全区比例（卡 V11；默认与 ``overlay.geometry`` 的常量相等）。
    safe_area_action: float = 0.93
    safe_area_title: float = 0.90
    head_bands: Dict[str, Tuple[float, float]] = field(
        default_factory=lambda: dict(HEAD_HEIGHT_BANDS))
    body_bands: Dict[str, Tuple[float, float]] = field(
        default_factory=lambda: dict(BODY_HEIGHT_BANDS))


def guard_config_from(app_config) -> GuardConfig:
    """把 ``AppConfig.guard``（含档位叠加）折成运行时阈值。唯一的构造入口。"""
    from ..contracts.config import resolve_guard_thresholds
    values = resolve_guard_thresholds(app_config.guard)
    bands = values.pop("size_bands", {})
    return GuardConfig(head_bands=dict(bands.get("head") or HEAD_HEIGHT_BANDS),
                       body_bands=dict(bands.get("body") or BODY_HEIGHT_BANDS),
                       **values)


# --------------------------------------------------------------------------- #
# 单帧六度量（FR-C2；R-构图 §3.2）
# --------------------------------------------------------------------------- #
def head_box(box: SubjectBox) -> Tuple[float, float]:
    """全身盒顶部的头球段 ``(bottom, top)``——按冻结几何比例切出，不另测。"""
    head_h = box.height * HEAD_FRACTION
    return box.top - head_h, box.top


def safe_area_bounds(value: float) -> Tuple[float, float]:
    """安全区比例 → 画面内缩后的 ``(下界, 上界)``。

    与 ``overlay.geometry.screen_rect`` 同源口径：``m = (1 - value) / 2``，
    安全区为 ``[m, 1-m]²``。``value=0.93`` ⇒ ``(0.035, 0.965)``。
    """
    margin = (1.0 - float(value)) / 2.0
    return margin, 1.0 - margin


def frame_metrics(box: SubjectBox, visible: float = 1.0) -> Dict[str, float]:
    """单帧度量（全部 NDC 比例，可 JSON）。

    * ``body_height_ratio``：脚底→头顶占画高（中远景口径）；
    * ``head_height_ratio``：头球**投影**高度占画高（近景口径）。**不按画框截断**——
      "只剩眼睛"的特写里头球比画面还高，截断后反而读成"太松"（2026-10-08 合成用例实测）；
      出框部分由 ``headroom``（负值）与 ``edge_clip`` 另行报告；
    * ``headroom``：头顶到画框上沿；``lead_room``：朝向侧留白（无朝向 ⇒ ``None`` 语义用 -1）；
    * ``thirds_deviation``：主体中心到最近三分交点的距离；
    * ``edge_clip``：包围盒落在画外的面积占比；``visible_ratio``：射线可见比例。
    """
    head_bottom, head_top = head_box(box)
    head_projected = max(head_top - head_bottom, 0.0)
    if box.facing > 0:
        lead_room = 1.0 - box.right
    elif box.facing < 0:
        lead_room = box.left
    else:
        lead_room = -1.0
    cx, cy = box.center_x, box.center_y
    thirds = min(((cx - tx) ** 2 + (cy - ty) ** 2) ** 0.5
                 for tx in THIRDS for ty in THIRDS)
    return {
        "body_height_ratio": max(box.height, 0.0),
        "head_height_ratio": head_projected,
        "headroom": 1.0 - box.top,
        "lead_room": lead_room,
        "thirds_deviation": thirds,
        "edge_clip": 1.0 - box.inside_ratio(),
        "visible_ratio": float(visible),
    }


def _band_for(shot_type: str, cfg: GuardConfig
              ) -> Optional[Tuple[str, Tuple[float, float]]]:
    """``(度量键, 区间)``；不在两张表里的景别（如 OTS/POV）不做景别回读。"""
    key = str(shot_type or "").upper()
    if key in cfg.head_bands:
        return "head_height_ratio", tuple(cfg.head_bands[key])
    if key in cfg.body_bands:
        return "body_height_ratio", tuple(cfg.body_bands[key])
    return None


def _runs(frames: Sequence[int], flags: Sequence[bool]) -> List[Tuple[int, int]]:
    """连续为真的帧段 ``[(start, end)]``（按采样序，相邻样本即视为连续）。"""
    runs: List[Tuple[int, int]] = []
    start: Optional[int] = None
    last: Optional[int] = None
    for frame, flag in zip(frames, flags):
        if flag and start is None:
            start = frame
        if not flag and start is not None:
            runs.append((start, last if last is not None else start))
            start = None
        last = frame
    if start is not None:
        runs.append((start, last if last is not None else start))
    return runs


def _sustained(run: Tuple[int, int], cfg: GuardConfig) -> bool:
    """持续违规判据：帧跨度（含端点）≥ ``sustain_frames``；瞬时越界不告警。"""
    return run[1] - run[0] + 1 >= int(cfg.sustain_frames)


# --------------------------------------------------------------------------- #
# 曲线事件（FR-C3）
# --------------------------------------------------------------------------- #
def _by_subject(samples: Sequence[FrameSample]) -> Dict[str, List[FrameSample]]:
    grouped: Dict[str, List[FrameSample]] = {}
    for sample in samples:
        grouped.setdefault(sample.subject, []).append(sample)
    for seq in grouped.values():
        seq.sort(key=lambda s: s.frame)
    return grouped


def _warning(shot_id: str, run: Tuple[int, int], kind: str, subject: str,
             evidence: Dict, severity: Severity, confidence: Confidence,
             intent: str = "", hint: str = "") -> GuardWarning:
    return GuardWarning(shot_id=shot_id, frame_range=(int(run[0]), int(run[1])),
                        type=kind, subject=subject, evidence=evidence,
                        severity=severity, confidence=confidence,
                        declared_intent=intent, suggestion_hint=hint)


def detect_events(samples: Sequence[FrameSample],
                  cfg: GuardConfig) -> List[GuardWarning]:
    """与声明无关的硬事件：机后、持续出画、画内不可见、两帧突变。"""
    warnings: List[GuardWarning] = []
    for subject, seq in _by_subject(samples).items():
        shot_id = seq[0].shot_id
        frames = [s.frame for s in seq]
        behind = [s.behind_camera for s in seq]
        #: 机后是投影失效，一帧就是硬错误（不走持续判据）
        for run in _runs(frames, behind):
            warnings.append(_warning(
                shot_id, run, "subject_behind_camera", subject,
                {"frames": run[1] - run[0] + 1}, Severity.ERROR, Confidence.HIGH,
                hint="主体落到相机后方：调整机位朝向或主体走位"))
        out = [(not s.behind_camera) and s.box.inside_ratio() <= 0.0 for s in seq]
        for run in _runs(frames, out):
            if _sustained(run, cfg):
                warnings.append(_warning(
                    shot_id, run, "subject_out_of_frame", subject,
                    {"frames": run[1] - run[0] + 1,
                     "sustain_frames": int(cfg.sustain_frames)},
                    Severity.ERROR, Confidence.HIGH,
                    hint="主体完全出画：若非剧本离场，移动相机或主体"))
        hidden = [(not s.behind_camera) and s.box.inside_ratio() > 0.0
                  and s.visible_ratio <= 0.0 for s in seq]
        for run in _runs(frames, hidden):
            if _sustained(run, cfg):
                warnings.append(_warning(
                    shot_id, run, "subject_not_visible", subject,
                    {"visible_ratio": 0.0, "frames": run[1] - run[0] + 1},
                    Severity.ERROR, Confidence.HIGH,
                    hint="主体在画框内但被完全挡住：挪开前景或换机位"))
        previous: Optional[FrameSample] = None
        for sample in seq:
            if sample.behind_camera:
                previous = None
                continue
            if previous is not None:
                before = max(previous.box.height, 1e-9)
                change = abs(sample.box.height - previous.box.height) / before
                if change > cfg.jump_ratio:
                    warnings.append(_warning(
                        shot_id, (previous.frame, sample.frame), "sudden_jump",
                        subject,
                        {"ratio_change": round(change, 4),
                         "jump_ratio": cfg.jump_ratio,
                         "before": round(previous.box.height, 4),
                         "after": round(sample.box.height, 4)},
                        Severity.WARNING, Confidence.HIGH,
                        hint="相邻采样帧主体占比突变：检查机位/焦段关键帧"))
            previous = sample

    #: 卡 V11：角色×角色碰撞箱穿透（warning，不进门；R002 的角色 vs 墙/道具
    #: error 判据一字不动）。同一帧的碰撞对复制在每个主体样本上，这里按
    #: ``(frame, pair)`` 去重后按配对聚合。
    pair_frames: Dict[str, set] = {}
    pair_gap: Dict[str, float] = {}
    pair_shot: Dict[str, str] = {}
    for sample in samples:
        for item in sample.collisions or []:
            pair = item.get("pair")
            if not (isinstance(pair, (list, tuple)) and len(pair) == 2):
                continue
            gap = item.get("gap")
            if (isinstance(gap, bool) or not isinstance(gap, (int, float))
                    or float(gap) >= 0.0):
                continue
            key = "|".join(sorted(str(part) for part in pair))
            pair_frames.setdefault(key, set()).add(int(sample.frame))
            pair_gap[key] = min(pair_gap.get(key, float("inf")), float(gap))
            pair_shot[key] = str(sample.shot_id) or pair_shot.get(key, "")
    for key in sorted(pair_frames):
        frames = sorted(pair_frames[key])
        for run in _runs(frames, [True] * len(frames)):
            if not _sustained(run, cfg):
                continue
            warnings.append(_warning(
                pair_shot[key], run, "element_collision", key,
                {"pair": key.split("|"),
                 "penetration_depth": round(-pair_gap[key], 4),
                 "frames": run[1] - run[0] + 1,
                 "sustain_frames": int(cfg.sustain_frames)},
                Severity.WARNING, Confidence.HIGH,
                hint="两角色碰撞箱穿透：挪开走位或缩小碰撞体"))
    return warnings


# --------------------------------------------------------------------------- #
# 与声明意图比对（FR-C2/C3；D-12 的"同一把尺"）
# --------------------------------------------------------------------------- #
def compare_with_intent(samples: Sequence[FrameSample], declared: DeclaredShot,
                        cfg: GuardConfig) -> List[GuardWarning]:
    """声明相关的告警：景别区间、留白、裁切、遮挡、景别漂移、计划外离场。"""
    warnings: List[GuardWarning] = []
    grouped = _by_subject(samples)
    subjects = [declared.subject] if declared.subject else sorted(grouped)
    intent = declared.intent or declared.shot_type
    band = _band_for(declared.shot_type, cfg)
    for subject in subjects:
        seq = [s for s in grouped.get(subject, []) if not s.behind_camera]
        if not seq:
            continue
        shot_id = declared.shot_id or seq[0].shot_id
        frames = [s.frame for s in seq]
        metrics = [frame_metrics(s.box, s.visible_ratio) for s in seq]
        in_frame = [s.box.inside_ratio() > 0.0 for s in seq]

        if band is not None:
            key, (lo, hi) = band
            for kind, test, hint in (
                    ("framing_too_tight", lambda v: v > hi,
                     "拉远相机或降焦段（距离 × 实测/目标上限）"),
                    ("framing_too_loose", lambda v: v < lo,
                     "推近相机或升焦段")):
                flags = [ok and test(m[key]) for m, ok in zip(metrics, in_frame)]
                for run in _runs(frames, flags):
                    if not _sustained(run, cfg):
                        continue
                    values = [m[key] for m, f, fl in zip(metrics, frames, flags)
                              if fl and run[0] <= f <= run[1]]
                    warnings.append(_warning(
                        shot_id, run, kind, subject,
                        {key: round(max(values) if kind.endswith("tight")
                                    else min(values), 4),
                         "expected_range": [lo, hi],
                         "shot_type": declared.shot_type.upper()},
                        Severity.WARNING, Confidence.HIGH, intent, hint))

        #: 留白只在"比全身更紧"的景别有意义（与 composition 的口径一致）
        if band is not None and band[0] == "head_height_ratio":
            lo_h, hi_h = HEADROOM_IDEAL
            flags = [ok and not (lo_h <= m["headroom"] <= hi_h)
                     for m, ok in zip(metrics, in_frame)]
            for run in _runs(frames, flags):
                if _sustained(run, cfg):
                    worst = [m["headroom"] for m, f in zip(metrics, frames)
                             if run[0] <= f <= run[1]]
                    warnings.append(_warning(
                        shot_id, run, "headroom_off", subject,
                        {"headroom": round(min(worst, key=lambda v: min(
                            abs(v - lo_h), abs(v - hi_h))), 4),
                         "expected_range": [lo_h, hi_h]},
                        Severity.WARNING, Confidence.HIGH, intent,
                        "调整机位高度或俯仰，让头顶留白回到区间"))

        flags = [ok and 0.0 <= m["lead_room"] < cfg.lead_room_min
                 for m, ok in zip(metrics, in_frame)]
        for run in _runs(frames, flags):
            if _sustained(run, cfg):
                warnings.append(_warning(
                    shot_id, run, "lead_room_short", subject,
                    {"lead_room": round(min(m["lead_room"] for m, f in
                                            zip(metrics, frames)
                                            if run[0] <= f <= run[1]), 4),
                     "lead_room_min": cfg.lead_room_min},
                    Severity.WARNING, Confidence.HIGH, intent,
                    "朝向侧留白不足：横移对准点或相机"))

        flags = [ok and m["edge_clip"] > cfg.edge_clip_max
                 for m, ok in zip(metrics, in_frame)]
        for run in _runs(frames, flags):
            if _sustained(run, cfg):
                #: 包围盒对细长姿态虚胖 ⇒ 裁切类度量标 low（PRD §6）
                warnings.append(_warning(
                    shot_id, run, "edge_clip", subject,
                    {"edge_clip": round(max(m["edge_clip"] for m, f in
                                            zip(metrics, frames)
                                            if run[0] <= f <= run[1]), 4),
                     "edge_clip_max": cfg.edge_clip_max},
                    Severity.WARNING, Confidence.LOW, intent,
                    "主体被画框裁切：拉远或调整构图"))

        if not declared.front_occlusion_declared:
            flags = [ok and 0.0 < m["visible_ratio"] < 1.0 - cfg.occlusion_warn
                     for m, ok in zip(metrics, in_frame)]
            for run in _runs(frames, flags):
                if _sustained(run, cfg):
                    in_run = [s for s in seq
                              if run[0] <= s.frame <= run[1]
                              and not s.behind_camera
                              and s.occlusion_by_class]
                    merged: Dict[str, float] = {}
                    for s in in_run:
                        for cls, fraction in s.occlusion_by_class.items():
                            merged[cls] = merged.get(cls, 0.0) + float(fraction)
                    if merged and in_run:
                        merged = {cls: round(total / len(in_run), 6)
                                  for cls, total in merged.items()}
                    warnings.append(_warning(
                        shot_id, run, "occlusion", subject,
                        {"visible_ratio": round(min(
                            m["visible_ratio"] for m, f in zip(metrics, frames)
                            if run[0] <= f <= run[1]), 4),
                         "occlusion_warn": cfg.occlusion_warn,
                         "occlusion_by_class": merged},
                        Severity.WARNING, Confidence.HIGH, intent,
                        "主体被挡：若是刻意前景遮挡请在计划里声明"))

        if band is not None and not declared.size_change_declared:
            key = band[0]
            values = [m[key] for m, ok in zip(metrics, in_frame) if ok]
            if values and values[0] > 0.0:
                drift = max(abs(v - values[0]) / values[0] for v in values)
                if drift > cfg.size_drift:
                    warnings.append(_warning(
                        shot_id, (frames[0], frames[-1]), "size_drift", subject,
                        {"drift": round(drift, 4), "size_drift": cfg.size_drift,
                         "first": round(values[0], 4),
                         "range": [round(min(values), 4), round(max(values), 4)]},
                        Severity.WARNING, Confidence.HIGH, intent,
                        "声明固定景别但镜内占比漂移：锁定机位或在计划里声明推拉"))

        out = [s.box.inside_ratio() <= 0.0 for s in seq]
        for run in _runs(frames, out):
            if not _sustained(run, cfg):
                continue
            exit_at = int(declared.declared_exit_frame or 0)
            diff = (run[0] - exit_at) if exit_at else None
            if exit_at and abs(diff) <= cfg.sustain_frames:
                continue
            warnings.append(_warning(
                shot_id, run, "unplanned_exit", subject,
                {"exit_frame": run[0], "declared_exit_frame": exit_at or None,
                 "diff_frames": diff, "tolerance_frames": cfg.sustain_frames},
                Severity.WARNING, Confidence.HIGH, intent,
                "出画时间与剧本声明不符：调整走位时机或声明离场"))

        #: 卡 V11：头部盒越出动作安全区（warning，不进门；声明离场后不判）。
        action_low, action_high = safe_area_bounds(cfg.safe_area_action)
        exit_at = int(declared.declared_exit_frame or 0)
        breach_flags: List[bool] = []
        breach_edges: List[List[str]] = []
        breach_exceed: List[List[float]] = []
        for s, ok in zip(seq, in_frame):
            judged = exit_at <= 0 or s.frame <= exit_at
            if not (ok and judged):
                breach_flags.append(False)
                breach_edges.append([])
                breach_exceed.append([])
                continue
            head_bottom, head_top = head_box(s.box)
            edges: List[str] = []
            exceeds: List[float] = []
            if s.box.left < action_low:
                edges.append("left")
                exceeds.append(action_low - s.box.left)
            if s.box.right > action_high:
                edges.append("right")
                exceeds.append(s.box.right - action_high)
            if head_bottom < action_low:
                edges.append("bottom")
                exceeds.append(action_low - head_bottom)
            if head_top > action_high:
                edges.append("top")
                exceeds.append(head_top - action_high)
            breach_flags.append(bool(edges))
            breach_edges.append(edges)
            breach_exceed.append(exceeds)
        for run in _runs(frames, breach_flags):
            if not _sustained(run, cfg):
                continue
            best_exceed = -1.0
            best_edges: List[str] = []
            best_head_h = 1e-9
            for index, frame in enumerate(frames):
                if not (run[0] <= frame <= run[1] and breach_exceed[index]):
                    continue
                exceed = max(breach_exceed[index])
                if exceed > best_exceed + 1e-12 or (
                        abs(exceed - best_exceed) <= 1e-12
                        and len(breach_edges[index]) > len(best_edges)):
                    best_exceed = exceed
                    best_edges = sorted(breach_edges[index])
                    head_bottom, head_top = head_box(seq[index].box)
                    best_head_h = max(head_top - head_bottom, 1e-9)
            warnings.append(_warning(
                shot_id, run, "safe_area_breach", subject,
                {"edges": best_edges,
                 "exceed_max": round(best_exceed, 4),
                 "exceed_ratio": round(best_exceed / best_head_h, 4),
                 "safe_area_action": round(float(cfg.safe_area_action), 4),
                 "frames": run[1] - run[0] + 1},
                Severity.WARNING, Confidence.HIGH, intent,
                "头部越过动作安全区：调整取景（拉远或压低机位）"
                "或在计划里声明刻意裁切"))
    return warnings


# --------------------------------------------------------------------------- #
# 镜头间（FR-C6 跳切风险；FR-B2 单调性只作 info）
# --------------------------------------------------------------------------- #
def cut_level_checks(shots: Sequence[ShotSummary],
                     cfg: GuardConfig) -> List[GuardWarning]:
    """相邻镜跳切风险（warning，由 LLM 裁决）＋ 全片镜长单调（info）。

    银幕左右序（``axis_screen_order``）由 ``cinema/axis.py`` 的状态机判（卡 B5），
    这里不重复实现第二份。
    """
    warnings: List[GuardWarning] = []
    for prev, cur in zip(shots, shots[1:]):
        base = max(prev.subject_ratio, 1e-9)
        size_diff = abs(cur.subject_ratio - prev.subject_ratio) / base
        angle = abs(cur.camera_angle_deg - prev.camera_angle_deg) % 360.0
        angle = min(angle, 360.0 - angle)
        if size_diff < cfg.jump_cut_size_diff and angle < cfg.jump_cut_angle_deg:
            warnings.append(_warning(
                cur.shot_id, (0, 0), "jump_cut_risk", "scene",
                {"previous_shot": prev.shot_id,
                 "size_diff": round(size_diff, 4),
                 "angle_diff_deg": round(angle, 3),
                 "jump_cut_size_diff": cfg.jump_cut_size_diff,
                 "jump_cut_angle_deg": cfg.jump_cut_angle_deg},
                Severity.WARNING, Confidence.HIGH,
                hint="与上一镜景别和角度都太接近：换角度 ≥30° 或换景别"))
    durations = [int(s.duration_frames) for s in shots if s.duration_frames > 0]
    if len(durations) >= 2 and len(set(durations)) == 1:
        warnings.append(_warning(
            "scene", (0, 0), "pace_monotony", "scene",
            {"shots": len(durations), "duration_frames": durations[0]},
            Severity.INFO, Confidence.HIGH,
            hint="全片镜长相同：节奏是创作选择，仅供参考"))
    return warnings


def thirds_info(samples: Sequence[FrameSample], declared: DeclaredShot,
                cfg: GuardConfig, threshold: float = 1.0 / 6.0
                ) -> List[GuardWarning]:
    """三分偏差：info 级（默认不打扰）。阈值＝相邻三分线间距的一半。"""
    warnings: List[GuardWarning] = []
    for subject, seq in _by_subject(samples).items():
        if declared.subject and subject != declared.subject:
            continue
        seq = [s for s in seq if not s.behind_camera and s.box.inside_ratio() > 0]
        if not seq:
            continue
        values = [frame_metrics(s.box)["thirds_deviation"] for s in seq]
        median = sorted(values)[len(values) // 2]
        if median > threshold:
            warnings.append(_warning(
                declared.shot_id or seq[0].shot_id, (seq[0].frame, seq[-1].frame),
                "thirds_deviation", subject,
                {"thirds_deviation": round(median, 4), "threshold": round(threshold, 4)},
                Severity.INFO, Confidence.HIGH, declared.intent))
    return warnings


# --------------------------------------------------------------------------- #
# 时间聚合（防告警疲劳）
# --------------------------------------------------------------------------- #
_SEVERITY_RANK = {Severity.INFO: 0, Severity.WARNING: 1, Severity.ERROR: 2}


def aggregate(warnings: Sequence[GuardWarning]) -> List[GuardWarning]:
    """同镜同主体同类合并：帧段取包络、严重度取最高、证据取最早一条并记合并数。

    输出按 ``(shot_id, frame_start, type, subject)`` 排序——确定性。
    """
    groups: Dict[Tuple[str, str, str], List[GuardWarning]] = {}
    for item in warnings:
        groups.setdefault((item.shot_id, item.subject, item.type), []).append(item)
    merged: List[GuardWarning] = []
    for (shot_id, subject, kind), items in groups.items():
        items = sorted(items, key=lambda w: w.frame_range)
        first = items[0]
        evidence = dict(first.evidence)
        if len(items) > 1:
            evidence["merged"] = len(items)
        severity = max((w.severity for w in items), key=_SEVERITY_RANK.get)
        confidence = (Confidence.HIGH if any(w.confidence is Confidence.HIGH
                                             for w in items) else Confidence.LOW)
        merged.append(GuardWarning(
            shot_id=shot_id,
            frame_range=(min(w.frame_range[0] for w in items),
                         max(w.frame_range[1] for w in items)),
            type=kind, subject=subject, evidence=evidence, severity=severity,
            confidence=confidence, declared_intent=first.declared_intent,
            suggestion_hint=first.suggestion_hint))
    merged.sort(key=lambda w: (w.shot_id, w.frame_range[0], w.type, w.subject))
    return merged


def shot_warnings(samples: Sequence[FrameSample], declared: DeclaredShot,
                  cfg: GuardConfig) -> List[GuardWarning]:
    """一镜的全部单镜告警（事件 ＋ 意图比对 ＋ 三分 info），已聚合。"""
    found = list(detect_events(samples, cfg))
    found += compare_with_intent(samples, declared, cfg)
    found += thirds_info(samples, declared, cfg)
    for item in found:
        if not item.shot_id:
            item.shot_id = declared.shot_id
    return aggregate(found)
