"""v1.7 卡 B2：secret_store 纯函数（掩码边界 + 读写 + 优先级）。"""

from __future__ import annotations

import json
import os

import pytest

from block_director.contracts.config import AppConfig
from block_director.utils import secret_store
from block_director.utils.secret_store import (
    UNIFIED_KEY_ENV,
    effective_key,
    load_secrets,
    mask_key,
    save_secret,
)


def test_mask_boundaries():
    assert mask_key("") == ""
    assert mask_key("1234567") == "*******"
    assert mask_key("12345678") == "123…****"
    assert mask_key("a" * 20) == "aaa…****"


def test_save_and_load_merge(tmp_path):
    path = tmp_path / "secrets.json"
    save_secret("deepseek", "sk-a", path)
    save_secret("openai", "sk-b", path)
    assert load_secrets(path) == {"deepseek": "sk-a", "openai": "sk-b"}
    assert "sk-a" in json.loads(path.read_text(encoding="utf-8"))["deepseek"]


def test_load_missing_returns_empty(tmp_path):
    assert load_secrets(tmp_path / "none.json") == {}


def test_effective_key_priority(monkeypatch, tmp_path):
    monkeypatch.delenv(UNIFIED_KEY_ENV, raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(secret_store, "load_secrets",
                        lambda path=None: {})
    config = AppConfig()
    config.llm.provider = "deepseek"
    config.llm.api_key = "from-config"

    assert effective_key("deepseek", config) == "from-config"

    monkeypatch.setenv("DEEPSEEK_API_KEY", "from-provider-env")
    assert effective_key("deepseek", config) == "from-provider-env"

    monkeypatch.setenv(UNIFIED_KEY_ENV, "from-unified-env")
    assert effective_key("deepseek", config) == "from-unified-env"


def test_secret_file_0600(tmp_path):
    if os.name != "posix":
        pytest.skip("0600 只在 POSIX 断言；Windows 走 NTFS 继承权限")
    path = tmp_path / "secrets.json"
    save_secret("deepseek", "sk-x", path)
    assert (path.stat().st_mode & 0o777) == 0o600
