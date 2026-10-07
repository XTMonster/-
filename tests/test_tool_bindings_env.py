"""v1.6 A3（D-17）：工具层"非在场主体做动作"的拒绝引导。

``tool_bindings.py`` 顶层 import bpy，pytest 环境无法直接导入；
"本镜出场角色"的判定逻辑放在纯模块 ``scene_context.py`` 中。
这里绕过 ``layer3_engine/__init__.py`` 的 eager bpy 导入，
直接加载 ``scene_context.py`` 并测试其契约与错误文案。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from block_director.contracts.plan import Plan, ShotPlan

ROOT = Path(__file__).resolve().parents[1]


def _load_scene_context():
    name = "block_director.layer3_engine.scene_context"
    path = ROOT / "block_director" / "layer3_engine" / "scene_context.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_scene_context = _load_scene_context()
SceneContext = _scene_context.SceneContext


def _context_with_shot(characters):
    plan = Plan(shots=[ShotPlan(shot_id="shot_001", intent="对峙",
                                shot_type="MS", duration_frames=48,
                                characters=list(characters))])
    ctx = SceneContext(current_shot_id="shot_001")
    ctx.plan = plan
    return ctx


def test_present_character_passes():
    ctx = _context_with_shot(["甲", "乙"])
    assert ctx.require_character_in_shot("甲") is None
    assert ctx.require_character_in_shot("乙") is None


def test_absent_character_returns_error_with_roster():
    ctx = _context_with_shot(["甲", "乙"])
    message = ctx.require_character_in_shot("丙")
    assert message is not None
    assert "丙" in message
    assert "甲" in message
    assert "乙" in message


def test_error_suggests_vfx_not_character_action():
    ctx = _context_with_shot(["甲"])
    message = ctx.require_character_in_shot("environment_flag")
    assert "vfx 字段" in message
    assert "create_vfx" in message
    assert "环境/氛围节拍" in message


def test_empty_shot_roster_shows_explicit_empty():
    ctx = _context_with_shot([])
    message = ctx.require_character_in_shot("甲")
    assert "（无）" in message


def test_no_active_shot_returns_error():
    ctx = SceneContext()
    assert ctx.require_character_in_shot("甲") == "没有当前活动镜头"


def test_character_id_is_coerced_to_string():
    ctx = _context_with_shot(["001"])
    assert ctx.require_character_in_shot("001") is None
    message = ctx.require_character_in_shot(999)
    assert "999" in message
