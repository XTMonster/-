"""场景构建器协议（执行文档 v1.2 §7.1 阶段 B2）。

驱动器**不 import bpy**：它只依赖这个协议；真正的 bpy 实现在
``layer3_engine/shot_builder.py``（``BpySceneBuilder``）。
这样 headless / 测试里可以注入假实现，驱动器本身仍可在 Blender 外单测。
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Protocol, runtime_checkable

from ..contracts.brief import SceneBrief
from ..contracts.plan import Plan


@runtime_checkable
class SceneBuilder(Protocol):
    """把一份分镜计划落成场景。返回摘要字典供审计与 UI 展示。"""

    def build(self, plan: Plan,
              brief: Optional[SceneBrief] = None) -> Dict[str, Any]:
        """``brief`` 是阶段 S 的剧本理解（§3.2）。

        用来决定站位与视线——没有它时退回"两人相对而立"的默认站位。
        """
        ...
