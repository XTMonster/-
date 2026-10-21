"""场级摆位锚点：自然语言方位 → 坐标（执行文档 v1.5 TDD §3.3 / §4.3）。

**与 ``cinema/anchor.py`` 的区别（命名容易撞车，先说清）**：``anchor.py`` 管的是
**角色自身的竖直锚点**（头顶/肩高，v1.4 冻结几何 1.70 与"头球相切"，ADR-0007），
是构图求解器的派生链；本模块管的是**场级物件锚点**（门、桌子、窗），把 LLM 写的
``relation``（"behind 甲"、"between 甲 and 乙"）解析成世界坐标，供走位与摆位使用。
两者只共享"锚点"这个中文词，语义、生产者、消费者都不同。

设计纪律（沿用 §4.3 与 SceneBrief"不猜代词"的同一条纪律）：

* 解析不出来就**记问题**，不猜复杂关系、不编坐标；
* 一切输出**确定性**：同一份输入必须给出同一份坐标（含"未解析"的缺省位）；
* 纯计算，**不 import bpy**（红线 R-1）。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

Vector3 = Tuple[float, float, float]

#: 关系里没写距离时的缺省距离（TDD §4.3：``behind X`` 的 2.0 m）。
DEFAULT_ANCHOR_DISTANCE = 2.0

#: ``ahead``（深处=背景纵深）缺省距离：画面深处的纵深距离大于普通关系
#: 缺省，取 3× ``DEFAULT_ANCHOR_DISTANCE``（确定性、无相机时可重建）。
AHEAD_ANCHOR_DISTANCE = 3.0 * DEFAULT_ANCHOR_DISTANCE

#: 支持的关系（TDD §4.3：``behind`` / ``between`` / ``left_of`` /
#: ``right_of``；R2 06/S1 增补剧本真实写法的 ``beside``（旁）、
#: ``front_of``（前方/朝向）、``ahead``（深处=背景纵深）、``opposite``
#: （对面）。带距离的写法如 ``left_of 甲 2m``。其余关系一律记为未解析。
ANCHOR_RELATIONS: Tuple[str, ...] = (
    "behind", "between", "left_of", "right_of",
    "beside", "front_of", "ahead", "opposite",
)

#: 中英两套关系词。命中即取；**第一个命中的**决定 kind（长词优先，见
#: :func:`_detect_kind`）。中文侧是按剧本里真实写法收的（"甲背后"/"在甲和乙之间"）。
_RELATION_PATTERNS: Tuple[Tuple[str, str], ...] = (
    ("between", "之间"), ("between", "中间"), ("between", "between"),
    ("behind", "背后"), ("behind", "身后"), ("behind", "后面"),
    ("behind", "后方"), ("behind", "behind"),
    ("left_of", "左侧"), ("left_of", "左边"), ("left_of", "左方"),
    ("left_of", "left"), ("left_of", "左"),
    ("right_of", "右侧"), ("right_of", "右边"), ("right_of", "右方"),
    ("right_of", "right"), ("right_of", "右"),
    ("beside", "旁边"), ("beside", "旁"),
    ("front_of", "前方"), ("front_of", "前面"), ("front_of", "朝向"),
    ("front_of", "front"),
    ("ahead", "深处"), ("ahead", "纵深"),
    ("opposite", "对面"), ("opposite", "opposite"),
)

#: 连接词/虚词：解析目标名时先去掉，避免 "and 甲 的 桌子" 这类噪声变成候选名。
_STOPWORDS: Tuple[str, ...] = (
    "and", "of", "the", "at", "from", "side", "left", "right", "behind",
    "between", "前方", "背后", "身后", "后面", "后方", "之间", "中间",
    "左侧", "左边", "左方", "右侧", "右边", "右方", "的", "在", "与", "和",
    "旁边", "前面", "朝向", "深处", "纵深", "对面", "旁", "边", "处",
)

_DISTANCE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:m|M|米|公尺)")

#: 环境锚自由文本（无角色参照）的方位词：``(规范方向, 中文词)``。
#: 剧本/LLM 的真实写法学自 20261019-r2-market-coin-full 的
#: ``plan.environment.anchors[].relation``：*场地右侧近处*、*左侧近处*、
#: *右侧中部*、*画面深处远处海面*、*远处背景人群*。这些锚点没有角色参照，
#: 语义是"相对场景中心"（与 ``spatial_design._anchor_from_environment`` 的
#: direction/distance 闭集同一语义），按同一数值表（2/6/12 m）落位，
#: 保证设计快照与场景世界 JSON 坐标一致。
SCENE_CENTER_DIRECTION_WORDS: Tuple[Tuple[str, str], ...] = (
    ("right", "右侧"), ("right", "右边"), ("right", "右方"), ("right", "右"),
    ("left", "左侧"), ("left", "左边"), ("left", "左方"), ("left", "左"),
    ("front", "前方"), ("front", "前面"), ("front", "正面"), ("front", "前"),
    ("back", "深处"), ("back", "远处"), ("back", "背景"), ("back", "后方"),
    ("back", "后面"), ("back", "后"),
)

#: 环境锚自由文本的距离档词：``(规范档位, 中文词)``。档位词与显式米数
#: 二选一；两者都出现时显式米数优先（与角色关系解析同一规则）。
SCENE_CENTER_DISTANCE_WORDS: Tuple[Tuple[str, str], ...] = (
    ("near", "近处"), ("near", "近"),
    ("mid", "中部"), ("mid", "中间"), ("mid", "中"),
    ("far", "远处"), ("far", "深处"), ("far", "远"),
)

#: 档位 -> 米（与 ``spatial_design.DISTANCE_METERS`` 同值：near=2/mid=6/far=12）。
SCENE_CENTER_DISTANCE_METERS: Dict[str, float] = {
    "near": 2.0, "mid": 6.0, "far": 12.0,
}

#: 规范方向 -> 世界方向向量（相对场景中心，XY 平面；Z-up、X=右、Y=前）。
SCENE_CENTER_VECTORS: Dict[str, Vector3] = {
    "right": (1.0, 0.0, 0.0),
    "left": (-1.0, 0.0, 0.0),
    "front": (0.0, 1.0, 0.0),
    "back": (0.0, -1.0, 0.0),
}


@dataclass(frozen=True)
class AnchorRelation:
    """解析后的关系：``between`` 有 2 个目标，其余有 1 个。"""

    kind: str
    targets: Tuple[str, ...]
    distance: float = DEFAULT_ANCHOR_DISTANCE


def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _vector(value: Any) -> Optional[Vector3]:
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        try:
            return (float(value[0]), float(value[1]), float(value[2]))
        except (TypeError, ValueError):
            return None
    return None


def _normalise(text: str) -> str:
    """把全角字符与空白归一，便于下面的词表匹配。"""
    table = {ord("（"): "(", ord("）"): ")", ord("，"): ",", ord("　"): " "}
    return "".join(table.get(ord(ch), ch) for ch in text).strip()


def _detect_kind(text: str) -> Optional[str]:
    """按**最长优先**匹配关系词，返回规范名；认不出返回 ``None``。"""
    for kind, word in sorted(_RELATION_PATTERNS, key=lambda item: -len(item[1])):
        if word in text:
            return kind
    return None


def _tokens(text: str) -> List[str]:
    """切出候选目标名：先按连接符切，再逐段去掉虚词。"""
    normalised = _normalise(text)
    for word in sorted(_STOPWORDS, key=len, reverse=True):
        normalised = normalised.replace(word, " ")
    for separator in (",", "，", "、", "/", "|", "+", "&"):
        normalised = normalised.replace(separator, " ")
    return [piece for piece in normalised.split() if piece]


def parse_relation(text: str, *,
                   aliases: Optional[Mapping[str, str]] = None,
                   known: Optional[Iterable[str]] = None
                   ) -> Optional[AnchorRelation]:
    """把自然语言方位解析成 :class:`AnchorRelation`；认不出返回 ``None``。

    ``aliases`` 是"显示名 → 角色 id"（剧本里写的是"伊恩"，计划里存的是
    ``char_001``）；``known`` 是合法目标集合（角色 id ＋ 其他锚点名）。
    解析出的名字必须能在两者之一里落地，否则按未解析处理——**不猜代词**。
    """
    raw = _text(text)
    if not raw:
        return None
    kind = _detect_kind(raw)
    if kind is None:
        return None
    match = _DISTANCE_RE.search(raw)
    distance = float(match.group(1)) if match else DEFAULT_ANCHOR_DISTANCE
    resolvable = dict(aliases or {})
    allowed = {str(item) for item in (known or []) if str(item)}

    def resolve(name: str) -> Optional[str]:
        if name in resolvable:
            return resolvable[name]
        if name in allowed:
            return name
        return None

    targets: List[str] = []
    for token in _tokens(raw):
        resolved = resolve(token)
        if resolved and resolved not in targets:
            targets.append(resolved)
    needed = 2 if kind == "between" else 1
    if len(targets) < needed:
        return None
    return AnchorRelation(kind=kind, targets=tuple(targets[:needed]),
                          distance=distance)


def resolve_scene_center_anchor(text: str) -> Optional[Vector3]:
    """把环境锚的自由文本（无角色参照）解析成相对场景中心的坐标。

    认法：最长优先匹配方位词（右侧/左侧/前方/深处/远处…）+ 距离档词
    （近处/中部/远处）；没有档位词但带显式 ``N 米`` 时按米数落位。
    方位或距离都认不出时返回 ``None``（不猜）。坐标系与角色锚一致：
    Z-up、X=右、Y=前，落点在原点（场景中心）偏移。
    """
    raw = _normalise(_text(text))
    if not raw:
        return None
    direction: Optional[str] = None
    for canonical, word in sorted(
            SCENE_CENTER_DIRECTION_WORDS, key=lambda item: -len(item[1])):
        if word in raw:
            direction = canonical
            break
    distance: Optional[str] = None
    for canonical, word in sorted(
            SCENE_CENTER_DISTANCE_WORDS, key=lambda item: -len(item[1])):
        if word in raw:
            distance = canonical
            break
    match = _DISTANCE_RE.search(raw)
    if match:
        meters = float(match.group(1))
        if direction is not None:
            vec = SCENE_CENTER_VECTORS[direction]
            return (round(vec[0] * meters, 4), round(vec[1] * meters, 4), 0.0)
    if direction is None or distance is None:
        return None
    vec = SCENE_CENTER_VECTORS[direction]
    meters = SCENE_CENTER_DISTANCE_METERS[distance]
    return (round(vec[0] * meters, 4), round(vec[1] * meters, 4), 0.0)


def _unit(value: Vector3) -> Optional[Vector3]:
    length = math.sqrt(sum(component * component
                          for component in (value[0], value[1])))
    if length <= 1e-9:
        return None
    return (value[0] / length, value[1] / length, 0.0)


def _left_of(facing: Vector3) -> Optional[Vector3]:
    """Z-up、X=右、Y=前：面朝 ``facing`` 时，角色的左手方向 = 绕 +Z 转 90°。"""
    unit = _unit(facing)
    if unit is None:
        return None
    return (-unit[1], unit[0], 0.0)


def _right_of(facing: Vector3) -> Optional[Vector3]:
    left = _left_of(facing)
    if left is None:
        return None
    return (-left[0], -left[1], 0.0)


def _place(relation: AnchorRelation,
           cast_positions: Mapping[str, Mapping[str, Any]]
           ) -> Optional[Vector3]:
    """按关系算出坐标；任何一环缺失都返回 ``None``（= 未解析）。"""
    known = []
    for target in relation.targets:
        entry = cast_positions.get(target) or {}
        position = _vector(entry.get("position"))
        if position is None:
            return None
        known.append((position, _vector(entry.get("facing")) or (0.0, 0.0, 0.0)))

    if relation.kind == "between":
        (first, _), (second, _) = known
        return ((first[0] + second[0]) / 2.0,
                (first[1] + second[1]) / 2.0,
                (first[2] + second[2]) / 2.0)

    position, facing = known[0]
    if relation.kind == "behind":
        unit = _unit(facing)
        if unit is None:
            return None
        direction = (-unit[0], -unit[1], 0.0)
    elif relation.kind == "left_of":
        direction = _left_of(facing)
    elif relation.kind == "right_of":
        direction = _right_of(facing)
    elif relation.kind == "beside":
        #: ``旁`` = 紧邻一侧：确定性取目标左手方向（与 left_of 同轴，
        #: 但语义是"贴邻"而非"在左方"；无相机时左右不分正负，
        #: 取左手侧保证可重建、可对拍）。
        direction = _left_of(facing)
    elif relation.kind == "front_of":
        unit = _unit(facing)
        if unit is None:
            return None
        direction = unit
    elif relation.kind == "ahead":
        #: ``深处`` = 背景纵深：目标 facing 正方向、距离放大
        #: （缺省 3×，显式距离优先）。
        unit = _unit(facing)
        if unit is None:
            return None
        direction = unit
    elif relation.kind == "opposite":
        #: ``对面`` = facing 反方向（与 behind 同一语义）。
        unit = _unit(facing)
        if unit is None:
            return None
        direction = (-unit[0], -unit[1], 0.0)
    else:
        return None
    if direction is None:
        return None
    if relation.kind == "ahead":
        #: 深处缺省纵深距离；显式 ``N 米`` 仍然优先（TDD §4.3 距离读取）。
        distance = (relation.distance
                    if relation.distance != DEFAULT_ANCHOR_DISTANCE
                    else AHEAD_ANCHOR_DISTANCE)
    else:
        distance = relation.distance
    return (position[0] + direction[0] * distance,
            position[1] + direction[1] * distance,
            position[2])


def solve_anchor_positions(
        anchors: Sequence[Any],
        cast_positions: Optional[Mapping[str, Mapping[str, Any]]] = None,
        *,
        aliases: Optional[Mapping[str, str]] = None,
        anchor_names: Optional[Iterable[str]] = None,
        default_distance: float = DEFAULT_ANCHOR_DISTANCE,
        origin: Vector3 = (0.0, 0.0, 0.0),
) -> Tuple[Dict[str, List[float]], List[Dict[str, str]]]:
    """把一份锚点声明表求解成 ``{锚点名: [x, y, z]}`` ＋ 问题清单。

    * 有显式 ``position`` 的锚点原样采用（求解器不覆盖用户/上游给的坐标）；
    * 关系解析失败、目标角色查不到、坐标缺失 ⇒ **记问题**，并把该锚点放到
      "原点附近的缺省位"；缺省位按未解析锚点的名字字典序排在半径
      ``default_distance`` 的圆上，**确定性**且互不重叠（TDD §4.3：不猜复杂关系，
      但要让场景可重建）；
    * ``depth``（fg/mid/bg）在求解器里**不用**：它是"相对相机视角"的分层，
      而这一步没有相机；它只随 SDL/提示词传给下游（如实记录，不假装已消费）。

    第二个返回值是问题清单，每条是 ``{"anchor": 锚点名, "reason": 原因}``
    （结构性问题的 ``anchor`` 为空串）。用记录而不是"名字: 原因"字符串，
    是为了让消费者读字段、不做前缀解析——审计行由调用方渲染。
    """
    cast = cast_positions or {}
    known = set(cast)
    known.update(str(item) for item in (anchor_names or []) if str(item))
    positions: Dict[str, List[float]] = {}
    problems: List[Dict[str, str]] = []
    unresolved: List[str] = []

    seen: set = set()
    for anchor in anchors or []:
        if isinstance(anchor, Mapping):
            name = _text(anchor.get("name"))
            relation_text = _text(anchor.get("relation"))
            explicit = _vector(anchor.get("position"))
        else:                       # 契约对象（SDLAnchor）也接受
            name = _text(getattr(anchor, "name", ""))
            relation_text = _text(getattr(anchor, "relation", ""))
            explicit = _vector(getattr(anchor, "position", None))
        if not name:
            problems.append({"anchor": "",
                             "reason": "锚点缺少 name，已跳过"})
            continue
        if name in seen:
            problems.append({"anchor": name,
                             "reason": "重复声明，已保留第一条"})
            continue
        seen.add(name)
        if explicit is not None:
            positions[name] = [round(value, 4) for value in explicit]
            continue
        relation = parse_relation(relation_text, aliases=aliases, known=known)
        place = _place(relation, cast) if relation is not None else None
        if place is None:
            #: R2 S1 补丁：环境锚没有角色参照（摊位/人群/光源），自由文本
            #: "场地右侧近处…" 解析成相对场景中心的坐标——与设计快照同值，
            #: 世界 JSON 实时对齐；认不出才落到"原点小圆环"缺省位。
            center = resolve_scene_center_anchor(relation_text)
            if center is not None:
                positions[name] = [round(value, 4) for value in center]
                continue
            reason = ("未声明 relation 也未给 position" if not relation_text
                      else f"relation={relation_text!r} 解析不出坐标")
            problems.append({"anchor": name, "reason": reason})
            unresolved.append(name)
            continue
        positions[name] = [round(value, 4) for value in place]

    # 未解析的锚点：确定性缺省位（原点附近的小圆环）。
    for index, name in enumerate(sorted(unresolved)):
        angle = 2.0 * math.pi * index / max(len(unresolved), 1)
        positions[name] = [
            round(origin[0] + default_distance * math.cos(angle), 4),
            round(origin[1] + default_distance * math.sin(angle), 4),
            round(origin[2], 4),
        ]
    # 输出顺序稳定（按声明顺序），便于逐字节对比与测试。
    ordered = {name: positions[name] for name in positions}
    return ordered, problems


__all__ = [
    "ANCHOR_RELATIONS", "DEFAULT_ANCHOR_DISTANCE", "AnchorRelation",
    "SCENE_CENTER_DIRECTION_WORDS", "SCENE_CENTER_DISTANCE_METERS",
    "SCENE_CENTER_DISTANCE_WORDS", "SCENE_CENTER_VECTORS",
    "parse_relation", "resolve_scene_center_anchor", "solve_anchor_positions",
]
