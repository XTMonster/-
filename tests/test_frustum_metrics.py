"""v1.6 B2：纯层视锥度量（cinema/frustum_metrics.py）——合成 SubjectBox，手算期望值。"""

from __future__ import annotations

import pytest

from block_director.cinema.anchor import DEFAULT_PROFILE
from block_director.cinema.composition import SubjectBox
from block_director.cinema.frustum_metrics import (
    HEAD_FRACTION,
    DeclaredShot,
    FrameSample,
    GuardConfig,
    ShotSummary,
    aggregate,
    compare_with_intent,
    cut_level_checks,
    detect_events,
    frame_metrics,
    guard_config_from,
    shot_warnings,
)
from block_director.contracts.config import AppConfig
from block_director.contracts.guard import Confidence, GuardWarning, Severity

CFG = GuardConfig()


def box(left, right, bottom, top, facing=0.0):
    return SubjectBox("a", left=left, right=right, top=top, bottom=bottom,
                      facing=facing)


def seq(b, frames, subject="a", shot="shot_001", visible=1.0, behind=False):
    return [FrameSample(f, subject, b, visible, behind, shot) for f in frames]


def kinds(warnings):
    return sorted(w.type for w in warnings)


# ---------------------------------------------------------------- 单帧度量
def test_head_fraction_comes_from_frozen_geometry():
    assert HEAD_FRACTION == pytest.approx(DEFAULT_PROFILE.head_d
                                          / DEFAULT_PROFILE.total_height)
    assert HEAD_FRACTION == pytest.approx(0.37)


def test_six_metrics_hand_computed():
    m = frame_metrics(box(0.30, 0.50, 0.10, 0.90, facing=1.0), visible=0.75)
    assert m["body_height_ratio"] == pytest.approx(0.80)
    assert m["head_height_ratio"] == pytest.approx(0.80 * 0.37)
    assert m["headroom"] == pytest.approx(0.10)
    assert m["lead_room"] == pytest.approx(0.50)          # 朝右 ⇒ 1 - right
    # 中心 (0.4, 0.5)，最近三分交点 (1/3, 1/3)：sqrt(0.0667² + 0.1667²)
    assert m["thirds_deviation"] == pytest.approx(((0.4 - 1 / 3) ** 2
                                                   + (0.5 - 1 / 3) ** 2) ** 0.5)
    assert m["edge_clip"] == pytest.approx(0.0)
    assert m["visible_ratio"] == pytest.approx(0.75)


def test_lead_room_follows_facing_and_edge_clip_counts_outside_area():
    left_facing = frame_metrics(box(0.20, 0.40, 0.0, 0.5, facing=-1.0))
    assert left_facing["lead_room"] == pytest.approx(0.20)
    assert frame_metrics(box(0.2, 0.4, 0.0, 0.5))["lead_room"] == -1.0
    half_out = frame_metrics(box(0.9, 1.1, 0.0, 0.5))
    assert half_out["edge_clip"] == pytest.approx(0.5)


def test_head_ratio_is_not_truncated_by_the_frame():
    """"只剩眼睛"：头球投影比画面还高，读数必须 >1，而不是被截成"太松"。"""
    m = frame_metrics(box(0.3, 0.7, -2.0, 1.3))
    assert m["head_height_ratio"] == pytest.approx(3.3 * 0.37)
    assert m["headroom"] < 0


# ---------------------------------------------------------------- 曲线事件
def test_transient_out_of_frame_does_not_warn_but_sustained_does():
    inside = box(0.4, 0.6, 0.1, 0.9)
    outside = box(1.2, 1.4, 0.1, 0.9)
    short = seq(inside, [1, 5]) + seq(outside, [9]) + seq(inside, [13, 17])
    assert "subject_out_of_frame" not in kinds(detect_events(short, CFG))
    long = seq(inside, [1]) + seq(outside, [5, 9, 13, 17]) + seq(inside, [21])
    found = [w for w in detect_events(long, CFG) if w.type == "subject_out_of_frame"]
    assert len(found) == 1
    assert found[0].frame_range == (5, 17)
    assert found[0].severity is Severity.ERROR


def test_behind_camera_is_a_hard_error_from_one_frame():
    found = detect_events(seq(box(0.4, 0.6, 0.1, 0.9), [7], behind=True), CFG)
    assert kinds(found) == ["subject_behind_camera"]
    assert found[0].severity is Severity.ERROR and found[0].confidence is Confidence.HIGH


def test_not_visible_inside_frame_is_error():
    found = detect_events(seq(box(0.4, 0.6, 0.1, 0.9), range(1, 20, 4),
                              visible=0.0), CFG)
    assert "subject_not_visible" in kinds(found)


def test_sudden_jump_reports_measured_change():
    samples = seq(box(0.4, 0.6, 0.1, 0.5), [1]) + seq(box(0.4, 0.6, 0.1, 0.9), [5])
    found = [w for w in detect_events(samples, CFG) if w.type == "sudden_jump"]
    assert len(found) == 1
    assert found[0].evidence["ratio_change"] == pytest.approx(1.0)   # 0.4 → 0.8
    assert found[0].frame_range == (1, 5)
    calm = seq(box(0.4, 0.6, 0.1, 0.5), [1]) + seq(box(0.4, 0.6, 0.1, 0.55), [5])
    assert "sudden_jump" not in kinds(detect_events(calm, CFG))


# ---------------------------------------------------------------- 意图比对
def test_eyes_only_close_up_cannot_pass_silently():
    """E-video P0-3：CU 机位过近只剩眼睛 ⇒ framing_too_tight，证据含实测头部占比。"""
    samples = seq(box(0.3, 0.7, -2.0, 1.3), range(1, 49, 4), shot="shot_002")
    found = compare_with_intent(samples, DeclaredShot("shot_002", "CU", "a", "CU：面部"), CFG)
    tight = [w for w in found if w.type == "framing_too_tight"]
    assert len(tight) == 1
    assert tight[0].evidence["head_height_ratio"] > 0.75
    assert tight[0].evidence["expected_range"] == [0.55, 0.75]
    assert tight[0].declared_intent == "CU：面部"
    assert tight[0].suggestion_hint


def test_close_up_inside_band_is_quiet():
    # 头部占比 0.65：全身高 0.65/0.37；头顶留白 0.08
    height = 0.65 / HEAD_FRACTION
    good = box(0.35, 0.65, 0.92 - height, 0.92)
    found = compare_with_intent(seq(good, range(1, 49, 4)),
                                DeclaredShot("shot_001", "CU", "a"), CFG)
    assert not {"framing_too_tight", "framing_too_loose", "headroom_off"} & set(kinds(found))


def test_loose_full_body_shot_is_reported():
    found = compare_with_intent(seq(box(0.45, 0.55, 0.40, 0.60), range(1, 49, 4)),
                                DeclaredShot("shot_001", "MLS", "a"), CFG)
    loose = [w for w in found if w.type == "framing_too_loose"]
    assert loose and loose[0].evidence["body_height_ratio"] == pytest.approx(0.20)


def test_size_drift_respects_declared_push_in():
    samples = (seq(box(0.4, 0.6, 0.1, 0.70), [1, 5, 9])
               + seq(box(0.4, 0.6, 0.1, 0.85), [13, 17, 21]))
    plain = compare_with_intent(samples, DeclaredShot("shot_001", "MS", "a"), CFG)
    drift = [w for w in plain if w.type == "size_drift"]
    assert drift and drift[0].evidence["drift"] == pytest.approx(0.25)
    declared = compare_with_intent(samples, DeclaredShot(
        "shot_001", "MS", "a", size_change_declared=True), CFG)
    assert "size_drift" not in kinds(declared)


def test_occlusion_warns_unless_foreground_is_declared():
    samples = seq(box(0.4, 0.6, 0.1, 0.9), range(1, 49, 4), visible=0.5)
    assert "occlusion" in kinds(compare_with_intent(
        samples, DeclaredShot("shot_001", "MLS", "a"), CFG))
    assert "occlusion" not in kinds(compare_with_intent(
        samples, DeclaredShot("shot_001", "MLS", "a", front_occlusion_declared=True), CFG))


def test_exit_matches_declaration_within_tolerance():
    inside, outside = box(0.4, 0.6, 0.1, 0.9), box(1.2, 1.4, 0.1, 0.9)
    samples = seq(inside, [1, 5, 9]) + seq(outside, [13, 17, 21, 25, 29])
    unplanned = compare_with_intent(samples, DeclaredShot("shot_001", "MLS", "a"), CFG)
    exit_warning = [w for w in unplanned if w.type == "unplanned_exit"]
    assert exit_warning and exit_warning[0].evidence["exit_frame"] == 13
    on_time = compare_with_intent(samples, DeclaredShot(
        "shot_001", "MLS", "a", declared_exit_frame=14), CFG)
    assert "unplanned_exit" not in kinds(on_time)
    late = compare_with_intent(samples, DeclaredShot(
        "shot_001", "MLS", "a", declared_exit_frame=60), CFG)
    assert [w.evidence["diff_frames"] for w in late if w.type == "unplanned_exit"] == [-47]


def test_lead_room_short_for_subject_facing_the_edge():
    found = compare_with_intent(seq(box(0.78, 0.98, 0.1, 0.9, facing=1.0), range(1, 49, 4)),
                                DeclaredShot("shot_001", "MLS", "a"), CFG)
    short = [w for w in found if w.type == "lead_room_short"]
    assert short and short[0].evidence["lead_room"] == pytest.approx(0.02)


# ---------------------------------------------------------------- 镜头间
def test_jump_cut_risk_and_pace_monotony():
    shots = [ShotSummary("s1", 0.50, 10.0, 96), ShotSummary("s2", 0.52, 20.0, 96),
             ShotSummary("s3", 0.80, 20.0, 96)]
    found = cut_level_checks(shots, CFG)
    risk = [w for w in found if w.type == "jump_cut_risk"]
    assert [w.shot_id for w in risk] == ["s2"]
    assert risk[0].severity is Severity.WARNING
    mono = [w for w in found if w.type == "pace_monotony"]
    assert mono and mono[0].severity is Severity.INFO
    varied = [ShotSummary("s1", 0.5, 0, 48), ShotSummary("s2", 0.9, 90, 96)]
    assert cut_level_checks(varied, CFG) == []


def test_jump_cut_angle_wraps_around_360():
    shots = [ShotSummary("s1", 0.5, 355.0), ShotSummary("s2", 0.5, 5.0)]
    assert kinds(cut_level_checks(shots, CFG)) == ["jump_cut_risk"]


# ---------------------------------------------------------------- 聚合与配置
def test_aggregate_merges_same_shot_subject_type():
    a = GuardWarning("s1", (1, 4), "occlusion", "a", {"v": 1}, Severity.WARNING, Confidence.LOW)
    b = GuardWarning("s1", (20, 30), "occlusion", "a", {"v": 2}, Severity.ERROR, Confidence.HIGH)
    c = GuardWarning("s1", (5, 9), "occlusion", "b", {}, Severity.WARNING, Confidence.HIGH)
    merged = aggregate([b, c, a])
    assert [(w.subject, w.frame_range) for w in merged] == [("a", (1, 30)), ("b", (5, 9))]
    assert merged[0].severity is Severity.ERROR
    assert merged[0].confidence is Confidence.HIGH
    assert merged[0].evidence == {"v": 1, "merged": 2}
    assert aggregate([b, c, a]) == merged                       # 确定性


def test_thresholds_come_from_config_and_presets():
    cfg = AppConfig()
    assert guard_config_from(cfg).sustain_frames == 12
    cfg.guard.preset = "strict"
    strict = guard_config_from(cfg)
    assert strict.sustain_frames == 6 and strict.edge_clip_max == 0.05
    cfg.guard.preset = "standard"
    cfg.guard.sustain_frames = 3
    lenient = guard_config_from(cfg)
    short = seq(box(1.2, 1.4, 0.1, 0.9), [1, 5])
    assert "subject_out_of_frame" in kinds(detect_events(short, lenient))
    assert "subject_out_of_frame" not in kinds(detect_events(short, CFG))


def test_shot_warnings_fills_shot_id_and_is_aggregated():
    samples = seq(box(0.3, 0.7, -2.0, 1.3), range(1, 49, 4), shot="")
    found = shot_warnings(samples, DeclaredShot("shot_009", "CU", "a"), CFG)
    assert found and all(w.shot_id == "shot_009" for w in found)
    keys = [(w.shot_id, w.subject, w.type) for w in found]
    assert len(keys) == len(set(keys))
