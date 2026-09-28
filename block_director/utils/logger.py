"""统一日志入口（执行文档 v1.2 §2.3 utils/logger.py）。

插件所有模块通过 get_logger() 取 logger，便于统一设置级别与输出格式；
在 Blender 里默认输出到系统控制台，同时可由 UI 调整级别。
"""

from __future__ import annotations

import logging

ROOT_LOGGER = "block_director"
_configured = False


def configure(level: int = logging.INFO, force: bool = False) -> logging.Logger:
    """初始化根 logger。重复调用是安全的（除非 force=True）。"""
    global _configured
    logger = logging.getLogger(ROOT_LOGGER)
    if _configured and not force:
        return logger
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(
            "[BlockDirector] %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    _configured = True
    return logger


def set_level(level: int) -> None:
    logging.getLogger(ROOT_LOGGER).setLevel(level)


def get_logger(name: str = "") -> logging.Logger:
    configure()
    return logging.getLogger(f"{ROOT_LOGGER}.{name}" if name else ROOT_LOGGER)
