"""v1.7 卡 B5：思考强度映射（TDD §4.2 的 16 格矩阵）。"""

from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_sidecar():
    spec = importlib.util.spec_from_file_location(
        "bd_sidecar_server_thinking_under_test",
        ROOT / "tools" / "sidecar_server.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sidecar = _load_sidecar()


def _body(provider: str) -> dict:
    body = {"model": "m", "messages": [], "max_tokens": 8192}
    if provider == "bailian":
        body["tool_choice"] = "required"
    return body


@pytest.mark.parametrize("provider",
                         ["openai", "deepseek", "bailian", "ollama"])
@pytest.mark.parametrize("level", ["off", "low", "medium", "high"])
def test_matrix_16(level, provider, capsys):
    original = _body(provider)
    body, trace = sidecar._apply_thinking(copy.deepcopy(original), level,
                                          provider)
    stderr = capsys.readouterr().err
    if level == "off":
        assert body == original
        assert trace == {}
        return
    if provider == "openai":
        assert body["reasoning_effort"] == level
    elif provider == "deepseek":
        assert body["model"] == "deepseek-reasoner"
        assert body["max_tokens"] == sidecar.REASONER_MAX_TOKENS_FLOORS[level]
        if level == "high":
            assert "600" in stderr
    elif provider == "bailian":
        assert body["enable_thinking"] is True
        assert body["thinking_budget"] == sidecar.BAILIAN_THINK_BUDGETS[level]
        assert body["tool_choice"] == "auto"
        assert trace == {"tool_choice_downgraded": True}
    else:
        assert body["think"] is True
        if level == "high":
            assert "num_ctx" in stderr


def test_off_preserves_cli_switches(capsys):
    openai_body = {"model": "m", "reasoning_effort": "max"}
    body, trace = sidecar._apply_thinking(openai_body, "off", "openai")
    assert body == {"model": "m", "reasoning_effort": "max"}
    assert trace == {}
    ollama_body = {"model": "m", "think": False}
    body, trace = sidecar._apply_thinking(ollama_body, "off", "ollama")
    assert body == {"model": "m", "think": False}


def test_bailian_tool_choice_downgrade():
    body, trace = sidecar._apply_thinking(
        {"tool_choice": "required"}, "low", "bailian")
    assert body["tool_choice"] == "auto"
    assert trace == {"tool_choice_downgraded": True}
    body, trace = sidecar._apply_thinking(
        {"tool_choice": {"type": "function", "function": {"name": "x"}}},
        "high", "bailian")
    assert body["tool_choice"] == "auto"
    assert trace == {"tool_choice_downgraded": True}


def test_unknown_provider_passthrough():
    original = {"model": "m", "max_tokens": 1}
    body, trace = sidecar._apply_thinking(copy.deepcopy(original), "high",
                                          "anthropic")
    assert body == original
    assert trace == {}


def test_unknown_level_falls_back_to_off():
    original = {"model": "m", "reasoning_effort": "max"}
    body, trace = sidecar._apply_thinking(copy.deepcopy(original), "turbo",
                                          "openai")
    assert body == original
    assert trace == {}


def test_provider_detection_order():
    config = sidecar.SidecarConfig.__new__(sidecar.SidecarConfig)
    config.upstream = "https://api.deepseek.com"
    config.kind = "openai"
    config.upstream_kind_explicit = False
    assert sidecar.thinking_provider(config) == "deepseek"
    config.upstream_kind_explicit = True
    assert sidecar.thinking_provider(config) == "openai"
    config.kind = "openai"
    config.upstream = "https://dashscope.aliyuncs.com/compatible-mode"
    config.upstream_kind_explicit = False
    assert sidecar.thinking_provider(config) == "bailian"
