"""阶段 0：每分镜决策树的纯层骨架（无 bpy）。

覆盖设计文档 §6 阶段 0 的判据：
- ``build_tree`` 对 13 镜样例每镜返回一棵树，节点非空，合法空间覆盖
  ``camera.side`` / ``movement`` / ``action_type`` / ``look_at.target``；
- 正面镜只开放正面轴侧，OTS 镜开放过肩，方向走 ``front_left`` /
  ``front_right``（不自创 token）；空镜不做轴侧闭集；
- ``project`` 对合法提议 ACCEPT 且无审计；拒绝必带原因与 ``source``；
  投影必带 ``original`` / ``projected`` / ``reason``。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from block_director.contracts.plan import Plan, ShotPlan
from block_director.layer5_orchestrator.decision_tree import (
    DecisionNode,
    ShotDecisionTree,
    TreeBuildError,
    Verdict,
    build_tree,
    project,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "shotlist_market_v10_nodes1_4.txt"


def _plan() -> Plan:
    from block_director.layer1_input.shotlist import parse_shot_list

    script, shot_list = parse_shot_list(FIXTURE.read_text(encoding="utf-8"))
    shots: list[ShotPlan] = []
    for index, declared in enumerate(shot_list.shots, start=1):
        shots.append(
            ShotPlan(
                shot_id=f"s{declared.shot_number:03d}",
                intent="",
                shot_type=declared.shot_type or "MS",
                duration_frames=96,
                order=index,
                characters=list(declared.characters),
                camera={"side": "front", "lens": 50.0},
            )
        )
    return Plan(shots=shots)


def _single(shot_id: str = "s001", *, characters=None, shot_type="MS",
            camera=None, actions=None) -> ShotPlan:
    return ShotPlan(
        shot_id=shot_id,
        intent="",
        shot_type=shot_type,
        duration_frames=96,
        order=1,
        characters=list(characters or []),
        camera=dict(camera or {"side": "front", "lens": 50.0}),
        actions=list(actions or []),
    )


def test_plan_fixture_has_13_shots_and_characters() -> None:
    plan = _plan()
    assert len(plan.shots) == 13
    assert any(shot.characters for shot in plan.shots)


def test_build_tree_returns_nonempty_tree_per_shot() -> None:
    plan = _plan()
    for shot in plan.shots:
        tree = build_tree(shot, plan)
        assert isinstance(tree, ShotDecisionTree)
        assert tree.shot_id == shot.shot_id
        assert tree.nodes
        assert tree.legal_space


def test_build_tree_rejects_bad_axis_side() -> None:
    shot = _single()
    with pytest.raises(TreeBuildError):
        build_tree(shot, _plan(), axis_side=2)


def test_axis_sides_for_positive_side_narrows_back_out() -> None:
    """轴侧 ±1：back 系不在合法闭集（双人/单人 camera_direction 都落在反侧）。"""
    for axis_side in (-1, 1):
        #: 必须带角色：无角色 = 空镜豁免（全 9 token），走不到收窄分支。
        sides = set(build_tree(_single(characters=["mika"]), _plan(),
                               axis_side=axis_side)
                    .legal_space["camera.side"])
        assert {"front", "front_left", "front_right", "left", "right"} <= sides
        assert not {"back", "back_left", "back_right"} & sides


def test_axis_sides_for_ots_appends_over_shoulder() -> None:
    shot = _single(shot_type="OTS", characters=["mika"])
    sides = build_tree(shot, _plan(), axis_side=1).legal_space["camera.side"]
    assert set(sides) == {"front", "front_left", "front_right",
                          "left", "right", "over_shoulder"}


def test_build_tree_without_injection_uses_plan_prediction() -> None:
    """无注入：13 镜树侧集合与 ``_axis_sides_from_plan`` 预测一致。"""
    from block_director.layer5_orchestrator.decision_tree import (
        _axis_sides_for,
        _axis_sides_from_plan,
    )

    plan = _plan()
    predicted = _axis_sides_from_plan(plan)
    for shot in plan.shots:
        tree = build_tree(shot, plan)
        expected = set(_axis_sides_for(
            predicted.get(shot.shot_id, 0), shot.shot_type or ""))
        if not shot.characters:
            expected = set(_axis_sides_for(0, shot.shot_type or ""))
        assert set(tree.legal_space["camera.side"]) == expected


def test_decision_node_must_have_exactly_one_of_allowed_or_range() -> None:
    with pytest.raises(TreeBuildError):
        DecisionNode(key="bad", kind="rule", priority=1, allowed=None,
                     range=None, reason="both empty", source="test")
    with pytest.raises(TreeBuildError):
        DecisionNode(key="bad", kind="rule", priority=1,
                     allowed=("a",), range=(0.0, 1.0), reason="both set",
                     source="test")


def test_legal_space_covers_core_keys() -> None:
    plan = _plan()
    shot = next(s for s in plan.shots if s.characters)
    tree = build_tree(shot, plan)
    assert "camera.side" in tree.legal_space
    assert "movement" in tree.legal_space
    assert "action_type" in tree.legal_space
    assert "look_at.target" in tree.legal_space


def test_legal_space_exports_opt_variables_from_true_sources() -> None:
    """§3.5.4：连续键导出为 ``legal_space["opt_variables"]``（与树同源）。"""
    from block_director.cinema.camera_motion import MOVEMENT_UNITS
    from block_director.layer5_orchestrator.continuous_optimizer import (
        OptVariable,
    )

    plan = _plan()
    shot = next(s for s in plan.shots if s.characters)
    tree = build_tree(shot, plan)
    variables = tree.legal_space["opt_variables"]
    assert isinstance(variables, tuple)
    assert variables
    assert all(isinstance(item, OptVariable) for item in variables)
    by_key = {item.key: item for item in variables}
    assert by_key["camera.lens"].low == 8.0
    assert by_key["camera.lens"].high == 300.0
    assert by_key["camera.lens"].unit == "毫米"
    for movement, (unit, low, high) in MOVEMENT_UNITS.items():
        key = f"camera.movements.{movement}.amount"
        item = by_key[key]
        assert item.low == float(low)
        assert item.high == float(high)
        assert item.unit == unit
        assert item.scale > 0
        assert item.step is not None and item.step > 0


def test_front_shot_side_set_is_front_only_or_front_pair() -> None:
    plan = _plan()
    shot = next(s for s in plan.shots if s.characters)
    tree = build_tree(shot, plan, axis_side=1)
    sides = tree.legal_space["camera.side"]
    assert set(sides) <= {"front", "front_left", "front_right", "back",
                          "back_left", "back_right", "left", "right",
                          "over_shoulder"}


def test_ots_shot_allows_over_shoulder_side() -> None:
    shot = _single(shot_type="OTS", characters=["mika"])
    tree = build_tree(shot, _plan(), axis_side=1)
    sides = tree.legal_space["camera.side"]
    assert "over_shoulder" in sides


def test_empty_shot_has_no_axis_side_restriction() -> None:
    shot = _single(characters=[])
    tree = build_tree(shot, _plan(), axis_side=0)
    assert "camera.side" in tree.legal_space
    assert "front" in tree.legal_space["camera.side"]


def test_back_side_is_rejected_when_axis_side_narrows() -> None:
    """收窄后 back 系不在合法空间 ⇒ project REJECTED（不投影）。"""
    for axis_side in (-1, 1):
        shot = _single(characters=["mika"])
        tree = build_tree(shot, _plan(), axis_side=axis_side)
        proposal = {"camera": {"side": "back", "lens": 50.0},
                    "actions": []}
        projected, records = project(tree, proposal, stage="draft")
        assert projected["camera"]["side"] == "back"
        side_records = [r for r in records if r.node_key == "camera.side"]
        assert side_records
        assert side_records[0].verdict == Verdict.REJECTED


def test_project_accepts_legal_proposal_without_audit() -> None:
    shot = _single(characters=["mika"])
    tree = build_tree(shot, _plan(), axis_side=1)
    proposal = {"camera": {"side": "front", "lens": 50.0},
                "actions": [{"action_type": "look_at",
                             "params": {"target": "mika"}}]}
    projected, records = project(tree, proposal, stage="draft")
    assert projected == proposal
    assert records == []


def test_project_rejects_look_at_dual_write_with_record() -> None:
    """G8-C：look_at 同时写 target 与角度不是合法提议，必须留非 accept 记录。"""
    shot = _single(characters=["mika"])
    tree = build_tree(shot, _plan(), axis_side=1)
    proposal = {"camera": {"side": "front", "lens": 50.0},
                "actions": [{"action_type": "look_at",
                             "params": {"target": "mika", "yaw_deg": 10.0}}]}
    projected, records = project(tree, proposal, stage="draft")
    assert records
    assert all(record.verdict != Verdict.ACCEPT for record in records)
    assert records[0].node_key == "action.look_at.dual_write"
    #: P3 归一到两者之一：target 优先，角度键丢弃（不猜谁更重要）。
    assert projected["actions"][0]["params"] == {"target": "mika"}


def test_project_does_not_mutate_input() -> None:
    """project 是纯层投影：不得改调用方的提议对象（含嵌套 params/列表）。"""
    from copy import deepcopy

    shot = _single(characters=["mika"])
    tree = build_tree(shot, _plan(), axis_side=1)
    proposal = {"camera": {"side": "side", "lens": 9999.0,
                           "movements": [{"type": "dolly_in",
                                          "amount": 500.0}]},
                "actions": [{"action_type": "look_at",
                             "params": {"angle_deg": 20.0}}]}
    snapshot = deepcopy(proposal)
    project(tree, proposal, stage="react")
    assert proposal == snapshot


def test_project_rejects_top_level_target_position_for_non_walk_actions() -> None:
    """工具 schema：动作项顶层的 target_position 只有 walk_to/run_to 认。"""
    shot = _single(characters=["mika"])
    tree = build_tree(shot, _plan(), axis_side=1)
    proposal = {"camera": {"side": "front", "lens": 50.0},
                "actions": [{"action_type": "enter_from",
                             "target_position": [0.0, 0.0, 0.0]}]}
    projected, records = project(tree, proposal, stage="draft")
    assert records
    assert records[0].verdict == Verdict.REJECTED
    assert records[0].node_key == "actions[*].target_position"
    assert projected == proposal  # 拒绝不改写提议


def test_project_rejects_script_hard_violation_with_source() -> None:
    shot = _single(characters=["mika"])
    tree = build_tree(shot, _plan(), axis_side=1)
    #: P0 硬约束语义：side 用合法值，拒绝只由 target 越界触发。
    proposal = {"camera": {"side": "front", "lens": 50.0},
                "actions": [{"action_type": "look_at",
                             "params": {"target": "stranger"}}]}
    projected, records = project(tree, proposal, stage="draft")
    assert projected == proposal
    assert records
    record = records[0]
    assert record.verdict == Verdict.REJECTED
    assert record.original == "stranger"
    assert record.reason
    assert record.node_key == "action.look_at.target"


def test_project_projects_nested_invalid_with_record_fields() -> None:
    shot = _single(characters=["mika"])
    tree = build_tree(shot, _plan(), axis_side=1)
    proposal = {"camera": {"side": "side", "lens": 9999.0}}
    projected, records = project(tree, proposal, stage="repair")
    assert projected["camera"]["side"] != "side"
    assert projected["camera"]["lens"] == 300.0
    assert records
    assert all(r.stage == "repair" for r in records)
    assert all(r.original is not None for r in records)
    assert all(r.projected is not None for r in records)
    assert all(r.reason for r in records)
    assert all(r.node_key for r in records)


def test_project_normalizes_alias_without_audit() -> None:
    shot = _single(characters=["mika"])
    tree = build_tree(shot, _plan(), axis_side=1)
    proposal = {"camera": {"side": "front", "lens": 50.0},
                "actions": [{"action_type": "look_at",
                             "params": {"angle_deg": 20.0}}]}
    projected, records = project(tree, proposal, stage="react")
    assert records == []
    assert projected["actions"][0]["params"]["yaw_deg"] == 20.0
    assert "angle_deg" not in projected["actions"][0]["params"]


def test_render_legal_space_is_stable_text() -> None:
    from block_director.layer5_orchestrator.decision_tree import (
        render_legal_space,
    )

    shot = _single(characters=["mika"])
    tree = build_tree(shot, _plan(), axis_side=1)
    text = render_legal_space(tree)
    assert "camera.side" in text
    assert "front" in text


def test_project_side_longest_prefix_wins() -> None:
    """front-right 同侧文本不因 front 前缀先行而退化成 front。"""
    shot = _single(characters=["mika"])
    tree = build_tree(shot, _plan(), axis_side=1)
    proposal = {"camera": {
        "side": "front-right, same 180° side as shot_004",
        "lens": 50.0}}
    projected, records = project(tree, proposal, stage="react")
    assert projected["camera"]["side"] == "front_right"
    side_records = [r for r in records if r.node_key == "camera.side"]
    assert side_records
    assert side_records[0].verdict == Verdict.PROJECTED


def test_project_dolly_in_spaced_form_is_projected() -> None:
    """P2：'dolly in' 归一为 dolly_in（距离 1 无歧义）→ PROJECTED。"""
    shot = _single(characters=["mika"])
    tree = build_tree(shot, _plan(), axis_side=1)
    proposal = {"camera": {"side": "front", "lens": 50.0,
                           "movements": [{"type": "dolly in",
                                          "amount": 1.0}]}}
    projected, records = project(tree, proposal, stage="react")
    assert projected["camera"]["movements"][0]["type"] == "dolly_in"
    kinds = [r.node_key for r in records]
    assert "camera.movements.type" in kinds


def test_project_movement_free_text_without_ambiguity_is_rejected() -> None:
    """P2：'fly to the moon' 与 24 种运镜无近邻，REJECTED 不投影。"""
    shot = _single(characters=["mika"])
    tree = build_tree(shot, _plan(), axis_side=1)
    proposal = {"camera": {"side": "front", "lens": 50.0,
                           "movements": [{"type": "fly to the moon",
                                          "amount": 1.0}]}}
    projected, records = project(tree, proposal, stage="react")
    movement_records = [r for r in records
                        if r.node_key == "camera.movements.type"]
    assert movement_records
    assert movement_records[0].verdict == Verdict.REJECTED
    assert projected["camera"]["movements"][0]["type"] == "fly to the moon"


def test_project_action_free_text_without_ambiguity_is_rejected() -> None:
    """P2：finger_snap 不在 17 个动作闭集且无近邻语义 → REJECTED。"""
    shot = _single(characters=["mika"])
    tree = build_tree(shot, _plan(), axis_side=1)
    proposal = {"camera": {"side": "front", "lens": 50.0},
                "actions": [{"action_type": "finger_snap",
                             "params": {}}]}
    projected, records = project(tree, proposal, stage="react")
    action_records = [r for r in records if r.node_key == "action_type"]
    assert action_records
    assert action_records[0].verdict == Verdict.REJECTED
    assert projected["actions"][0]["action_type"] == "finger_snap"
