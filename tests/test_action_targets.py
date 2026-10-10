"""卡 G8-C：结构化 look/hand 目标（look_at.target / hand_to.toward / 拍点 target）。

真跑现场（v10–v13，``work/_g2_ds_run/blender_v1*.log``）：模型反复写
``look_at.to`` / ``look_at.toward`` / ``look_at.target_position`` = 角色、
拍点 target = 场外角色（'伊恩' 不在本镜）或坐标字符串（'[2,0,0]'）、
``hand_to.to`` = 角色。用户裁决：把这些提成一等公民；屏幕相对词
（screen_left / screen_right / front / 画面中心 / left_third / 左侧三分位）
照旧拒绝。
"""

from __future__ import annotations

import math

import pytest

from block_director.cinema.anchor import DEFAULT_PROFILE
from block_director.contracts.beats import ShotBeat, validate_beats
from block_director.layer5_orchestrator.beat_compiler import (
    resolve_action_targets,
)
from block_director.motion import model as M
from block_director.motion.targets import (
    TargetError,
    facing_degrees,
    looks_like_coordinate_string,
    resolve_target,
    target_kind,
    yaw_pitch_to,
)

EYE = DEFAULT_PROFILE.eye_z


# --------------------------------------------------------------------------- #
# 目标形状与解析（targets.py）
# --------------------------------------------------------------------------- #
def test_target_kind_accepts_exactly_the_three_shapes():
    assert target_kind("伊恩") == "character"
    assert target_kind({"character": "伊恩"}) == "character"
    assert target_kind({"point": [2.0, 0.0, 0.0]}) == "point"
    #: 非法形状一律 None：缺键 / 多键 / 分量不是 3 个数字 / 空串。
    assert target_kind("") is None
    assert target_kind({"character": ""}) is None
    assert target_kind({"character": 3}) is None
    assert target_kind({"point": [1.0, 2.0]}) is None
    assert target_kind({"point": ["x", 0, 0]}) is None
    assert target_kind({"character": "a", "point": [1, 2, 3]}) is None
    assert target_kind(3) is None
    assert target_kind([1.0, 0.0, 0.0]) is None


def test_resolve_target_accepts_all_three_shapes():
    cast = {"伊恩": (3.0, -1.0, 0.0)}
    assert resolve_target("伊恩", cast) == (3.0, -1.0, 0.0)
    assert resolve_target({"character": "伊恩"}, cast) == (3.0, -1.0, 0.0)
    assert resolve_target({"point": [2.0, 0.0, 0.5]}, cast) == (2.0, 0.0, 0.5)


def test_resolve_target_never_defaults_to_zero():
    with pytest.raises(TargetError) as excinfo:
        resolve_target("不在场", {"伊恩": (1.0, 0.0, 0.0)})
    assert "不在场" in str(excinfo.value)
    with pytest.raises(TargetError) as excinfo:
        resolve_target({"character": "不在场"}, {"伊恩": (1.0, 0.0, 0.0)})
    assert "不在场" in str(excinfo.value)
    with pytest.raises(TargetError) as excinfo:
        resolve_target({"point": [1, 2]}, {"伊恩": (1.0, 0.0, 0.0)})
    assert "无法理解" in str(excinfo.value)


def test_coordinate_looking_strings_are_detected():
    assert looks_like_coordinate_string("[2,0,0]")
    assert looks_like_coordinate_string("1.15,0")
    assert looks_like_coordinate_string("(2, 0, 0)")
    assert not looks_like_coordinate_string("screen_right")
    assert not looks_like_coordinate_string("伊恩")
    assert not looks_like_coordinate_string("[x, y, z]")


def test_facing_degrees_matches_the_facing_convention():
    assert facing_degrees((0.0, 1.0)) == pytest.approx(0.0, abs=1e-9)
    #: facing_to_rotation_z 的约定：面朝 +X ⇒ θ = atan2(-1, 0) = -90°。
    assert facing_degrees((1.0, 0.0)) == pytest.approx(-90.0, abs=1e-9)
    assert facing_degrees((-1.0, 0.0)) == pytest.approx(90.0, abs=1e-9)


# --------------------------------------------------------------------------- #
# yaw/pitch 几何：0 方向与符号和既有 look_at 逐字节同源
# --------------------------------------------------------------------------- #
def test_yaw_pitch_front_is_zero():
    yaw, pitch = yaw_pitch_to((0.0, 0.0, 0.0), 0.0, (0.0, 5.0, EYE), EYE)
    assert yaw == pytest.approx(0.0, abs=1e-6)
    assert pitch == pytest.approx(0.0, abs=1e-6)


def test_yaw_pitch_left_right_signs():
    #: 面朝 +Y，目标在 +X（身体右侧）→ yaw = -90；左侧 → +90。
    yaw_right, _ = yaw_pitch_to((0.0, 0.0, 0.0), 0.0, (3.0, 0.0, EYE), EYE)
    yaw_left, _ = yaw_pitch_to((0.0, 0.0, 0.0), 0.0, (-3.0, 0.0, EYE), EYE)
    assert yaw_right == pytest.approx(-90.0, abs=1e-6)
    assert yaw_left == pytest.approx(90.0, abs=1e-6)


def test_yaw_pitch_back_is_clamped_like_head_track():
    yaw, pitch = yaw_pitch_to((0.0, 0.0, 0.0), 0.0, (0.0, -5.0, EYE), EYE)
    assert abs(yaw) <= 90.0 + 1e-6
    assert pitch == pytest.approx(0.0, abs=1e-6)


def test_yaw_pitch_up_down_signs():
    _yaw, pitch_up = yaw_pitch_to((0.0, 0.0, 0.0), 0.0,
                                  (0.0, 10.0, EYE + 2.0), EYE)
    _yaw, pitch_down = yaw_pitch_to((0.0, 0.0, 0.0), 0.0,
                                    (0.0, 10.0, EYE - 2.0), EYE)
    assert pitch_up > 0.0
    assert pitch_down < 0.0
    assert pitch_up == pytest.approx(-pitch_down, abs=1e-6)


def test_yaw_pitch_is_byte_identical_to_head_track_angles():
    """同一个朝向、同一份几何：新函数必须**逐字节复用**既有 look_at 约定。"""
    from block_director.motion.model import head_track_angles

    theta = math.radians(37.0)
    facing = (-math.sin(theta), math.cos(theta))
    origin, target = (1.0, 2.0, 0.0), (4.0, -1.0, 2.0)
    yaw_a, pitch_a = yaw_pitch_to(origin, 37.0, target, EYE)
    yaw_b, pitch_b, _note = head_track_angles(origin, facing, target,
                                              eye_height=EYE)
    assert yaw_a == yaw_b
    assert pitch_a == pitch_b


# --------------------------------------------------------------------------- #
# validate_beats：full_cast 给与不给的两套口径
# --------------------------------------------------------------------------- #
def test_full_cast_allows_an_off_shot_character_as_target_but_not_as_subject():
    beats = [ShotBeat(t=0.1, subject="a", verb="walk_to", target="b")]
    assert validate_beats(beats, ["a"], full_cast=["a", "b"]) == []
    off_subject = [ShotBeat(t=0.1, subject="b", verb="nod")]
    problems = validate_beats(off_subject, ["a"], full_cast=["a", "b"])
    assert any("不在本镜角色里" in item for item in problems)


def test_full_cast_accepts_structured_targets():
    beats = [
        ShotBeat(t=0.0, subject="a", verb="walk_to",
                 target={"point": [2.0, 0.0, 0.0]}),
        ShotBeat(t=0.5, subject="a", verb="look_at",
                 target={"character": "b"}),
    ]
    assert validate_beats(beats, ["a"], full_cast=["a", "b"]) == []
    bad = validate_beats(
        [ShotBeat(t=0.1, subject="a", verb="nod",
                  target={"character": "zz"})],
        ["a"], full_cast=["a", "b"])
    assert any("不在全剧组" in item for item in bad)


def test_full_cast_still_accepts_anchor_names():
    beats = [ShotBeat(t=0.1, subject="a", verb="walk_to", target="door")]
    assert validate_beats(beats, ["a"], ["door"], full_cast=["a"]) == []


def test_screen_relative_strings_stay_rejected_with_full_cast():
    for value in ("screen_left", "screen_right", "front", "画面中心",
                  "left_third", "左侧三分位"):
        problems = validate_beats(
            [ShotBeat(t=0.1, subject="a", verb="walk_to", target=value)],
            ["a"], full_cast=["a", "b"])
        assert problems, f"{value!r} 必须仍被拒绝"


def test_coordinate_strings_are_rejected_with_the_point_hint():
    for value in ("[2,0,0]", "1.15,0"):
        problems = validate_beats(
            [ShotBeat(t=0.1, subject="a", verb="walk_to", target=value)],
            ["a"], full_cast=["a", "b"])
        assert len(problems) == 1
        assert '{"point": [x, y, z]}' in problems[0]


def test_without_full_cast_behaviour_is_unchanged():
    """未传 full_cast：报错文案与历史逐字节一致（G8-C 的回归边界）。"""
    problems = validate_beats(
        [ShotBeat(t=0.1, subject="char_001", verb="nod", target="ghost")],
        ["char_001"], ["door"])
    assert problems == [
        "第 1 个拍点的 target='ghost' 既不在角色表也不在锚点表里"]
    #: 锚点表未知 → 跳过锚点那一半（"未知"与"空"不是一回事）。
    assert validate_beats(
        [ShotBeat(t=0.1, subject="char_001", verb="nod", target="door")],
        ["char_001"]) == []
    #: 结构化目标在未传 full_cast 时按旧的字符串化口径走，不抛 TypeError。
    problems = validate_beats(
        [ShotBeat(t=0.1, subject="c", verb="nod",
                  target={"point": [2.0, 0.0, 0.0]})],
        ["c"], ["door"])
    assert any("既不在角色表" in item for item in problems)


def test_shotbeat_round_trips_structured_targets():
    beat = ShotBeat(t=0.25, subject="a", verb="look_at",
                    target={"character": "b"})
    assert ShotBeat.from_dict(beat.to_dict()) == beat
    assert ShotBeat.from_dict(
        {"t": 0.5, "subject": "a", "verb": "walk_to",
         "target": {"point": [2.0, 0.0, 0.0]}}).target == {
        "point": [2.0, 0.0, 0.0]}


# --------------------------------------------------------------------------- #
# 模型级校验：look_at.target / hand_to.toward
# --------------------------------------------------------------------------- #
def test_look_at_target_is_a_known_param_in_all_three_shapes():
    assert M.unknown_action_params("look_at", {"target": "伊恩"}) == []
    assert M.action_param_problems("look_at", {"target": "伊恩"}) == []
    assert M.action_param_problems(
        "look_at", {"target": {"character": "伊恩"}}) == []
    assert M.action_param_problems(
        "look_at", {"target": {"point": [1.0, 2.0, 3.0]}}) == []


def test_look_at_target_conflicts_with_angles():
    problems = M.action_param_problems(
        "look_at", {"target": "伊恩", "yaw_deg": 30.0})
    assert any("不能同时写" in item for item in problems)
    problems = M.action_param_problems(
        "look_at", {"target": "伊恩", "pitch_deg": 5.0})
    assert any("不能同时写" in item for item in problems)


def test_look_at_target_malformed_shapes_are_rejected():
    assert M.action_param_problems("look_at", {"target": 3})
    assert M.action_param_problems("look_at", {"target": {"point": [1, 2]}})
    assert M.action_param_problems("look_at", {"target": {}})
    problems = M.action_param_problems("look_at", {"target": "[2,0,0]"})
    assert any('{"point": [x, y, z]}' in item for item in problems)


def test_hand_to_toward_accepts_existing_forms_and_structured_targets():
    assert M.action_param_problems("hand_to", {"toward": "left"}) == []
    assert M.action_param_problems(
        "hand_to", {"toward": [1.0, 0.0, 0.0]}) == []
    assert M.action_param_problems(
        "hand_to", {"toward": {"character": "伊恩"}}) == []
    assert M.action_param_problems(
        "hand_to", {"toward": {"point": [1.0, 2.0, 3.0]}}) == []


def test_hand_to_toward_still_rejects_words_numbers_and_string_coordinates():
    #: 既有判据一字不动：camera 不是方向词、裸数字不是方向量。
    assert M.action_param_problems("hand_to", {"toward": "camera"})
    assert M.action_param_problems("hand_to", {"toward": 3})
    assert M.action_param_problems("hand_to", {"toward": {"character": 3}})
    problems = M.action_param_problems("hand_to", {"toward": "[2,0,0]"})
    assert any('{"point": [x, y, z]}' in item for item in problems)


def test_expand_refuses_an_unresolved_look_at_target():
    """结构化 target 漏折算 = 确定性报错，绝不静默取默认 30°。"""
    with pytest.raises(M.MotionParamError) as excinfo:
        M.expand(M.ActionRequest("look_at", 1, 24, {"target": "伊恩"}))
    assert "未在编译层折算" in str(excinfo.value)
    #: 折算好的角度照旧走既有 look_at 路径（±90° 钳位、末帧到达）。
    specs = M.expand(M.ActionRequest(
        "look_at", 1, 24, {"yaw_deg": -90.0, "pitch_deg": 0.0}))
    pose = specs[0].pose_fn(24)
    assert pose[M.CH_HEAD_ROT_Z] == pytest.approx(math.radians(-90.0),
                                                  abs=1e-6)


# --------------------------------------------------------------------------- #
# 编译层转换（beat_compiler.resolve_action_targets）
# --------------------------------------------------------------------------- #
def test_compile_resolves_a_character_target_to_eye_level_gaze():
    params, problems = resolve_action_targets(
        "look_at", "a", {"target": "b"},
        {"a": (0.0, 0.0, 0.0), "b": (3.0, 0.0, 0.0)}, (0.0, 1.0))
    assert problems == []
    assert "target" not in params
    assert params["yaw_deg"] == pytest.approx(-90.0, abs=1e-6)
    assert params["pitch_deg"] == pytest.approx(0.0, abs=1e-6)


def test_compile_resolves_a_point_target_as_written():
    params, problems = resolve_action_targets(
        "look_at", "a", {"target": {"point": [0.0, 3.0, EYE + 1.0]}},
        {"a": (0.0, 0.0, 0.0)}, (0.0, 1.0))
    assert problems == []
    assert params["yaw_deg"] == pytest.approx(0.0, abs=1e-6)
    assert params["pitch_deg"] > 0.0


def test_compile_reports_an_unresolvable_target_and_keeps_params():
    params, problems = resolve_action_targets(
        "look_at", "a", {"target": "不在场"},
        {"a": (0.0, 0.0, 0.0)}, (0.0, 1.0))
    assert any("无法解析" in item and "不在场" in item for item in problems)
    assert params == {"target": "不在场"}
    params, problems = resolve_action_targets(
        "look_at", "a", {"target": "b", "yaw_deg": 10.0},
        {"a": (0.0, 0.0, 0.0), "b": (1.0, 0.0, 0.0)}, (0.0, 1.0))
    assert any("不能同时写" in item for item in problems)
    assert params == {"target": "b", "yaw_deg": 10.0}


def test_compile_resolves_prop_toward_to_a_direction_vector():
    params, problems = resolve_action_targets(
        "hand_to", "a", {"prop": "钱袋", "toward": {"character": "b"}},
        {"a": (0.0, 0.0, 0.0), "b": (3.0, -4.0, 0.0)}, (0.0, 1.0))
    assert problems == []
    assert params["toward"] == [3.0, -4.0, 0.0]
    params, problems = resolve_action_targets(
        "place_prop", "a", {"prop": "箱子",
                            "toward": {"point": [1.0, 2.0, 0.0]}},
        {"a": (0.0, 0.0, 0.0)}, (0.0, 1.0))
    assert problems == []
    assert params["toward"] == [1.0, 2.0, 0.0]


def test_compile_leaves_plain_actions_untouched():
    params, problems = resolve_action_targets(
        "walk_to", "a", {"target_position": [1.0, 0.0, 0.0]},
        {"a": (0.0, 0.0, 0.0)}, (0.0, 1.0))
    assert problems == []
    assert params == {"target_position": [1.0, 0.0, 0.0]}
