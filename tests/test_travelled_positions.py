"""`walk_to` 的缺省起点必须接力，而不是每次都回到剧本起始站位（v1.6）。

现场（2026-10-04，`work/_walk_once_probe.py` ＋ `work/_drift_probe.py`）：
`motion/model.py` 的 `walk_to` 在**没有 `from`** 时把 `target_position` 当成
**相对位移**（`base + target`），而规划器几乎从不写 `from` ⇒ 构建器一直拿
`CastMember.initial_location` 当缺省起点，同一角色的一串行走于是**累加**：
`long9` 重建里伊恩从起始站位一路加到 (13.0, −12.6)，而计划里每个目的地都在
9.5 m 以内。

本文件钉 `cinema/schedule.travelled_positions`：按计划顺序推算"到这一镜开始时
人在哪"——上一次行走的**绝对**终点就是下一次的起点；没有人走动的角色保持
起始站位；非行走动作（sit/turn/look）不参与接力。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.cinema.schedule import travelled_positions  # noqa: E402
from block_director.contracts.plan import Plan, ShotPlan  # noqa: E402


def _shot(shot_id: str, actions, order: int) -> ShotPlan:
    return ShotPlan.from_dict({
        "shot_id": shot_id, "order": order, "intent": "推进",
        "shot_type": "MS", "duration_frames": 48,
        "characters": ["char_001"], "actions": list(actions)})


def _plan(*shots) -> Plan:
    return Plan(shots=list(shots), scene_heading="INT. 码头 - 日")


INITIAL = {"char_001": (-0.9, 0.0, 0.0), "char_002": (0.9, 0.0, 0.0)}


def test_a_walk_hands_its_endpoint_to_the_next_shot():
    plan = _plan(
        _shot("shot_001", [{"character_id": "char_001", "action_type": "walk_to",
                            "start_frame": 1, "end_frame": 48,
                            "params": {"target_position": [4.0, 1.0, 0.0]}}], 1),
        _shot("shot_002", [], 2),
        _shot("shot_003", [{"character_id": "char_001", "action_type": "walk_to",
                            "start_frame": 1, "end_frame": 48,
                            "params": {"target_position": [6.0, 3.0, 0.0]}}], 3),
    )
    places = travelled_positions(plan, INITIAL)
    assert places["shot_001"]["char_001"] == (-0.9, 0.0, 0.0)   # 第一镜从起始站位出发
    assert places["shot_002"]["char_001"] == (4.0, 1.0, 0.0)
    assert places["shot_003"]["char_001"] == (4.0, 1.0, 0.0)   # 第二镜没走，还在那
    assert places["shot_003"]["char_002"] == (0.9, 0.0, 0.0)   # 没动过的角色不变


def test_top_level_target_position_counts_too():
    """草案 schema 把 `target_position` 声明在**顶层**——接力必须认得它。"""
    plan = _plan(
        _shot("shot_001", [{"character_id": "char_001", "action_type": "walk_to",
                            "start_frame": 1, "end_frame": 48,
                            "target_position": [2.5, -1.5, 0.0]}], 1),
        _shot("shot_002", [], 2),
    )
    places = travelled_positions(plan, INITIAL)
    assert places["shot_002"]["char_001"] == (2.5, -1.5, 0.0)


def test_non_walking_actions_do_not_move_the_handover():
    """坐下/转头/看向某人都不改平面位置，不该参与接力。"""
    plan = _plan(
        _shot("shot_001", [{"character_id": "char_001", "action_type": "sit",
                            "start_frame": 1, "end_frame": 24, "params": {}},
                           {"character_id": "char_001", "action_type": "look_at",
                            "start_frame": 25, "end_frame": 48,
                            "params": {"yaw_deg": 20}}], 1),
        _shot("shot_002", [], 2),
    )
    places = travelled_positions(plan, INITIAL)
    assert places["shot_002"]["char_001"] == (-0.9, 0.0, 0.0)


def test_enter_and_exit_actions_also_hand_over_positions():
    """语义级入场/出场同样是位移，不能让下一镜回到更早的位置。"""
    plan = _plan(
        _shot("shot_001", [{
            "character_id": "char_001", "action_type": "enter_from",
            "start_frame": 1, "end_frame": 24,
            "params": {"from": [-5.0, 0.0, 0.0],
                       "to": [0.0, 2.0, 0.0]},
        }], 1),
        _shot("shot_002", [{
            "character_id": "char_001", "action_type": "exit_frame",
            "start_frame": 1, "end_frame": 24,
            "params": {"to": [5.0, 2.0, 0.0]},
        }], 2),
        _shot("shot_003", [], 3),
    )
    places = travelled_positions(plan, INITIAL)
    assert places["shot_002"]["char_001"] == (0.0, 2.0, 0.0)
    assert places["shot_003"]["char_001"] == (5.0, 2.0, 0.0)


def test_a_walk_without_a_destination_is_ignored():
    """缺目的地的行走（解析期会被拒）不该把接力点改坏。"""
    plan = _plan(
        _shot("shot_001", [{"character_id": "char_001", "action_type": "walk_to",
                            "start_frame": 1, "end_frame": 48, "params": {}}], 1),
        _shot("shot_002", [], 2),
    )
    places = travelled_positions(plan, INITIAL)
    assert places["shot_002"]["char_001"] == (-0.9, 0.0, 0.0)


def test_a_short_target_is_padded_to_three_components():
    """模型的 2 元组目的地（x, y）要补 z，不能当成坏数据丢掉。"""
    plan = _plan(
        _shot("shot_001", [{"character_id": "char_001", "action_type": "walk_to",
                            "start_frame": 1, "end_frame": 48,
                            "params": {"target_position": [3.0, 2.0]}}], 1),
        _shot("shot_002", [], 2),
    )
    places = travelled_positions(plan, INITIAL)
    assert places["shot_002"]["char_001"] == (3.0, 2.0, 0.0)


def test_missing_initial_values_do_not_explode():
    plan = _plan(_shot("shot_001", [], 1))
    places = travelled_positions(plan, {"char_002": (0.9, 0.0)})
    assert places["shot_001"]["char_002"] == (0.9, 0.0, 0.0)
    assert "char_001" not in places["shot_001"]
