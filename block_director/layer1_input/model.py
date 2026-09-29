"""解析后的剧本数据结构（执行文档 v1.2 §4.2）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ParsedDialogue:
    character: str
    text: str
    parenthetical: str = ""          # （愤怒地）之类
    source_index: int = 0            # 原文顺序，便于回查
    start_frame: Optional[int] = None
    end_frame: Optional[int] = None
    emotion: str = "normal"
    #: 剧本里写明的时长（"（约3秒）"）。v1.3 起它优先于引擎的 3 字/秒估算。
    declared_seconds: Optional[float] = None

    @property
    def duration_frames(self) -> Optional[int]:
        if self.start_frame is None or self.end_frame is None:
            return None
        return self.end_frame - self.start_frame + 1

    def to_dict(self) -> Dict[str, Any]:
        return {"character": self.character, "text": self.text,
                "parenthetical": self.parenthetical,
                "source_index": self.source_index,
                "start_frame": self.start_frame, "end_frame": self.end_frame,
                "emotion": self.emotion,
                "declared_seconds": self.declared_seconds}


@dataclass
class ParsedAction:
    text: str
    characters_mentioned: List[str] = field(default_factory=list)
    source_index: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {"text": self.text,
                "characters_mentioned": list(self.characters_mentioned),
                "source_index": self.source_index}


@dataclass
class ParsedScene:
    scene_number: int
    heading: str
    location: str = ""
    time_of_day: str = ""
    interior_exterior: str = "INT"      # INT / EXT / INT_EXT
    actions: List[ParsedAction] = field(default_factory=list)
    dialogues: List[ParsedDialogue] = field(default_factory=list)
    scene_id: str = ""

    def __post_init__(self) -> None:
        if not self.scene_id:
            self.scene_id = f"scene_{self.scene_number:03d}"

    @property
    def characters(self) -> List[str]:
        """本场出现过的角色名（对白优先，动作补充），保持首次出现顺序。"""
        seen: List[str] = []
        for dialogue in self.dialogues:
            if dialogue.character and dialogue.character not in seen:
                seen.append(dialogue.character)
        for action in self.actions:
            for name in action.characters_mentioned:
                if name and name not in seen:
                    seen.append(name)
        return seen

    def to_dict(self) -> Dict[str, Any]:
        return {"scene_id": self.scene_id, "scene_number": self.scene_number,
                "heading": self.heading, "location": self.location,
                "time_of_day": self.time_of_day,
                "interior_exterior": self.interior_exterior,
                "characters": self.characters,
                "actions": [a.to_dict() for a in self.actions],
                "dialogues": [d.to_dict() for d in self.dialogues]}


@dataclass
class ParsedScript:
    title: str = ""
    source_format: str = "text"
    scenes: List[ParsedScene] = field(default_factory=list)
    #: 纯文本没有场景标题时置位：结构需要 LLM 补全（§4.1）
    needs_llm_structure: bool = False
    warnings: List[str] = field(default_factory=list)

    @property
    def character_names(self) -> List[str]:
        seen: List[str] = []
        for scene in self.scenes:
            for name in scene.characters:
                if name not in seen:
                    seen.append(name)
        return seen

    @property
    def dialogue_count(self) -> int:
        return sum(len(scene.dialogues) for scene in self.scenes)

    def to_dict(self) -> Dict[str, Any]:
        return {"title": self.title, "source_format": self.source_format,
                "needs_llm_structure": self.needs_llm_structure,
                "characters": self.character_names,
                "warnings": list(self.warnings),
                "scenes": [s.to_dict() for s in self.scenes]}

    def digest(self, *, max_scenes: int = 6) -> str:
        """给 LLM 看的紧凑剧本摘要（比原文更省 token，且结构明确）。"""
        lines = [f"剧本《{self.title or '未命名'}》："
                 f"{len(self.scenes)} 场，{self.dialogue_count} 句对白",
                 f"角色：{'、'.join(self.character_names) or '（未识别）'}"]
        for scene in self.scenes[:max_scenes]:
            lines.append(f"\n【{scene.heading}】")
            for action in scene.actions:
                lines.append(f"  · {action.text}")
            for dialogue in scene.dialogues:
                tag = f"（{dialogue.parenthetical}）" if dialogue.parenthetical else ""
                lines.append(f"  {dialogue.character}{tag}：{dialogue.text}")
        if len(self.scenes) > max_scenes:
            lines.append(f"\n（其余 {len(self.scenes) - max_scenes} 场略）")
        return "\n".join(lines)
