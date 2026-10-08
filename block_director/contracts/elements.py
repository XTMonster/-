"""元素登记表 ``elements.json``（v1.6 FR-A2 / TDD §3.3）。纯层，不 import bpy。

全片元素（角色 / 道具 / 环境件）一处登记，是下游"身份图"与白模元素一一对上的
单一真源：``prompts.md`` 的稳定 token、逐元素遮罩色表（E2）与定妆卡（E3）都从
这份表读同一套 id / 名字 / 颜色 / 形状。

确定性是硬要求（FR-A2）：``to_dict()`` 按 id 排序，同一份计划＋同一份
cast/props/environment 数据两次构建**逐字节相同**。

数据源纪律（红线）：只从计划与显式传入的 cast / props / environment 数据登记，
**不从图像反推**；角色颜色只读 cast 的确定性调色板分配（``cast.DEFAULT_COLORS``），
不在这里改动分配算法。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from ..motion.model import PROP_ACTIONS
from .cast import DEFAULT_COLORS

#: 元素类型的闭集（TDD §3.3）。
ELEMENT_KINDS: tuple = ("character", "prop", "environment")

#: 角色的固定形状（TDD §3.3：圆柱身 + 头球）。角色形状**没有别的取值**。
CHARACTER_SHAPE = "capsule_q"

#: 环境件的统一灰阶（FR-A2 / E2 遮罩同源：环境件一律 ``#808080``）。
ENVIRONMENT_COLOR = "#808080"

#: 道具缺省色。**只读复制** ``layer3_engine/scene_executor.py::DEFAULT_PROP_COLOR
#: (0.7, 0.66, 0.6)`` 的十六进制形——纯层不能 import bpy，若那边改值这里必须同步。
DEFAULT_PROP_COLOR_HEX = "#B2A899"


def _color_to_hex(value: Any) -> str:
    """``#RRGGBB`` 字符串原样保留；0..1 三元组转 ``#RRGGBB``；读不出返回空串。"""
    if value is None:
        return ""
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ""
        return text if text.startswith("#") else f"#{text}"
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        channels: List[int] = []
        for channel in value[:3]:
            try:
                channels.append(min(max(int(round(float(channel) * 255)), 0), 255))
            except (TypeError, ValueError):
                return ""
        return "#" + "".join(f"{channel:02X}" for channel in channels)
    return ""


@dataclass
class Element:
    """登记表里的一条元素（TDD §3.3 的字段逐字）。"""

    id: str
    kind: str
    label: str
    color_hex: str
    shape: str = ""
    first_shot: str = ""

    def __post_init__(self) -> None:
        self.id = str(self.id or "").strip()
        self.kind = str(self.kind or "").strip()
        self.label = str(self.label or "").strip()
        self.color_hex = str(self.color_hex or "").strip()
        self.first_shot = str(self.first_shot or "").strip()
        if self.kind not in ELEMENT_KINDS:
            raise ValueError(
                f"未知元素类型 {self.kind!r}（合法值：{', '.join(ELEMENT_KINDS)}）")
        #: 角色形状是**固定值**，任何写入都被归一（不许出现别的形状）。
        self.shape = CHARACTER_SHAPE if self.kind == "character" \
            else str(self.shape or "").strip()

    def to_dict(self) -> Dict[str, Any]:
        from .serde import to_plain
        return to_plain(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Element":
        from .serde import from_plain
        if not isinstance(data, dict):
            raise ValueError(f"元素条目必须是对象，收到 {type(data).__name__}")
        return from_plain(cls, data)


@dataclass
class ElementRegistry:
    """全片元素登记表（TDD §3.3）。"""

    elements: List[Element] = field(default_factory=list)

    def by_id(self) -> Dict[str, Element]:
        """``{id: Element}``。重复 id 是登记表的真实损坏，直接报错不静默覆盖。"""
        out: Dict[str, Element] = {}
        for element in self.elements:
            if element.id in out:
                raise ValueError(f"元素 id 重复：{element.id}")
            out[element.id] = element
        return out

    def to_dict(self) -> Dict[str, Any]:
        """按 id 排序序列化——两跑逐字节相同的确定性来源（FR-A2）。"""
        ordered = sorted(self.elements, key=lambda item: item.id)
        return {"elements": [element.to_dict() for element in ordered]}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ElementRegistry":
        if not isinstance(data, dict) or "elements" not in data:
            raise ValueError("登记表数据必须是含 elements 键的对象")
        return cls(elements=[Element.from_dict(item)
                             for item in (data.get("elements") or [])])


def _member_id(member: Any) -> str:
    if isinstance(member, dict):
        return str(member.get("id") or "").strip()
    return str(getattr(member, "id", "") or "").strip()


def _member_label(member: Any) -> str:
    if isinstance(member, dict):
        return str(member.get("name") or member.get("label") or "").strip()
    return str(getattr(member, "name", "") or "").strip()


def _member_color(member: Any) -> str:
    if isinstance(member, dict):
        return _color_to_hex(member.get("color"))
    return _color_to_hex(getattr(member, "color", ""))


def _characters(plan: Any, cast: Optional[Sequence[Any]]) -> List[Element]:
    """角色：计划**首次出现顺序**在前，cast 里没出场的成员追加在后。"""
    cast_by_id: Dict[str, Any] = {}
    cast_order: List[str] = []
    for member in cast or []:
        character_id = _member_id(member)
        if not character_id or character_id in cast_by_id:
            continue
        cast_by_id[character_id] = member
        cast_order.append(character_id)

    plan_order: List[str] = []
    for shot in getattr(plan, "shots", None) or []:
        for character_id in getattr(shot, "characters", None) or []:
            character_id = str(character_id or "").strip()
            if character_id and character_id not in plan_order:
                plan_order.append(character_id)

    entries: List[Element] = []
    all_ids = plan_order + [cid for cid in cast_order if cid not in plan_order]
    for character_id in all_ids:
        member = cast_by_id.get(character_id)
        color = _member_color(member) if member is not None else ""
        if not color:
            if character_id in plan_order:
                #: 与 ``SceneSpec.from_plan`` 同一份确定性分配（只读、不改算法）。
                index = plan_order.index(character_id)
                color = DEFAULT_COLORS[index % len(DEFAULT_COLORS)]
            else:
                color = "#FFFFFF"
        label = _member_label(member) if member is not None else ""
        entries.append(Element(id=character_id, kind="character",
                               label=label or character_id, color_hex=color,
                               shape=CHARACTER_SHAPE))
    return entries


def _props(props: Optional[Sequence[Any]]) -> List[Element]:
    """道具逐条登记；``id`` 必填，缺 id / 非对象是错误（不静默跳过）。"""
    entries: List[Element] = []
    for item in props or []:
        if not isinstance(item, dict):
            raise ValueError(f"道具条目必须是对象，收到 {type(item).__name__}")
        prop_id = str(item.get("id") or "").strip()
        if not prop_id:
            raise ValueError("道具条目缺少 id")
        label = str(item.get("label") or item.get("name") or "").strip()
        entries.append(Element(
            id=prop_id, kind="prop", label=label or prop_id,
            color_hex=_color_to_hex(item.get("color")) or DEFAULT_PROP_COLOR_HEX,
            shape=str(item.get("shape") or "")))
    return entries


def _environment(environment: Optional[Sequence[Any]]) -> List[Element]:
    """环境件：有 ``id`` 用之；否则按 ``direction`` 派生 ``env_<方位>_<序号>``，
    两者都没有按输入顺序 ``env_<序号>``。颜色统一灰阶。"""
    entries: List[Element] = []
    direction_counts: Dict[str, int] = {}
    sequence = 0
    for item in environment or []:
        if not isinstance(item, dict):
            raise ValueError(f"环境件条目必须是对象，收到 {type(item).__name__}")
        env_id = str(item.get("id") or "").strip()
        if not env_id:
            direction = str(item.get("direction") or "").strip()
            if direction:
                direction_counts[direction] = direction_counts.get(direction, 0) + 1
                env_id = f"env_{direction}_{direction_counts[direction]}"
            else:
                sequence += 1
                env_id = f"env_{sequence:02d}"
        label = str(item.get("label") or item.get("name") or "").strip()
        entries.append(Element(id=env_id, kind="environment",
                               label=label or env_id,
                               color_hex=ENVIRONMENT_COLOR))
    return entries


def _referenced_names(shot: Any) -> List[str]:
    """一镜计划里对道具 / 环境件的引用名（按出现顺序，可能重复）。

    * 道具：``place_prop`` / ``pick_up`` / ``hand_to`` 动作的 ``params.prop``；
    * 环境件 / 道具：执行拍点的 ``target``（锚点名 / 道具名 / 角色 id）。

    这是"元素在哪一镜"的**计划内引用面**——不做图像推断，不另造数据。
    """
    names: List[str] = []
    for action in getattr(shot, "actions", None) or []:
        if not isinstance(action, dict):
            continue
        if str(action.get("action_type") or "") not in PROP_ACTIONS:
            continue
        params = action.get("params") or {}
        if not isinstance(params, dict):
            continue
        name = str(params.get("prop") or "").strip()
        if name:
            names.append(name)
    for beat in getattr(shot, "beats", None) or []:
        if not isinstance(beat, dict):
            continue
        target = str(beat.get("target") or "").strip()
        if target:
            names.append(target)
    return names


def shot_element_ids(shot: Any, registry: "ElementRegistry") -> List[str]:
    """这一镜的 ``elements_in_frame``：道具 + 环境件（**不含角色**）。

    引用按登记表 id 或显示名解析；解析不到登记表成员、或指向角色的引用
    一律不算（角色仍走 ``shots.json`` 的既有 ``characters`` 字段）。
    输出按引用出现顺序去重，确定性。
    """
    by_id = registry.by_id()
    by_label = {element.label: element.id for element in registry.elements
                if element.label and element.label not in by_id}
    ordered: List[str] = []
    for name in _referenced_names(shot):
        element_id = name if name in by_id else by_label.get(name)
        if element_id is None or element_id in ordered:
            continue
        if by_id[element_id].kind != "character":
            ordered.append(element_id)
    return ordered


def _stamp_first_shots(plan: Any, registry: ElementRegistry) -> None:
    """按计划镜序回填 ``first_shot``：只记第一次命中，未出场的元素留空。"""
    first: Dict[str, str] = {}
    for shot in getattr(plan, "shots", None) or []:
        shot_id = str(getattr(shot, "shot_id", "") or "").strip()
        if not shot_id:
            continue
        ids = [str(cid or "").strip()
               for cid in (getattr(shot, "characters", None) or [])]
        ids.extend(shot_element_ids(shot, registry))
        for element_id in ids:
            first.setdefault(element_id, shot_id)
    for element in registry.elements:
        element.first_shot = first.get(element.id, "")


def build_registry(plan: Any, *,
                   cast: Optional[Sequence[Any]] = None,
                   props: Optional[Sequence[Any]] = None,
                   environment: Optional[Sequence[Any]] = None,
                   ) -> ElementRegistry:
    """从计划 + 交付已有的 cast / props / environment 数据构建唯一登记表。

    * 角色：颜色取 cast 的确定性调色板分配（没有 cast 时按
      :data:`cast.DEFAULT_COLORS` 同序回落——与 ``SceneSpec.from_plan`` 同一份
      分配，**只读不写**）；显示名取 cast 的名字，缺省回落到 id。
    * 道具：``id`` 必填；颜色 / 形状读道具数据（缺省用白模道具灰）。
    * 环境件：颜色统一 :data:`ENVIRONMENT_COLOR`（灰阶，遮罩同源）。
    * ``first_shot``：按计划镜序扫描，角色看 ``shot.characters``，道具 /
      环境件看该镜动作 ``params.prop`` 与拍点 ``target`` 的引用。

    数据源只有计划与显式传入的数据；**不从图像反推**（FR-A2 / 卡 E1 红线）。
    """
    registry = ElementRegistry(
        elements=_characters(plan, cast) + _props(props)
        + _environment(environment))
    _stamp_first_shots(plan, registry)
    return registry


__all__ = [
    "ELEMENT_KINDS", "CHARACTER_SHAPE", "ENVIRONMENT_COLOR",
    "DEFAULT_PROP_COLOR_HEX", "Element", "ElementRegistry",
    "build_registry", "shot_element_ids",
]
