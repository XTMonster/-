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
from .plan import Responsibility

#: v1.5：**SDL 文件格式版本升到 1.5**（软件包/协议版本仍是 1.3.0，不在本次
#: 改动范围）。1.5 只**增字段**：``SDLEnvironment.anchors`` / ``light``、
#: ``SDLShot.beats`` / ``composition`` / ``rule_justifications``——无删除、
#: 无改名，所以 1.4 工程加载后行为逐字节不变（见 sdl_migrate.KNOWN_VERSIONS）。
#:
#: v1.6（C1，FR-A1；连同 D1 的 rhythm_arc）：``project.brief`` 里新增
#: ``environment[]`` 与 ``rhythm_arc[]``。同样**只增字段**、无删除无改名——
#: 1.5 工程迁移后这两个字段取空表，旧字段逐字节不变。
#:
#: v1.7（A6，R-痛点 M5）：``SDLShot.responsibility``（分工声明）——只增字段、
#: 无删除无改名；旧文件迁移后每镜补 ``null``（未声明）。
SDL_VERSION = "1.7"


@dataclass
class SDLAnchor:
    """场级摆位锚点（执行文档 v1.5 §3.3）。

    ``relation`` 是**自然语言方位**（"behind 甲" / "between 甲 and 乙"），
    由摆位求解器解析成 ``position``；LLM 只写 ``name`` / ``depth`` /
    ``relation``，坐标由求解器回填，契约层不猜。
    """
    name: str = ""
    #: 纵深分层：fg / mid / bg（相对相机视角）。自由字符串，由提示词约束。
    depth: str = "mid"
    relation: str = ""
    #: 求解器回填的坐标；LLM 不写，缺省空表 = 未求解。
    position: List[float] = field(default_factory=list)


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
    #: v1.5 §3.1：执行拍点（``contracts/beats.py::ShotBeat`` 的 dict 形）。
    #: **命名消歧**：这里与 ``contracts/plan.py::ShotPlan.beats`` 同义（执行
    #: 拍点），**不是** ``contracts/brief.py::SceneBrief.beats``（叙事节拍）。
    beats: List[Dict[str, Any]] = field(default_factory=list)
    #: v1.5 §3.5：构图声明（``{rule, subject_position}``），缺省空 = 求解器默认。
    composition: Dict[str, Any] = field(default_factory=dict)
    #: v1.5 §3.6：破例辩护（``{rule, action, reason, precedent}``）。
    rule_justifications: List[Dict[str, Any]] = field(default_factory=list)
    prompt: str = ""
    #: v1.7 §14.1（R-痛点 M5）：分工声明。None = 未声明（≠ 全空）；
    #: ``skip_white_model`` 的执行语义在卡 J3（本卡只落数据）。
    responsibility: Optional[Responsibility] = None


@dataclass
class SDLEnvironment:
    ground_size: List[float] = field(default_factory=lambda: [120.0, 120.0])
    walls: List[Dict[str, Any]] = field(default_factory=list)
    props: List[Dict[str, Any]] = field(default_factory=list)
    lighting: str = "clay_studio"
    room: Optional[List[float]] = None
    #: v1.3：群众代理（``{count, mode, seed, area, ...}``），独立于 characters。
    crowd: List[Dict[str, Any]] = field(default_factory=list)
    #: v1.5 §3.3：场级摆位锚点，缺省空表（1.4 工程迁移后即为空表）。
    anchors: List[SDLAnchor] = field(default_factory=list)
    #: v1.5 §3.4：灯光语义（``{time_of_day, mood, key_direction}``）。
    #: 从不含灯具参数（energy/color/size）——语义到预设的映射在引擎侧。
    light: Dict[str, Any] = field(default_factory=dict)


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
    #: v1.7 E2：阶段 P 的剧本优化产物（PolishResult.to_dict()）。照 brief 模式
    #: 落进项目文件——采纳与否、建议与改写稿都跟随工程走。
    polish: Dict[str, Any] = field(default_factory=dict)
    #: v1.4 S9：标签是否进参考视频（对应 ``SceneSpec.with_labels``）。
    #: v1.3 的 SDL 从来没有这个字段，于是"存了再打开"会把用户的关闭状态丢掉。
    with_labels: bool = True

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
