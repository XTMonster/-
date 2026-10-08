"""v1.6 D1（FR-B1）：节奏闭集、DTO serde 往返、SceneBrief.rhythm_arc 集成。"""
from __future__ import annotations

import json
import pytest

from block_director.contracts.rhythm import (
    CURVE_TO_INTERPOLATION,
    CURVE_VALUES,
    DEFAULT_CURVE,
    PACING_PROFILES,
    RhythmArc,
    ShotRhythm,
    TENSION_MAX,
    TENSION_MIN,
    curve_problems,
    pacing_profile_problems,
    rhythm_arc_problems,
)
from block_director.contracts.brief import SceneBrief
from block_director.contracts.enums import ErrorCode


def test_curve_values_closed_set_and_interpolation_mapping():
    assert set(CURVE_VALUES) == {"linear", "smooth", "ease_in", "ease_out", "sharp"}
    assert DEFAULT_CURVE in CURVE_VALUES
    assert set(CURVE_TO_INTERPOLATION) == set(CURVE_VALUES)
    assert CURVE_TO_INTERPOLATION["sharp"] == "LINEAR"   # 蓄-发-收
    assert CURVE_TO_INTERPOLATION["smooth"] == "BEZIER"


def test_pacing_profiles_closed_set():
    assert set(PACING_PROFILES) == {"contemplative", "standard", "urgent"}
    for name, data in PACING_PROFILES.items():
        lo, hi = data["asl_band_s"]
        assert 0 < lo < hi, name


def test_curve_problems_rejects_unknown_and_accepts_all_valid():
    for valid in CURVE_VALUES:
        assert curve_problems(valid) == []
    assert curve_problems(None) == []   # None = 缺省 smooth
    assert curve_problems("") == []
    p = curve_problems("bounce")
    assert p and "bounce" in p[0]


def test_pacing_profile_problems_rejects_unknown():
    assert pacing_profile_problems("standard") == []
    p = pacing_profile_problems("extreme")
    assert p and "extreme" in p[0]


def test_shot_rhythm_defaults_are_valid():
    r = ShotRhythm()
    assert r.tension == 3 and r.pace == "normal" and r.curve == DEFAULT_CURVE
    assert r.problems() == []


def test_shot_rhythm_invalid_fields_report_problems():
    assert ShotRhythm(tension=0).problems()   # below min
    assert ShotRhythm(tension=6).problems()   # above max
    assert ShotRhythm(tension=True).problems()  # bool is not int
    assert ShotRhythm(pace="flying").problems()
    assert ShotRhythm(curve="bounce").problems()
    assert ShotRhythm(tension=1, pace="slow", curve="linear").problems() == []


def test_shot_rhythm_serde_round_trip():
    r = ShotRhythm(tension=4, pace="brisk", curve="ease_out")
    restored = ShotRhythm.from_dict(json.loads(json.dumps(r.to_dict())))
    assert restored.tension == r.tension
    assert restored.pace == r.pace
    assert restored.curve == r.curve
    assert restored.to_dict() == r.to_dict()


def test_shot_rhythm_from_dict_accepts_missing_fields():
    minimal = ShotRhythm.from_dict({})
    assert minimal.problems() == []
    assert minimal.curve == DEFAULT_CURVE


def test_rhythm_arc_problems_rejects_missing_shot_id_and_bad_tension():
    assert RhythmArc("", 3).problems()              # empty shot_id
    assert RhythmArc("s1", 0).problems()            # below min
    assert RhythmArc("s1", 6).problems()            # above max
    assert RhythmArc("s1", 3).problems() == []


def test_rhythm_arc_serde_round_trip():
    a = RhythmArc("shot_007", 5, "climax")
    restored = RhythmArc.from_dict(json.loads(json.dumps(a.to_dict())))
    assert restored.shot_id == a.shot_id
    assert restored.tension == a.tension
    assert restored.note == a.note


def test_rhythm_arc_problems_detects_duplicate_shot_ids():
    items = [{"shot_id": "s1", "tension": 3}, {"shot_id": "s1", "tension": 4}]
    p = rhythm_arc_problems(items)
    assert p and any("重复" in x for x in p)


def test_rhythm_arc_problems_accepts_empty_list():
    assert rhythm_arc_problems([]) == []
    assert rhythm_arc_problems(None) == []


def test_brief_carries_rhythm_arc_and_validates_it():
    b = SceneBrief()
    b.rhythm_arc = [{"shot_id": "s1", "tension": 3}, {"shot_id": "s2", "tension": 2}]
    assert b.validate() == []
    b.rhythm_arc = [{"shot_id": "", "tension": 3}]   # empty shot_id
    assert b.validate()


def test_brief_serde_round_trip_preserves_rhythm_arc():
    b = SceneBrief()
    b.rhythm_arc = [{"shot_id": "s1", "tension": 4, "note": "顶点"}]
    restored = SceneBrief.from_dict(json.loads(json.dumps(b.to_dict())))
    assert restored.rhythm_arc == b.rhythm_arc


def test_brief_002_error_code_exists_and_is_registered_in_user_messages():
    from block_director.contracts.errors import USER_MESSAGES, user_message
    assert ErrorCode.BRIEF_002 == ErrorCode.BRIEF_002
    assert ErrorCode.BRIEF_002 in USER_MESSAGES
    msg = user_message(ErrorCode.BRIEF_002, reason="测试原因")
    assert "节奏弧" in msg and "测试原因" in msg
