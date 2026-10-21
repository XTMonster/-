"""剧组与场景设定（执行文档 v1.2 §5.1 的 characters / environment）。

刻意不依赖 bpy：Layer 2（SDL）与 Layer 3（执行引擎）都要用它，放进 contracts
才不会让 SDL 反向依赖执行引擎。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .plan import Plan

DEFAULT_COLORS = ("#FF6B6B", "#6BC5FF", "#FFD166", "#9B8CFF",
                  "#6BE3A2", "#FF9F6B")
DEFAULT_SPACING = 1.5
#: 两人相对而立时的间距（§9.7 的"社交距离"上限附近，镜头里读得出对峙感）
OPPOSITE_SPACING = 1.8
#: §9.7 的人际距离四档 → 白模里的实际间距（米）
DISTANCE_CLASS_GAP = {"intimate": 0.6, "personal": 1.1, "social": 1.8,
                      "public": 3.2}
DEFAULT_GROUND = (120.0, 120.0)

ID_PREFIX = "char_"
ID_DIGITS = 3


def default_station(count: int) -> List[Tuple[Tuple[float, float, float],
                                             Tuple[float, float, float]]]:
    """没有更多语义信息时的默认站位：``[(位置, 朝向), ...]``。

    v1.3 修正：v1.2 把所有角色沿 X 轴排开、**一律面朝 +Y**，于是两个正在
    对话的人并排朝前、谁也不看谁——与"互相看向对方"的剧本语义正好相反，
    也与"站位决定轴线"的 §10.3 前提不符。现在的规则是：

    * 1 人：站在原点，面朝 +Y（不变）；
    * 2 人：**相对而立**，对称分布在 X 轴上，互相面对；
    * ≥3 人：沿 X 轴排开，各自面向队伍重心（比"全部朝前"更接近围谈）。

    真正的站位由 v1.3 的 ``SceneBrief.space`` 决定；这里只保证"缺省姿态
    是合理可读的"。纯函数，可单测。
    """
    total = int(count)
    if total <= 0:
        return []
    if total == 1:
        return [((0.0, 0.0, 0.0), (0.0, 1.0, 0.0))]
    if total == 2:
        half = OPPOSITE_SPACING / 2.0
        return [((-half, 0.0, 0.0), (1.0, 0.0, 0.0)),
                ((half, 0.0, 0.0), (-1.0, 0.0, 0.0))]

    stations = []
    for index in range(total):
        offset = (index - (total - 1) / 2.0) * DEFAULT_SPACING
        if offset > 1e-9:
            facing = (-1.0, 0.0)
        elif offset < -1e-9:
            facing = (1.0, 0.0)
        else:
            facing = (0.0, 1.0)
        stations.append(((round(offset, 3), 0.0, 0.0), facing))
    return stations


def _unit2(vector) -> Tuple[float, float]:
    x, y = float(vector[0]), float(vector[1])
    length = math.hypot(x, y)
    return (x / length, y / length) if length > 1e-9 else (0.0, 1.0)


def station_from_space(characters: List[str], space,
                       *, default_spacing: float = OPPOSITE_SPACING
                       ) -> List[Tuple[Tuple[float, float, float],
                                       Tuple[float, float, float]]]:
    """按 ``SceneBrief.space`` 把默认站位改写成**剧本声明的关系站位**。

    ``space`` 描述的是"谁相对谁、什么关系、多远"（§3.2）。这里按声明顺序
    逐条落实：先取默认站位作为基线，再把被点名的角色摆到参照角色旁边。
    没有声明的角色保持默认位置——**不替剧本扩大解释**。

    纯函数，可单测。
    """
    base = default_station(len(characters))
    if not characters:
        return []
    locations = {name: list(base[index][0]) for index, name in enumerate(characters)}
    facings = {name: list(base[index][1]) for index, name in enumerate(characters)}
    placed = set()

    for raw in space or []:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("character") or "").strip()
        other = str(raw.get("relative_to") or "").strip()
        if name not in locations or other not in locations or name == other:
            continue
        relation = str(raw.get("relation") or "facing").strip().lower()
        gap = DISTANCE_CLASS_GAP.get(
            str(raw.get("distance_class") or "").strip().lower(), default_spacing)
        forward = _unit2(facings[other])
        right = (forward[1], -forward[0])
        origin = locations[other]

        def place(offset) -> None:
            candidate = [origin[0] + offset[0], origin[1] + offset[1],
                         origin[2]]
            #: 已有关系约束优先：闭环 space（A↔B、C↔A、B↔C）不能把
            #: 先求出的角色再挪回默认点；只给尚未落实的角色写位置。
            if name in placed:
                return
            #: 候选点若与已有角色重叠，沿参照角色右轴向自由侧避让，
            #: 这是空间尺可计算的几何修正，不是随机猜位。
            for other_name, other_pos in locations.items():
                if other_name == name or other_name not in placed:
                    continue
                dx = candidate[0] - other_pos[0]
                dy = candidate[1] - other_pos[1]
                if (dx * dx + dy * dy) ** 0.5 >= 0.8:
                    continue
                side = right
                candidate[0] += side[0] * max(gap, 0.8)
                candidate[1] += side[1] * max(gap, 0.8)
            locations[name] = [round(candidate[0], 3),
                               round(candidate[1], 3), candidate[2]]
            placed.add(name)

        if relation == "side_by_side":
            place((right[0] * gap, right[1] * gap))
            facings[name] = list(forward)
        elif relation == "behind":
            place((-forward[0] * gap, -forward[1] * gap))
            facings[name] = list(forward)
        elif relation == "ahead":
            place((forward[0] * gap, forward[1] * gap))
            facings[name] = list(forward)
        elif relation == "apart":
            place((-forward[0] * gap, -forward[1] * gap))
            facings[name] = [-forward[0], -forward[1]]
        else:                                    # facing（默认）：相对而立
            place((forward[0] * gap, forward[1] * gap))
            facings[name] = [-forward[0], -forward[1]]
            facings[other] = list(forward)

    # ``round(x, 3) or 0.0``：把 -0.0 归一成 0.0，免得落盘的 JSON 里
    # 出现 "−0.0" 这种"看起来像笔误"的数。
    return [((locations[name][0], locations[name][1], locations[name][2]),
             (round(facings[name][0], 6) or 0.0,
              round(facings[name][1], 6) or 0.0, 0.0))
            for name in characters]

#: 从"角色 / 背景内容"字段里认出群众的字样 → 估算人数
_CROWD_HINTS = ("路人", "人群", "群众", "行人", "商贩", "顾客", "围观",
                "顾客群", "过客", "行人")

#: v1.4 D-2：中文数字词表。分镜表里写的是"约三十名商贩"，旧正则只认阿拉伯
#: 数字，于是 30 人被估成默认的 6 人。
_CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "两": 2, "二": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000}
_CN_NUMBER_RE = (r"[零〇一二两三四五六七八九十百千]{1,6}")


def parse_chinese_number(text: str) -> Optional[int]:
    """``"三十"`` → 30、``"二十五"`` → 25、``"一百二十"`` → 120。

    只支持分镜表里真的会出现的量级（≤ 9999）；解析不出来返回 ``None``——
    宁可退回"人群"的默认规模，也不要猜错人数。
    """
    value = str(text or "").strip()
    if not value:
        return None
    if value.isdigit():
        return int(value)
    total, current, seen = 0, 0, False
    for char in value:
        if char in _CN_DIGITS:
            current = _CN_DIGITS[char]
            seen = True
        elif char in _CN_UNITS:
            unit = _CN_UNITS[char]
            total += (current or 1) * unit
            current = 0
            seen = True
        else:
            return None
    if not seen:
        return None
    return total + current


#: 数量：阿拉伯数字或中文数字 + 量词；"约/近/共/大约"是**数量修饰词**，
#: 不是否定词（§2.5：把它们放进否定表会直接打红既有的市场剧本用例）。
_CROWD_COUNT_RE = re.compile(
    r"(?:约|大约|近|共)?\s*(?P<num>\d{1,3}|" + _CN_NUMBER_RE + r")\s*"
    r"(?:名|个|位|人|号)")

#: 否定词：出现在数量**之前 ≤6 个字**的窗口里时，这条声明按"没有人"处理。
_CROWD_NEGATIONS = ("无", "没有", "未有", "不", "禁止", "不得")
NEGATION_WINDOW = 6


def _negated(text: str, start: int) -> bool:
    """数量词前面 ``NEGATION_WINDOW`` 个字里有没有否定词（D-2）。"""
    window = str(text or "")[max(start - NEGATION_WINDOW, 0):start]
    return any(word in window for word in _CROWD_NEGATIONS)


#: 分句边界：中英文句号、分号、换行（§2.5 的"分句窗口"）。
_CLAUSE_SPLIT_RE = re.compile(r"[。！？!?；;\n]+")


def _split_clauses(text: str) -> List[str]:
    """把一行按分句切开——D-2 的否定判定只在**同一个分句**里生效。"""
    return [part.strip() for part in _CLAUSE_SPLIT_RE.split(str(text or ""))
            if part.strip()]


def crowd_from_script(script, *, enabled: Optional[bool] = None,
                      max_instances: int = 40, mode: str = "walk",
                      seed: int = 0) -> List[Dict[str, Any]]:
    """从分镜表的声明里读出群众（v1.3 §3.6）。

    这是**声明侧**的确定性抽取：只有剧本自己写了"约 30 名路人""背景有人群"
    才生成群众代理。没有声明就不生成——不替剧本扩大解释。

    返回 ``[{"count", "mode", "seed", "spread", "label"}]``（**至多一条**）。

    同一场戏里好几个镜头都会提到路人，但那通常是**同一批人**（在码头市场
    走来走去的还是那群人）。所以取声明的最大值而不是把它们相加——
    相加会让一个 30 人的市场变成 40 个互不相干的代理。

    v1.4 X17：``enabled`` 三态 — ``False`` = 显式关闭（最高优先级）；
    ``True`` = 强制按声明生成；``None``（默认）= 按剧本声明。
    优先级：**显式 false > 剧本声明 > 默认关**。
    """
    if enabled is False:
        return []
    limit = max(int(max_instances), 0)
    if limit == 0:
        return []
    seen: set = set()
    declared = list(getattr(script, "declared_shots", []) or [])
    sources: List[str] = []
    for shot in declared:
        sources.append(str(shot.field("角色") or ""))
        sources.append(str(shot.field("背景内容") or ""))
        sources.append(str(shot.field("画面内容") or ""))
    if not declared:
        for scene in getattr(script, "scenes", None) or []:
            for action in scene.actions:
                sources.append(str(action.text or ""))
    best_count = 0
    best_label = ""
    for text in sources:
        if text in seen:
            continue
        seen.add(text)
        # v1.4 D-2：**按分句**判定，不按整行。同一行里"无路人入镜"与
        # "约三十名商贩"是两个分句：前者判 0，后者判 30。整行一起看的话，
        # 否定词会把后面合法的数量一起否掉（或反过来）。
        for clause in _split_clauses(text):
            if not clause or not any(hint in clause
                                     for hint in _CROWD_HINTS):
                continue
            match = _CROWD_COUNT_RE.search(clause)
            if match is None:
                if any(word in clause for word in _CROWD_NEGATIONS):
                    continue            # "无路人"这种没有数字的否定声明
                count = 6               # 只写了"人群"时的默认规模
            elif _negated(clause, match.start()):
                continue                # "无 30 名路人" = 0
            else:
                number = parse_chinese_number(match.group("num"))
                if number is None:
                    continue
                count = number
            if count > best_count:
                best_count, best_label = count, clause
    if best_count <= 0:
        return []
    return [{"count": max(min(best_count, limit), 1), "mode": str(mode),
             "seed": int(seed), "spread": 6.0, "label": best_label[:40]}]


def next_character_id(existing) -> str:
    """分配下一个空闲角色 id（``char_001``…）。

    纯函数、可单测。放在契约层是因为"角色 id 长什么样"是 §5.1 的约定，
    UI 的"添加角色"与 SDL 校验都依赖它。
    """
    used = set()
    for item in existing or ():
        text = str(item or "")
        if text.startswith(ID_PREFIX) and text[len(ID_PREFIX):].isdigit():
            used.add(int(text[len(ID_PREFIX):]))
    index = 1
    while index in used:
        index += 1
    return f"{ID_PREFIX}{index:0{ID_DIGITS}d}"


@dataclass
class CastMember:
    """一名角色的设定。

    字段名与执行文档 §5.1 / §16.1（``CharacterDef``）保持一致：落盘键是
    ``initial_location`` / ``initial_facing``，以免 SDL 文件与规范漂移。
    """

    id: str
    name: str
    color: str = "#FFFFFF"
    initial_location: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    initial_facing: Tuple[float, float, float] = (0.0, 1.0, 0.0)

    def to_dict(self) -> Dict[str, Any]:
        from .serde import to_plain
        return to_plain(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CastMember":
        from .serde import from_plain
        return from_plain(cls, data)


@dataclass
class SceneSpec:
    """场景设定：谁在场、环境长什么样。"""

    heading: str = ""
    cast: List[CastMember] = field(default_factory=list)
    ground_size: Tuple[float, float] = DEFAULT_GROUND
    walls: List[Dict[str, Any]] = field(default_factory=list)
    props: List[Dict[str, Any]] = field(default_factory=list)
    lighting: str = "clay_studio"
    room: Optional[Tuple[float, float, float, float]] = None
    with_labels: bool = True
    #: v1.3 §3.6：群众代理（**独立于 cast**）。
    #: 元素形如 ``{count, mode, seed, spread, label}``。独立存放是因为
    #: 角色面板、场景状态、构图评分与标签都按 ``cast`` 遍历——群众混进去
    #: 会让这四处全部失真（`tests/test_cast_panel.py` 直接断言角色数）。
    crowd: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_plan(cls, plan: Plan, brief=None, crowd=None,
                  **overrides) -> "SceneSpec":
        """按计划里出现的角色自动生成一份确定性剧组设定。

        站位用 :func:`default_station`：两人时相对而立（v1.2 是并排朝前，
        两个对话者谁也不看谁）。

       """
        character_ids: List[str] = []
        for shot in plan.shots:
            for character_id in shot.characters:
                if character_id not in character_ids:
                    character_ids.append(character_id)
        stations = default_station(len(character_ids))
        if brief is not None and getattr(brief, "space", None):
            # §3.2：真正的站位由 SceneBrief.space 决定；默认站位只是兜底。
            stations = station_from_space(character_ids, brief.space)
        cast: List[CastMember] = [
            CastMember(id=character_id, name=character_id,
                       color=DEFAULT_COLORS[index % len(DEFAULT_COLORS)],
                       initial_location=location,
                       initial_facing=facing)
            for index, (character_id, (location, facing))
            in enumerate(zip(character_ids, stations))]
        return cls(heading=plan.scene_heading, cast=cast,
                   crowd=[dict(item) for item in (crowd or [])],
                   **overrides)

    def to_dict(self) -> Dict[str, Any]:
        from .serde import to_plain
        return to_plain(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SceneSpec":
        from .serde import from_plain
        return from_plain(cls, data)
