"""当前场景的上下文单例（供工具层读写）。

场景建好之后，工具（查询/角色/相机）需要知道"现在有哪些角色、当前是哪台
相机、轴线是哪条"。把这些放进一个薄上下文，避免工具去猜对象命名。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ..cinema.axis import Axis
from ..contracts.cast import SceneSpec
from ..contracts.plan import Plan


@dataclass
class SceneContext:
    characters: Dict[str, Any] = field(default_factory=dict)     # id → Character
    #: v1.3 §3.6：群众代理对象。**刻意不进 characters**——角色面板、场景
    #: 状态、构图评分与标签都按 characters 遍历，混进去这四处会一起失真。
    crowd: List[Any] = field(default_factory=list)
    vfx: Dict[str, Any] = field(default_factory=dict)            # vfx_id → 对象
    cameras: Dict[str, Any] = field(default_factory=dict)        # shot_id → camera 对象
    shot_types: Dict[str, str] = field(default_factory=dict)     # shot_id → 景别
    schedule: Dict[str, Tuple[int, int]] = field(default_factory=dict)  # shot_id → (起, 止)
    plan: Optional[Plan] = None
    spec: Optional[SceneSpec] = None      # §13.1 的角色管理要写回这里
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

    def subjects_for(self, shot_id: str = "") -> List[Any]:
        """本镜的**被摄主体**：镜头自己声明的角色；为空时退回全部角色。

        构图评分与规则判定必须共用同一份主体集合。v1.2 的
        ``check_composition`` 工具直接拿 ``character_list``（全剧组）去评分，
        于是画面里的第三个人会被当成主体——实测两人相对而立时，单人镜的
        搭档离机位更近、显得更大，评分从 71 掉到 40，修复循环被完全带偏。
        """
        shot = self.shot(shot_id)
        if shot is not None:
            subjects = [self.character(cid) for cid in shot.characters]
            subjects = [item for item in subjects if item is not None]
            if subjects:
                return subjects
        return self.character_list

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
