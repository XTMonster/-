"""逐镜草案的提示词必须把**每个动作允许的参数键**说清楚（v1.5）。

现场（2026-10-03 的 64 镜真跑，`docs/evidence/20261003_chunked_long/`）：
**62/64 条草案**被 `extract_draft` 判无效，理由清一色"这个动作不认识的参数"——
模型写的是 `stand: {base_z}`、`look_at: {toward}`、`nod: {degrees}` 这类**同义词**，
而工具 schema 的 `params` 只声明了**全部动作的键的并集**，等于告诉模型
"这些键都能用"。无效草案是**整条丢掉**的（这一镜没有动作、没有取景、没有对白
时间轴），于是 B1 阶段在真实长剧本上形同虚设。

修法：把参数表**从 `motion/model.py::ACTION_PARAMS` 生成**并放进提示词
（单一真源，改表即改提示）。本文件钉三件事：表覆盖全部动作、逐字等于真源、
提示词真的把它拼进去了。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.layer5_orchestrator import editor as E  # noqa: E402
from block_director.motion.model import ACTION_PARAMS, ACTION_TYPES  # noqa: E402


def test_the_table_covers_every_action_and_matches_the_single_source():
    table = E.render_action_params()
    for kind in ACTION_TYPES:
        assert f"`{kind}`" in table, f"{kind} 不在参数表里"
    for kind, keys in ACTION_PARAMS.items():
        for key in keys:
            assert f"`{key}`" in table
    #: 反面对照：表里不许出现某个动作**没有**的键（那是"以为能用"的老毛病）。
    assert "walk_to」" not in table            # 措辞不是那种格式，防手写粘贴
    look_at_line = [line for line in table.splitlines() if "`look_at`" in line][0]
    assert "`yaw_deg`" in look_at_line and "`pitch_deg`" in look_at_line
    assert "`toward`" not in look_at_line      # toward 只属于 body_tilt


def test_the_prompt_has_the_placeholder_and_the_payload_fills_it():
    assert "{action_params}" in E.EDITOR_SYSTEM_PROMPT
    from block_director.contracts.enums import ShotType
    from block_director.contracts.plan import Plan, ShotPlan

    plan = Plan(shots=[ShotPlan(shot_id="shot_001", intent="推进",
                                shot_type=ShotType.MS, duration_frames=48)])
    payload = E.build_editor_payload(plan.shots[0], plan)
    system = payload.messages[0].content
    assert "{action_params}" not in system, "占位符没被替换 —— 表没进提示词"
    assert "动作参数表" in system
    for kind in ACTION_PARAMS:
        assert f"`{kind}`" in system
