"""R2 S1 补丁：环境锚自由文本（无角色参照）→ 场景中心世界坐标。

真跑 20261019-r2-market-coin-full 的 ``plan.environment.anchors[].relation``
是自由文本（"场地右侧近处，摊面陈列银币…"）。场景侧
``solve_anchor_positions`` 只认"相对角色"的关系，环境锚没有角色参照，
于是 5/5 落到"原点附近小圆环"缺省位；``runtime_world_state.json`` 里的
锚点坐标（0.618/-1.618…）与设计快照（right near=2m / left near=2m /
right mid=6m / back far=12m）完全不一致——JSON 世界坐标没有实时对齐。

本测试要求：无角色参照的自由文本方位 + 距离档（近处/中部/远处）按
"场景中心锚定"解析，坐标与 ``spatial_design`` 同一数值（2/6/12 m）。
"""

from __future__ import annotations

from block_director.cinema.staging import (
    resolve_scene_center_anchor, solve_anchor_positions,
)


#: 真跑 LLM 计划里 5 个环境锚的 relation 原文（一字不改）。
REAL_FREE_TEXT_ANCHORS = [
    {"name": "银币摊",
     "relation": "场地右侧近处，摊面陈列银币，日光下金属反光明亮清晰"},
    {"name": "生蚝摊",
     "relation": "场地左侧近处，遮阳摊位与货架，浅景深虚化背景"},
    {"name": "市场通道",
     "relation": "右侧中部，阳光照入的通道留白，纵深分明"},
    {"name": "海面日光",
     "relation": "画面深处远处海面，白天晴天逆光光源，光晕与体积光"},
    {"name": "模糊人群",
     "relation": "远处背景人群，虚化成模糊人影"},
]


def test_real_free_text_relations_resolve_to_design_snapshot_coords():
    """验收：5 个真实自由文本锚点全部解析，0 条 problem，坐标=设计快照。"""
    positions, problems = solve_anchor_positions(REAL_FREE_TEXT_ANCHORS, {})
    assert problems == [], problems
    assert set(positions) == {a["name"] for a in REAL_FREE_TEXT_ANCHORS}
    assert positions["银币摊"] == [2.0, 0.0, 0.0]        # right near
    assert positions["生蚝摊"] == [-2.0, 0.0, 0.0]       # left near
    assert positions["市场通道"] == [6.0, 0.0, 0.0]      # right mid
    assert positions["海面日光"] == [0.0, -12.0, 0.0]    # back far
    assert positions["模糊人群"] == [0.0, -12.0, 0.0]    # back far


def test_scene_center_resolver_unknown_text_is_none():
    """认不出的文本如实返回 None（不猜），空文本也返回 None。"""
    assert resolve_scene_center_anchor("不明文本") is None
    assert resolve_scene_center_anchor("") is None
    assert resolve_scene_center_anchor("海面反光，微风") is None


def test_scene_center_resolver_explicit_meters():
    """方位 + 显式米数（无档位词）→ 按米数落位。"""
    assert resolve_scene_center_anchor("右侧 5 米") == (5.0, 0.0, 0.0)
    assert resolve_scene_center_anchor("前方 3 米") == (0.0, 3.0, 0.0)


def test_character_relative_anchors_still_win_over_scene_center():
    """相对角色的关系（有角色参照）不被场景中心解析抢走语义。"""
    cast = {
        "米迦尔": {"position": (0.0, 0.0, 0.0), "facing": (1.0, 0.0, 0.0)},
    }
    anchors = [
        {"name": "日光", "relation": "米迦尔右侧 6 米"},
    ]
    positions, problems = solve_anchor_positions(anchors, cast)
    assert problems == [], problems
    # 米迦尔朝 +X ⇒ 右手方向 -Y，6 m
    assert positions["日光"] == [0.0, -6.0, 0.0]
