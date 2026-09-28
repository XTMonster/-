"""场景观察（执行文档 v1.2 §7.3）——LLM 的眼睛。

纯计算：状态数据结构与给 LLM 看的文本摘要都在这里，不依赖 bpy；
采集由 ``layer3_engine/scene_state.py`` 负责。这样"摘要长什么样"可以被单测。
"""

from __future__ import annotations

from .state import CameraState, CharacterState, SceneState, format_scene_state

__all__ = ["SceneState", "CameraState", "CharacterState", "format_scene_state"]
