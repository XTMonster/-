"""密钥存取与掩码（v1.7 卡 B2 / TDD §4.3，R-UI-1）。

纯 Python、无 bpy。落盘 ``%APPDATA%/BlockDirector/secrets.json``（POSIX
``~/.config/blockdirector/secrets.json``），0600；读取优先级（钉死）：
环境变量 > secrets.json > 配置文件 ``llm.api_key``。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from ..contracts.config import AppConfig, default_config_dir

#: 统一密钥环境变量优先；其次 ``<PROVIDER 大写>_API_KEY``（如 DEEPSEEK_API_KEY）。
UNIFIED_KEY_ENV = "BLOCKDIRECTOR_API_KEY"


def secrets_path() -> Path:
    """``%APPDATA%/BlockDirector/secrets.json``；POSIX
    ``~/.config/blockdirector/secrets.json``。复用
    :func:`contracts.config.default_config_dir`，不自己拼。
    """
    return default_config_dir() / "secrets.json"


def load_secrets(path: Optional[Path] = None) -> Dict[str, str]:
    """读取全部 provider→key；缺文件/坏 JSON 一律回空表（key 是附属品）。"""
    target = Path(path) if path is not None else secrets_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): str(value) for key, value in data.items()
            if value is not None}


def save_secret(provider: str, api_key: str,
                path: Optional[Path] = None) -> None:
    """合并写一条 key；写后 ``chmod 0600``（POSIX 语义；Windows 上 NTFS
    ACL 兜底——本函数不实现 ACL，注释如实说明）。"""
    target = Path(path) if path is not None else secrets_path()
    secrets = load_secrets(target)
    secrets[str(provider)] = str(api_key)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(secrets, ensure_ascii=False, indent=2)
    target.write_text(text, encoding="utf-8")
    if os.name == "posix":
        os.chmod(target, 0o600)
    #: Windows：NTFS 权限继承自 %APPDATA% 用户目录，本函数不额外设 ACL。


def mask_key(key: str) -> str:
    """长度 <8 → 全长 ``*``（空串 → ""）；否则 前 3 字符 + ``…****``。"""
    text = str(key or "")
    if not text:
        return ""
    if len(text) < 8:
        return "*" * len(text)
    return text[:3] + "…****"


def effective_key(provider: str, config: AppConfig) -> str:
    """生效 key 解析顺序（TDD §4.3 钉死）：

    1. ``BLOCKDIRECTOR_API_KEY``（统一变量）；
    2. ``<PROVIDER 大写>_API_KEY``（按序取第一个非空）；
    3. ``secrets.json`` 的该 provider 条目；
    4. 配置文件 ``llm.api_key``。

    插件侧 transport 的切换（env 优先口径）列移交事项，本卡只让 sidecar 用。
    """
    candidates = [os.environ.get(UNIFIED_KEY_ENV, ""),
                  os.environ.get(f"{str(provider).upper()}_API_KEY", "")]
    for candidate in candidates:
        if candidate:
            return candidate
    stored = load_secrets().get(str(provider), "")
    if stored:
        return stored
    return str((config.llm.api_key or "")).strip()
