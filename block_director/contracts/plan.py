"""分镜计划契约（执行文档 v1.2 §7.2 / §16.1）。

``ShotPlan`` 是阶段 A 的产物，也是 ``emit_plan`` 工具的参数形态。
放在 contracts 下是为了让插件侧与 sidecar 侧共享同一份定义。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .enums import SHOT_TYPES, ShotType

FPS = 24


@dataclass
class ShotPlan:
    """一个镜头的计划。时长以帧为单位（唯一时长真源，§5.1）。"""

    shot_id: str
    intent: str
    shot_type: ShotType
    duration_frames: int
    order: int = 0
    characters: List[str] = field(default_factory=list)
    dialogue_ids: List[str] = field(default_factory=list)
    axis_note: str = ""
    continuity_in: str = ""

    @property
    def duration_seconds(self) -> float:
        return self.duration_frames / FPS

    def to_dict(self) -> Dict[str, Any]:
        return {
            "shot_id": self.shot_id,
            "order": self.order,
            "intent": self.intent,
            "shot_type": str(self.shot_type),
            "duration_frames": self.duration_frames,
            "characters": list(self.characters),
            "dialogue_ids": list(self.dialogue_ids),
            "axis_note": self.axis_note,
            "continuity_in": self.continuity_in,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ShotPlan":
        raw_type = str(data.get("shot_type", "MS")).upper()
        shot_type = ShotType(raw_type) if raw_type in SHOT_TYPES else ShotType.MS
        return cls(
            shot_id=str(data["shot_id"]),
            intent=str(data.get("intent", "")),
            shot_type=shot_type,
            duration_frames=int(data["duration_frames"]),
            order=int(data.get("order", 0)),
            characters=list(data.get("characters", []) or []),
            dialogue_ids=list(data.get("dialogue_ids", []) or []),
            axis_note=str(data.get("axis_note", "")),
            continuity_in=str(data.get("continuity_in", "")),
        )


@dataclass
class Plan:
    """整场计划：镜头序列 + 连续性备注。"""

    shots: List[ShotPlan] = field(default_factory=list)
    continuity_notes: List[str] = field(default_factory=list)
    scene_heading: str = ""

    @property
    def total_frames(self) -> int:
        return sum(s.duration_frames for s in self.shots)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scene_heading": self.scene_heading,
            "continuity_notes": list(self.continuity_notes),
            "shots": [s.to_dict() for s in self.shots],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Plan":
        shots = [ShotPlan.from_dict(s) for s in data.get("shots", [])]
        for index, shot in enumerate(shots, start=1):
            if not shot.order:
                shot.order = index
        return cls(
            shots=shots,
            continuity_notes=list(data.get("continuity_notes", []) or []),
            scene_heading=str(data.get("scene_heading", "")),
        )
