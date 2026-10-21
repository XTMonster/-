"""R2 Ticket 06（S1）：中文方位/相对锚点解析为世界坐标，0 unresolved。

覆盖剧本 market_coin 的中文关系写法：左侧/右侧/旁/前方/深处/对面/之间。
坐标系与 ``tests/test_staging_anchors.py`` 一致：Z-up、X=右、Y=前。
"""

from __future__ import annotations

from block_director.cinema.staging import solve_anchor_positions


#: 三角色：米迦尔在原点朝 +X（右）；伊恩在 x=4 朝 -X；偷盗者在 x=8 朝 -X。
CAST = {
    "米迦尔": {"position": (0.0, 0.0, 0.0), "facing": (1.0, 0.0, 0.0)},
    "伊恩": {"position": (4.0, 0.0, 0.0), "facing": (-1.0, 0.0, 0.0)},
    "偷盗者": {"position": (8.0, 0.0, 0.0), "facing": (-1.0, 0.0, 0.0)},
}

#: market_coin 场景锚的 8 个声明（relation 用剧本真实中文写法）。
MARKET_ANCHORS = [
    {"name": "生蚝摊", "relation": "米迦尔旁 2 米"},
    {"name": "银币摊", "relation": "偷盗者左侧 2 米"},
    {"name": "银币", "relation": "偷盗者前方 1 米"},
    {"name": "市场通道", "relation": "米迦尔和伊恩之间"},
    {"name": "海面", "relation": "米迦尔前方 12 米"},
    {"name": "背景人群", "relation": "伊恩深处 8 米"},
    {"name": "围栏", "relation": "偷盗者对面 3 米"},
    {"name": "日光", "relation": "米迦尔右侧 6 米"},
]


def test_market_anchors_all_resolve_with_zero_problems():
    """验收 1：market_coin 全部待解析锚点解析出坐标，0 条 unresolved。"""
    positions, problems = solve_anchor_positions(MARKET_ANCHORS, CAST)
    assert problems == [], problems
    assert set(positions) == {a["name"] for a in MARKET_ANCHORS}


def test_relation_semantics_left_right_beside_front_deep_opposite_between():
    """验收 2：每个关系词的语义落到正确坐标（相对参照物成立）。"""
    positions, problems = solve_anchor_positions(MARKET_ANCHORS, CAST)
    assert problems == []
    # 旁（beside）：米迦尔朝 +X ⇒ 左手方向 +Y，2.0 m
    assert positions["生蚝摊"] == [0.0, 2.0, 0.0]
    # 左侧（left_of）：偷盗者朝 -X ⇒ 左手方向 -Y，2.0 m
    assert positions["银币摊"] == [8.0, -2.0, 0.0]
    # 前方（front_of）：偷盗者朝 -X ⇒ -X 方向 1.0 m
    assert positions["银币"] == [7.0, 0.0, 0.0]
    # 之间（between）：米迦尔(0,0) 与 伊恩(4,0) 中点
    assert positions["市场通道"] == [2.0, 0.0, 0.0]
    # 前方（front_of）：米迦尔朝 +X ⇒ +X 方向 12.0 m
    assert positions["海面"] == [12.0, 0.0, 0.0]
    # 深处（ahead）：伊恩朝 -X ⇒ 背景纵深 -X 方向 8.0 m
    assert positions["背景人群"] == [-4.0, 0.0, 0.0]
    # 对面（opposite）：偷盗者朝 -X ⇒ 对面 = 背后 = +X 方向 3.0 m
    assert positions["围栏"] == [11.0, 0.0, 0.0]
    # 右侧（right_of）：米迦尔朝 +X ⇒ 右手方向 -Y，6.0 m
    assert positions["日光"] == [0.0, -6.0, 0.0]


def test_market_anchor_solution_is_deterministic():
    """同一输入两次求解，逐位一致（确定性纪律）。"""
    import json
    first, p1 = solve_anchor_positions(MARKET_ANCHORS, CAST)
    second, p2 = solve_anchor_positions(MARKET_ANCHORS, CAST)
    assert p1 == p2 == []
    assert json.dumps(first, sort_keys=True, ensure_ascii=False) == \
        json.dumps(second, sort_keys=True, ensure_ascii=False)


def test_relation_words_are_detected_with_the_new_kinds():
    """新关系词必须解析成规定的 kind（旁/前方/深处/对面）。"""
    from block_director.cinema.staging import parse_relation
    assert parse_relation("甲旁", aliases={"甲": "米迦尔"},
                          known=set(CAST)).kind == "beside"
    assert parse_relation("甲前方", aliases={"甲": "米迦尔"},
                          known=set(CAST)).kind == "front_of"
    assert parse_relation("甲深处", aliases={"甲": "米迦尔"},
                          known=set(CAST)).kind == "ahead"
    assert parse_relation("甲对面", aliases={"甲": "米迦尔"},
                          known=set(CAST)).kind == "opposite"
