"""§9.6 / §9.7 动作库与混合的纯计算测试。"""

from __future__ import annotations

import math

import pytest

from block_director.motion.model import (
    BLEND_FRAMES,
    CH_BODY_ROT_X,
    CH_HEAD_ROT_X,
    CH_HEAD_ROT_Z,
    CH_LEG_L,
    CH_LEG_R,
    CH_ROOT_LOC,
    CH_ROOT_ROT_Z,
    LAYER_BASE,
    LAYER_BODY,
    LAYER_HEAD,
    LAYER_LEGS,
    LAYER_OF,
    ActionRequest,
    check_conflicts,
    compose,
    expand,
    head_track_angles,
)


def walk(start=1, end=48, target=(2.0, 0.0, 0.0)):
    return ActionRequest("walk_to", start, end,
                         {"from": (0.0, 0.0, 0.0), "target_position": target,
                          "speed": "walk"})


def layers_of(request):
    return {spec.layer for spec in expand(request)}


def channels_of(request):
    return {ch for spec in expand(request) for ch in spec.channels}


# --------------------------------------------------------------------------- #
# 层归属与展开
# --------------------------------------------------------------------------- #
def test_layer_table_matches_document():
    assert LAYER_OF["walk_to"] == LAYER_BASE
    assert LAYER_OF["turn_head"] == LAYER_HEAD
    assert LAYER_OF["fall_down"] == LAYER_BODY
    assert LAYER_OF["sit"] == LAYER_BODY
    assert LAYER_OF["jump"] == LAYER_BASE


def test_walk_expands_to_base_and_legs():
    assert layers_of(walk()) == {LAYER_BASE, LAYER_LEGS}
    assert channels_of(walk()) == {CH_ROOT_LOC, CH_ROOT_ROT_Z, CH_LEG_L, CH_LEG_R}


def test_run_adds_body_lean():
    run = ActionRequest("run_to", 1, 24,
                        {"from": (0, 0, 0), "target_position": (3, 0, 0)})
    assert layers_of(run) == {LAYER_BASE, LAYER_LEGS, LAYER_BODY}
    assert CH_BODY_ROT_X in channels_of(run)


def test_unknown_action_raises():
    with pytest.raises(ValueError):
        expand(ActionRequest("backflip", 1, 10))


def test_layer_channel_ownership_is_disjoint():
    """分层之所以能并行，是因为各层写的通道互不重叠。"""
    owners = {}
    for kind in ("walk_to", "run_to", "turn_body", "jump", "body_tilt",
                 "fall_down", "sit", "stand", "turn_head", "look_at",
                 "nod", "shake_head"):
        for spec in expand(ActionRequest(kind, 1, 12)):
            for channel in spec.channels:
                assert channel not in owners or owners[channel] == spec.layer, (
                    f"{channel} 同时被 {owners.get(channel)} 和 {spec.layer} 写入")
                owners[channel] = spec.layer


# --------------------------------------------------------------------------- #
# 姿态数值
# --------------------------------------------------------------------------- #
def test_walk_moves_root_and_faces_target():
    trace = compose([walk(1, 48, (2.0, 0.0, 0.0))])
    assert trace[1][CH_ROOT_LOC][0] == pytest.approx(0.0)
    assert trace[48][CH_ROOT_LOC][0] == pytest.approx(2.0)
    # 朝 +X 走 → 绕 Z 旋转 -90°。
    # 角色正面是局部 +Y，绕 Z 转 θ 后世界朝向为 (-sin θ, cos θ)；
    # 取 θ = -π/2 才得到 (1, 0)。v1.2 断言的是 +π/2，那会让角色面朝 -X
    # 也就是"倒着走"——这正是 P0-1 修正的镜像缺陷。
    theta = trace[48][CH_ROOT_ROT_Z]
    assert theta == pytest.approx(-math.pi / 2)
    # 直接断言真正的不变量：脸的朝向 == 移动方向。
    assert -math.sin(theta) == pytest.approx(1.0)
    assert math.cos(theta) == pytest.approx(0.0, abs=1e-9)


def test_walk_faces_a_diagonal_target():
    """斜向走位同样要面朝目标，而不是它的镜像。"""
    trace = compose([walk(1, 48, (2.0, 2.0, 0.0))])
    theta = trace[48][CH_ROOT_ROT_Z]
    assert -math.sin(theta) == pytest.approx(math.sqrt(0.5), abs=1e-6)
    assert math.cos(theta) == pytest.approx(math.sqrt(0.5), abs=1e-6)


def test_leg_swing_is_antisymmetric():
    trace = compose([walk(1, 48)])
    for frame in (12, 24, 36):
        assert trace[frame][CH_LEG_L] == pytest.approx(-trace[frame][CH_LEG_R])
    assert max(abs(trace[f][CH_LEG_L]) for f in range(1, 49)) > math.radians(15)


def test_head_yaw_is_clamped_to_90_degrees():
    """§9.3：头部水平旋转 ±90°。"""
    request = ActionRequest("turn_head", 1, 24, {"angle_deg": 200.0})
    trace = compose([request])
    assert trace[24][CH_HEAD_ROT_Z] == pytest.approx(math.radians(90.0))


def test_nod_only_touches_head_pitch():
    trace = compose([ActionRequest("nod", 1, 24, {"cycles": 2})])
    keys = set().union(*(pose.keys() for pose in trace.values()))
    assert keys == {CH_HEAD_ROT_X}
    assert max(abs(trace[f][CH_HEAD_ROT_X]) for f in trace) <= math.radians(10.5)


def test_shake_head_uses_yaw_channel():
    trace = compose([ActionRequest("shake_head", 1, 24)])
    keys = set().union(*(pose.keys() for pose in trace.values()))
    assert keys == {CH_HEAD_ROT_Z}


def test_fall_down_reaches_ninety_degrees():
    trace = compose([ActionRequest("fall_down", 1, 72)])
    assert trace[72][CH_BODY_ROT_X] == pytest.approx(math.pi / 2, abs=1e-6)
    # 三阶段：中途应小于终值
    assert trace[30][CH_BODY_ROT_X] < trace[72][CH_BODY_ROT_X]


def test_sit_then_stand_returns_to_ground():
    """先坐后站必须精确回到地面——这正是"接管冻结"语义要保证的。"""
    trace = compose([ActionRequest("sit", 1, 24, {"drop": 0.2}),
                     ActionRequest("stand", 25, 48, {"drop": 0.2})])
    assert trace[24][CH_ROOT_LOC][2] == pytest.approx(-0.2, abs=1e-6)
    assert trace[48][CH_ROOT_LOC][2] == pytest.approx(0.0, abs=1e-4)


def test_base_pose_preserves_placement():
    """坐下不得把角色从摆位拽回原点——Phase 4 落场景时发现的缺陷。"""
    trace = compose([ActionRequest("sit", 1, 24, {"drop": 0.2})],
                    base_pose={CH_ROOT_LOC: (0.75, 0.0, 0.0)})
    assert trace[1][CH_ROOT_LOC] == pytest.approx((0.75, 0.0, 0.0))
    assert trace[24][CH_ROOT_LOC] == pytest.approx((0.75, 0.0, -0.2))


def test_jump_is_a_parabola():
    trace = compose([ActionRequest("jump", 1, 24, {"height": 0.3})])
    heights = [trace[f][CH_ROOT_LOC][2] for f in range(1, 25)]
    assert min(heights) == pytest.approx(0.0, abs=1e-6)
    assert max(heights) == pytest.approx(0.3, abs=1e-2)
    assert heights.index(max(heights)) in range(10, 15)


# --------------------------------------------------------------------------- #
# 跨层合成
# --------------------------------------------------------------------------- #
def test_layers_compose_together():
    """走位（base+legs）与点头（head）可同时存在，互不覆盖。"""
    trace = compose([walk(1, 48), ActionRequest("nod", 1, 48)])
    frame = trace[24]
    assert CH_ROOT_LOC in frame and CH_LEG_L in frame and CH_HEAD_ROT_X in frame


def test_same_layer_actions_accumulate_without_resetting():
    """转身 90° 再接转身 90° 应得到 180°，且交接处连续。"""
    first = ActionRequest("turn_body", 1, 30, {"angle_deg": 90.0})
    second = ActionRequest("turn_body", 31, 60, {"angle_deg": 90.0})
    trace = compose([first, second])
    assert trace[30][CH_ROOT_ROT_Z] == pytest.approx(math.radians(90.0))
    assert trace[31][CH_ROOT_ROT_Z] == pytest.approx(math.radians(90.0), abs=1e-3)
    assert trace[60][CH_ROOT_ROT_Z] == pytest.approx(math.radians(180.0))
    values = [trace[f][CH_ROOT_ROT_Z] for f in range(1, 61)]
    assert all(b >= a - 1e-6 for a, b in zip(values, values[1:])), "转身过程不得回退"


# --------------------------------------------------------------------------- #
# 冲突仲裁（§9.7）
# --------------------------------------------------------------------------- #
def test_walk_plus_fall_is_rejected_when_overlapping():
    problems = check_conflicts([walk(1, 48), ActionRequest("fall_down", 20, 60)])
    assert problems and "语义冲突" in problems[0]


def test_walk_then_fall_is_allowed():
    """§9.7 的补救方式就是"先结束移动"——串行执行合法。"""
    assert check_conflicts([walk(1, 48),
                            ActionRequest("fall_down", 49, 90)]) == []


def test_walk_plus_jump_is_rejected_when_overlapping():
    assert check_conflicts([walk(1, 48), ActionRequest("jump", 10, 20)])


def test_walk_then_sit_is_allowed():
    assert check_conflicts([walk(1, 48), ActionRequest("sit", 49, 72)]) == []


def test_look_at_combines_with_walk():
    assert check_conflicts([walk(1, 48), ActionRequest("look_at", 1, 48)]) == []


# --------------------------------------------------------------------------- #
# v1.3 诉求 2：头部跟踪目标（不能只转固定的 30°）
# --------------------------------------------------------------------------- #
def test_head_track_turns_toward_a_target_in_front():
    # 站在原点、面朝 +Y，目标在 +X 侧 → 需要向右偏 90°
    # v1.4 P10（§1.6 #17）：目标高度必须用**引擎自己的**眼睛高度，
    # 否则几何一改，这条断言就变成"量错但继续绿"。
    from block_director.motion.model import EYE_Z_DEFAULT

    yaw, pitch, note = head_track_angles((0, 0, 0), (0, 1, 0),
                                         (3, 0, EYE_Z_DEFAULT))
    assert yaw == pytest.approx(-90.0)      # facing_to_rotation_z 的约定
    assert pitch == pytest.approx(0.0)
    assert note == ""


def test_head_track_is_zero_when_the_target_is_straight_ahead():
    from block_director.motion.model import EYE_Z_DEFAULT

    yaw, pitch, _note = head_track_angles((0, 0, 0), (0, 1, 0),
                                          (0, 5, EYE_Z_DEFAULT))
    assert yaw == pytest.approx(0.0)
    assert pitch == pytest.approx(0.0)


def test_head_track_clamps_and_warns_about_a_target_behind():
    """头部只有 ±90°：目标在身后必须提示去转身体，而不是硬拧。"""
    from block_director.motion.model import EYE_Z_DEFAULT

    yaw, _pitch, note = head_track_angles((0, 0, 0), (0, 1, 0),
                                          (0, -5, EYE_Z_DEFAULT))
    assert abs(yaw) <= 90.0 + 1e-6
    assert "身体后方" in note and "face_character" in note


def test_head_track_pitches_for_a_high_target():
    _yaw, pitch, _note = head_track_angles((0, 0, 0), (0, 1, 0),
                                           (0, 10, 3.10))
    assert pitch > 0.0
    assert pitch <= 30.0 + 1e-6             # HEAD_LIMIT_X


def test_head_track_handles_a_coincident_target():
    yaw, pitch, note = head_track_angles((1, 1, 0), (0, 1, 0), (1, 1, 0))
    assert yaw == 0.0 and pitch == 0.0
    assert "重合" in note


def test_two_characters_facing_each_other_need_no_head_turn():
    """相对而立时，两人看对方是 0°——这正是不该再靠扭头硬凑的原因。"""
    a_pos, a_face = (-0.9, 0.0, 0.0), (1.0, 0.0, 0.0)
    b_pos, b_face = (0.9, 0.0, 0.0), (-1.0, 0.0, 0.0)
    yaw_a, _p, note_a = head_track_angles(a_pos, a_face, b_pos)
    yaw_b, _p, note_b = head_track_angles(b_pos, b_face, a_pos)
    assert yaw_a == pytest.approx(0.0) and yaw_b == pytest.approx(0.0)
    assert note_a == "" and note_b == ""


def test_overlapping_same_layer_actions_are_reported():
    problems = check_conflicts([walk(1, 48), ActionRequest("turn_body", 20, 60)])
    assert any("同层动作必须串行" in p for p in problems)


def test_sequential_same_layer_actions_are_allowed():
    assert check_conflicts([ActionRequest("turn_body", 1, 30),
                            ActionRequest("turn_body", 31, 60)]) == []


def test_tail_blend_window_keeps_pose_after_end():
    """动作结束后仍有 BLEND_FRAMES 帧保持姿态，供下一个动作平滑接管。"""
    trace = compose([ActionRequest("turn_body", 1, 24, {"angle_deg": 90.0})])
    assert max(trace) == 24 + BLEND_FRAMES
    assert trace[24 + BLEND_FRAMES][CH_ROOT_ROT_Z] == pytest.approx(math.radians(90.0))
