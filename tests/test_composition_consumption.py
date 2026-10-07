"""构图声明 → 对准点偏移（执行文档 v1.5 卡 P3-T4 / TDD §4.6）。

纯层用例：钉住"每一档声明翻成什么偏移"，以及**空声明 = 求解器默认、
逐字节不动**这条（它是 G3 对照的分母）。
"""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.cinema.station import (  # noqa: E402
    LEAD_ROOM_OFFSET,
    aim_offset_for_composition,
    aim_offset_for_lead_room,
)
from block_director.contracts.beats import (  # noqa: E402
    COMPOSITION_RULES,
    SUBJECT_POSITIONS,
    CompositionSpec,
)

#: 机位在主体 +Y（`direction` 是"主体 → 机位"），主体朝 +X 写实。
DIRECTION = (0.0, 1.0)
FACING = (1.0, 0.0)


# --------------------------------------------------------------------------- #
# 空声明：必须原样返回默认值（= 接线前的行为）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("default", [0.0, 0.2, -0.3, LEAD_ROOM_OFFSET])
@pytest.mark.parametrize("empty", [None, {}, {"rule": "", "subject_position": ""},
                                   CompositionSpec()])
def test_an_empty_declaration_returns_the_default_untouched(empty, default):
    assert aim_offset_for_composition(empty, DIRECTION, FACING,
                                      default=default) == default


def test_a_missing_declaration_matches_the_lead_room_default():
    """单主体镜头的默认值就是 §10.4 的视线留白——空声明不许改它。"""
    default = aim_offset_for_lead_room(DIRECTION, FACING)
    assert aim_offset_for_composition({}, DIRECTION, FACING,
                                      default=default) == default


# --------------------------------------------------------------------------- #
# subject_position：横向落点，正 = 朝画面右侧偏
# --------------------------------------------------------------------------- #
def test_left_third_pushes_the_aim_right_by_a_sixth_of_the_frame():
    assert aim_offset_for_composition(
        {"subject_position": "left_third"}, DIRECTION, FACING) == LEAD_ROOM_OFFSET


def test_right_third_pushes_the_aim_left_by_a_sixth_of_the_frame():
    assert aim_offset_for_composition(
        {"subject_position": "right_third"}, DIRECTION, FACING) == -LEAD_ROOM_OFFSET


def test_explicit_center_puts_the_subject_back_in_the_middle():
    assert aim_offset_for_composition(
        {"subject_position": "center"}, DIRECTION, FACING, default=0.2) == 0.0


def test_the_two_thirds_positions_are_mirror_images_of_each_other():
    left = aim_offset_for_composition({"subject_position": "left_third"},
                                      DIRECTION, FACING)
    right = aim_offset_for_composition({"subject_position": "right_third"},
                                       DIRECTION, FACING)
    assert left == -right
    assert abs(left) == LEAD_ROOM_OFFSET


# --------------------------------------------------------------------------- #
# rule：求解器默认的显式覆盖
# --------------------------------------------------------------------------- #
def test_rule_center_and_symmetry_override_the_thirds_default():
    for rule in ("center", "symmetry"):
        assert aim_offset_for_composition({"rule": rule}, DIRECTION, FACING,
                                          default=LEAD_ROOM_OFFSET) == 0.0


def test_rule_lead_room_is_the_facing_derived_offset():
    expected = aim_offset_for_lead_room(DIRECTION, FACING)
    assert aim_offset_for_composition({"rule": "lead_room"}, DIRECTION, FACING) == expected
    #: 主体**正对镜头**时没有视线留白可言（与底层函数同一条纪律）。
    facing_camera = (-DIRECTION[0], -DIRECTION[1], 0.0)
    assert aim_offset_for_composition({"rule": "lead_room"}, DIRECTION,
                                      facing_camera) == 0.0


@pytest.mark.parametrize("rule", ["thirds", "diagonal", "frame_within_frame"])
def test_rules_the_solver_does_not_implement_fall_back_to_the_default(rule):
    """`diagonal`/`frame_within_frame` 本版只记录，不改几何（TDD §4.6）。"""
    assert aim_offset_for_composition({"rule": rule}, DIRECTION, FACING,
                                      default=0.2) == 0.2


# --------------------------------------------------------------------------- #
# 组合与容错
# --------------------------------------------------------------------------- #
def test_the_more_specific_subject_position_wins_over_the_rule():
    """`subject_position` 直接说主体站哪；`rule` 是构图法 ⇒ 前者优先。"""
    assert aim_offset_for_composition(
        {"rule": "center", "subject_position": "left_third"},
        DIRECTION, FACING) == LEAD_ROOM_OFFSET
    assert aim_offset_for_composition(
        {"rule": "lead_room", "subject_position": "center"},
        DIRECTION, FACING, default=LEAD_ROOM_OFFSET) == 0.0


def test_a_composition_spec_instance_is_accepted_directly():
    spec = CompositionSpec(rule="center")
    assert aim_offset_for_composition(spec, DIRECTION, FACING,
                                      default=LEAD_ROOM_OFFSET) == 0.0


@pytest.mark.parametrize("unknown", [{"rule": "unknown_rule"},
                                     {"subject_position": "unknown_position"},
                                     "not-a-mapping", 3])
def test_values_outside_the_closed_sets_fall_back_and_never_raise(unknown):
    """校验层会拦下这些值；求解器这一层不许因为它们崩掉——退回默认。"""
    assert aim_offset_for_composition(unknown, DIRECTION, FACING,
                                      default=0.25) == 0.25


def test_every_handled_value_really_lives_in_the_contract_closed_sets():
    handled_positions = {"left_third", "right_third", "center"}
    handled_rules = {"center", "symmetry", "lead_room", "thirds",
                     "diagonal", "frame_within_frame"}
    assert handled_positions <= set(SUBJECT_POSITIONS)
    assert handled_rules <= set(COMPOSITION_RULES)
