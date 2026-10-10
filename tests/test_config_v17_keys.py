"""卡 A2：配置新键（UI 组）（v1.7 TDD §4.1）。"""

from __future__ import annotations

import copy

from block_director.contracts.config import AppConfig
from block_director.contracts.enums import Severity


def _default_without_new_keys() -> dict:
    """1.3.0 形态：从默认配置摘掉 v1.7 新键（历史配置零 error 加载的对拍口径）。"""
    data = copy.deepcopy(AppConfig().to_dict())
    data["llm"].pop("thinking_level", None)
    data["audit"].pop("rules_disabled", None)
    for key in ("enabled", "viewport_sprite", "web_auto_open"):
        data["ui"].pop(key, None)
    data.pop("script_polish", None)
    return data


def test_defaults_roundtrip():
    restored = AppConfig.from_dict(AppConfig().to_dict())
    assert restored == AppConfig()


def test_cfg170_triggers_once():
    config = AppConfig()
    config.llm.thinking_level = "turbo"
    issues = [issue for issue in config.validate()
              if issue.code == "CFG_170"]
    assert len(issues) == 1
    assert issues[0].severity is Severity.WARNING


def test_cfg171_triggers_once():
    config = AppConfig()
    config.audit.rules_disabled = ["R09"]
    issues = [issue for issue in config.validate()
              if issue.code == "CFG_171"]
    assert len(issues) == 1
    assert issues[0].severity is Severity.WARNING


def test_old_config_zero_new_errors():
    config = AppConfig.from_dict(_default_without_new_keys())
    assert config.errors() == []
    assert config.llm.thinking_level == "off"
    assert config.audit.rules_disabled == []
    assert config.ui.enabled is True
    assert config.ui.viewport_sprite is True
    assert config.ui.web_auto_open is False
    assert config.script_polish.enabled is False


def test_script_polish_defaults():
    config = AppConfig()
    assert config.script_polish.enabled is False
    assert config.script_polish.max_suggestions == 20
