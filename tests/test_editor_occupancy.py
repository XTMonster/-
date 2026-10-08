"""v1.6 F4（D-16）接线：B1 起草提示里必须带"本镜同层已占帧区间表"。"""
from __future__ import annotations

from block_director.contracts.plan import Plan, ShotPlan
from block_director.layer5_orchestrator.editor import build_editor_payload


def _shot(actions):
    return ShotPlan(shot_id="shot_001", intent="小明坐下", shot_type="MS",
                    duration_frames=96, characters=["char_001"],
                    actions=actions, order=1)


def test_occupied_intervals_reach_the_draft_prompt():
    shot = _shot([{"character_id": "char_001", "action_type": "nod",
                   "start_frame": 12, "end_frame": 30, "params": {}}])
    system = build_editor_payload(shot, Plan(shots=[shot])).messages[0].content
    assert "{occupancy_table}" not in system
    assert "12-30" in system


def test_empty_shot_gets_an_explicit_placeholder():
    shot = _shot([])
    system = build_editor_payload(shot, Plan(shots=[shot])).messages[0].content
    assert "{occupancy_table}" not in system
    assert "（本镜尚未排任何动作）" in system
