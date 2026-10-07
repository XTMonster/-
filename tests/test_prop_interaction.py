"""道具交互的纯逻辑（执行文档 v1.5 卡 P3-T3 / TDD §4.4）。纯 Python，不碰 bpy。"""

from __future__ import annotations

from block_director.cinema.anchor import DEFAULT_PROFILE, hand_offset
from block_director.cinema.props import (
    PROP_INTERACTION_ACTIONS,
    influence_keys,
    merge_windows,
    prop_interaction_windows,
)
from block_director.motion.model import PROP_ACTIONS


def test_the_verb_table_is_the_single_source():
    """动词表**导入** ``motion/model.py``，不在这里抄第二份（红线 R-7）。"""
    assert PROP_INTERACTION_ACTIONS == tuple(PROP_ACTIONS)
    assert set(PROP_INTERACTION_ACTIONS) == {"place_prop", "pick_up", "hand_to"}


def test_no_interaction_means_no_window():
    windows, problems = prop_interaction_windows(
        [{"character_id": "char_001", "action_type": "nod",
          "start_frame": 1, "end_frame": 24}],
        shot_id="shot_001", shot_start=1, duration_frames=96)
    assert windows == {} and problems == []


def test_a_prop_action_without_a_named_prop_is_a_pantomime():
    """``prop`` 为空的交互动作：角色侧动作照旧，但**没有对象要跟随**。"""
    windows, problems = prop_interaction_windows(
        [{"character_id": "char_001", "action_type": "pick_up",
          "start_frame": 5, "end_frame": 30, "params": {}}],
        shot_id="shot_001", shot_start=1, duration_frames=96)
    assert windows == {} and problems == []


def test_local_frames_are_folded_to_absolute_ones():
    """镜内局部帧 → 绝对帧走单一真源 ``action_frame_window``（夹回镜头内）。"""
    windows, _problems = prop_interaction_windows(
        [{"character_id": "char_001", "action_type": "pick_up",
          "start_frame": 10, "end_frame": 40, "params": {"prop": "cup"}}],
        shot_id="shot_002", shot_start=97, duration_frames=96)
    # 97 + 10 - 1 = 106；97 + 40 - 1 = 136
    assert windows["cup"] == [(106, 136)]


def test_an_overlong_window_is_clamped_into_the_shot():
    windows, _problems = prop_interaction_windows(
        [{"character_id": "char_001", "action_type": "hand_to",
          "start_frame": 1, "end_frame": 900, "params": {"prop": "cup"}}],
        shot_id="shot_001", shot_start=1, duration_frames=48)
    assert windows["cup"] == [(1, 48)]


def test_two_window_helpers_merge_neighbours_and_overlaps():
    assert merge_windows([(10, 20), (21, 30)]) == [(10, 30)]
    assert merge_windows([(10, 30), (20, 40)]) == [(10, 40)]
    assert merge_windows([(40, 50), (10, 20)]) == [(10, 20), (40, 50)]
    assert merge_windows([]) == []


def test_influence_keys_bracket_every_window():
    keys = influence_keys([(10, 20)])
    assert keys == [(9, 0.0), (10, 1.0), (20, 1.0), (21, 0.0)]
    # 从第 1 帧就开始：没有"第 0 帧"可写，首点省略
    assert influence_keys([(1, 12)]) == [(1, 1.0), (12, 1.0), (13, 0.0)]


def test_influence_keys_never_overlap_for_two_interactions():
    keys = influence_keys([(10, 20), (30, 40)])
    frames = [frame for frame, _value in keys]
    assert frames == sorted(set(frames))
    assert keys == [(9, 0.0), (10, 1.0), (20, 1.0), (21, 0.0),
                    (29, 0.0), (30, 1.0), (40, 1.0), (41, 0.0)]


def test_the_same_prop_interacted_twice_yields_two_windows():
    windows, _problems = prop_interaction_windows(
        [{"character_id": "char_001", "action_type": "pick_up",
          "start_frame": 1, "end_frame": 10, "params": {"prop": "cup"}},
         {"character_id": "char_001", "action_type": "hand_to",
          "start_frame": 40, "end_frame": 60, "params": {"prop": "cup"}}],
        shot_id="shot_001", shot_start=1, duration_frames=96)
    assert windows["cup"] == [(1, 10), (40, 60)]


def test_only_prop_verbs_produce_windows():
    """别的动词哪怕写了 ``prop`` 参数也不产生跟随窗（动词表是唯一入口）。"""
    windows, _problems = prop_interaction_windows(
        [{"character_id": "char_001", "action_type": "walk_to",
          "start_frame": 1, "end_frame": 10, "params": {"prop": "cup"}}],
        shot_id="shot_001", shot_start=1, duration_frames=96)
    assert windows == {}


# --------------------------------------------------------------------------- #
# 手部代理的落点（从冻结 profile 派生，不另写数字）
# --------------------------------------------------------------------------- #
def test_hand_offset_derives_from_the_frozen_profile():
    from block_director.cinema.anchor import HAND_PROXY_FORWARD, HAND_PROXY_SIDE

    offset = hand_offset(DEFAULT_PROFILE, 1.0)
    assert offset[0] == HAND_PROXY_SIDE
    assert offset[1] == HAND_PROXY_FORWARD
    # 高度是"相对髋部"的胸口高度 = chest_z − hip_z
    assert abs(offset[2] - (DEFAULT_PROFILE.chest_z
                            - DEFAULT_PROFILE.hip_z)) < 1e-12


def test_hand_offset_swaps_sides():
    left = hand_offset(DEFAULT_PROFILE, -1.0)
    right = hand_offset(DEFAULT_PROFILE, 1.0)
    assert left[0] == -right[0]
    assert left[1:] == right[1:]


def test_the_hand_proxy_stays_inside_the_torso_silhouette_envelope():
    """代理不该跑到躯干包围盒外面太远——它是"手"，不是新几何。"""
    offset = hand_offset(DEFAULT_PROFILE, 1.0)
    assert 0.0 < offset[0] <= 0.30
    assert 0.0 < offset[1] <= 0.35
    assert DEFAULT_PROFILE.hip_z < offset[2] + DEFAULT_PROFILE.hip_z \
        <= DEFAULT_PROFILE.torso_top_z
