"""模块注册/注销编排（执行文档 v1.2 §21.6）。

所有需要注册 bpy 类的子模块在此集中登记；register/unregister 成对出现，
任一模块注册失败都会被记录并继续，避免单个 UI 模块拖垮整个插件加载。
"""

from __future__ import annotations

import importlib
from typing import List, Tuple

from .utils.logger import get_logger

log = get_logger("registration")

# 顺序即注册顺序；注销时逆序执行。
MODULES: Tuple[str, ...] = (
    "block_director.layer7_ui.panel_main",
    "block_director.layer7_ui.panel_shots",
    "block_director.layer7_ui.panel_debug",
    "block_director.layer7_ui.draw_overlay",
    "block_director.layer7_ui.operator_path_draw",
    "block_director.layer5_orchestrator.modal_operator",
)

_registered: List[str] = []


def register_all() -> List[str]:
    """导入并注册全部模块，返回实际注册成功的模块名。"""
    del _registered[:]
    for name in MODULES:
        try:
            module = importlib.import_module(name)
            module.register()
            _registered.append(name)
        except Exception as exc:  # noqa: BLE001 - 单个模块失败不应中断加载
            log.error("注册模块 %s 失败: %s: %s", name, type(exc).__name__, exc)
    return list(_registered)


def unregister_all() -> None:
    """逆序注销已注册模块。"""
    for name in reversed(_registered):
        try:
            module = importlib.import_module(name)
            module.unregister()
        except Exception as exc:  # noqa: BLE001
            log.error("注销模块 %s 失败: %s: %s", name, type(exc).__name__, exc)
    del _registered[:]
