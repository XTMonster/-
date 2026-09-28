"""剧组与场景设定（执行文档 v1.2 §5.1 的 characters / environment）。

刻意不依赖 bpy：Layer 2（SDL）与 Layer 3（执行引擎）都要用它，放进 contracts
才不会让 SDL 反向依赖执行引擎。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .plan import Plan

DEFAULT_COLORS = ("#FF6B6B", "#6BC5FF", "#FFD166", "#9B8CFF",
                  "#6BE3A2", "#FF9F6B")
DEFAULT_SPACING = 1.5
DEFAULT_GROUND = (120.0, 120.0)

ID_PREFIX = "char_"
ID_DIGITS = 3


def next_character_id(existing) -> str:
    """分配下一个空闲角色 id（``char_001``…）。

    纯函数、可单测。放在契约层是因为"角色 id 长什么样"是 §5.1 的约定，
    UI 的"添加角色"与 SDL 校验都依赖它。
    """
    used = set()
    for item in existing or ():
        text = str(item or "")
        if text.startswith(ID_PREFIX) and text[len(ID_PREFIX):].isdigit():
            used.add(int(text[len(ID_PREFIX):]))
    index = 1
    while index in used:
        index += 1
    return f"{ID_PREFIX}{index:0{ID_DIGITS}d}"


@dataclass
class CastMember:
    """一名角色的设定。

    字段名与执行文档 §5.1 / §16.1（``CharacterDef``）保持一致：落盘键是
    ``initial_location`` / ``initial_facing``，以免 SDL 文件与规范漂移。
    """

    id: str
    name: str
    color: str = "#FFFFFF"
    initial_location: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    initial_facing: Tuple[float, float, float] = (0.0, 1.0, 0.0)

    def to_dict(self) -> Dict[str, Any]:
        from .serde import to_plain
        return to_plain(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CastMember":
        from .serde import from_plain
        return from_plain(cls, data)


@dataclass
class SceneSpec:
    """场景设定：谁在场、环境长什么样。"""

    heading: str = ""
    cast: List[CastMember] = field(default_factory=list)
    ground_size: Tuple[float, float] = DEFAULT_GROUND
    walls: List[Dict[str, Any]] = field(default_factory=list)
    props: List[Dict[str, Any]] = field(default_factory=list)
    lighting: str = "clay_studio"
    room: Optional[Tuple[float, float, float, float]] = None
    with_labels: bool = True

    @classmethod
    def from_plan(cls, plan: Plan, **overrides) -> "SceneSpec":
        """按计划里出现的角色自动生成一份确定性剧组设定。"""
        character_ids: List[str] = []
        for shot in plan.shots:
            for character_id in shot.characters:
                if character_id not in character_ids:
                    character_ids.append(character_id)
        cast: List[CastMember] = []
        count = len(character_ids)
        for index, character_id in enumerate(character_ids):
            offset = (index - (count - 1) / 2.0) * DEFAULT_SPACING
            cast.append(CastMember(
                id=character_id, name=character_id,
                color=DEFAULT_COLORS[index % len(DEFAULT_COLORS)],
                initial_location=(round(offset, 3), 0.0, 0.0)))
        return cls(heading=plan.scene_heading, cast=cast, **overrides)

    def to_dict(self) -> Dict[str, Any]:
        from .serde import to_plain
        return to_plain(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SceneSpec":
        from .serde import from_plain
        return from_plain(cls, data)
