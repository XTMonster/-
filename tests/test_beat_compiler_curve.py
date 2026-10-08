"""v1.6 D2（FR-B3 / FR-B4）：速度曲线编译——pace×curve → 帧长倍率与插值轮廓。

断言口径（TDD §4.4 逐字）：

* ``PACE_FRAME_MULTIPLIER`` 作用于 ``BEAT_DURATION_TABLE`` 与走位估帧；
* ``CURVE_PROFILE`` 把曲线词落实为 ``(插值模式, 位移时间轮廓)``；
* ``ease_in`` 前 20% 帧位移 ≤10%；``ease_out`` 末 20% 帧位移 ≤10%；
  ``sharp`` 前 15% 帧完成 ≥85%——这些断言量的是**编译出的帧表**
  （同输入同帧表，确定性），不是事后手算的期望值。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.contracts.beats import ShotBeat, validate_beats  # noqa: E402
from block_director.contracts.enums import MOVEMENT_TYPES  # noqa: E402
from block_director.contracts.rhythm import (  # noqa: E402
    CURVE_TO_INTERPOLATION,
    CURVE_VALUES,
    DEFAULT_CURVE,
    curve_problems,
)
from block_director.layer5_orchestrator.beat_compiler import (  # noqa: E402
    BEAT_DURATION_TABLE,
    CURVE_PROFILE,
    PACE_FRAME_MULTIPLIER,
    compile_beats,
)


def _shot(beats, *, duration=200, shot_id="shot_001", dialogues=None):
    class _Shot:
        pass

    shot = _Shot()
    shot.shot_id = shot_id
    shot.intent = "x"
    shot.shot_type = "MS"
    shot.duration_frames = duration
    shot.characters = ["char_001", "char_002"]
    shot.beats = list(beats)
    shot.dialogues = list(dialogues or [])
    return shot


def _beat(t, subject, verb, **kwargs):
    payload = {"t": t, "subject": subject, "verb": verb}
    payload.update(kwargs)
    return payload


def _cumulative_fraction(actions, frame):
    """按编译出的分段帧表重建累计位移占比（量编译产物，不重算轮廓）。"""
    walks = [item for item in actions if item["action_type"] in
             ("walk_to", "run_to")]
    assert walks, "没有走位段，断言没有意义"
    origin = walks[0]["params"]["from"]
    target = walks[-1]["params"]["target_position"]
    total = math.hypot(target[0] - origin[0], target[1] - origin[1])
    assert total > 0
    moved = 0.0
    for item in walks:
        start = int(item["start_frame"])
        end = int(item["end_frame"])
        if frame < start:
            break
        lo = item["params"]["from"]
        hi = item["params"]["target_position"]
        if frame >= end:
            moved = math.hypot(hi[0] - origin[0], hi[1] - origin[1])
            continue
        fraction = (frame - start) / max(end - start, 1)
        x = lo[0] + (hi[0] - lo[0]) * fraction
        y = lo[1] + (hi[1] - lo[1]) * fraction
        moved = math.hypot(x - origin[0], y - origin[1])
        break
    return moved / total


# --------------------------------------------------------------------------- #
# ShotBeat.curve（serde 往返 + 闭集校验）
# --------------------------------------------------------------------------- #
def test_shotbeat_curve_defaults_to_the_rhythm_single_source():
    assert ShotBeat().curve == DEFAULT_CURVE == "smooth"


def test_shotbeat_curve_serde_round_trip_for_every_closed_set_word():
    for curve in CURVE_VALUES:
        beat = ShotBeat(t=0.5, subject="char_001", verb="nod", curve=curve)
        restored = ShotBeat.from_dict(beat.to_dict())
        assert restored.curve == curve
        assert restored.to_dict() == beat.to_dict()


def test_shotbeat_curve_is_validated_by_curve_problems():
    for curve in CURVE_VALUES:
        assert validate_beats([ShotBeat(t=0.0, subject="c", verb="nod",
                                        curve=curve)], ["c"]) == []
    problems = validate_beats([ShotBeat(t=0.0, subject="c", verb="nod",
                                        curve="bounce")], ["c"])
    assert any("curve" in item and "闭集" in item for item in problems)


def test_curve_problems_accepts_empty_and_defaults_to_smooth_semantics():
    assert curve_problems("") == []
    assert curve_problems(None) == []
    assert curve_problems("smooth") == []


# --------------------------------------------------------------------------- #
# pace × curve → 帧长倍率与插值表（两张表逐字）
# --------------------------------------------------------------------------- #
def test_pace_frame_multiplier_table_is_verbatim():
    assert PACE_FRAME_MULTIPLIER == {"slow": 1.35, "normal": 1.0, "brisk": 0.7}


def test_curve_profile_table_is_verbatim():
    assert CURVE_PROFILE == {
        "linear": ("LINEAR", None),
        "smooth": ("BEZIER", None),
        "ease_in": ("BEZIER", "slow_start"),
        "ease_out": ("BEZIER", "slow_end"),
        "sharp": ("LINEAR", "burst"),
    }
    assert set(CURVE_PROFILE) == set(CURVE_VALUES)


def test_curve_profile_interpolation_agrees_with_the_contract_table():
    for curve in CURVE_VALUES:
        assert CURVE_PROFILE[curve][0] == CURVE_TO_INTERPOLATION[curve]


def test_pace_scales_the_beat_duration_table():
    expected = {
        "slow": int(round(BEAT_DURATION_TABLE["nod"] * 1.35)),
        "normal": BEAT_DURATION_TABLE["nod"],
        "brisk": int(round(BEAT_DURATION_TABLE["nod"] * 0.7)),
    }
    assert expected == {"slow": 16, "normal": 12, "brisk": 8}
    for pace, frames in expected.items():
        actions, problems = compile_beats(_shot(
            [_beat(0.0, "char_001", "nod", pace=pace)]))
        assert problems == []
        assert actions[0]["end_frame"] - actions[0]["start_frame"] + 1 == frames


def test_pace_scales_walk_frame_estimates():
    anchors = {"door": [4.0, 0.0, 0.0]}
    cast = {"char_001": [0.0, 0.0, 0.0]}
    expected = {"slow": 108, "normal": 80, "brisk": 56}
    for pace, frames in expected.items():
        actions, problems = compile_beats(
            _shot([_beat(0.0, "char_001", "walk_to", target="door",
                         pace=pace)]), anchors, cast)
        assert problems == []
        assert actions[0]["end_frame"] - actions[0]["start_frame"] + 1 == frames


# --------------------------------------------------------------------------- #
# 位移时间轮廓（编译产物上的三段硬断言）
# --------------------------------------------------------------------------- #
def test_ease_in_first_20_percent_of_frames_move_at_most_10_percent():
    actions, problems = compile_beats(
        _shot([_beat(0.0, "char_001", "walk_to", target="door",
                     curve="ease_in")]),
        {"door": [10.0, 0.0, 0.0]}, {"char_001": [0.0, 0.0, 0.0]})
    assert problems == []
    start = min(int(item["start_frame"]) for item in actions)
    end = max(int(item["end_frame"]) for item in actions)
    boundary = start + int(round(0.2 * (end - start)))
    assert _cumulative_fraction(actions, boundary) <= 0.10
    assert _cumulative_fraction(actions, end) == pytest.approx(1.0)


def test_ease_out_last_20_percent_of_frames_move_at_most_10_percent():
    actions, problems = compile_beats(
        _shot([_beat(0.0, "char_001", "walk_to", target="door",
                     curve="ease_out")]),
        {"door": [10.0, 0.0, 0.0]}, {"char_001": [0.0, 0.0, 0.0]})
    assert problems == []
    start = min(int(item["start_frame"]) for item in actions)
    end = max(int(item["end_frame"]) for item in actions)
    boundary = start + int(round(0.8 * (end - start)))
    moved_in_tail = (_cumulative_fraction(actions, end)
                     - _cumulative_fraction(actions, boundary))
    assert moved_in_tail <= 0.10


def test_sharp_first_15_percent_of_frames_reach_at_least_85_percent():
    actions, problems = compile_beats(
        _shot([_beat(0.0, "char_001", "walk_to", target="door",
                     curve="sharp")]),
        {"door": [10.0, 0.0, 0.0]}, {"char_001": [0.0, 0.0, 0.0]})
    assert problems == []
    start = min(int(item["start_frame"]) for item in actions)
    end = max(int(item["end_frame"]) for item in actions)
    boundary = start + int(round(0.15 * (end - start)))
    assert _cumulative_fraction(actions, boundary) >= 0.85


def test_smooth_and_linear_walks_keep_the_single_segment_shape():
    """smooth/linear 的轮廓是 None：单段、与旧输出逐字段相同（零行为差）。"""
    for curve in ("smooth", "linear"):
        actions, problems = compile_beats(
            _shot([_beat(0.0, "char_001", "walk_to", target="door",
                         curve=curve)]),
            {"door": [4.0, 0.0, 0.0]}, {"char_001": [0.0, 0.0, 0.0]})
        assert problems == []
        assert len(actions) == 1
        assert actions[0]["params"]["from"] == [0.0, 0.0, 0.0]
        assert actions[0]["params"]["target_position"] == [4.0, 0.0, 0.0]


def test_displacement_profiles_are_deterministic():
    for curve in ("ease_in", "ease_out", "sharp"):
        first = compile_beats(
            _shot([_beat(0.0, "char_001", "walk_to", target="door",
                         curve=curve)]),
            {"door": [10.0, 0.0, 0.0]}, {"char_001": [0.0, 0.0, 0.0]})
        second = compile_beats(
            _shot([_beat(0.0, "char_001", "walk_to", target="door",
                         curve=curve)]),
            {"door": [10.0, 0.0, 0.0]}, {"char_001": [0.0, 0.0, 0.0]})
        assert first == second


def test_unknown_curve_is_reported_and_compiles_with_the_default_profile():
    actions, problems = compile_beats(
        _shot([_beat(0.0, "char_001", "walk_to", target="door",
                     curve="bounce")]),
        {"door": [4.0, 0.0, 0.0]}, {"char_001": [0.0, 0.0, 0.0]})
    assert any("curve" in item and "闭集" in item for item in problems)
    assert len(actions) == 1, "非法 curve 报问题后按缺省 smooth 轮廓，不猜"


def test_b1_schema_curve_enum_is_the_rhythm_closed_set_not_a_copy():
    from block_director.layer5_orchestrator.editor import (
        EMIT_SHOT_DRAFT_PARAMETERS,
    )
    beat_props = EMIT_SHOT_DRAFT_PARAMETERS["properties"]["beats"]["items"][
        "properties"]
    assert beat_props["curve"]["enum"] == list(CURVE_VALUES)


def test_pace_and_curve_compose_on_one_walk():
    """brisk（0.7×窗口）＋ ease_in（前 20% ≤10%）：两个维度同时生效。"""
    actions, problems = compile_beats(
        _shot([_beat(0.0, "char_001", "walk_to", target="door",
                     pace="brisk", curve="ease_in")]),
        {"door": [10.0, 0.0, 0.0]}, {"char_001": [0.0, 0.0, 0.0]})
    assert problems == []
    start = min(int(item["start_frame"]) for item in actions)
    end = max(int(item["end_frame"]) for item in actions)
    assert end - start + 1 == 140   # 200 帧 * 0.7
    boundary = start + int(round(0.2 * (end - start)))
    assert _cumulative_fraction(actions, boundary) <= 0.10


# --------------------------------------------------------------------------- #
# 24 运镜 × 5 曲线矩阵（纯层：curve 词被携带 + 插值被选中）
# --------------------------------------------------------------------------- #
def test_24_movements_times_5_curves_matrix():
    assert len(MOVEMENT_TYPES) == 24
    for movement in MOVEMENT_TYPES:
        for curve in CURVE_VALUES:
            assert curve_problems(curve) == [], curve
            interpolation, profile = CURVE_PROFILE[curve]
            assert interpolation == CURVE_TO_INTERPOLATION[curve], curve
            assert interpolation in ("LINEAR", "BEZIER"), curve
            assert profile in (None, "slow_start", "slow_end", "burst"), curve
