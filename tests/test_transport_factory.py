"""§2.5 运行时传输接线的测试（离线 / sidecar / 直连三条路径）。"""

from __future__ import annotations

import pytest

from block_director.contracts.config import AppConfig
from block_director.contracts.enums import TransportMode
from block_director.contracts.transport import OpenAICompatibleTransport, SidecarTransport
from block_director.layer5_orchestrator.offline import OfflineTransport
from block_director.layer5_orchestrator.transport_factory import (
    TransportUnavailable,
    build_direct,
    make_transport,
)


def _config(**llm_overrides) -> AppConfig:
    config = AppConfig()
    for key, value in llm_overrides.items():
        setattr(config.llm, key, value)
    return config


def test_offline_mode_is_returned_as_is():
    transport, mode = make_transport(_config(), offline=True)
    assert isinstance(transport, OfflineTransport) and mode == "offline"


def test_direct_mode_uses_configured_key():
    transport, mode = make_transport(
        _config(transport=TransportMode.DIRECT, api_key="sk-test",
                model="deepseek-chat"))
    assert mode == "direct"
    assert isinstance(transport, OpenAICompatibleTransport)
    assert transport.api_key == "sk-test" and transport.model == "deepseek-chat"


def test_direct_mode_without_credentials_is_refused():
    with pytest.raises(TransportUnavailable) as excinfo:
        make_transport(_config(transport=TransportMode.DIRECT))
    message = str(excinfo.value)
    assert "离线自检" in message and "sidecar" in message and "api_key" in message


def test_auto_falls_back_to_direct_when_sidecar_is_unreachable():
    config = _config(transport=TransportMode.AUTO, api_key="sk-test",
                     sidecar_url="http://127.0.0.1:1")
    transport, mode = make_transport(config)
    assert mode == "direct" and isinstance(transport, OpenAICompatibleTransport)


def test_auto_prefers_sidecar_when_healthy(monkeypatch):
    config = _config(transport=TransportMode.AUTO, api_key="sk-test")
    monkeypatch.setattr(SidecarTransport, "probe",
                        lambda self, timeout=2.0: object())
    transport, mode = make_transport(config)
    assert mode == "sidecar" and isinstance(transport, SidecarTransport)


def test_local_endpoint_without_key_is_enough():
    """本地模型（Ollama/vLLM）不需要 API Key，只要有 base_url。"""
    transport = build_direct(_config(base_url="http://127.0.0.1:11434"))
    assert transport is not None
    assert transport.base_url == "http://127.0.0.1:11434/v1"
    assert transport.api_key == ""


def test_explicit_v1_suffix_is_not_doubled():
    transport = build_direct(_config(base_url="http://127.0.0.1:8000/v1"))
    assert transport.base_url == "http://127.0.0.1:8000/v1"


def test_default_openai_endpoint_when_only_key_given():
    transport = build_direct(_config(api_key="sk-test"))
    assert transport.base_url == "https://api.openai.com/v1"


def test_no_endpoint_and_no_key_returns_none():
    assert build_direct(_config()) is None
