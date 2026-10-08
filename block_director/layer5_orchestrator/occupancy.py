"""同层时间轴占用表（v1.6 卡 F4 / D-16）。

纯 Python、零 bpy（红线 R-1）。阶段 B1 起草每镜时，把"本镜各动作层已被
占用的帧区间"渲染成结构化表格注入计划提示，模型起草时避让；构建期保底
串行化（``beat_compiler._serialise_same_subject`` 与
``motion.model.stagger_conflicts``）**保留不变**——它是兜底，本表是提示侧的
事前信息，不得取代它。

单一真源纪律（红线 R-7 的同一条）：

* 动作 → 层：``motion/model.py::expand`` 展开后的 ``MotionSpec.layer``。
  层集合只由 ``action_type`` 决定（无参数依赖），因此以空参数展开——
  这与构建期 ``check_conflicts`` / ``stagger_conflicts`` 的层归属**同源**，
  不另抄一份层映射（``walk_to`` 占 base+legs、``sit`` 占 base+legs+body
  这类多轨事实才不会漏）。
* 拍点 → 帧：``beat_compiler.py::compile_beats``（**导入复用**，不重写
  估时）。拍点的 ``t`` 是归一化时机，换算必须知道整镜 ``duration_frames``；
  输入含拍点却未给 ``duration_frames`` 时**显式抛 ValueError**，不猜。

口径（与本表用途一致，不是构建期的重复）：

* 直写 ``actions[]``（帧级动作）**原样列出**——已排好的两条同层重叠区间
  都会出现在表里，模型看见的是计划原貌（构建期保底串行化仍会兜底）。
* 拍点经 ``compile_beats`` 编译后取**串行化之后**的帧窗：那是构建期真正
  会落的时间轴。
* ``compile_beats`` 的 ``problems``（走位无锚点/角色位置被跳过、同层后移
  留痕）**不在这里返回**——返回形状由接口钉死，且构建期编译器与审计仍会
  报出同一批通知；本函数只是提示侧估算。走位拍点在提示期拿不到坐标时会
  被编译器按"不猜"纪律跳过（不进表），这是已知限制，见模块 docstring 末尾。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..contracts.beats import ShotBeat
from ..motion.model import ALL_LAYERS, ActionRequest, expand
from .beat_compiler import compile_beats

#: 帧级动作里"秒"单位的键（``fps`` 只在它们出现时参与换算；计划的
#: ``EMIT_SHOT_DRAFT_PARAMETERS`` 只用 ``start_frame`` / ``end_frame``）。
SECONDS_KEYS = frozenset({"start_s", "end_s"})


def _get(item: Any, name: str, default: Any = None) -> Any:
    """dict 与鸭子类型对象统一取值。"""
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _is_shot_like(value: Any) -> bool:
    """``ShotPlan`` / 其 ``to_dict()`` / 任意带 ``beats`` 或 ``actions`` 的载体。"""
    if isinstance(value, dict):
        return "beats" in value or "actions" in value
    return hasattr(value, "beats") or hasattr(value, "actions")


def _is_action_like(item: Any) -> bool:
    names = ("action_type", "start_frame", "end_frame", "start_s", "end_s")
    if isinstance(item, dict):
        return any(name in item for name in names)
    return any(hasattr(item, name) for name in names)


def _is_beat_like(item: Any) -> bool:
    """``ShotBeat`` / 拍点 dict（``{t, verb, ...}``）。"""
    if isinstance(item, ShotBeat):
        return True
    if isinstance(item, dict):
        return "t" in item and "verb" in item
    return hasattr(item, "t") and hasattr(item, "verb")


def _frame_value(item: Any, names: Iterable[str], fps: float) -> Optional[int]:
    """按键序取帧号；``*_s`` 键按 ``fps`` 从秒折算，取不出来显式报错。"""
    for name in names:
        value = _get(item, name)
        if value is None:
            continue
        try:
            if name in SECONDS_KEYS:
                return max(1, int(round(float(value) * float(fps))))
            return int(value)
        except (TypeError, ValueError):
            raise ValueError(
                f"占用表：{name}={value!r} 不是合法帧号（帧键要整数、"
                f"秒键要数字）") from None
    return None


def _action_window(item: Any, fps: float) -> Tuple[int, int]:
    """帧级动作的 ``(start, end)``；缺省 = 单帧，不替调用方编时长。"""
    start = _frame_value(item, ("start_frame", "start_s"), fps)
    end = _frame_value(item, ("end_frame", "end_s"), fps)
    if start is None:
        start = 1
    if end is None:
        end = start
    return int(start), int(end)


def _layers_of(action_type: str) -> Tuple[str, ...]:
    """动作展开后占用的**全部**层（单一真源 = ``motion/model.py::expand``）。

    层集合只由 ``action_type`` 决定，参数不影响层归属，因此以空参数展开；
    参数校验不是本函数的职责（``extract_draft`` 已在解析期核过）。未知动作
    类型由 ``expand`` 抛 ``ValueError``——**不静默归到 base 层**。
    """
    specs = expand(ActionRequest(action_type=action_type, start_frame=1,
                                 end_frame=2, params={}))
    layers: List[str] = []
    for spec in specs:
        if spec.layer not in layers:
            layers.append(spec.layer)
    return tuple(layers)


def _owner_of(item: Any, action_type: str) -> str:
    character_id = str(_get(item, "character_id") or "").strip()
    if character_id:
        return f"{character_id}:{action_type}"
    return str(action_type)


def _sort_intervals(entries: Iterable[Tuple[int, int, str]]
                    ) -> List[Tuple[int, int, str]]:
    return sorted(entries, key=lambda entry: (entry[0], entry[1], entry[2]))


def layer_occupancy(actions_or_beats: Any, *, fps: float = 24,
                    duration_frames: Optional[int] = None,
                    anchors: Any = None, cast: Any = None,
                    current_positions: Any = None,
                    shot_id: str = "") -> Dict[str, List[Tuple[int, int, str]]]:
    """已排动作/拍点 → ``{层: [(start_frame, end_frame, 占用者描述), ...]}``。

    输入三种形态（``None`` / 空 → 空字典）：

    * **镜头载体**（``ShotPlan``、其 ``to_dict()`` 或任何带 ``beats`` /
      ``actions`` 的对象）：``actions`` 原样列出，``beats`` 用载体自带的
      ``duration_frames`` 编译（``shot_id`` / ``dialogues`` 一并带上）；
    * **帧级动作序列**（``action_type`` + ``start_frame``/``end_frame``，
      或秒键 ``start_s``/``end_s``）：原样列出，重叠**不**合并、不串行——
      计划里长什么样表里就长什么样；
    * **拍点序列**（``ShotBeat`` 或 ``{t, verb, ...}``）：经
      ``beat_compiler.compile_beats`` 编译（**必须**给 ``duration_frames``，
      可选给 ``anchors``/``cast``/``current_positions`` 供走位估时，缺了就
      按编译器的"不猜"纪律跳过该走位拍点）。

    非动作、非拍点的条目跳过（与 ``beat_compiler._coerce`` /
    ``merge_with_actions`` 同纪律）。层序固定为 ``ALL_LAYERS``，层内按
    ``(start, end, owner)`` 升序——同一输入两次调用结果逐项相同。
    """
    if actions_or_beats is None:
        return {}

    source = actions_or_beats
    frame_items: List[Any] = []
    beat_items: List[Any] = []
    dialogues: Any = None

    if _is_shot_like(source):
        frame_items.extend(list(_get(source, "actions") or []))
        beat_items.extend(list(_get(source, "beats") or []))
        if duration_frames is None:
            duration_frames = int(_get(source, "duration_frames") or 0)
        if not shot_id:
            shot_id = str(_get(source, "shot_id") or "")
        dialogues = _get(source, "dialogues")
    else:
        if isinstance(source, dict) and (_is_action_like(source)
                                         or _is_beat_like(source)):
            source = [source]
        for item in source or []:
            if _is_beat_like(item):
                beat_items.append(item)
            elif _is_action_like(item):
                frame_items.append(item)

    if beat_items:
        if duration_frames is None:
            raise ValueError(
                "layer_occupancy：输入含拍点（ShotBeat）时必须给出 "
                "duration_frames，否则无法把归一化时机 t 换算成帧号")
        shim = SimpleNamespace(
            beats=list(beat_items),
            duration_frames=int(duration_frames),
            shot_id=str(shot_id),
            dialogues=list(dialogues or []) if dialogues is not None else [],
        )
        compiled, _problems = compile_beats(
            shim, anchors=anchors, cast=cast,
            current_positions=current_positions)
        frame_items = list(compiled) + frame_items

    buckets: Dict[str, List[Tuple[int, int, str]]] = {}
    for item in frame_items:
        action_type = str(_get(item, "action_type") or "").strip()
        if not action_type:
            continue
        start, end = _action_window(item, fps)
        owner = _owner_of(item, action_type)
        for layer in _layers_of(action_type):
            buckets.setdefault(layer, []).append((start, end, owner))

    ordered: Dict[str, List[Tuple[int, int, str]]] = {}
    for layer in ALL_LAYERS:
        if layer in buckets:
            ordered[layer] = _sort_intervals(buckets[layer])
    for layer in sorted(set(buckets) - set(ALL_LAYERS)):
        ordered[layer] = _sort_intervals(buckets[layer])
    return ordered


def _owner_matches(owner: str, character_id: str) -> bool:
    return owner == character_id or owner.startswith(character_id + ":")


def render_occupancy_table(occupancy: Any,
                           character_id: Optional[str] = None) -> str:
    """占用表 → 紧凑结构化文本（每行一个占用区间，帧号为整数，非散文）。

    格式：``{层}: {start}-{end} {占用者描述}``；层与区间顺序 = 输入字典
    顺序（``layer_occupancy`` 已保证确定性）。空表或过滤后为空 → 空串。
    ``character_id`` 给定时只保留该角色的行（按占用者前缀精确匹配）。
    """
    filter_id = str(character_id or "").strip()
    lines: List[str] = []
    for layer, intervals in (occupancy or {}).items():
        for start, end, owner in intervals:
            if filter_id and not _owner_matches(str(owner), filter_id):
                continue
            lines.append(f"{layer}: {int(start)}-{int(end)} {owner}")
    return "\n".join(lines)


__all__ = ["layer_occupancy", "render_occupancy_table"]
