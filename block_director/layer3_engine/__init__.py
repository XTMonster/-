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
from .scene_sync import (
    SYNC_ID_KEY,
    USER_ANIMATED_KEY,
    SceneSynchronizer,
    SyncRecord,
    get_synchronizer,
    is_user_animated,
    mark_user_animated,
    note_build,
    reset_synchronizer,
    suppress_sync,
)
from .shot_regenerator import (
    ShotRegenError,
    clear_keyframes_in_range,
    regenerate_shot,
    shot_ranges,
)

__all__ = ["build_scene", "BpySceneBuilder", "SceneSpec", "CastMember",
           "BuildSummary", "ShotBuildResult",
           "SceneSynchronizer", "SyncRecord", "suppress_sync",
           "SYNC_ID_KEY", "USER_ANIMATED_KEY", "mark_user_animated",
           "is_user_animated", "get_synchronizer", "reset_synchronizer",
           "note_build",
           "regenerate_shot", "shot_ranges", "clear_keyframes_in_range",
           "ShotRegenError"]
