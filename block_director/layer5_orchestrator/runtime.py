"""当前运行的单例句柄。

UI 面板要读运行状态，而模态算子要写它；用一个极薄的模块级单例避免两者
互相 import（也避免把驱动器实例塞进 bpy 属性里）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # pragma: no cover
    from .driver import PrevisDriver

_active: Optional["PrevisDriver"] = None


def set_active(driver: Optional["PrevisDriver"]) -> None:
    global _active
    _active = driver


def get_active() -> Optional["PrevisDriver"]:
    return _active


def clear_active() -> None:
    global _active
    _active = None


def is_running() -> bool:
    return _active is not None and not _active.finished
