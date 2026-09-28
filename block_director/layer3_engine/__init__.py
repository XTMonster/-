"""执行引擎（执行文档 v1.2 §8）。

本层直接操作 bpy，所有对外的入口都必须是主线程调用：
公共函数用 ``@main_thread_only`` 装饰，违反时抛 ``ThreadViolation``。
"""

from __future__ import annotations

from .shot_builder import (
    BpySceneBuilder,
    BuildSummary,
    CastMember,
    SceneSpec,
    ShotBuildResult,
    build_scene,
)

__all__ = ["build_scene", "BpySceneBuilder", "SceneSpec", "CastMember",
           "BuildSummary", "ShotBuildResult"]
