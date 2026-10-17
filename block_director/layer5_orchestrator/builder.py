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


class PreparableSceneBuilder(SceneBuilder, Protocol):
    """方案 B 的可选能力（§3.6.3）：先准备场景，再逐镜预演。

    这两个方法是**可选**的：运行时用 ``hasattr(builder, "prepare_scene")``
    / ``hasattr(builder, "rebuild_shot")`` 探测，未实现时驱动器退回整场
    ``build`` 路径（兼容回退，不是降级）。因此它们不写进
    ``@runtime_checkable`` 的 :class:`SceneBuilder`（否则只实现 ``build``
    的假 builder 会因 ``isinstance`` 判定而红）。

    - ``prepare_scene(plan, brief=None, spec=None) -> Dict``：只建场景与元素
      （清对象/集合、环境/锚点/灯光、角色/标签、道具、群众），落
      ``SceneContext`` 并记基线；**不摆相机、不烘焙动作**。
    - ``rebuild_shot(shot_id, *, plan=None, brief=None) -> Dict``：只重建/
      预演当前镜（换该镜相机、清该镜帧窗关键帧、重烘该镜动作），不推倒
      环境/角色/其他镜。
    """

    def prepare_scene(self, plan: Plan,
                      brief: Optional[SceneBrief] = None,
                      spec: Optional[Any] = None) -> Dict[str, Any]:
        ...

    def rebuild_shot(self, shot_id: str, *, plan: Optional[Plan] = None,
                     brief: Optional[SceneBrief] = None) -> Dict[str, Any]:
        ...
