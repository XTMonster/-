"""插件侧配置单例：把 contracts.AppConfig 接到磁盘（执行文档 v1.2 §21.5）。

注意：模块名刻意不叫 config，避免与 block_director.contracts.config 混淆。
"""

from __future__ import annotations

from typing import Optional

from .contracts.config import AppConfig
from .utils.logger import get_logger

log = get_logger("settings")

_config: Optional[AppConfig] = None
_config_path = None


def load_config(path=None) -> AppConfig:
    """读取配置（不存在则用默认值），并把校验问题写进日志。"""
    global _config, _config_path
    _config = AppConfig.load(path)
    _config_path = path
    for issue in _config.validate():
        level = log.error if issue.severity.value == "error" else log.warning
        level("配置问题 %s", issue)
    log.info("已加载配置：transport=%s rag=%s backend=%s",
             _config.llm.transport, _config.rag.backend,
             _config.delivery.render_backend)
    return _config


def get_config() -> AppConfig:
    """获取当前配置，必要时惰性加载。"""
    if _config is None:
        return load_config()
    return _config


def set_config(config: AppConfig) -> None:
    """覆盖当前配置（测试与 UI 修改用）。"""
    global _config
    _config = config


def reset_config() -> None:
    """清空缓存，下次 get_config() 会重新读盘。"""
    global _config, _config_path
    _config = None
    _config_path = None


def config_path():
    return _config_path
