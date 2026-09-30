"""超图 RAG 的 schema、校验门与检索（执行文档 v1.4 §2.3）。

纯 stdlib、无 bpy：本模块既能被 sidecar 直接跑，也能被插件侧的测试导入。
索引本身（LLM 抽取）在 `tools/kb_fetch/` 与 sidecar 侧构建；这里只放
**可判定的规则**：

* 节点 16 类 / qualifier 10 类 / 超边 6 类的闭集；
* `edge_id = "hg:" + sha1(type + sorted(members) + source_kind + hardness + schema_version)[:12]`；
* 9 条校验门（§2.3 第 3 步）与 `raw = valid_unique + duplicates + rejects`；
* 去重键 `(type, frozenset(members), source_kind, hardness)`，合并时保留
  `occurrences / sources / confidence_max`；
* 四步检索（种子 -> 扩展 -> 打分 -> 闭合输出）与原子注入渲染。
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from ..cinema.composition import WEIGHTS as COMPOSITION_WEIGHTS
from ..cinema.framing import SHOT_FRAME
from .bm25 import tokenize as _bm25_tokenize

SCHEMA_VERSION = "hg/v2"

#: 节点类型闭集（17 类，§2.3 是单一真源）。v1.5 起新增 `intent`（意图）：它是
#: "角色/导演想干什么"这一层，和 `emotion`（感受）一样是**强耦合的源头**——
#: 意图决定镜头语言，所以 `INTENT_PACK` 必须能把它写进边里。
NODE_TYPES: Tuple[str, ...] = (
    "emotion", "movement", "shot_size", "lens", "pacing", "vfx", "sfx",
    "composition_rule", "axis_topic", "character", "object", "action", "genre",
    "beat_type", "camera_angle", "lighting", "intent",
)

#: qualifier 类型闭集（10 类）。`axis_side` 必须在表里——否则最高优先级的
#: `AXIS_RULE` 会被自己的校验门 ③ 全部拒收。
QUALIFIER_KINDS: Tuple[str, ...] = (
    "pair", "axis_side", "intensity", "applies_to_genre", "applies_to_shot_size",
    "headroom_policy", "avg_shot_len", "transition", "scene_type", "example_shot",
)

ALLOWED_KINDS = frozenset(NODE_TYPES) | frozenset(QUALIFIER_KINDS)
ROLES = frozenset({"allow", "forbid", "qualifier"})

EMOTION_PACK = "EMOTION_PACK"
SHOT_PATTERN = "SHOT_PATTERN"
AXIS_RULE = "AXIS_RULE"
TROPE = "TROPE"
EDIT_RHYTHM = "EDIT_RHYTHM"
LIGHT_PACK = "LIGHT_PACK"
#: v1.5 新增：用户裁决"边要更细、把电影制作里除灯光以外的强耦合元素都囊括进来"。
#: 这七类都是**跨域强耦合**，不是"再拆一个原子字段"（单独一个字段不需要超边）。
ACTION_BEAT = "ACTION_BEAT"            # 动作×叙事节拍×强度
PERFORMANCE_PACK = "PERFORMANCE_PACK"  # 角色行为：情绪×动作×机位
INTENT_PACK = "INTENT_PACK"            # 意图×镜头语言（景别＋运镜）
IMPACT_PACK = "IMPACT_PACK"            # 震动与打击感：特效×音效×运镜
STAGING_PACK = "STAGING_PACK"          # 构图×调度：构图规则×景别×机位
SOUND_PACK = "SOUND_PACK"              # 声画关系：音效×节奏×强度
TRANSITION_PACK = "TRANSITION_PACK"    # 转场×节奏×场景类型

EDGE_TYPES: Tuple[str, ...] = (
    EMOTION_PACK, SHOT_PATTERN, AXIS_RULE, TROPE, EDIT_RHYTHM, LIGHT_PACK,
    ACTION_BEAT, PERFORMANCE_PACK, INTENT_PACK, IMPACT_PACK, STAGING_PACK,
    SOUND_PACK, TRANSITION_PACK,
)

#: 类型优先级（§2.3 的排序表）。
TYPE_PRIORITY: Dict[str, float] = {
    AXIS_RULE: 1.0, EMOTION_PACK: 1.0, LIGHT_PACK: 0.8,
    SHOT_PATTERN: 0.9, EDIT_RHYTHM: 0.7, TROPE: 0.6,
    #: v1.5 新增类型沿用"越靠近硬约束越高"的口径：
    #: 意图/表演/调度直接影响演员与机位，打击感/声画是呈现层，转场最弱。
    INTENT_PACK: 0.95, PERFORMANCE_PACK: 0.9, STAGING_PACK: 0.85,
    ACTION_BEAT: 0.8, IMPACT_PACK: 0.75, SOUND_PACK: 0.7, TRANSITION_PACK: 0.65,
}

#: 必填成员（role, kind）。
REQUIRED_MEMBERS: Dict[str, Tuple[Tuple[str, str], ...]] = {
    EMOTION_PACK: (("allow", "emotion"), ("qualifier", "intensity")),
    SHOT_PATTERN: (("allow", "shot_size"), ("allow", "lens"), ("qualifier", "headroom_policy")),
    AXIS_RULE: (("qualifier", "pair"), ("qualifier", "axis_side")),
    TROPE: (("allow", "genre"), ("allow", "emotion")),
    EDIT_RHYTHM: (("allow", "pacing"), ("qualifier", "avg_shot_len")),
    LIGHT_PACK: (("allow", "lighting"), ("qualifier", "intensity")),
    ACTION_BEAT: (("allow", "action"), ("qualifier", "beat_type"), ("qualifier", "intensity")),
    PERFORMANCE_PACK: (("allow", "emotion"), ("allow", "action"), ("qualifier", "camera_angle")),
    INTENT_PACK: (("allow", "intent"), ("allow", "shot_size"), ("qualifier", "movement")),
    IMPACT_PACK: (("allow", "vfx"), ("allow", "sfx"), ("qualifier", "movement")),
    STAGING_PACK: (("qualifier", "composition_rule"), ("allow", "shot_size"),
                   ("qualifier", "camera_angle")),
    SOUND_PACK: (("allow", "sfx"), ("allow", "pacing"), ("qualifier", "intensity")),
    TRANSITION_PACK: (("qualifier", "transition"), ("allow", "pacing"),
                      ("qualifier", "scene_type")),
}

#: 选填成员：表里没有的 (role, kind) 组合即非法（防止抽取器往边里塞任意东西）。
OPTIONAL_MEMBERS: Dict[str, Tuple[Tuple[str, str], ...]] = {
    EMOTION_PACK: (("allow", "movement"), ("allow", "shot_size"), ("allow", "lens"),
                   ("allow", "pacing"), ("allow", "vfx"), ("allow", "sfx"),
                   ("forbid", "movement"), ("forbid", "shot_size"), ("forbid", "vfx"),
                   ("qualifier", "applies_to_genre"), ("qualifier", "applies_to_shot_size")),
    SHOT_PATTERN: (("allow", "movement"), ("qualifier", "composition_rule")),
    #: v1.5：`AXIS_RULE` 的必填成员只有 `pair`/`axis_side` 两个 **schema 常量**，
    #: 它们在查询空间里没有对应取值（`轴线=` 映射到的是 `axis_topic`）——于是这类边
    #: 在检索里**一个种子都挂不上**，Q1/Q2 结构性为 0（实测 held-out 里 23/125 的
    #: 未命中就是这种）。允许把 `axis_topic` 挂在 AXIS_RULE 上，让边能锚到查询。
    AXIS_RULE: (("allow", "shot_size"), ("allow", "movement"),
                ("qualifier", "axis_topic")),
    TROPE: (("allow", "vfx"), ("allow", "movement"), ("qualifier", "example_shot")),
    EDIT_RHYTHM: (("qualifier", "transition"), ("qualifier", "scene_type")),
    LIGHT_PACK: (("allow", "emotion"), ("allow", "camera_angle")),
    ACTION_BEAT: (("allow", "movement"), ("allow", "emotion"),
                  ("qualifier", "applies_to_genre"), ("qualifier", "scene_type")),
    PERFORMANCE_PACK: (("allow", "shot_size"), ("qualifier", "intensity"),
                       ("qualifier", "beat_type")),
    INTENT_PACK: (("allow", "lens"), ("qualifier", "camera_angle"),
                  ("qualifier", "composition_rule"), ("qualifier", "intensity")),
    IMPACT_PACK: (("allow", "movement"), ("qualifier", "intensity"),
                  ("qualifier", "transition"), ("qualifier", "scene_type")),
    STAGING_PACK: (("allow", "lens"), ("allow", "movement"),
                   ("qualifier", "applies_to_shot_size")),
    SOUND_PACK: (("allow", "vfx"), ("qualifier", "transition"),
                 ("qualifier", "scene_type"), ("qualifier", "beat_type")),
    TRANSITION_PACK: (("allow", "shot_size"), ("qualifier", "avg_shot_len"),
                      ("allow", "movement"), ("qualifier", "example_shot")),
}

#: §2.3d T3：qualifier 的取值域。`None` = 显式"不设枚举"。
VALUE_DOMAINS: Dict[str, Optional[Tuple[str, ...]]] = {
    "pacing": ("short", "medium", "long"),
    "transition": ("cut", "dissolve", "fade", "whip"),
    "axis_side": ("left", "right", "neutral"),
    "avg_shot_len": ("<1s", "1-3s", "3-8s", ">8s"),
    "scene_type": ("establish", "dialogue", "action", "reaction", "transition", "insert"),
    "genre": ("film", "anime", "documentary"),
    "beat_type": ("establish", "coverage", "reaction", "insert", "transition"),
    "intensity": ("low", "mid", "high"),
    "headroom_policy": ("board", "cinematic"),
    "pair": ("any_two",),
    "applies_to_genre": ("film", "anime", "documentary"),
    "applies_to_shot_size": tuple(SHOT_FRAME.keys()),
    "composition_rule": tuple(sorted(COMPOSITION_WEIGHTS.keys())),
    "example_shot": None,  # 自由文本：参考资料引用，不参与判定
    #: v1.5：意图的闭集——"角色想要什么/导演在铺什么"。闭集才能被机器判对错；
    #: 中文取值，避免与 `must` 里的写法不一致（这正是本地模型最常翻车的地方）。
    "intent": ("铺垫", "推进", "揭示", "转折", "停顿", "压迫", "释放", "回望",
               "收束", "煽动", "留白", "对抗"),
}

#: `source_kind`（来源性质）与 `hardness`（软硬）是边级属性，
#: 与 `provenance_kind`（来源介质）不是一个东西（§2.3）。
SOURCE_KINDS = frozenset({"theory", "experience", "lesson"})
HARDNESS = frozenset({"hard", "soft"})

#: `provenance_kind` -> 来源权威度（§2.3 第 3 步）。
AUTHORITY: Dict[str, float] = {
    "拉片笔记": 1.0, "权威文档": 0.9, "生成卡片": 0.7, "网络语料": 0.5,
}
DEFAULT_AUTHORITY = 0.7

#: §2.3 的检索上限（写死，防止 hub 节点把整图炸开）。
SEED_TOP_K = 20
MAX_HOPS = 2
MAX_EDGES_PER_NODE = 8
MAX_EDGES_TOTAL = 40
MAX_NODES = 120
MAX_RENDER_TOKENS = 400

SCORE_WEIGHTS = {
    #: 实测标定（`work` 里的调参脚本，400 条抽样）：
    #: `coverage .70 / occurrences .15` 这一档把 Q1 0.327→0.449、Q2 0.622→0.663，
    #: 是四组里最好的一组；纯覆盖率（C 组）反而更差（0.296/0.561），说明
    #: `occurrences` 提供的"这条耦合在语料里反复出现"的排序信号不能丢。
    #: 权重是"默认值 + 写进 trace"，改它不动任何验收线。
    "coverage": 0.70, "type_priority": 0.05, "occurrences": 0.15,
    "confidence": 0.02, "authority": 0.05, "forbid_hit": 0.03,
}

#: 查询键（中文）-> kind。布尔项（如"对白=有"）映射到 `pacing`/`scene_type`，不新造节点类型。
QUERY_KEYS: Dict[str, str] = {
    "情绪": "emotion", "动作": "action", "运镜": "movement", "景别": "shot_size",
    "镜头": "lens", "节奏": "pacing", "特效": "vfx", "音效": "sfx",
    "机位": "camera_angle", "光线": "lighting", "构图": "composition_rule",
    "轴线": "axis_topic", "题材": "genre", "桥段": "beat_type",
    #: v1.5：意图是"角色/导演想干什么"，`INTENT_PACK` 的必填成员就是它。
    "意图": "intent",
    "对白": "scene_type",
}

#: 查询值的别名（§2.3 第 1 步要求"别名至少覆盖查询里会出现的值"）。
VALUE_ALIASES: Dict[str, str] = {
    "甩镜": "whip_pan", "甩镜头": "whip_pan", "whip_pan": "whip_pan",
    "固定机位": "固定", "固定": "固定", "static": "固定",
    "中景": "MS", "中近景": "MCU", "特写": "CU", "大特写": "ECU",
    "近景": "MCU", "全景": "LS", "远景": "ELS",
    "荒诞": "荒诞", "滑稽": "荒诞", "absurd": "荒诞",
    "跺脚": "跺脚", "stomp": "跺脚",
    "石化": "petrify", "petrify": "petrify",
}


class GateError(ValueError):
    """单条超边未通过校验门。"""


@dataclass(frozen=True)
class Node:
    node_id: str
    type: str
    name: str
    aliases: Tuple[str, ...] = ()
    value: str = ""
    unit: str = ""

    @property
    def text(self) -> str:
        return f"{self.type} {self.name} {' '.join(self.aliases)} {self.value or ''}".strip()

    def to_dict(self) -> Dict:
        return {"record": "node", "node_id": self.node_id, "type": self.type,
                "name": self.name, "aliases": list(self.aliases),
                "value": self.value, "unit": self.unit}

    @classmethod
    def from_dict(cls, data: Dict) -> "Node":
        return cls(node_id=data["node_id"], type=data["type"], name=data.get("name", ""),
                   aliases=tuple(data.get("aliases", [])), value=data.get("value", ""),
                   unit=data.get("unit", ""))


@dataclass(frozen=True)
class Member:
    role: str
    kind: str
    node_id: str

    def __str__(self) -> str:
        return f"{self.role}:{self.kind}:{self.node_id}"

    def to_dict(self) -> List[str]:
        return [self.role, self.kind, self.node_id]

    @classmethod
    def from_dict(cls, data: Sequence) -> "Member":
        return cls(role=str(data[0]), kind=str(data[1]), node_id=str(data[2]))


@dataclass
class HyperEdge:
    type: str
    members: Tuple[Member, ...]
    source_kind: str = "theory"
    hardness: str = "hard"
    weight: float = 1.0
    confidence: float = 0.7
    confidence_max: float = 0.7
    occurrences: int = 1
    sources: Tuple[str, ...] = ()
    source_span: Dict = field(default_factory=dict)
    extractor: Dict = field(default_factory=dict)
    provenance_kind: str = "生成卡片"
    schema_version: str = SCHEMA_VERSION
    #: 从索引文件读回时**声明**的 id（校验门 ② 要拿它和重算值对拍；
    #: 构造函数里算出来的 id 恒等于重算值，所以只有它能让门 ② 有牙齿）。
    declared_edge_id: str = ""

    @property
    def edge_id(self) -> str:
        return edge_id_for(self.type, self.members, self.source_kind, self.hardness,
                           self.schema_version)

    @property
    def norm_key(self) -> Tuple[str, frozenset]:
        return (self.type, frozenset((m.role, m.kind, m.node_id) for m in self.members))

    @property
    def dedupe_key(self) -> Tuple[str, frozenset, str, str]:
        return (self.type, frozenset((m.role, m.kind, m.node_id) for m in self.members),
                self.source_kind, self.hardness)

    def members_with(self, role: str) -> Tuple[Member, ...]:
        return tuple(m for m in self.members if m.role == role)

    @property
    def allows(self) -> Tuple[Member, ...]:
        return self.members_with("allow")

    @property
    def forbids(self) -> Tuple[Member, ...]:
        return self.members_with("forbid")

    @property
    def qualifiers(self) -> Tuple[Member, ...]:
        return self.members_with("qualifier")

    def to_dict(self) -> Dict:
        return {
            "record": "edge",
            "edge_id": self.edge_id,
            "type": self.type,
            "members": [m.to_dict() for m in self.members],
            "weight": self.weight,
            "confidence": self.confidence,
            "confidence_max": self.confidence_max,
            "occurrences": self.occurrences,
            "sources": list(self.sources),
            "source_span": dict(self.source_span),
            "extractor": dict(self.extractor),
            "source_kind": self.source_kind,
            "hardness": self.hardness,
            "provenance_kind": self.provenance_kind,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "HyperEdge":
        return cls(
            type=str(data["type"]),
            members=tuple(Member.from_dict(m) for m in data["members"]),
            source_kind=str(data.get("source_kind", "theory")),
            hardness=str(data.get("hardness", "hard")),
            weight=float(data.get("weight", 1.0)),
            confidence=float(data.get("confidence", 0.7)),
            confidence_max=float(data.get("confidence_max", data.get("confidence", 0.7))),
            occurrences=int(data.get("occurrences", 1)),
            sources=tuple(data.get("sources", [])),
            source_span=dict(data.get("source_span", {})),
            extractor=dict(data.get("extractor", {})),
            provenance_kind=str(data.get("provenance_kind", "生成卡片")),
            schema_version=str(data.get("schema_version", SCHEMA_VERSION)),
            declared_edge_id=str(data.get("edge_id", "")),
        )


def edge_id_for(edge_type: str, members: Iterable[Member], source_kind: str,
                hardness: str, schema_version: str = SCHEMA_VERSION) -> str:
    """§2.3 的冻结公式：必须含 `source_kind` 与 `hardness`。"""
    payload = "|".join([
        edge_type,
        ",".join(sorted(str(m) for m in members)),
        source_kind,
        hardness,
        schema_version,
    ])
    return "hg:" + hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def render_tokens(text: str) -> int:
    """超边渲染的 token 估算：CJK 单字约 1 token，拉丁词约 0.3 token（保守上界）。"""
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    latin_words = re.findall(r"[A-Za-z]+", text)
    latin_chars = sum(len(word) for word in latin_words)
    other = len(text) - cjk - latin_chars
    return int(cjk + len(latin_words) * 0.3 + other * 0.3) + 1


# --------------------------------------------------------------------------- 校验门


def node_value(node: Optional["Node"], node_id: str) -> str:
    """取成员的"值"：优先节点显式 `value`，否则取 `node_id` 里 `kind:` 之后的部分。

    约定（P14-2 写死）：枚举型节点的 id 形如 `intensity:high` / `shot_size:CU`，
    因此即使抽取器忘了填 `value`，门⑨ 与打分仍然拿得到可判定的取值。
    """
    if node is not None and node.value:
        return node.value
    return node_id.split(":", 1)[1] if ":" in node_id else node_id


def _values_for(edge: HyperEdge, kind: str, roles: Sequence[str],
                nodes: Dict[str, Node]) -> List[str]:
    out: List[str] = []
    for member in edge.members:
        if member.kind != kind or member.role not in roles:
            continue
        out.append(node_value(nodes.get(member.node_id), member.node_id))
    return out


def validate_edge(edge: HyperEdge, nodes: Dict[str, Node]) -> None:
    """9 条校验门（§2.3 第 3 步）。不过门即抛 `GateError`，调用方计入 rejects。"""
    # (1) 边类型闭集
    if edge.type not in EDGE_TYPES:
        raise GateError(f"gate1_type:{edge.type}")
    # (2) edge_id 自洽（能按公式重算）＋ 边级属性闭集
    if edge.declared_edge_id:
        recomputed = edge_id_for(edge.type, edge.members, edge.source_kind,
                                 edge.hardness, edge.schema_version)
        if edge.declared_edge_id != recomputed:
            raise GateError("gate2_edge_id")
    if edge.source_kind not in SOURCE_KINDS:
        raise GateError(f"gate2_source_kind:{edge.source_kind}")
    if edge.hardness not in HARDNESS:
        raise GateError(f"gate2_hardness:{edge.hardness}")
    # (3) kind / role 闭集
    for member in edge.members:
        if member.kind not in ALLOWED_KINDS:
            raise GateError(f"gate3_kind:{member.kind}")
        if member.role not in ROLES:
            raise GateError(f"gate3_role:{member.role}")
    # (4) 必填成员齐 ＋ arity 不小于 2 ＋ 成员组合合法
    present = {(m.role, m.kind) for m in edge.members}
    for required in REQUIRED_MEMBERS[edge.type]:
        if required not in present:
            raise GateError(f"gate4_missing:{required[0]}/{required[1]}")
    legal = set(REQUIRED_MEMBERS[edge.type]) | set(OPTIONAL_MEMBERS[edge.type])
    for pair in present:
        if pair not in legal:
            raise GateError(f"gate4_illegal_member:{pair[0]}/{pair[1]}")
    if len(edge.members) < 2:
        raise GateError("gate4_arity")
    # (5) 同一 node_id 不得同时 allow 与 forbid
    allow_ids = {m.node_id for m in edge.allows}
    forbid_ids = {m.node_id for m in edge.forbids}
    if allow_ids & forbid_ids:
        raise GateError(f"gate5_allow_forbid_overlap:{sorted(allow_ids & forbid_ids)[0]}")
    # (6) source_span 可解析（chunk_id ＋ 字符区间）
    span = edge.source_span or {}
    if not str(span.get("chunk_id", "")).strip():
        raise GateError("gate6_source_span:chunk_id")
    if not (isinstance(span.get("start"), int) and isinstance(span.get("end"), int)
            and int(span["end"]) >= int(span["start"]) >= 0):
        raise GateError("gate6_source_span:range")
    # (7) 按 kind 逐类包含（只有 shot_size / genre 参与）
    for kind, applies_kind in (("shot_size", "applies_to_shot_size"),
                               ("genre", "applies_to_genre")):
        constrained = _values_for(edge, kind, ("allow", "forbid"), nodes)
        if not constrained:
            continue
        gate_values = _values_for(edge, applies_kind, ("qualifier",), nodes)
        if not gate_values:
            continue  # 缺省 = 全适用
        if not set(constrained) <= set(gate_values):
            raise GateError(f"gate7_containment:{kind}")
    # (8) 单条超边的渲染成本不超过 400 token
    if render_tokens(render_edge(edge, nodes)) > MAX_RENDER_TOKENS:
        raise GateError("gate8_render_cost")
    # (9) qualifier 的 value 必须落在 T3 的取值域内
    for member in edge.qualifiers + edge.allows:
        domain = VALUE_DOMAINS.get(member.kind)
        if domain is None:
            continue
        value = node_value(nodes.get(member.node_id), member.node_id)
        if value not in domain:
            raise GateError(f"gate9_value:{member.kind}={value}")


# --------------------------------------------------------------------------- 渲染


def render_edge(edge: HyperEdge, nodes: Dict[str, Node]) -> str:
    """把一条超边渲染成一行。闭合输出：`forbid` 必须与 `allow` 一起出现。"""
    def name(node_id: str) -> str:
        node = nodes.get(node_id)
        return node.name if node is not None and node.name else node_id

    allows: List[str] = []
    for member in edge.allows:
        if member.kind == "emotion":
            continue
        allows.append(f"{member.kind}={name(member.node_id)}")
    quals: List[str] = []
    for member in edge.qualifiers:
        quals.append(f"{member.kind}={node_value(nodes.get(member.node_id), member.node_id)}")
    forbids = sorted(name(m.node_id) for m in edge.forbids)
    emotion = ", ".join(name(m.node_id) for m in edge.allows if m.kind == "emotion")
    parts = [f"[{edge.type}]"]
    if emotion:
        parts.append(f"{emotion} =>")
    if allows:
        parts.append(" ".join(allows))
    if quals:
        parts.append(" ".join(quals))
    if forbids:
        parts.append("禁={" + ", ".join(forbids) + "}")
    return " ".join(parts)


def render_edges(edges: Sequence[HyperEdge], nodes: Dict[str, Node],
                 token_limit: int) -> Tuple[str, List[str], bool]:
    """原子注入：整条加入直到上限；装不下就整条不注入（绝不截断）。

    返回 `(渲染文本, dropped_edge_ids, quality_fail)`；单条自超限时
    `quality_fail = True`（§2.3 第 4 步）。
    """
    lines: List[str] = []
    dropped: List[str] = []
    quality_fail = False
    used = 0
    for edge in edges:
        line = render_edge(edge, nodes)
        cost = render_tokens(line)
        if cost > token_limit:
            dropped.append(edge.edge_id)
            quality_fail = True
            continue
        if used + cost > token_limit:
            dropped.append(edge.edge_id)
            continue
        lines.append(line)
        used += cost
    return "\n".join(lines), dropped, quality_fail


# --------------------------------------------------------------------------- 索引


@dataclass
class BuildReport:
    raw_edges: int = 0
    valid_unique: int = 0
    duplicates: int = 0
    rejects: int = 0
    reject_reasons: Dict[str, int] = field(default_factory=dict)
    processed_chunks: int = 0
    total_chunks: int = 0

    @property
    def reject_ratio(self) -> float:
        return self.rejects / self.raw_edges if self.raw_edges else 0.0

    @property
    def passed(self) -> bool:
        """§2.3 的构建门（唯一两处）：rejects 不超过 5% 且没有 chunk 被跳过。"""
        if self.raw_edges <= 0 or self.total_chunks <= 0:
            return False
        return (self.reject_ratio <= 0.05
                and self.processed_chunks == self.total_chunks
                and self.valid_unique > 0)

    def to_dict(self) -> Dict:
        return {
            "raw_edges": self.raw_edges,
            "valid_unique": self.valid_unique,
            "duplicates": self.duplicates,
            "rejects": self.rejects,
            "reject_reasons": dict(sorted(self.reject_reasons.items())),
            "reject_ratio": round(self.reject_ratio, 6),
            "processed_chunks": self.processed_chunks,
            "total_chunks": self.total_chunks,
            "passed": self.passed,
        }


def merge_duplicates(edges: Sequence[HyperEdge]) -> Tuple[List[HyperEdge], int]:
    """按 `(type, frozenset(members), source_kind, hardness)` 合并；次数只作权重。"""
    merged: Dict[Tuple, HyperEdge] = {}
    duplicates = 0
    for edge in edges:
        key = edge.dedupe_key
        if key not in merged:
            merged[key] = edge
            continue
        duplicates += 1
        keeper = merged[key]
        keeper.occurrences += edge.occurrences
        keeper.confidence_max = max(keeper.confidence_max, edge.confidence_max)
        keeper.confidence = max(keeper.confidence, edge.confidence)
        keeper.sources = tuple(sorted(set(keeper.sources) | set(edge.sources)))
    return list(merged.values()), duplicates


def build_index(edges: Sequence[HyperEdge], nodes: Dict[str, Node],
                processed_chunks: int, total_chunks: int,
                reject_sink: Optional[List[Dict]] = None,
                ) -> Tuple[List[HyperEdge], BuildReport]:
    """过 9 条门 -> 去重合并 -> 构建门报告（`raw = valid_unique + duplicates + rejects`）。

    `reject_sink` 给了就把**边级**拒收明细逐条追加进去。这条账必须能被外面的
    `hypergraph.rejects.jsonl` 逐行对上：manifest 说 `rejects=N` 而文件有 M 行时
    （N≠M），外人无法判断索引到底被门挡掉了多少东西——P14-5 的 Q0 就是这么判的。
    """
    report = BuildReport(raw_edges=len(edges), processed_chunks=processed_chunks,
                         total_chunks=total_chunks)
    valid: List[HyperEdge] = []
    for edge in edges:
        try:
            validate_edge(edge, nodes)
        except GateError as exc:
            report.rejects += 1
            key = str(exc).split(":", 1)[0]
            report.reject_reasons[key] = report.reject_reasons.get(key, 0) + 1
            if reject_sink is not None:
                reject_sink.append({"phase": "gate", "edge_id": edge.edge_id,
                                    "type": edge.type, "reason": str(exc)})
            continue
        valid.append(edge)
    unique, duplicates = merge_duplicates(valid)
    report.valid_unique = len(unique)
    report.duplicates = duplicates
    if report.raw_edges != report.valid_unique + report.duplicates + report.rejects:
        raise AssertionError("超边计数恒等式被打破：raw ≠ valid_unique + duplicates + rejects")
    return unique, report


# --------------------------------------------------------------------------- 检索


def parse_query(text: str) -> Dict[str, List[str]]:
    """解析 `SceneContract` 查询串：`情绪=荒诞；动作=跺脚；运镜=固定；景别=中景`。"""
    out: Dict[str, List[str]] = {}
    for chunk in re.split(r"[；;]", text or ""):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        key, _, raw_value = chunk.partition("=")
        kind = QUERY_KEYS.get(key.strip())
        if kind is None:
            continue
        value = raw_value.strip()
        if kind == "scene_type" and value in ("有", "是", "yes", "true"):
            value = "dialogue"
        out.setdefault(kind, []).append(VALUE_ALIASES.get(value, value))
    return out


@dataclass
class RetrievalTrace:
    query: str = ""
    seeds: List[str] = field(default_factory=list)
    expanded_edges: List[str] = field(default_factory=list)
    scores: Dict[str, float] = field(default_factory=dict)
    selected: List[str] = field(default_factory=list)
    seed_miss: bool = False
    expansion_truncated: bool = False
    dropped_edge_ids: List[str] = field(default_factory=list)
    quality_fail: bool = False

    def to_dict(self) -> Dict:
        return {
            "query": self.query,
            "seeds": list(self.seeds),
            "expanded_edges": list(self.expanded_edges),
            "scores": {k: round(v, 6) for k, v in self.scores.items()},
            "selected": list(self.selected),
            "seed_miss": self.seed_miss,
            "expansion_truncated": self.expansion_truncated,
            "dropped_edge_ids": list(self.dropped_edge_ids),
            "quality_fail": self.quality_fail,
        }


class Hypergraph:
    """节点 ＋ 超边 ＋ 四步检索。"""

    def __init__(self, nodes: Sequence[Node], edges: Sequence[HyperEdge]) -> None:
        self.nodes: Dict[str, Node] = {node.node_id: node for node in nodes}
        self.edges: List[HyperEdge] = list(edges)
        self.by_id: Dict[str, HyperEdge] = {edge.edge_id: edge for edge in self.edges}
        self.adjacency: Dict[str, List[str]] = {}
        for edge in self.edges:
            for member in edge.members:
                self.adjacency.setdefault(member.node_id, []).append(edge.edge_id)
        self.max_occurrences = max((e.occurrences for e in self.edges), default=1)

    # ------------------------------------------------------------------ 种子
    def seeds_for(self, query: Dict[str, List[str]]) -> List[str]:
        """在 `node_text` 上做词面匹配（词元命中数 / 长度归一）。"""
        wanted = [value for values in query.values() for value in values]
        if not wanted:
            return []
        scored: List[Tuple[float, str]] = []
        for node in self.nodes.values():
            text_tokens = set(_bm25_tokenize(node.text))
            if not text_tokens:
                continue
            hits = 0
            for value in wanted:
                value_tokens = set(_bm25_tokenize(value))
                if value_tokens and (value_tokens <= text_tokens or value == node.value):
                    hits += 1
            if hits:
                scored.append((hits / (1.0 + math.log1p(len(text_tokens))), node.node_id))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [node_id for _score, node_id in scored[:SEED_TOP_K]]

    # ------------------------------------------------------------------ 扩展
    def _edge_coverage(self, edge: HyperEdge, seed_set: set) -> float:
        if not seed_set:
            return 0.0
        members = {m.node_id for m in edge.members}
        return len(members & seed_set) / len(seed_set)

    def expand(self, seed_ids: Sequence[str]) -> Tuple[List[HyperEdge], bool]:
        seed_set = set(seed_ids)
        frontier = list(seed_ids)
        seen_nodes = set(seed_ids)
        seen_edges: Dict[str, HyperEdge] = {}
        truncated = False
        hub_threshold = len(self.edges) / 20.0 if self.edges else 0.0
        for _hop in range(MAX_HOPS):
            next_frontier: List[str] = []
            for node_id in frontier:
                candidates = self.adjacency.get(node_id, [])
                edges = [self.by_id[eid] for eid in candidates]
                if hub_threshold and len(candidates) > hub_threshold:
                    edges.sort(key=lambda e: (-self._edge_coverage(e, seed_set),
                                              -e.occurrences, e.edge_id))
                    edges = edges[:min(4, MAX_EDGES_PER_NODE)]
                    truncated = truncated or len(candidates) > len(edges)
                for edge in edges:
                    if edge.edge_id in seen_edges:
                        continue
                    if len(seen_edges) >= MAX_EDGES_TOTAL:
                        truncated = True
                        break
                    seen_edges[edge.edge_id] = edge
                    for member in edge.members:
                        if member.node_id in seen_nodes:
                            continue
                        if len(seen_nodes) >= MAX_NODES:
                            truncated = True
                            continue
                        seen_nodes.add(member.node_id)
                        next_frontier.append(member.node_id)
                if len(seen_edges) >= MAX_EDGES_TOTAL:
                    break
            frontier = next_frontier
            if not frontier:
                break
        return list(seen_edges.values()), truncated

    # ------------------------------------------------------------------ 打分
    def score(self, edge: HyperEdge, query: Dict[str, List[str]], seed_set: set) -> float:
        coverage = self._edge_coverage(edge, seed_set)
        priority = TYPE_PRIORITY.get(edge.type, 0.5)
        occurrence = (math.log1p(edge.occurrences) / math.log1p(self.max_occurrences)
                      if self.max_occurrences > 0 else 0.0)
        authority = AUTHORITY.get(edge.provenance_kind, DEFAULT_AUTHORITY)
        forbid_hit = 0.0
        for member in edge.forbids:
            value = node_value(self.nodes.get(member.node_id), member.node_id)
            if value in query.get(member.kind, []):
                forbid_hit = 1.0
                break
        return (SCORE_WEIGHTS["coverage"] * coverage
                + SCORE_WEIGHTS["type_priority"] * priority
                + SCORE_WEIGHTS["occurrences"] * occurrence
                + SCORE_WEIGHTS["confidence"] * edge.confidence
                + SCORE_WEIGHTS["authority"] * authority
                + SCORE_WEIGHTS["forbid_hit"] * forbid_hit)

    # ------------------------------------------------------------------ 四步
    def retrieve(self, query_text: str, top_k: int = 5,
                 token_limit: int = MAX_RENDER_TOKENS
                 ) -> Tuple[List[HyperEdge], str, RetrievalTrace]:
        query = parse_query(query_text)
        trace = RetrievalTrace(query=query_text)
        seed_ids = self.seeds_for(query)
        if not seed_ids:
            trace.seed_miss = True
            return [], "", trace
        trace.seeds = list(seed_ids)
        seed_set = set(seed_ids)
        candidates, truncated = self.expand(seed_ids)
        trace.expansion_truncated = truncated
        trace.expanded_edges = [e.edge_id for e in candidates]
        scored = [(self.score(edge, query, seed_set), edge) for edge in candidates]
        scored.sort(key=lambda item: (-item[0], item[1].edge_id))
        for value, edge in scored:
            trace.scores[edge.edge_id] = value
        selected = [edge for _value, edge in scored[:max(1, top_k)]]
        trace.selected = [e.edge_id for e in selected]
        text, dropped, quality_fail = render_edges(selected, self.nodes, token_limit)
        trace.dropped_edge_ids = dropped
        trace.quality_fail = quality_fail
        return selected, text, trace
