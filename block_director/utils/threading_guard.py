"""主线程守卫（执行文档 v1.2 §3.1 的强制化实现）。

**为什么需要它（实测依据）**
架构审核 `tools/audit_architecture.py::threading_model` 在 Blender 5.2 上验证：
从后台线程调用 ``bpy.data.objects.new()``、``bpy.ops.mesh.primitive_cube_add()``
以及 ``bpy.context.view_layer.update()`` **全部静默成功，不报任何错**。
也就是说 Blender 不提供跨线程护栏，"网络在后台线程、bpy 只在主线程"
这条架构红线完全依赖开发者自觉。

本模块把这条红线变成**可断言的运行时约束**：凡是触碰 bpy 的入口，
一律先过 :func:`assert_main_thread`。违反时立即抛 :class:`ThreadViolation`，
把"偶尔崩溃、难以复现"变成"当场报错、定位到调用点"。

本模块不 import bpy，可在任意 Python 环境与测试中使用。
"""

from __future__ import annotations

import functools
import logging
import threading
from typing import Any, Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

# 记录主线程标识。模块通常在主线程被导入；若在别处导入，
# 可在 Blender 的 register() 里显式调用 capture_main_thread() 修正。
_MAIN_THREAD_ID: Optional[int] = threading.main_thread().ident


class ThreadViolation(RuntimeError):
    """在非主线程访问了只允许主线程使用的资源（通常是 bpy）。"""


def capture_main_thread() -> int:
    """显式登记"当前线程为主线程"。在插件 register() 中调用。"""
    global _MAIN_THREAD_ID
    _MAIN_THREAD_ID = threading.get_ident()
    logger.debug("BlockDirector: main thread captured (ident=%s)", _MAIN_THREAD_ID)
    return _MAIN_THREAD_ID


def main_thread_id() -> Optional[int]:
    return _MAIN_THREAD_ID


def is_main_thread() -> bool:
    return threading.get_ident() == _MAIN_THREAD_ID


def assert_main_thread(operation: str = "") -> None:
    """断言当前处于主线程；否则抛 :class:`ThreadViolation`。"""
    if not is_main_thread():
        current = threading.get_ident()
        where = f"（{operation}）" if operation else ""
        raise ThreadViolation(
            f"检测到非主线程访问 bpy{where}：当前线程 {current}，"
            f"主线程 {_MAIN_THREAD_ID}。"
            "按 §3.1，bpy 只能在主线程触碰；请把该调用投递回主线程"
            "（Modal timer 或 headless 同步循环）。"
        )


def off_main_thread(operation: str = "") -> bool:
    """便捷判定：当前是否在后台线程（后台线程允许做纯计算/网络）。"""
    return not is_main_thread()


def main_thread_only(operation: str = "") -> Callable[[F], F]:
    """装饰器：包裹只允许在主线程执行的函数。"""
    label = operation

    def deco(fn: F) -> F:
        name = label or getattr(fn, "__qualname__", getattr(fn, "__name__", "callable"))

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            assert_main_thread(name)
            return fn(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return deco
