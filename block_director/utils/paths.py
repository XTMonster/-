"""跨平台路径解析（执行文档 v1.2 §1.4 / §14.3）。

禁止在别处硬编码 ~/.config 或 Windows 反斜杠拼接，一律经过本模块。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from ..contracts.config import default_config_dir, default_config_path

APP_DIR_NAME = "BlockDirector"


def config_dir() -> Path:
    return default_config_dir()


def config_path() -> Path:
    return default_config_path()


def default_project_root() -> Path:
    """默认项目根目录：文档目录下的 BlockDirector Projects。"""
    env = os.environ.get("BLOCKDIRECTOR_PROJECTS")
    if env:
        return Path(env)
    home = Path.home()
    documents = home / "Documents"
    base = documents if documents.exists() else home
    return base / "BlockDirector Projects"


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def is_windows() -> bool:
    return sys.platform.startswith("win")
