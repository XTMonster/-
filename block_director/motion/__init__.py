"""动作与姿态模型（执行文档 v1.2 §9.6 / §9.7）。

本包**不依赖 bpy**：姿态函数、跨层冲突仲裁、混合权重全是纯计算，
因此可以用 pytest 直接覆盖；真正写关键帧的落地代码在
``layer3_engine/character_system/motion_library.py``。

这是对 §2.3 目录清单的一处刻意调整：把"可测的核心"从 bpy 模块里拿出来，
否则混合与冲突逻辑永远只能靠人工在 Blender 里点。
"""

from __future__ import annotations

from .model import (
    ACTION_TYPES,
    BLEND_FRAMES,
    CHANNEL_OWNER,
    FPS,
    LAYER_OF,
    ActionRequest,
    MotionSpec,
    check_conflicts,
    compose,
    expand,
)

__all__ = [
    "ActionRequest", "MotionSpec", "expand", "compose", "check_conflicts",
    "LAYER_OF", "CHANNEL_OWNER", "BLEND_FRAMES", "FPS",
    "ACTION_TYPES",
]
