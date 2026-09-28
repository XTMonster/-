"""当前场景的上下文单例（供工具层读写）。

场景建好之后，工具（查询/角色/相机）需要知道"现在有哪些角色、当前是哪台
相机、轴线是哪条"。把这些放进一个薄上下文，避免工具去猜对象命名。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ..cinema.axis import Axis
from ..contracts.plan import Plan


@dataclass
class SceneContext:
    characters: Dict[str, Any] = field(default_factory=dict)     # id → Character
    cameras: Dict[str, Any] = field(default_factory=dict)        # shot_id → camera 对象
    shot_types: Dict[str, str] = field(default_factory=dict)     # shot_id → 景别
    schedule: Dict[str, Tuple[int, int]] = field(default_factory=dict)  # shot_id → (起, 止)
    plan: Optional[Plan] = None
    current_shot_id: str = ""
    axis: Optional[Axis] = None
    notes: List[str] = field(default_factory=list)

    def character(self, character_id: str):
        return self.characters.get(character_id)

    def camera_for(self, shot_id: str = ""):
        key = shot_id or self.current_shot_id
        return self.cameras.get(key)

    def camera_by_name(self, name: str):
        for camera in self.cameras.values():
            if getattr(camera, "name", "") == name:
                return camera
        return None

    def shot(self, shot_id: str = ""):
        """取镜头计划（默认当前镜头）。"""
        if self.plan is None:
            return None
        key = shot_id or self.current_shot_id
        for shot in self.plan.shots:
            if shot.shot_id == key:
                return shot
        return None

    @property
    def character_list(self) -> List[Any]:
        return list(self.characters.values())


_active: Optional[SceneContext] = None


def set_context(context: Optional[SceneContext]) -> None:
    global _active
    _active = context


def get_context() -> Optional[SceneContext]:
    return _active


def clear_context() -> None:
    global _active
    _active = None
