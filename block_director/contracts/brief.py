"""剧本理解契约（Stage S，v1.3 §3.2）。

Layer 1 只做**格式解析**（谁说了什么话、有几场戏）；它推不出"谁对谁说、
谁看谁、情绪怎么走、谁站在谁的哪一边"。v1.2 就直接把这层空白跳过去让
阶段 A 规划镜头，于是计划里没有一处承载"米迦尔和伊恩应该是看着彼此的"
这类语义——镜头也就拍不出这层关系。

``SceneBrief`` 就是补在这个缺口上的**结构化理解**：

```
speakers[]   {dialogue_ref, speaker, listener}   谁对谁说
gaze[]       {from, to, scope}                   谁看谁、覆盖哪些镜头
beats[]      {id, summary, participants, emotion, function}
space[]      {character, relative_to, relation, distance_class}
arc          {emotion_start, emotion_end, turning_point}
props[]      {id, kind, owner, state_changes}
notes[]      模型认为需要人工确认的地方
```

设计约束：

* 纯数据 + 纯校验（本模块**不 import bpy、不 import layer5**，契约层红线）；
* 字段一律用 ``Dict[str, Any]``，与 ``ShotPlan.camera`` 的做法一致——
  线协议里的键名（``from`` / ``to``）是 Python 关键字，包一层字典比
  再做一遍名字映射更不容易漂移；
* ``validate()`` 只**回答问题**、从不抛异常：理解阶段的任何瑕疵都不该
  把整次运行打断（§3.2「失败时降级为确定性抽取，永不致命」）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

#: 每个子结构的键（提示词 schema、解析与校验共用同一份）
SPEAKER_KEYS = ("dialogue_ref", "speaker", "listener")
GAZE_KEYS = ("from", "to", "scope")
BEAT_KEYS = ("id", "summary", "participants", "emotion", "function")
SPACE_KEYS = ("character", "relative_to", "relation", "distance_class")
ENVIRONMENT_KEYS = ("label", "direction", "distance", "size", "mood")
PROP_KEYS = ("id", "kind", "owner", "state_changes")
ARC_KEYS = ("emotion_start", "emotion_end", "turning_point")

#: 与 SceneBrief.space[].relation 对应的取值；未知值只记告警。
SPACE_RELATIONS = ("facing", "side_by_side", "behind", "ahead", "apart")

#: v1.6 C1（FR-A1）：环境件相对**场景中心**的方位闭集。环境件（拱廊、摊位、
#: 海面……）一律写进 ``SceneBrief.environment[]``；``space[]`` 仍只描述角色间
#: 关系，语义不许混（TDD §3.4）。
SPACE_DIRECTIONS = ("front", "back", "left", "right", "above", "ground")
#: 距离档（相对场景中心）：near≤4m / mid≤10m / far>10m。
SPACE_DISTANCES = ("near", "mid", "far")
#: 体量档：s / m / l。
SPACE_SIZES = ("s", "m", "l")

#: ``gaze[].scope`` 的通配写法：覆盖整场戏
GAZE_SCOPE_ALL = "all"

#: 来源标记：模型产出 vs 本地确定性抽取（降级路径）
SOURCE_LLM = "llm"
SOURCE_DETERMINISTIC = "deterministic"


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def scope_tokens(value: Any) -> List[str]:
    """把 ``scope`` 规整成一组可比较的记号。

    Brief 产生在**阶段 S**，那时计划还不存在，所以里面的引用只能是剧本级
    锚点：``all``（整场）、``镜号4``（第 4 个声明镜号）或裸数字 ``4``。
    计划出来之后按"第几个镜头"回对——R015 已经保证计划与声明的镜号顺序
    一一对应。也容忍直接写计划里的 shot id，便于人工编辑。
    """
    return [text.strip().lower() for text in _clean_list(value)]


def shot_anchors(shot_id: str = "", index: int = 0) -> List[str]:
    """某个镜头的全部可比较记号（裸序号、镜号 N、计划 shot id）。"""
    tokens: List[str] = []
    if index:
        tokens += [str(int(index)), f"镜号{int(index)}", f"#{int(index)}"]
    if shot_id:
        tokens.append(_clean_text(shot_id).lower())
        digits = "".join(ch for ch in str(shot_id) if ch.isdigit())
        if digits:
            tokens.append(digits.lstrip("0") or "0")
    return [token for token in tokens if token]


def _clean_list(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [text for text in (_clean_text(item) for item in value) if text]
    return []


def _clean_dicts(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


@dataclass
class SceneBrief:
    """一次剧本理解的结果。空 brief 是合法的（等价于"没有额外信息"）。"""

    speakers: List[Dict[str, Any]] = field(default_factory=list)
    gaze: List[Dict[str, Any]] = field(default_factory=list)
    beats: List[Dict[str, Any]] = field(default_factory=list)
    space: List[Dict[str, Any]] = field(default_factory=list)
    #: v1.6 C1（FR-A1）：环境元素闭集
    #: ``{label, direction, distance, size, mood}``，与 ``space[]`` 并列。
    #: direction/distance/size 是闭集词（SPACE_DIRECTIONS / SPACE_DISTANCES /
    #: SPACE_SIZES），氛围（颜色/材质/气氛）只能进自由文本 ``mood``。
    #: 解析不出就是问题、绝不猜（见 ``validate()``）。
    environment: List[Dict[str, Any]] = field(default_factory=list)
    arc: Dict[str, Any] = field(default_factory=dict)
    props: List[Dict[str, Any]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    #: v1.6 D1（FR-B1）：剧本节奏弧，每镜一拍 ``{shot_id, tension(1–5), note}``。
    #: 空列表合法；理解两次失败时由 ``deterministic_rhythm()`` 回退生成（E_BRIEF_002）。
    rhythm_arc: List[Dict[str, Any]] = field(default_factory=list)
    #: ``llm`` 或 ``deterministic``；决定审计里怎么描述这份理解的来源。
    source: str = SOURCE_LLM

    # ------------------------------------------------------------------ 查询
    @property
    def is_empty(self) -> bool:
        return not (self.speakers or self.gaze or self.beats or self.space
                    or self.environment or self.arc or self.props or self.notes)

    def listener_of(self, speaker: str, shot_id: str = "",
                    index: int = 0, dialogue_ref: str = "") -> str:
        """这一镜里 ``speaker`` 在跟谁说；找不到时返回空串。

        匹配顺序：先按台词锚点，再按镜头锚点，最后才退回"这位说话人只对过
        一个人说"这一唯一解。三者都不成立就返回空——宁可没有听话人，
        也不要猜一个（§3.2「不猜代词」）。
        """
        entries = [item for item in self.speakers
                   if _clean_text(item.get("speaker")) == _clean_text(speaker)]
        if not entries:
            return ""
        wanted = _clean_text(dialogue_ref).lower()
        if wanted:
            for item in entries:
                if wanted in scope_tokens(item.get("dialogue_ref")):
                    return _clean_text(item.get("listener"))
        anchors = set(shot_anchors(shot_id, index))
        if anchors:
            for item in entries:
                if set(scope_tokens(item.get("dialogue_ref"))) & anchors:
                    return _clean_text(item.get("listener"))
        listeners = {_clean_text(item.get("listener")) for item in entries}
        listeners.discard("")
        return listeners.pop() if len(listeners) == 1 else ""

    def gazes_in(self, shot_id: str = "", index: int = 0
                 ) -> List[Dict[str, Any]]:
        """覆盖这一镜的注视关系（``scope`` 为 all / 空 / 本镜锚点时算命中）。"""
        anchors = set(shot_anchors(shot_id, index))
        found: List[Dict[str, Any]] = []
        for item in self.gaze:
            scopes = set(scope_tokens(item.get("scope")))
            if not scopes or GAZE_SCOPE_ALL in scopes or scopes & anchors:
                found.append(item)
        return found

    def emotion_at(self, index: int) -> str:
        """第 ``index`` 个节拍的情绪（用于检索与运镜决策）。"""
        if 0 <= index < len(self.beats):
            return _clean_text(self.beats[index].get("emotion"))
        return ""

    # ------------------------------------------------------------------ 校验
    def validate(self,
                 characters: Optional[Sequence[str]] = None) -> List[str]:
        """返回问题清单（空列表表示没问题）。**从不抛异常。**"""
        problems: List[str] = []
        roster = {_clean_text(name) for name in (characters or []) if _clean_text(name)}

        def require(item: Dict[str, Any], keys: Sequence[str],
                    where: str) -> bool:
            missing = [key for key in keys
                       if not _clean_text(item.get(key))
                       and not isinstance(item.get(key), (list, tuple))]
            if missing:
                problems.append(f"{where} 缺少字段：{'、'.join(missing)}")
                return False
            return True

        def check_roster(name: str, where: str) -> None:
            if roster and name and name not in roster:
                problems.append(f"{where} 引用了不在角色表里的 {name}（将被忽略）")

        for index, item in enumerate(self.speakers, start=1):
            if require(item, ("speaker",), f"speakers[{index}]"):
                check_roster(_clean_text(item.get("speaker")),
                             f"speakers[{index}].speaker")
            check_roster(_clean_text(item.get("listener")),
                         f"speakers[{index}].listener")
        for index, item in enumerate(self.gaze, start=1):
            if not require(item, ("from", "to"), f"gaze[{index}]"):
                continue
            check_roster(_clean_text(item.get("from")),
                         f"gaze[{index}].from")
            check_roster(_clean_text(item.get("to")), f"gaze[{index}].to")
        for index, item in enumerate(self.beats, start=1):
            require(item, ("summary",), f"beats[{index}]")
        for index, item in enumerate(self.space, start=1):
            if not require(item, ("character",), f"space[{index}]"):
                continue
            check_roster(_clean_text(item.get("character")),
                         f"space[{index}].character")
            check_roster(_clean_text(item.get("relative_to")),
                         f"space[{index}].relative_to")
            relation = _clean_text(item.get("relation"))
            if relation and relation not in SPACE_RELATIONS:
                problems.append(f"space[{index}].relation 取值 {relation!r} "
                                f"不在 {list(SPACE_RELATIONS)} 内")
        for index, item in enumerate(self.environment, start=1):
            where = f"environment[{index}]"
            if not require(item, ENVIRONMENT_KEYS[:4], where):
                continue
            #: 闭集字段逐项核对：取值在集合外只记问题，**绝不猜/绝不改写**
            #: （FR-A1「解析不出就是 finding」的契约侧；自由文本只允许在 mood）。
            for key, closed in (("direction", SPACE_DIRECTIONS),
                                ("distance", SPACE_DISTANCES),
                                ("size", SPACE_SIZES)):
                value = _clean_text(item.get(key))
                if value not in closed:
                    problems.append(f"{where}.{key} 取值 {value!r} "
                                    f"不在闭集 {list(closed)} 内")
        for index, item in enumerate(self.props, start=1):
            require(item, ("id",), f"props[{index}]")
        from .rhythm import rhythm_arc_problems
        problems.extend(rhythm_arc_problems(self.rhythm_arc))
        if self.source not in (SOURCE_LLM, SOURCE_DETERMINISTIC):
            problems.append(f"source 取值 {self.source!r} 非法")
        return problems

    # ------------------------------------------------------------------ 序列
    def to_dict(self) -> Dict[str, Any]:
        from .serde import to_plain
        return to_plain(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "SceneBrief":
        """宽容地还原：未知字段忽略，列表里的非字典元素丢弃。

        模型返回的 JSON 不会永远听话，而"理解"这一步的产物不值得为一条
        格式瑕疵让整次运行失败。
        """
        payload = dict(data or {})
        arc = payload.get("arc")
        return cls(
            speakers=_clean_dicts(payload.get("speakers")),
            gaze=_clean_dicts(payload.get("gaze")),
            beats=_clean_dicts(payload.get("beats")),
            space=_clean_dicts(payload.get("space")),
            environment=_clean_dicts(payload.get("environment")),
            arc=dict(arc) if isinstance(arc, dict) else {},
            props=_clean_dicts(payload.get("props")),
            notes=_clean_list(payload.get("notes")),
            rhythm_arc=_clean_dicts(payload.get("rhythm_arc")),
            source=(_clean_text(payload.get("source"))
                    or SOURCE_LLM),
        )
