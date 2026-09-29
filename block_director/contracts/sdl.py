"""SDL 场景描述层（执行文档 v1.2 §5.1）。

SDL 既是执行过程的结构化记录，也是项目保存/加载的格式。它是纯数据：
``layer2_sdl`` 负责组装与校验，``layer9_persistence`` 负责落盘。

与 v1.0 的关键差异：**shot 只声明 ``duration_frames``**，绝对帧号由排片器
统一生成后回填（§10.2），避免"两个真源互相覆盖"。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .cast import CastMember

SDL_VERSION = "1.3"


@dataclass
class SDLCamera:
    id: str = ""
    position: List[float] = field(default_factory=list)
    target: List[float] = field(default_factory=list)
    lens: float = 50.0
    sensor_width: float = 36.0
    #: 旧版的单个运镜名（v1.2 遗留字段）。新写入一律用 ``movements``，
    #: 这里保留是为了让老项目加载后仍能被读出来（``prompts.py`` 做兜底）。
    movement: str = "static"
    #: v1.3：声明式运镜清单，元素形如
    #: ``{type, amount, start_frame, end_frame, seed, subject}``（帧号为镜头内局部帧）。
    movements: List[Dict[str, Any]] = field(default_factory=list)
    request: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SDLShot:
    id: str
    intent: str = ""
    shot_type: str = "MS"
    duration_frames: int = 0
    start_frame: int = 0                 # 排片结果（由排片器回填）
    end_frame: int = 0
    transition_in: str = "cut"
    transition_out: str = "cut"
    camera: SDLCamera = field(default_factory=SDLCamera)
    axis_line: Optional[Dict[str, Any]] = None
    active_speakers: List[str] = field(default_factory=list)
    characters: List[str] = field(default_factory=list)
    actions: List[Dict[str, Any]] = field(default_factory=list)
    dialogues: List[Dict[str, Any]] = field(default_factory=list)
    #: v1.3：谁看谁（``{from, to, scope}``），由阶段 S 的 SceneBrief 落实。
    gaze: List[Dict[str, Any]] = field(default_factory=list)
    #: v1.3：特效代理（``{id, type, position, size, start_frame, end_frame}``）。
    vfx: List[Dict[str, Any]] = field(default_factory=list)
    prompt: str = ""


@dataclass
class SDLEnvironment:
    ground_size: List[float] = field(default_factory=lambda: [120.0, 120.0])
    walls: List[Dict[str, Any]] = field(default_factory=list)
    props: List[Dict[str, Any]] = field(default_factory=list)
    lighting: str = "clay_studio"
    room: Optional[List[float]] = None
    #: v1.3：群众代理（``{count, mode, seed, area, ...}``），独立于 characters。
    crowd: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class SDLScene:
    id: str
    number: int = 1
    heading: str = ""
    environment: SDLEnvironment = field(default_factory=SDLEnvironment)
    shots: List[SDLShot] = field(default_factory=list)

    @property
    def total_frames(self) -> int:
        return sum(shot.duration_frames for shot in self.shots)


@dataclass
class SDLProject:
    name: str = "BlockDirector"
    version: str = SDL_VERSION
    fps: int = 24
    characters: List[CastMember] = field(default_factory=list)
    scenes: List[SDLScene] = field(default_factory=list)
    continuity: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    #: v1.3：阶段 S 的剧本理解（§3.2）。落进项目文件后可以人工编辑，
    #: 再重新生成——"理解"和"计划"一样是可见、可改、可复现的产物。
    brief: Dict[str, Any] = field(default_factory=dict)

    @property
    def shots(self) -> List[SDLShot]:
        return [shot for scene in self.scenes for shot in scene.shots]

    @property
    def total_frames(self) -> int:
        return sum(scene.total_frames for scene in self.scenes)

    def to_dict(self) -> Dict[str, Any]:
        from .serde import to_plain
        return to_plain(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SDLProject":
        from .serde import from_plain
        return from_plain(cls, data)
