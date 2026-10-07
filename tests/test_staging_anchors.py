"""场级摆位锚点求解（执行文档 v1.5 卡 P3-T2 / TDD §4.3）。纯 Python，不碰 bpy。"""

from __future__ import annotations

import math

from block_director.cinema.staging import (
    DEFAULT_ANCHOR_DISTANCE,
    parse_relation,
    solve_anchor_positions,
)

#: 甲 站在原点朝 +X（右）；乙 站在 x=+4 朝 -X。坐标系 Z-up、X=右、Y=前。
CAST = {
    "char_001": {"position": (0.0, 0.0, 0.0), "facing": (1.0, 0.0, 0.0)},
    "char_002": {"position": (4.0, 0.0, 0.0), "facing": (-1.0, 0.0, 0.0)},
}
ALIASES = {"伊恩": "char_001", "米迦": "char_002"}


# --------------------------------------------------------------------------- #
# 关系解析
# --------------------------------------------------------------------------- #
def test_relation_words_produce_the_documented_kinds():
    for text, kind in (("behind 甲", "behind"), ("甲背后", "behind"),
                       ("甲身后", "behind"),
                       ("between 甲 and 乙", "between"), ("在甲和乙之间", "between"),
                       ("left_of 甲", "left_of"), ("甲左侧", "left_of"),
                       ("right_of 甲", "right_of"), ("甲右边", "right_of")):
        relation = parse_relation(text, aliases={"甲": "char_001", "乙": "char_002"},
                                  known=set(CAST))
        assert relation is not None, text
        assert relation.kind == kind, text


def test_distance_is_read_from_the_text_and_defaults_to_two_metres():
    called = parse_relation("behind 甲", aliases={"甲": "char_001"}, known=set(CAST))
    assert called.distance == DEFAULT_ANCHOR_DISTANCE == 2.0
    explicit = parse_relation("left_of 甲 3.5m", aliases={"甲": "char_001"},
                              known=set(CAST))
    assert explicit.distance == 3.5
    chinese = parse_relation("甲右侧 1.5 米", aliases={"甲": "char_001"},
                             known=set(CAST))
    assert chinese.distance == 1.5


def test_an_unknown_target_is_not_parsed():
    """认不出目标就返回 None——**不猜代词**（与 SceneBrief 同一条纪律）。"""
    assert parse_relation("behind 他", known=set(CAST)) is None
    assert parse_relation("在甲和丙之间", aliases={"甲": "char_001"},
                          known=set(CAST)) is None


def test_a_relation_less_text_is_not_parsed():
    assert parse_relation("", known=set(CAST)) is None
    assert parse_relation("靠近一点", known=set(CAST)) is None


# --------------------------------------------------------------------------- #
# 摆位求解
# --------------------------------------------------------------------------- #
def test_behind_goes_opposite_of_the_facing():
    positions, problems = solve_anchor_positions(
        [{"name": "door", "relation": "behind 甲"}],
        CAST, aliases={"甲": "char_001"})
    assert problems == []
    # 甲 朝 +X ⇒ 背后是 -X，2.0 m
    assert positions["door"] == [-2.0, 0.0, 0.0]


def test_behind_uses_the_targets_own_facing():
    positions, problems = solve_anchor_positions(
        [{"name": "door", "relation": "behind 乙"}], CAST,
        aliases={"乙": "char_002"})
    assert problems == []
    # 乙 朝 -X ⇒ 背后是 +X：4.0 + 2.0
    assert positions["door"] == [6.0, 0.0, 0.0]


def test_between_is_the_midpoint():
    positions, problems = solve_anchor_positions(
        [{"name": "table", "relation": "between 甲 and 乙"}], CAST,
        aliases={"甲": "char_001", "乙": "char_002"})
    assert problems == []
    assert positions["table"] == [2.0, 0.0, 0.0]


def test_left_and_right_use_the_local_axis():
    """Z-up/X=右：朝 +X 的角色，左手方向是 +Y（舞台前方），右手方向是 -Y。"""
    left, _ = solve_anchor_positions([{"name": "l", "relation": "left_of 甲"}],
                                     CAST, aliases={"甲": "char_001"})
    right, _ = solve_anchor_positions([{"name": "r", "relation": "right_of 甲"}],
                                      CAST, aliases={"甲": "char_001"})
    assert left["l"] == [0.0, 2.0, 0.0]
    assert right["r"] == [0.0, -2.0, 0.0]
    assert math.isclose(left["l"][1], -right["r"][1])


def test_explicit_position_wins():
    positions, problems = solve_anchor_positions(
        [{"name": "window", "relation": "behind 甲", "position": [1.0, 2.0, 3.0]}],
        CAST, aliases={"甲": "char_001"})
    assert problems == []
    assert positions["window"] == [1.0, 2.0, 3.0]


def test_a_character_id_works_without_an_alias():
    positions, problems = solve_anchor_positions(
        [{"name": "door", "relation": "behind char_001"}], CAST)
    assert problems == []
    assert positions["door"] == [-2.0, 0.0, 0.0]


def test_an_unresolved_anchor_is_reported_and_placed_deterministically():
    anchors = [{"name": "b_door", "relation": "靠近他"},
               {"name": "a_table", "relation": "在他身后"}]
    first, problems = solve_anchor_positions(anchors, CAST)
    second, again = solve_anchor_positions(anchors, CAST)
    assert len(problems) == 2 and again == problems
    assert [item["anchor"] for item in problems] == ["b_door", "a_table"]
    assert all(item["reason"] for item in problems)
    assert first == second                       # 确定性
    # 缺省位：排在一个半径 2.0 的圆上（按名字字典序，互不重叠）
    radius = lambda point: math.hypot(point[0], point[1])
    assert math.isclose(radius(first["a_table"]), 2.0, abs_tol=1e-4)
    assert math.isclose(radius(first["b_door"]), 2.0, abs_tol=1e-4)
    assert first["a_table"] != first["b_door"]


def test_a_missing_facing_makes_the_relation_unresolved():
    """没有朝向就求不出"背后/左右"——记问题、放缺省位，不猜。"""
    positions, problems = solve_anchor_positions(
        [{"name": "door", "relation": "behind char_001"}],
        {"char_001": {"position": (0.0, 0.0, 0.0)}})
    assert len(problems) == 1 and problems[0]["anchor"] == "door"
    assert positions["door"][2] == 0.0


def test_a_duplicate_name_is_reported_and_the_first_wins():
    positions, problems = solve_anchor_positions(
        [{"name": "door", "position": [1.0, 0.0, 0.0]},
         {"name": "door", "position": [9.0, 9.0, 9.0]}], CAST)
    assert positions["door"] == [1.0, 0.0, 0.0]
    assert any("重复" in item["reason"] for item in problems)


def test_an_anchor_without_a_name_is_reported():
    positions, problems = solve_anchor_positions([{"relation": "behind 甲"}],
                                                 CAST, aliases={"甲": "char_001"})
    assert positions == {}
    assert any("缺少 name" in item["reason"] for item in problems)
    assert problems[0]["anchor"] == ""


def test_an_empty_declaration_is_a_no_op():
    """空声明 = 现状：没有锚点、没有问题、没有对象要建。"""
    assert solve_anchor_positions([], CAST) == ({}, [])
    assert solve_anchor_positions(None, {}) == ({}, [])


def test_depth_is_carried_but_not_consumed_by_the_solver():
    """``depth`` 是"相对相机视角"的分层，这一步没有相机 ⇒ 坐标不受它影响。"""
    near, _ = solve_anchor_positions(
        [{"name": "door", "depth": "fg", "relation": "behind 甲"}], CAST,
        aliases={"甲": "char_001"})
    far, _ = solve_anchor_positions(
        [{"name": "door", "depth": "bg", "relation": "behind 甲"}], CAST,
        aliases={"甲": "char_001"})
    assert near == far
