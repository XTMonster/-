"""`SceneContract`：把一镜的**语义**收敛成**可执行描述**（v1.4 P11 / BW-4b）。

v1.3 的链路是"分镜表 → 计划"直通：谁看谁、谁在跟谁说话、说话人到底是谁，
全靠模型在计划里顺手写。于是一句"她还没有回信"里的"她"要么被丢掉、要么被
随便安到某个角色头上——而**没有任何一层**负责回答"这一镜到底在讲什么关系"。

本模块就是那一层。它是**纯计算**（不依赖 bpy、不调用 LLM），输入的
``Plan`` 与 ``SceneBrief`` 都是既有产物：

* ``facing_target``：这一镜里谁该朝向谁（来自 SceneBrief.gaze，或由计划自己
  声明的 gaze）；
* ``speaker_status``：说话人解析出来了吗？**没解析出来就不许伪造
  ``character_id``**（F2：未知说话人必须留空并标注 ``unresolved``）；
* ``unresolved[]``：上述两类未落实项的清单，交给调用方报错或让人工裁决。

它**不新增任何字段到 SDL/计划**——契约是运行时结构（v1.4 §2.3 的
"``SCENE_EVENT`` 已从索引里移出，成为 ``SceneContract`` 的运行时结构"）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

STATUS_RESOLVED = "resolved"
STATUS_UNRESOLVED = "unresolved"

#: §2.3b 的检索路由：把契约串投给超图那一条通道。键集与
#: `block_director/knowledge/hypergraph.py::QUERY_KEYS` 同源（那边是消费者）。
QUERY_KEYS: Dict[str, str] = {
    "情绪": "emotion", "动作": "action", "运镜": "movement", "景别": "shot_size",
    "镜头": "lens", "节奏": "pacing", "特效": "vfx", "音效": "sfx",
    "机位": "camera_angle", "光线": "lighting", "构图": "composition_rule",
    "轴线": "axis_topic", "题材": "genre", "桥段": "beat_type", "对白": "scene_type",
}


def _first_value(item: Any, *keys: str) -> str:
    """从映射里取第一个非空值（`movements[]` 的键在历史上换过名字）。"""
    if not isinstance(item, dict):
        return ""
    for key in keys:
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def shot_constraint_query(shot, *, per_kind: int = 3) -> str:
    """把**一镜的计划字段**变成 §2.3b 的查询串：``键=值；键=值``。

    为什么需要它：超图的入口 ``hypergraph.parse_query`` **只认契约串**
    （``景别=MS；运镜=dolly_in``）。在此之前生产侧没有任何地方产出这种串，
    于是 `block_for_shot` 拿到的中文自由文本一个种子都命中不了，超图那一栏
    （含 ``forbid`` 禁忌）在真实运行里**从来没有被注入过**——三栏里只剩两栏。

    纪律：

    * **只写有值的键**：计划里没有"情绪"这个字段就不写 ``情绪=``，空值会造出
      永不命中的种子，把 `seed_miss` 伪装成"知识库里没有"；
    * **确定性**：同一镜两次调用得到同一个串（取值按出现顺序去重）；
    * **每个 kind 最多 `per_kind` 个取值**：查询串越长越容易被无关种子稀释。

    入参可以是 ``ShotPlan`` 也可以是 :class:`ShotContract`（同名属性）。
    """
    pairs: List[tuple] = []
    used: Dict[str, set] = {}

    def add(key: str, values) -> None:
        seen = used.setdefault(key, set())
        for value in values:
            text = str(value or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            pairs.append((key, text))
            if len(seen) >= per_kind:
                break

    add("景别", [getattr(shot, "shot_type", "")])
    camera = getattr(shot, "camera", None) or {}
    if isinstance(camera, dict):
        add("镜头", [camera.get("lens")])
        add("运镜", [_first_value(item, "type", "kind")
                     for item in (camera.get("movements") or [])])
    add("动作", [_first_value(item, "action_type", "type")
                 for item in (getattr(shot, "actions", None) or [])])
    add("特效", [_first_value(item, "type", "kind")
                 for item in (getattr(shot, "vfx", None) or [])])
    if getattr(shot, "dialogues", None):
        pairs.append(("对白", "有"))
    return "；".join(f"{key}={value}" for key, value in pairs)


def _pairs(entries) -> List[Dict[str, str]]:
    """把 ``{from,to}`` 形状的注视关系规范化成 ``[{source,target}]``。"""
    out: List[Dict[str, str]] = []
    for item in entries or []:
        if not isinstance(item, dict):
            continue
        source = str(item.get("from") or item.get("source") or "").strip()
        target = str(item.get("to") or item.get("target") or "").strip()
        if source and target and source != target:
            out.append({"source": source, "target": target})
    return out


@dataclass
class ShotContract:
    """一镜的可执行描述（语义收敛的产物）。"""

    shot_id: str
    order: int = 0
    intent: str = ""
    characters: List[str] = field(default_factory=list)
    #: ``{character_id: target_character_id}``——这一镜里谁该朝向谁。
    facing_target: Dict[str, str] = field(default_factory=dict)
    #: 逐条对白：``{speaker_raw, speaker, speaker_status, text}``。
    dialogues: List[Dict[str, Any]] = field(default_factory=list)
    vfx: List[Dict[str, Any]] = field(default_factory=list)
    unresolved: List[str] = field(default_factory=list)

    def constraint_query(self) -> str:
        """这一镜的检索契约串（§2.3b 的 ``constraint_query``）。"""
        return shot_constraint_query(self)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "shot_id": self.shot_id, "order": self.order,
            "intent": self.intent, "characters": list(self.characters),
            "facing_target": dict(self.facing_target),
            "dialogues": [dict(item) for item in self.dialogues],
            "vfx": [dict(item) for item in self.vfx],
            "unresolved": list(self.unresolved),
        }


def resolve_speaker(raw: str, characters) -> tuple:
    """``(speaker_id, status)``：能把说话人落到在场角色上就 resolved。

    F2 的硬约束：**认不出来就返回空 id + unresolved**，绝不写一个猜的 id
    （``sdl_validator`` 的 S2 只校验已解析的 id，伪造出来的坏 id 会被判错，
    而"空 id"会被正确地当成"这一镜没有说话人"）。

    认人规则（确定性，可单测）：去空白后**全等**；或名字是某个角色 id、
    或与角色的 ``name``/别名相等。刻意不做模糊匹配——猜名字正是 F2 要堵的洞。
    """
    name = str(raw or "").strip()
    if not name:
        return "", STATUS_UNRESOLVED
    for character_id in characters or []:
        if name == str(character_id):
            return str(character_id), STATUS_RESOLVED
    return "", STATUS_UNRESOLVED


@dataclass
class SceneContract:
    """整场的语义收敛结果。"""

    shots: List[ShotContract] = field(default_factory=list)
    #: 跨镜的未落实项（说话人、注视关系…），供审核与人工裁决。
    unresolved: List[Dict[str, Any]] = field(default_factory=list)
    source: str = ""

    @property
    def ok(self) -> bool:
        return not self.unresolved

    def shot(self, shot_id: str) -> Optional[ShotContract]:
        for item in self.shots:
            if item.shot_id == shot_id:
                return item
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {"source": self.source,
                "shots": [item.to_dict() for item in self.shots],
                "unresolved": [dict(item) for item in self.unresolved]}

    # ------------------------------------------------------------------ 构造
    @classmethod
    def from_plan(cls, plan, *, brief=None, parsed=None,
                  cast=None) -> "SceneContract":
        """把计划 + SceneBrief 收敛成契约。

        ``cast`` 是"场上到底有谁"的权威名单（``{name: character_id}`` 或
        可迭代的 id）；不给时退回计划里出现过的角色 id。
        """
        known: List[str] = []
        aliases: Dict[str, str] = {}
        if cast:
            if isinstance(cast, dict):
                known = [str(value) for value in cast.values()]
                aliases = {str(key): str(value) for key, value in cast.items()}
            else:
                known = [str(item) for item in cast]
        if parsed is not None:
            for canonical, items in (getattr(parsed, "character_aliases", {})
                                     or {}).items():
                for alias in items:
                    aliases.setdefault(str(alias), str(canonical))
        contract = cls(source=(getattr(brief, "source", "") if brief is not None
                               else ""))
        shots: List[ShotContract] = []
        for index, shot in enumerate(getattr(plan, "shots", []) or [], start=1):
            shot_id = str(getattr(shot, "shot_id", "") or "")
            characters = [str(item) for item in
                          (getattr(shot, "characters", None) or [])]
            for character_id in characters:
                if character_id not in known:
                    known.append(character_id)
            item = ShotContract(shot_id=shot_id,
                                order=int(getattr(shot, "order", 0) or index),
                                intent=str(getattr(shot, "intent", "") or ""),
                                characters=characters,
                                vfx=[dict(v) for v in
                                     (getattr(shot, "vfx", None) or [])])
            # 注视关系：SceneBrief 是首选（它是"读剧本"的产物），计划里
            # 自己写的 gaze 只作补充。
            pairs = []
            if brief is not None:
                pairs.extend(_pairs(brief.gazes_in(shot_id, index)))
            pairs.extend(_pairs(getattr(shot, "gaze", None)))
            for pair in pairs:
                item.facing_target[pair["source"]] = pair["target"]
            # 逐条对白：说话人解析不出来就进 unresolved，**不伪造 id**。
            for dialogue in (getattr(shot, "dialogues", None) or []):
                if not isinstance(dialogue, dict):
                    continue
                raw = str(dialogue.get("character_id")
                          or dialogue.get("speaker") or "").strip()
                speaker_id, status = resolve_speaker(raw, characters)
                if status is STATUS_UNRESOLVED:
                    speaker_id, status = resolve_speaker(
                        aliases.get(raw, raw), characters)
                entry = {"speaker_raw": raw, "speaker": speaker_id,
                         "speaker_status": status,
                         "text": str(dialogue.get("text") or "")}
                item.dialogues.append(entry)
                if status is STATUS_UNRESOLVED:
                    item.unresolved.append(
                        f"说话人未解析：{raw or '（空）'}")
                    contract.unresolved.append({
                        "shot_id": shot_id, "kind": "speaker", "raw": raw,
                        "text": entry["text"]})
            shots.append(item)
        contract.shots = shots
        return contract
