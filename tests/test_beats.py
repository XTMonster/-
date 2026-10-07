"""拍点表契约（执行文档 v1.5 / TDD §3.1/§3.4/§3.5/§3.6 / 卡 P2-T1）。

两件事必须在这里钉住，它们都是本项目已经付过代价的形状：

1. **词表只有一份真源**：``BEAT_VERBS`` 必须**逐字等于** ``motion/model.py``
   的 ``ACTION_TYPES``（红线 R-7）。抄第二份就会在扩动词时漂。
2. **``ShotBeat`` 不是 ``SceneBrief.beats``**：两个 `beats` 概念不同、不得合并。
   这条用"字段集不相交"的机器断言守住，而不是靠注释自觉。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.contracts.beats import (  # noqa: E402
    BEAT_VERBS,
    COMPOSITION_RULES,
    FACE_TO_VALUES,
    KEY_DIRECTION_VALUES,
    LIGHT_MOOD_VALUES,
    MAX_BEATS,
    PACE_VALUES,
    RULE_ACTIONS,
    SUBJECT_POSITIONS,
    TIME_OF_DAY_VALUES,
    CompositionSpec,
    LightSpec,
    RuleJustification,
    ShotBeat,
    validate_beats,
    validate_composition_spec,
    validate_justifications,
    validate_light_spec,
)
from block_director.motion.model import ACTION_TYPES  # noqa: E402


def _good_beats():
    return [
        ShotBeat(t=0.0, subject="char_001", verb="walk_to", target="door"),
        ShotBeat(t=0.5, subject="char_001", verb="look_at", face_to="char_002"),
        ShotBeat(t=0.6, subject="char_002", verb="nod", pace="slow"),
    ]


# --------------------------------------------------------------------------- #
# 词表的单一真源
# --------------------------------------------------------------------------- #
def test_the_verb_table_is_the_motion_table_not_a_copy():
    """红线 R-7：动词词表**导入**自 `motion/model.py`，不是第二份手抄。"""
    assert BEAT_VERBS == ACTION_TYPES
    assert BEAT_VERBS is ACTION_TYPES, "必须是同一个对象，不是内容相同的副本"


def test_the_semantic_verbs_are_registered_in_the_motion_table():
    """语义动词（入场/出场/道具交互）必须先落进 motion 的表，再被契约导入。"""
    for verb in ("enter_from", "exit_frame", "place_prop", "pick_up", "hand_to"):
        assert verb in ACTION_TYPES
        assert verb in BEAT_VERBS


def test_shotbeat_is_not_scenebrief_beats():
    """两个 `beats` 概念不同：字段集必须不相交（防合并/防互相喂入）。"""
    from dataclasses import fields

    from block_director.contracts.brief import SceneBrief

    # SceneBrief.beats 的元素是叙事节拍 dict；ShotBeat 是执行拍点。
    narrative_keys = {"id", "summary", "participants", "emotion", "function"}
    beat_keys = {item.name for item in fields(ShotBeat)}
    assert beat_keys == {"t", "subject", "verb", "target", "face_to", "pace",
                         "react"}
    assert not (beat_keys & narrative_keys), (
        "ShotBeat 的字段与叙事节拍的字段重叠了：两个概念开始糊在一起")
    # 反向哨兵：SceneBrief 仍然有它自己的 beats（不是本模块的）。
    assert "beats" in {item.name for item in fields(SceneBrief)}


# --------------------------------------------------------------------------- #
# serde
# --------------------------------------------------------------------------- #
def test_beat_round_trips_through_dict():
    beat = ShotBeat(t=0.25, subject="char_001", verb="sit", target="chair",
                    face_to="camera", pace="brisk", react="犹豫")
    assert ShotBeat.from_dict(beat.to_dict()) == beat
    # 缺键容错（旧响应没有新键）
    assert ShotBeat.from_dict({}).verb == ""
    assert ShotBeat.from_dict({"t": "0.5", "subject": " c "}).subject == "c"


def test_light_and_composition_and_justification_round_trip():
    light = LightSpec(time_of_day="night", mood="gloomy", key_direction="side")
    assert LightSpec.from_dict(light.to_dict()) == light
    assert LightSpec.from_dict({}).is_empty
    comp = CompositionSpec(rule="lead_room", subject_position="left_third")
    assert CompositionSpec.from_dict(comp.to_dict()) == comp
    assert CompositionSpec.from_dict({}).is_empty
    just = RuleJustification(rule="R001", action="break", reason="表现关系破裂",
                             precedent="《闪灵》")
    assert RuleJustification.from_dict(just.to_dict()) == just
    # action 缺省是 follow（不是空串——空串会让审计对拍少一类）
    assert RuleJustification.from_dict({}).action == "follow"


# --------------------------------------------------------------------------- #
# validate_beats 的不变量
# --------------------------------------------------------------------------- #
def test_a_well_formed_table_has_no_problems():
    assert validate_beats(_good_beats(), ["char_001", "char_002"],
                          ["door", "table"]) == []


def test_t_outside_the_unit_interval_is_reported():
    problems = validate_beats([ShotBeat(t=1.4, subject="c", verb="nod")], ["c"])
    assert any("不在 [0,1]" in item for item in problems)
    problems = validate_beats([ShotBeat(t=-0.1, subject="c", verb="nod")], ["c"])
    assert any("不在 [0,1]" in item for item in problems)


def test_out_of_order_beats_for_the_same_subject_are_reported():
    beats = [ShotBeat(t=0.6, subject="c", verb="nod"),
             ShotBeat(t=0.2, subject="c", verb="nod")]
    assert any("单调不减" in item for item in validate_beats(beats, ["c"]))
    # 不同 subject 之间互不约束（两个角色的拍点本来就交错）
    ok = [ShotBeat(t=0.6, subject="a", verb="nod"),
          ShotBeat(t=0.2, subject="b", verb="nod")]
    assert validate_beats(ok, ["a", "b"]) == []


def test_unknown_subject_and_target_are_reported():
    beats = [ShotBeat(t=0.1, subject="char_999", verb="nod", target="ghost")]
    problems = validate_beats(beats, ["char_001"], ["door"])
    assert any("不在本镜角色里" in item for item in problems)
    assert any("既不在角色表也不在锚点表里" in item for item in problems)
    # 锚点表未知（None）时不报锚点那一半——"未知"与"空"不是一回事
    assert validate_beats([ShotBeat(t=0.1, subject="char_001", verb="nod",
                                    target="door")], ["char_001"]) == []
    # 角色也未知时同样不报（离线替身/单测的常见输入）
    assert validate_beats([ShotBeat(t=0.1, subject="who", verb="nod")]) == []


def test_unknown_verb_is_reported_with_the_domain():
    problems = validate_beats([ShotBeat(t=0.1, subject="c", verb="backflip")], ["c"])
    assert any("不在动词闭集内" in item for item in problems)
    assert any("walk_to" in item for item in problems)   # 报错里带合法取值


def test_face_to_and_pace_outside_their_domains_are_reported():
    beats = [ShotBeat(t=0.1, subject="c", verb="look_at", face_to="up",
                      pace="fast")]
    problems = validate_beats(beats, ["c"])
    assert any("face_to" in item for item in problems)
    assert any("pace" in item for item in problems)
    # 闭集内合法
    for value in FACE_TO_VALUES:
        assert validate_beats([ShotBeat(t=0.1, subject="c", verb="look_at",
                                        face_to=value)], ["c"]) == []
    for value in PACE_VALUES:
        assert validate_beats([ShotBeat(t=0.1, subject="c", verb="nod",
                                        pace=value)], ["c"]) == []
    # face_to 也允许角色 id
    assert validate_beats([ShotBeat(t=0.1, subject="c", verb="look_at",
                                    face_to="other")], ["c", "other"]) == []


def test_too_many_beats_are_reported():
    beats = [ShotBeat(t=i / (MAX_BEATS + 1), subject="c", verb="nod")
             for i in range(MAX_BEATS + 1)]
    assert any("超过上限" in item for item in validate_beats(beats, ["c"]))
    assert validate_beats(beats[:MAX_BEATS], ["c"]) == []


def test_missing_subject_is_reported():
    assert any("缺少 subject" in item
               for item in validate_beats([ShotBeat(t=0.1, verb="nod")]))


# --------------------------------------------------------------------------- #
# 三个小规格的闭集校验
# --------------------------------------------------------------------------- #
def test_light_spec_domains():
    assert validate_light_spec(LightSpec()) == []
    for value in TIME_OF_DAY_VALUES:
        assert validate_light_spec(LightSpec(time_of_day=value)) == []
    for value in LIGHT_MOOD_VALUES:
        assert validate_light_spec(LightSpec(mood=value)) == []
    for value in KEY_DIRECTION_VALUES:
        assert validate_light_spec(LightSpec(key_direction=value)) == []
    assert validate_light_spec(LightSpec(time_of_day="noon"))
    assert validate_light_spec({"mood": "非常压抑"})


def test_composition_spec_domains():
    assert validate_composition_spec(CompositionSpec()) == []
    for rule in COMPOSITION_RULES:
        assert validate_composition_spec(CompositionSpec(rule=rule)) == []
    for position in SUBJECT_POSITIONS:
        assert validate_composition_spec(
            CompositionSpec(subject_position=position)) == []
    assert validate_composition_spec(CompositionSpec(rule="golden_spiral"))
    assert validate_composition_spec({"subject_position": "middle"})


def test_justification_requires_a_reason_when_breaking():
    assert validate_justifications([]) == []
    assert validate_justifications(
        [RuleJustification(rule="R001", action="follow")]) == []
    broken = validate_justifications(
        [RuleJustification(rule="R001", action="break")])
    assert any("没写 reason" in item for item in broken)
    ok = validate_justifications(
        [RuleJustification(rule="R001", action="break", reason="关系破裂")])
    assert ok == []
    assert any("缺少 rule" in item for item in validate_justifications(
        [RuleJustification(action="follow")]))
    assert any("action" in item for item in validate_justifications(
        [RuleJustification(rule="R001", action="ignore")]))
    assert RULE_ACTIONS == ("follow", "break")


# --------------------------------------------------------------------------- #
# 纯层：无 bpy
# --------------------------------------------------------------------------- #
def test_beats_module_imports_without_bpy():
    """红线 R-1：契约层在**没有 bpy** 的解释器里也必须可导入。"""
    result = subprocess.run(
        [sys.executable, "-c",
         "import sys, block_director.contracts.beats as b;"
         "print('bpy' in sys.modules)"],
        capture_output=True, text=True, cwd=str(ROOT), encoding="utf-8")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False", "契约层把 bpy 拉进来了"
