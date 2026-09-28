"""SceneState 数据结构与文本格式化（执行文档 v1.2 §7.3）。

设计要点：**轻量摘要**不含屏幕投影（只有位置/朝向），只有在
``check_composition`` / ``check_visibility`` 这类查询里才做完整投影与遮挡
检测——避免每次观察都付一遍投影与射线的代价。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

Vector3 = Tuple[float, float, float]
ScreenPoint = Tuple[float, float]


@dataclass
class CharacterState:
    id: str
    name: str
    position: Vector3
    facing: Vector3
    in_frame: Optional[bool] = None            # 需要投影才有值
    screen_position: Optional[ScreenPoint] = None
    height_fraction: Optional[float] = None
    occluded: Optional[bool] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "name": self.name,
            "position": [round(float(v), 3) for v in self.position],
            "facing": [round(float(v), 3) for v in self.facing],
            "in_frame": self.in_frame,
            "screen_position": ([round(float(v), 3) for v in self.screen_position]
                                if self.screen_position else None),
            "height_fraction": self.height_fraction,
            "occluded": self.occluded,
        }


@dataclass
class CameraState:
    id: str
    shot_id: str = ""
    shot_type: str = ""
    position: Vector3 = (0.0, 0.0, 0.0)
    target: Vector3 = (0.0, 0.0, 0.0)
    lens: float = 50.0
    composition_score: Optional[float] = None
    visible_characters: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "shot_id": self.shot_id, "shot_type": self.shot_type,
            "position": [round(float(v), 3) for v in self.position],
            "target": [round(float(v), 3) for v in self.target],
            "lens": self.lens, "composition_score": self.composition_score,
            "visible_characters": list(self.visible_characters),
        }


@dataclass
class SceneState:
    frame: int = 1
    total_frames: int = 0
    current_shot_id: str = ""
    current_camera_id: str = ""
    characters: List[CharacterState] = field(default_factory=list)
    camera: Optional[CameraState] = None
    notes: List[str] = field(default_factory=list)
    detailed: bool = False          # 是否包含屏幕投影（完整采集）

    def to_dict(self) -> Dict[str, Any]:
        return {
            "frame": self.frame, "total_frames": self.total_frames,
            "current_shot_id": self.current_shot_id,
            "current_camera_id": self.current_camera_id,
            "detailed": self.detailed,
            "camera": self.camera.to_dict() if self.camera else None,
            "characters": [c.to_dict() for c in self.characters],
            "notes": list(self.notes),
        }


def _fmt_vec(value: Optional[Sequence[float]]) -> str:
    if value is None:
        return "—"
    return "(" + ", ".join(f"{float(v):.2f}" for v in value) + ")"


def _fmt_character(character: CharacterState) -> str:
    parts = [
        f"- {character.id} {character.name}",
        f"位置 {_fmt_vec(character.position)}",
        f"朝向 {_fmt_vec(character.facing)}",
    ]
    if character.in_frame is not None:
        parts.append("在画" if character.in_frame else "**不在画**")
    if character.screen_position is not None:
        parts.append(f"屏幕 ({character.screen_position[0]:.2f}, "
                     f"{character.screen_position[1]:.2f})")
    if character.height_fraction is not None:
        parts.append(f"高度占比 {character.height_fraction:.2f}")
    if character.occluded:
        parts.append("**被遮挡**")
    return " ".join(parts)


def format_scene_state(state: SceneState) -> str:
    """把场景状态压成 LLM 可读的紧凑文本（§7.3）。"""
    header = (f"场景状态（帧 {state.frame}/{state.total_frames or '?'}｜"
              f"当前镜头 {state.current_shot_id or '—'}｜"
              f"当前相机 {state.current_camera_id or '—'}）")
    lines: List[str] = [header]

    camera = state.camera
    if camera is not None:
        camera_line = (f"相机 {camera.id}（{camera.shot_type or '—'}）"
                       f"位置 {_fmt_vec(camera.position)} "
                       f"目标 {_fmt_vec(camera.target)} "
                       f"焦距 {camera.lens:g}mm")
        if camera.composition_score is not None:
            camera_line += f" 构图 {camera.composition_score:.1f}"
        if camera.visible_characters:
            camera_line += f" 可见 {'/'.join(camera.visible_characters)}"
        lines.append(camera_line)
    else:
        lines.append("相机：尚未设置")

    if state.characters:
        lines.append(f"角色（{len(state.characters)}）：")
        lines.extend(_fmt_character(c) for c in state.characters)
    else:
        lines.append("角色：尚未放置")

    if not state.detailed:
        lines.append("提示：本摘要不含屏幕投影；需要画面内位置请调用 "
                     "check_visibility / check_composition。")
    if state.notes:
        lines.extend(f"注意：{note}" for note in state.notes)
    return "\n".join(lines)
