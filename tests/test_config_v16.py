"""v1.6 A4：LLM 超时配置与面板设置（D-01）。"""

from __future__ import annotations

import pytest

from block_director.contracts.config import AppConfig
from block_director.layer5_orchestrator.driver import DriverLimits, PrevisDriver
from block_director.layer6_audit.audit_logger import AuditLogger
from block_director.layer7_ui.run_settings import apply_scene_settings


def test_default_llm_timeout_is_300s():
    cfg = AppConfig()
    assert cfg.llm.timeout_s == 300.0


def test_non_positive_timeout_is_an_error():
    cfg = AppConfig()
    cfg.llm.timeout_s = 0.0
    assert any(item.code == "CFG_023" for item in cfg.errors())
    cfg.llm.timeout_s = -10.0
    assert any(item.code == "CFG_023" for item in cfg.errors())


def test_default_config_has_no_errors():
    assert AppConfig().errors() == []


def test_run_settings_applies_timeout():
    cfg = AppConfig()
    _, problems = apply_scene_settings(cfg, {"llm_timeout_s": 600.0})
    assert problems == []
    assert cfg.llm.timeout_s == 600.0


def test_run_settings_rejects_non_positive_timeout():
    cfg = AppConfig()
    _, problems = apply_scene_settings(cfg, {"llm_timeout_s": 0.0})
    assert any("必须为正数" in p for p in problems)


def test_run_settings_rejects_non_numeric_timeout():
    cfg = AppConfig()
    _, problems = apply_scene_settings(cfg, {"llm_timeout_s": "fast"})
    assert any("必须是数字" in p for p in problems)


def test_driver_reads_timeout_from_config():
    class _DummyTransport:
        def chat(self, payload, timeout):
            return {"content": "ok"}

    cfg = AppConfig()
    cfg.llm.timeout_s = 750.0
    driver = PrevisDriver(
        transport=_DummyTransport(), audit=AuditLogger(), config=cfg)
    assert driver.limits.llm_timeout_s == 750.0


def test_driver_explicit_limits_override_config_timeout():
    class _DummyTransport:
        def chat(self, payload, timeout):
            return {"content": "ok"}

    cfg = AppConfig()
    cfg.llm.timeout_s = 750.0
    limits = DriverLimits(llm_timeout_s=120.0)
    driver = PrevisDriver(
        transport=_DummyTransport(), audit=AuditLogger(), config=cfg,
        limits=limits)
    assert driver.limits.llm_timeout_s == 120.0
