"""v1.7 卡 I4：目标模型适配器（纯函数，只建议不执行）。"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

from block_director.contracts.config import AppConfig
from block_director.contracts.plan import Plan, ShotPlan
from block_director.contracts.target_models import ModelSpec, load_table

ROOT = Path(__file__).resolve().parents[1]


def _load_target_advisor():
    #: ``layer8_delivery/__init__`` eager import bpy 绑定模块；照
    #: ``tests/test_tool_bindings_env.py`` 先例直接按文件路径加载纯函数模块。
    package = types.ModuleType("block_director.layer8_delivery")
    package.__path__ = [str(ROOT / "block_director" / "layer8_delivery")]
    sys.modules["block_director.layer8_delivery"] = package
    name = "block_director.layer8_delivery.target_advisor"
    path = ROOT / "block_director" / "layer8_delivery" / "target_advisor.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


advisor = _load_target_advisor()


def _plan(durations: list[float]) -> Plan:
    shots = []
    for index, seconds in enumerate(durations, start=1):
        shots.append(ShotPlan(
            shot_id=f"shot_{index:03d}", order=index, intent="建立",
            shot_type="MS", duration_frames=int(seconds * 24)))
    return Plan(shots=shots)


def _config(target_model: str = "seedance_2.5") -> AppConfig:
    config = AppConfig()
    config.delivery.target_model = target_model
    return config


def test_45s_single_shot_seedance():
    config = _config()
    plan = _plan([45.0])
    issues = advisor.check_specs(config, plan)
    over_limit = [issue for issue in issues
                  if issue.code == "TARGET_003"]
    assert len(over_limit) == 1
    advice = advisor.suggest_slices(plan, load_table()["seedance_2.5"])
    assert len(advice) == 1
    assert advice[0].cut_frame == 45 * 24 + 1


def test_within_limit_silent():
    config = _config()
    plan = _plan([10.0, 10.0, 10.0])
    assert advisor.check_specs(config, plan) == []
    assert advisor.suggest_slices(plan, load_table()["seedance_2.5"]) == []


def test_unknown_model_falls_back():
    config = _config("unknown_x")
    plan = _plan([45.0])
    issues = advisor.check_specs(config, plan)
    assert any(issue.code == "TARGET_001" and "seedance_2.5" in issue.message
               for issue in issues)
    assert any(issue.code == "TARGET_003" for issue in issues)


def test_missing_spec_key_skips():
    target = ModelSpec(label="X", raw={"max_segment_s": 30})
    config = _config()
    plan = _plan([12.0])
    issues = advisor.check_specs(config, plan)
    assert all(issue.code != "TARGET_002" for issue in issues)
    assert advisor.suggest_slices(plan, target) == []


def test_slices_prefer_shot_bounds():
    plan = _plan([12.0, 12.0, 12.0])
    advice = advisor.suggest_slices(plan, load_table()["seedance_2.5"])
    assert [item.cut_frame for item in advice] == [12 * 24 * 2 + 1]
    assert "shot_002" in advice[0].reason
