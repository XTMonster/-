"""Blender 端集成测试的共享夹具。

放在单独模块而不是互相 import 测试脚本：测试脚本在 import 时会执行模块级
代码，互相引用很容易踩到顺序问题。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.contracts.plan import Plan, ShotPlan  # noqa: E402


def two_shot_plan(with_actions: bool = True) -> Plan:
    """一份确定性的两镜计划：MLS 双人 → MCU 单人并坐下。"""
    first = ShotPlan.from_dict({
        "shot_id": "shot_001", "order": 1, "intent": "建立场景与人物关系",
        "shot_type": "MLS", "duration_frames": 96,
        "characters": ["char_001", "char_002"],
        "actions": ([{"character_id": "char_001", "action_type": "nod",
                      "start_frame": 1, "end_frame": 96, "params": {"cycles": 2}}]
                    if with_actions else []),
    })
    second = ShotPlan.from_dict({
        "shot_id": "shot_002", "order": 2, "intent": "推进对话，给出反应",
        "shot_type": "MCU", "duration_frames": 120,
        "characters": ["char_002"],
        "actions": ([{"character_id": "char_002", "action_type": "sit",
                      "start_frame": 1, "end_frame": 60, "params": {"drop": 0.2}}]
                    if with_actions else []),
    })
    return Plan(shots=[first, second], scene_heading="INT. 咖啡馆 - 日")


def three_shot_plan_with_empty(with_actions: bool = True) -> Plan:
    """两镜计划再加一镜**空镜**（无角色，只建环境/留白）。

    D1 交接 §3b：逐镜预演路径的空镜（无角色）走"建相机无动作 → audit
    空镜豁免"，per-shot 探针此前未覆盖；此夹具供探针验证空镜在
    ``prepare_scene + rebuild_shot`` 下不崩、结果形状与整场一致。
    """
    base = two_shot_plan(with_actions=with_actions)
    empty = ShotPlan.from_dict({
        "shot_id": "shot_003", "order": 3, "intent": "建立环境，交代空场",
        "shot_type": "LS", "duration_frames": 72,
        "characters": [],
    })
    return Plan(shots=[*base.shots, empty],
                scene_heading=base.scene_heading)
