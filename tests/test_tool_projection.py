"""阶段 2：决策树 → 工具调用投影适配层（纯层，无 bpy）。

设计文档 ``work/per_shot_decision_tree_design.md`` §7.3：

- ``setup_camera`` 的 ``side``/``lens``、``move_camera`` 的
  ``movement_type``/``amount``、``character_action`` 的
  ``action_type``/``params`` 都在树的判域里；
- ``look_at``/``face_character`` 的 ``target`` 走剧本硬约束闭集
  （角色 ∪ 锚点）；``target_position`` 是坐标、不进树；
- ``move_character``/``place_character``/``interact_with`` 不进树
  （坐标/速度/交互类型由工具 schema 自己管）；
- REJECTED ⇒ 不执行工具（剧本硬约束最高优先级）；PROJECTED ⇒ 改写参数后执行。
"""

from __future__ import annotations

import json
from typing import Any, Dict

import pytest

from block_director.contracts.plan import Plan, ShotPlan
from block_director.layer5_orchestrator.decision_tree import (
    Verdict,
    build_tree,
)
from block_director.layer5_orchestrator.tool_projection import (
    ToolProjectionError,
    project_tool_call,
)


def _plan() -> Plan:
    shots = [
        ShotPlan(
            shot_id="s001",
            intent="",
            shot_type="MS",
            duration_frames=96,
            order=1,
            characters=["米迦尔"],
            camera={"side": "front", "lens": 50.0},
        ),
        ShotPlan(
            shot_id="s002",
            intent="",
            shot_type="OTS",
            duration_frames=96,
            order=2,
            characters=["米迦尔", "伊恩"],
            camera={"side": "over_shoulder", "lens": 85.0},
        ),
        ShotPlan(
            shot_id="s003",
            intent="",
            shot_type="MS",
            duration_frames=96,
            order=3,
            characters=[],
            camera={"side": "front", "lens": 50.0},
        ),
    ]
    return Plan(shots=shots,
                environment={"anchors": [{"name": "吧台", "kind": "prop"}]})


def _tree(shot_id: str = "s001", axis_side: int = 1) -> Any:
    plan = _plan()
    shot = next(item for item in plan.shots if item.shot_id == shot_id)
    return build_tree(shot, plan, axis_side=axis_side)


def _project(tool: str, args: Dict[str, Any], *, shot_id: str = "s001",
             stage: str = "react") -> Any:
    tree = _tree(shot_id)
    return project_tool_call(tree, tool, dict(args), stage=stage)


def _args_text(args: Dict[str, Any]) -> str:
    return json.dumps(args, ensure_ascii=False)


def test_setup_camera_side_and_lens_are_projected() -> None:
    result = _project("setup_camera", {
        "shot_id": "s001",
        "side": "front-right, same 180° side as shot_004",
        "lens": 999.0,
    })
    assert result.verdict == Verdict.PROJECTED
    assert result.args["side"] == "front_right"   # 连字符归一，不再退化成 front
    assert result.args["lens"] == 300.0
    kinds = [r.node_key for r in result.records]
    assert "camera.side" in kinds and "camera.lens" in kinds


def test_setup_camera_side_single_token_projects_to_pair() -> None:
    result = _project("setup_camera", {"shot_id": "s001", "side": "side"})
    assert result.verdict == Verdict.PROJECTED
    assert result.args["side"] == "left"


def test_setup_camera_side_already_legal_is_accepted() -> None:
    result = _project("setup_camera", {"shot_id": "s001", "side": "front_left"})
    assert result.verdict == Verdict.ACCEPT
    assert result.args["side"] == "front_left"
    assert result.records == []


def test_reframe_only_lens_is_in_tree_scope() -> None:
    result = _project("reframe", {"shot_id": "s001", "lens": 12.0})
    assert result.verdict == Verdict.ACCEPT
    assert result.args["lens"] == 12.0
    assert result.records == []


def test_reframe_bad_lens_is_clamped() -> None:
    result = _project("reframe", {"shot_id": "s001", "lens": 9999.0})
    assert result.verdict == Verdict.PROJECTED
    assert result.args["lens"] == 300.0
    assert result.records[0].node_key == "camera.lens"


def test_move_camera_type_and_amount_are_projected() -> None:
    result = _project("move_camera", {
        "movement_type": "dolly in",
        "amount": 9999.0,
        "start_frame": 1,
        "end_frame": 24,
    })
    assert result.verdict == Verdict.PROJECTED
    assert result.args["movement_type"] in ("dolly_in", "dolly-in")
    #: dolly_in 是平移（单位米）：典型区间 (0.3, 2.0)，9999 → 2.0。
    assert result.args["amount"] == 2.0
    kinds = [r.node_key for r in result.records]
    assert any("amount" in kind for kind in kinds)


def test_move_camera_unknown_type_is_rejected() -> None:
    result = _project("move_camera", {
        "movement_type": "fly to the moon",
        "start_frame": 1,
        "end_frame": 24,
    })
    assert result.verdict == Verdict.REJECTED
    assert result.records and result.records[0].node_key == \
        "camera.movements.type"


def test_character_action_action_type_out_of_closed_set_is_rejected() -> None:
    result = _project("character_action", {
        "character_id": "米迦尔",
        "action_type": "finger_snap",
        "start_frame": 1,
        "end_frame": 24,
        "params": {},
    })
    assert result.verdict == Verdict.REJECTED
    assert result.records[0].node_key == "action_type"


def test_character_action_unknown_params_keys_are_dropped() -> None:
    result = _project("character_action", {
        "character_id": "米迦尔",
        "action_type": "body_tilt",
        "start_frame": 1,
        "end_frame": 24,
        "params": {"angle": 10.0, "mystery_key": 1},
    })
    assert result.verdict == Verdict.PROJECTED
    assert result.args["params"] == {"angle": 10.0}
    assert any(record.node_key == "actions[*].params"
               for record in result.records)


def test_look_at_target_must_be_in_shot_roster_or_anchor() -> None:
    result = _project("look_at", {
        "character_id": "米迦尔",
        "target": "伊恩",
        "start_frame": 1,
        "end_frame": 24,
    }, shot_id="s002")
    assert result.verdict == Verdict.ACCEPT

    result = _project("look_at", {
        "character_id": "米迦尔",
        "target": "陌生人",
        "start_frame": 1,
        "end_frame": 24,
    }, shot_id="s002")
    assert result.verdict == Verdict.REJECTED
    assert result.records[0].node_key == "action.look_at.target"


def test_look_at_anchor_target_is_accepted() -> None:
    result = _project("look_at", {
        "character_id": "米迦尔",
        "target": "吧台",
        "start_frame": 1,
        "end_frame": 24,
    }, shot_id="s001")
    assert result.verdict == Verdict.ACCEPT


def test_look_at_target_position_is_not_in_tree_domain() -> None:
    """坐标不是角色/锚点闭集；工具 handler 自己管坐标合法性。"""
    result = _project("look_at", {
        "character_id": "米迦尔",
        "target_position": [1.0, 2.0, 3.0],
        "start_frame": 1,
        "end_frame": 24,
    }, shot_id="s001")
    assert result.verdict == Verdict.ACCEPT
    assert result.records == []


def test_face_character_target_roster_is_enforced() -> None:
    result = _project("face_character", {
        "character_id": "米迦尔",
        "target": "陌生人",
    }, shot_id="s002")
    assert result.verdict == Verdict.REJECTED
    assert result.records[0].node_key == "action.look_at.target"


def test_look_at_projection_carries_tool_name() -> None:
    result = _project("look_at", {
        "character_id": "米迦尔",
        "target": "伊恩",
        "start_frame": 1,
        "end_frame": 24,
    }, shot_id="s002")
    assert result.tool == "look_at"

    result = _project("look_at", {
        "character_id": "米迦尔",
        "start_frame": 1,
        "end_frame": 24,
    }, shot_id="s002")
    assert result.tool == "look_at"


def test_face_character_projection_carries_tool_name() -> None:
    result = _project("face_character", {
        "character_id": "米迦尔",
        "target": "伊恩",
        "start_frame": 1,
        "end_frame": 24,
    }, shot_id="s002")
    assert result.tool == "face_character"


@pytest.mark.parametrize("tool", [
    "move_character", "place_character", "interact_with",
])
def test_tools_outside_tree_domain_pass_through(tool: str) -> None:
    args = {"character_id": "米迦尔",
            "target_position": [1.0, 2.0, 3.0],
            "start_frame": 1, "end_frame": 24}
    if tool == "interact_with":
        args = {"character_id": "米迦尔", "prop_id": "椅子",
                "interaction_type": "sit", "start_frame": 1, "end_frame": 24}
    result = _project(tool, args)
    assert result.verdict == Verdict.ACCEPT
    assert result.records == []
    assert result.args == args


def test_projected_args_are_serializable_back_into_arguments() -> None:
    result = _project("setup_camera", {
        "shot_id": "s001",
        "side": "front-right, same 180° side as shot_004",
        "lens": 999.0,
    })
    text = _args_text(result.args)
    decoded = json.loads(text)
    assert decoded["side"] == "front_right"
    assert decoded["lens"] == 300.0


def test_unknown_tool_raises() -> None:
    with pytest.raises(ToolProjectionError):
        _project("no_such_tool", {})


def test_stage_flows_into_record() -> None:
    tree = _tree("s001")
    result = project_tool_call(tree, "setup_camera", {
        "shot_id": "s001", "side": "side", "lens": 999.0,
    }, stage="repair")
    assert result.records and all(r.stage == "repair" for r in result.records)
    assert all(r.shot_id == "s001" for r in result.records)
