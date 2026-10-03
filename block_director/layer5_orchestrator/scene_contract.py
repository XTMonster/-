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

from ..knowledge.hypergraph import QUERY_KEYS

STATUS_RESOLVED = "resolved"
STATUS_UNRESOLVED = "unresolved"

#: §2.3b 的检索路由：把契约串投给超图那一条通道。
#:
#: **这里不再手抄一份键表**（2026-10-03 实测的漂移）：原先本模块自己写了一张
#: 15 个键的副本，而 §50 给逐镜查询加上 `意图=` 之后，**同一个文件里的副本立刻
#: 少了那一个键**——声明表说"发不出意图"，生产者却真的在发。这正是本项目已经
#: 付过两次代价的"各抄一份"（v1.5 的 6 类型/16 kind、v1.6 的查询键）。
#: 现在唯一真源是 `knowledge/hypergraph.py::QUERY_KEYS`（消费者侧），
#: `tests/test_q5_plan_shaped_entries.py` 再拿**真正的生产者**与它对拍。


def _first_value(item: Any, *keys: str) -> str:
    """从映射里取第一个非空值（`movements[]` 的键在历史上换过名字）。"""
    if not isinstance(item, dict):
        return ""
    for key in keys:
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


#: 引擎的运镜名 → **查询词表里的规范取值**。
#:
#: 计划里的运镜是**引擎名**（`static`／`fixed`／`dolly_in`…），而 held-out 的 `q`
#: 与冻结词表用的是 `固定`／`dolly_in`…。两边对不上时 `运镜=static` 是**死值**：
#: 它命不中任何节点（`seeds_for` 只在节点名/别名上匹配），还会占掉 `q` 的一位，
#: 让 Q5 的"键值对集合相等"永远不成立（实测：一次真实运行的 8 条契约串与 466 个
#: held-out 键集**零命中**）。`NodeIndex` 认得 `static`／`静止机位` 这些别名，
#: 但 `fixed` 不在其中，所以这里给出一张**显式**的等价表，其余引擎名与词表同名
#: （`dolly_in`／`follow_subject`…）原样通过。
_MOVEMENT_ALIASES: Dict[str, str] = {
    "static": "固定", "fixed": "固定", "静止机位": "固定", "固定机位": "固定",
    "locked": "固定", "locked_off": "固定",
}


def _canonical(key: str, value: str) -> str:
    """把一个契约取值折到**查询词表的规范写法**上；折不到就原样返回。"""
    text = str(value or "").strip()
    if key == "运镜":
        return _MOVEMENT_ALIASES.get(text.lower(), text)
    if key == "镜头":
        #: 词表的镜头取值是 `50mm` 这种字符串，而计划里给的是数字（`50.0`）。
        #: 不折的话 `镜头=50.0` 同样是死值——实测计划里的镜头维度**从来没进过种子**。
        try:
            return "%dmm" % int(round(float(text)))
        except (TypeError, ValueError):
            return text
    if key == "对白":
        #: `对白=有` 不在词表里（`scene_type` 的取值是 establish/dialogue/…）。
        #: "这一镜有人说话"在词表里的说法就是 `dialogue`。
        return "dialogue" if text in ("有", "true", "True", "yes") else text
    return text


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
            text = _canonical(key, str(value or "").strip())
            if not text or text in seen:
                continue
            seen.add(text)
            pairs.append((key, text))
            if len(seen) >= per_kind:
                break

    add("景别", [getattr(shot, "shot_type", "")])
    #: v1.5 §2.3d T3 的**意图轴**：这一镜"想干什么"的闭集取值。它必须进搜索串，
    #: 否则 `INTENT_PACK`（意图×景别×运镜）只能靠"景别＋运镜"猜意图——实测 64 镜
    #: 那一跑 shot 域 231/320 次命中的都是 INTENT_PACK，而拿回来的"意图知识"
    #: 与这一镜真正要做什么无关。键名 `意图` 是 `hypergraph.QUERY_KEYS` 的既有键，
    #: 取值由 `emit_plan` 的 enum 保证落在闭集内（`VALUE_DOMAINS["intent"]`）。
    add("意图", [getattr(shot, "intent_type", "")])
    #: 剧本**声明**的拍摄手法是检索前已知的输入（不是结果），先挂它。
    #: 没有它，锁机位的镜头在超图那一栏一个运镜种子都没有：实测 2026-10-03，
    #: `shotlist_market` 第 1 镜声明"固定镜头"，而这一镜真实发出的契约串只有
    #: `景别=MCU`——"固定机位该怎么构图"那族边（含禁忌）因此从来进不了这一镜。
    #: `_canonical` 会把 `static` 折成查询词表的 `固定`（引擎词表里没有"不动"，
    #: 那是**能力**问题；这里是**检索**问题，两套词表本来就不是一回事）。
    add("运镜", [getattr(shot, "declared_camera_move", "")])
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
        pairs.append(("对白", _canonical("对白", "有")))
    return "；".join(f"{key}={value}" for key, value in pairs)


def declared_constraint_query(shots, *, per_kind: int = 3) -> str:
    """从**分镜表的声明**拼出计划阶段的检索契约串（§2.3b 的 ``constraint_query``）。

    计划阶段还没有计划，但剧本里**已经写了**镜别与拍摄手法（``declared_shots[]``
    的 ``shot_type`` / ``camera_move``）。不把它们变成契约串，`block_for_plan`
    就只能拿中文摘要去查超图——而 ``parse_query`` 只认 ``键=值``，于是一整场
    预取里含 ``forbid`` 的那一栏永远空着。

    声明缺失时返回空串（调用方据此退回自由文本），**不猜**。
    """
    pairs: List[tuple] = []
    seen: Dict[str, set] = {}

    def add(key: str, value) -> None:
        text = str(value or "").strip()
        bucket = seen.setdefault(key, set())
        if not text or text in bucket or len(bucket) >= per_kind:
            return
        bucket.add(text)
        pairs.append((key, text))

    for shot in shots or []:
        add("景别", getattr(shot, "shot_type", ""))
        add("运镜", getattr(shot, "camera_move", ""))
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


class _ContractView:
    """`ShotContract` → :func:`shot_constraint_query` 吃的那个形状。

    唯一的适配层：两个类型的字段名不同（`vfx_kinds` vs `vfx`、`movements` 是
    字符串 vs `{"type": …}`），但只要**生产者只有一个**，这些差异就只在一处发生。
    """

    def __init__(self, contract: "ShotContract") -> None:
        self.shot_type = contract.shot_type
        self.intent_type = contract.intent_type
        self.declared_camera_move = contract.declared_camera_move
        self.camera = {"lens": contract.lens,
                       "movements": [{"type": item}
                                     for item in contract.movements]}
        self.actions = [{"action_type": item} for item in contract.actions]
        self.vfx = [{"type": item} for item in contract.vfx_kinds]
        self.dialogues = list(contract.dialogues)


@dataclass
class ShotContract:
    """一镜的可执行描述（语义收敛的产物）。"""

    shot_id: str
    order: int = 0
    intent: str = ""
    #: 检索契约串要用的字段（§2.3b）：景别 / 焦段 / 运镜 / 动作 / 特效。
    #: 它们从计划里**抄一份**（不是第二真源——计划仍是唯一真源，这里只是
    #: 把"这一镜要检索什么"收敛成一个对象，供 `constraint_query()` 消费）。
    shot_type: str = ""
    lens: str = ""
    #: v1.5 §2.3d T3：意图的闭集取值（进契约串的 `意图=`，与 `shot_type`/`lens`
    #: 同性质——"这一镜要检索什么"收敛成对象，计划仍是唯一真源）。
    intent_type: str = ""
    #: 剧本**声明**的拍摄手法（计划上的 `ShotPlan.declared_camera_move`）。
    #: 契约串要它，是因为"锁机位"这种声明进不了引擎的运镜词表（引擎没有"不动"
    #: 这个类型），但它在**查询**词表里是合法的 `固定`——§40 实测：不带上它，
    #: 锁机位的镜头在超图那一栏一个运镜种子都没有。
    declared_camera_move: str = ""
    movements: List[str] = field(default_factory=list)
    actions: List[str] = field(default_factory=list)
    vfx_kinds: List[str] = field(default_factory=list)
    characters: List[str] = field(default_factory=list)
    #: ``{character_id: target_character_id}``——这一镜里谁该朝向谁。
    facing_target: Dict[str, str] = field(default_factory=dict)
    #: 逐条对白：``{speaker_raw, speaker, speaker_status, text}``。
    dialogues: List[Dict[str, Any]] = field(default_factory=list)
    vfx: List[Dict[str, Any]] = field(default_factory=list)
    unresolved: List[str] = field(default_factory=list)

    def constraint_query(self) -> str:
        """这一镜的检索契约串（§2.3b 的 ``constraint_query``）。

        **只有一个生产者**：本方法把对象摊成 :func:`shot_constraint_query` 吃的那个
        形状再交给它，所以两条路径**逐字符同源**——而不是"两边各写一遍规则，
        然后指望它们不漂"。

        为什么改成委托（2026-10-03 实测，写 `tests/test_q5_plan_shaped_entries.py`
        时当场量到的）：原先这两条路径确实是**各写一遍**，于是真的漂了——

        * 契约那条把 `lens` 原样发出：真实计划里是浮点 `50.0`，而索引的镜头节点是
          `50mm` ⇒ `镜头=50.0` 是**死值**（命不中任何节点，还占掉 `q` 的一位）；
        * 它**漏掉剧本声明的运镜**（`declared_camera_move` 不在 `ShotContract` 上），
          于是锁机位的镜头在这一条路径上又变回"没有运镜种子"；
        * 它也不折 `static → 固定`。

        而 `tests/test_scene_contract.py` 那条"两条生产者不许漂"的用例**看不出来**：
        它的夹具给的是已经规范化的字符串 `"85mm"`、且没有声明——两条路径在那种
        输入下**必然**相等。夹具比生产线更友好，就是"测试恒绿"的老毛病。
        """
        return shot_constraint_query(_ContractView(self))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "shot_id": self.shot_id, "order": self.order,
            "intent": self.intent, "characters": list(self.characters),
            "shot_type": self.shot_type, "lens": self.lens,
            "intent_type": self.intent_type,
            "declared_camera_move": self.declared_camera_move,
            "movements": list(self.movements), "actions": list(self.actions),
            "vfx_kinds": list(self.vfx_kinds),
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
                                shot_type=str(getattr(shot, "shot_type", "") or ""),
                                intent_type=str(
                                    getattr(shot, "intent_type", "") or ""),
                                declared_camera_move=str(
                                    getattr(shot, "declared_camera_move", "")
                                    or ""),
                                lens=str((getattr(shot, "camera", None) or {}).get(
                                    "lens") or ""),
                                movements=[_first_value(entry, "type", "kind")
                                           for entry in
                                           ((getattr(shot, "camera", None) or {})
                                            .get("movements") or [])],
                                actions=[_first_value(entry, "action_type", "type")
                                         for entry in
                                         (getattr(shot, "actions", None) or [])],
                                vfx_kinds=[_first_value(entry, "type", "kind")
                                           for entry in
                                           (getattr(shot, "vfx", None) or [])],
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
