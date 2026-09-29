"""解析后的剧本数据结构（执行文档 v1.2 §4.2）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ParsedShotDeclaration:
    """分镜表里一个镜号的**声明**（v1.3）。

    它记录"导演写下来的东西"——镜号、时长、景别、拍摄手法、角色、画面内容
    与台词。计划（阶段 A）与场景（阶段 B）是它的**落实**，R015/R016 负责
    比较两侧。
    """

    shot_number: int
    declared_seconds: Optional[float] = None
    fields: Dict[str, str] = field(default_factory=dict)
    timecodes: List[Any] = field(default_factory=list)   # [(起, 止), ...]
    characters: List[str] = field(default_factory=list)
    shot_type: str = ""              # 由"拍摄距离"映射出的景别提示
    camera_move: str = ""            # 由"拍摄手法"映射出的运镜提示
    declared_dialogue_seconds: Optional[float] = None
    node_number: int = 0
    node_title: str = ""
    #: 本镜的台词（与 :class:`ParsedScene.dialogues` 是同一批对象）
    dialogues: List["ParsedDialogue"] = field(default_factory=list)

    @property
    def dialogue_count(self) -> int:
        return len(self.dialogues)

    def field(self, key: str, default: str = "") -> str:
        return str(self.fields.get(key, default) or default)

    def to_dict(self) -> Dict[str, Any]:
        return {"shot_number": self.shot_number,
                "declared_seconds": self.declared_seconds,
                "fields": dict(self.fields),
                "timecodes": [list(item) for item in self.timecodes],
                "characters": list(self.characters),
                "shot_type": self.shot_type,
                "camera_move": self.camera_move,
                "dialogue_count": self.dialogue_count,
                "declared_dialogue_seconds": self.declared_dialogue_seconds,
                "dialogues": [item.to_dict() for item in self.dialogues],
                "node_number": self.node_number,
                "node_title": self.node_title}


@dataclass
class ParsedNodeDeclaration:
    """分镜表里的一个节点（若干镜号）及其声明总时长。"""

    node_number: int
    title: str = ""
    declared_seconds: Optional[float] = None
    shots: List[ParsedShotDeclaration] = field(default_factory=list)

    @property
    def declared_shot_seconds(self) -> Optional[float]:
        values = [shot.declared_seconds for shot in self.shots
                  if shot.declared_seconds is not None]
        return round(sum(values), 3) if values else None

    def to_dict(self) -> Dict[str, Any]:
        return {"node_number": self.node_number, "title": self.title,
                "declared_seconds": self.declared_seconds,
                "declared_shot_seconds": self.declared_shot_seconds,
                "shots": [shot.to_dict() for shot in self.shots]}


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
    #: 分镜表里**逐镜声明**的内容（v1.3）。非分镜表输入时为空列表。
    #: 它是"剧本落实审核"（R015/R016）的声明侧来源。
    declared_nodes: List["ParsedNodeDeclaration"] = field(default_factory=list)

    @property
    def declared_shots(self) -> List["ParsedShotDeclaration"]:
        return [shot for node in self.declared_nodes for shot in node.shots]

    @property
    def declared_total_seconds(self) -> Optional[float]:
        """分镜表声明的总时长（各镜声明之和）；没有声明时返回 None。"""
        declared = [shot.declared_seconds for shot in self.declared_shots
                    if shot.declared_seconds is not None]
        return round(sum(declared), 3) if declared else None

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
                "declared_nodes": [node.to_dict()
                                   for node in self.declared_nodes],
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
