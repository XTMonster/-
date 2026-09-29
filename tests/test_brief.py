"""阶段 S 的契约层测试：SceneBrief 的校验、查询与容错（v1.3 §3.2）。"""

from __future__ import annotations

import pytest

from block_director.contracts.brief import SceneBrief, shot_anchors, scope_tokens
from block_director.contracts.cast import (
    DISTANCE_CLASS_GAP,
    SceneSpec,
    default_station,
    station_from_space,
)
from block_director.contracts.plan import Plan


def _brief(**kwargs) -> SceneBrief:
    return SceneBrief.from_dict(kwargs)


# --------------------------------------------------------------------------- #
# 还原的容错
# --------------------------------------------------------------------------- #
def test_from_dict_tolerates_junk_instead_of_raising():
    brief = SceneBrief.from_dict({
        "speakers": [{"speaker": "甲"}, "不是字典", None],
        "gaze": "不是列表",
        "beats": [{"summary": "开场"}],
        "arc": "不是字典",
        "notes": ["一句", "", 3],
        "unknown_field": 1,
    })
    assert brief.speakers == [{"speaker": "甲"}]
    assert brief.gaze == [] and brief.arc == {}
    assert brief.notes == ["一句", "3"]
    assert brief.source == "llm"


def test_from_dict_keeps_the_source_marker():
    assert SceneBrief.from_dict({"source": "deterministic"}).source == \
        "deterministic"
    assert SceneBrief.from_dict(None).is_empty


def test_round_trip_is_stable():
    brief = _brief(beats=[{"id": "b1", "summary": "开场", "emotion": "平静"}],
                   notes=["待确认"])
    assert SceneBrief.from_dict(brief.to_dict()) == brief


# --------------------------------------------------------------------------- #
# 校验：只回答问题，从不抛异常
# --------------------------------------------------------------------------- #
def test_validate_flags_unknown_characters_only_when_a_roster_is_given():
    brief = _brief(gaze=[{"from": "甲", "to": "丙"}])
    assert brief.validate(["甲", "乙"]) == [
        "gaze[1].to 引用了不在角色表里的 丙（将被忽略）"]
    assert brief.validate() == []            # 没有角色表 → 无从判定


def test_validate_reports_missing_required_fields():
    problems = _brief(speakers=[{"listener": "乙"}],
                      gaze=[{"from": "甲"}]).validate()
    assert "speakers[1] 缺少字段：speaker" in problems
    assert "gaze[1] 缺少字段：to" in problems


def test_validate_reports_an_unknown_relation():
    problems = _brief(space=[{"character": "甲", "relative_to": "乙",
                              "relation": "并排站着"}]).validate()
    assert any("relation" in problem for problem in problems)


def test_validate_reports_an_unknown_source():
    brief = _brief(notes=["x"])
    brief.source = "模型猜的"
    assert any("source" in problem for problem in brief.validate())


# --------------------------------------------------------------------------- #
# 查询：scope 锚点
# --------------------------------------------------------------------------- #
def test_scope_anchors_accept_the_script_and_the_plan_spelling():
    assert scope_tokens("镜号2") == ["镜号2"]
    assert "镜号2" in shot_anchors("shot_002", 2)
    assert "2" in shot_anchors("shot_002", 2)
    assert "shot_002" in shot_anchors("shot_002", 2)


def test_gaze_scope_matches_only_the_covered_shots():
    brief = _brief(gaze=[
        {"from": "甲", "to": "乙", "scope": ["all"]},
        {"from": "甲", "to": "丙", "scope": ["镜号3"]},
    ])
    assert [item["to"] for item in brief.gazes_in("shot_002", 2)] == ["乙"]
    assert [item["to"] for item in brief.gazes_in("shot_003", 3)] == ["乙", "丙"]
    plain = _brief(gaze=[{"from": "甲", "to": "乙"}])
    assert plain.gazes_in("shot_009", 9)        # 没写 scope 视为整场


def test_listener_lookup_prefers_the_exact_dialogue_then_the_shot():
    brief = _brief(speakers=[
        {"dialogue_ref": "镜号1", "speaker": "甲", "listener": "乙"},
        {"dialogue_ref": "镜号2", "speaker": "甲", "listener": "丙"},
    ])
    assert brief.listener_of("甲", "shot_002", 2) == "丙"
    assert brief.listener_of("甲", "shot_001", 1) == "乙"
    assert brief.listener_of("甲", dialogue_ref="镜号1") == "乙"


def test_listener_lookup_does_not_guess_when_it_is_ambiguous():
    brief = _brief(speakers=[
        {"speaker": "甲", "listener": "乙"},
        {"speaker": "甲", "listener": "丙"},
    ])
    assert brief.listener_of("甲", "shot_007", 7) == ""
    single = _brief(speakers=[
        {"speaker": "甲", "listener": "乙"},
        {"speaker": "甲", "listener": "乙"},
    ])
    assert single.listener_of("甲", "shot_007", 7) == "乙"


# --------------------------------------------------------------------------- #
# 站位：SceneBrief.space → 实际位置
# --------------------------------------------------------------------------- #
def test_station_from_space_places_the_pair_opposite_each_other():
    stations = station_from_space(
        ["甲", "乙"],
        [{"character": "乙", "relative_to": "甲", "relation": "facing",
          "distance_class": "intimate"}])
    # 参照角色不挪窝，另一个人按声明的距离站到它正前方
    gap = DISTANCE_CLASS_GAP["intimate"]
    assert stations[1][0][0] - stations[0][0][0] == pytest.approx(gap)
    assert stations[1][1][:2] == (-1.0, 0.0)
    assert stations[0][1][:2] == (1.0, 0.0)


def test_station_from_space_falls_back_to_the_default_station():
    assert station_from_space(["甲", "乙"], []) == default_station(2)
    # 引用了一个不在场的角色 → 忽略该条，不产生位移
    assert station_from_space(["甲", "乙"],
                              [{"character": "丙", "relative_to": "甲"}]) == \
        default_station(2)


def test_station_from_space_handles_all_relations():
    for relation in ("facing", "side_by_side", "behind", "ahead", "apart"):
        stations = station_from_space(
            ["甲", "乙"],
            [{"character": "乙", "relative_to": "甲", "relation": relation}])
        assert len(stations) == 2
        assert stations[1][0] != stations[0][0]


def test_scene_spec_reads_the_brief_space():
    plan = Plan.from_dict({
        "scene_heading": "INT. 码头 - 午后",
        "shots": [{"shot_id": "shot_001", "order": 1, "intent": "对峙",
                   "shot_type": "MLS", "duration_frames": 48,
                   "characters": ["char_001", "char_002"]}]})
    brief = _brief(space=[{"character": "char_002",
                           "relative_to": "char_001", "relation": "facing",
                           "distance_class": "public"}])
    spec = SceneSpec.from_plan(plan, brief=brief)
    gap = abs(spec.cast[1].initial_location[0] - spec.cast[0].initial_location[0])
    assert gap == pytest.approx(DISTANCE_CLASS_GAP["public"])
    # 不给 brief 时仍是默认站位
    plain = SceneSpec.from_plan(plan)
    assert abs(plain.cast[1].initial_location[0]
               - plain.cast[0].initial_location[0]) == 1.8
