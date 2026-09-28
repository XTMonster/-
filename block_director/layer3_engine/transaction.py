"""事务式执行（执行文档 v1.2 §8.1）。

任何一批场景写入要么全部生效，要么全部回滚；回滚后必须回收孤儿 datablock
（实测：删除 5 个对象会留下 5 个孤儿 mesh，见架构审核报告）。
"""

from __future__ import annotations

import contextlib
from typing import Any, Dict, List, Tuple

import bpy
from bpy.types import Object

from ..utils.logger import get_logger
from ..utils.threading_guard import main_thread_only
from .collection_router import purge_orphan_data

log = get_logger("transaction")


class TransactionError(RuntimeError):
    """事务内发生异常并被回滚。"""


class Transaction:
    """记录本次创建/修改的对象，异常时回滚。"""

    def __init__(self, name: str = "bd-tx") -> None:
        self.name = name
        self.created: List[str] = []
        self.modified: List[Tuple[str, Dict[str, Any]]] = []
        self._active = False
        self._existing: set = set()

    # ------------------------------------------------------------- 记录
    @main_thread_only("Transaction.track_create")
    def track_create(self, obj: Object) -> Object:
        self.created.append(obj.name)
        return obj

    @main_thread_only("Transaction.track_modify")
    def track_modify(self, obj: Object) -> Object:
        self.modified.append((obj.name, self._snapshot(obj)))
        return obj

    @staticmethod
    def _snapshot(obj: Object) -> Dict[str, Any]:
        return {
            "location": tuple(obj.location),
            "rotation_euler": tuple(obj.rotation_euler),
            "scale": tuple(obj.scale),
        }

    # ------------------------------------------------------------- 生命周期
    def __enter__(self) -> "Transaction":
        self._active = True
        # 快照现有对象名：退出时据此自动识别"本批新建"的对象，
        # 调用方不必手动 track_create（少一个漏登记的坑）。
        self._existing = {obj.name for obj in bpy.data.objects}
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self._active = False
        if exc_type is not None:
            for obj in bpy.data.objects:
                if obj.name not in self._existing and obj.name not in self.created:
                    self.created.append(obj.name)
            self.rollback()
            log.warning("事务 %s 回滚：%s: %s", self.name,
                        exc_type.__name__, exc_val)
            return False        # 让异常继续向上传播
        return False

    @main_thread_only("Transaction.rollback")
    def rollback(self) -> None:
        for name, state in reversed(self.modified):
            obj = bpy.data.objects.get(name)
            if obj is None:
                continue
            obj.location = state["location"]
            obj.rotation_euler = state["rotation_euler"]
            obj.scale = state["scale"]
        for name in reversed(self.created):
            obj = bpy.data.objects.get(name)
            if obj is not None:
                bpy.data.objects.remove(obj, do_unlink=True)
        if self.created:
            purge_orphan_data()
        self.created.clear()
        self.modified.clear()


@contextlib.contextmanager
@main_thread_only("atomic")
def atomic(name: str = "bd-tx"):
    """便捷用法：``with atomic("build scene"): ...``"""
    with Transaction(name):
        yield
