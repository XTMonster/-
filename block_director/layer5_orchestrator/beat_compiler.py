"""拍点表 → 现有 ``actions[]`` 的确定性编译（执行文档 v1.5 TDD §4.1/§4.2）。

拍点表（``ShotBeat``）是**语义层**：归一化时机 ``t``、有限动词表、目标锚点。
``actions[]`` 是**执行层**：绝对帧号 ＋ 坐标 ＋ 参数。这一层负责把前者换成
后者，**并且只做这一件事**：

* ``t → 帧``：``start_frame = max(1, round(t × duration_frames))``，``end_frame``
  由动词时长表给（走位按距离估，固定类动作用表里的定值）；
* ``face_to → look_at``：把"看向谁/看向哪边"折算成头部偏角（几何来自
  ``motion/model.py::head_track_angles``，不另抄公式）；
* ``enter_from``/``exit_frame`` → ``walk_to``（起点/终点在画外锚点）；
* ``place_prop``/``pick_up``/``hand_to`` 原样落地（角色那一侧由
  ``motion/model.py::expand`` 演，道具那一侧由构建器写关键帧，见 TDD §4.4）。

三条纪律（都是本项目付过代价的那几条）：

1. **纯函数、零 bpy**（红线 R-1）——编译要能在 pytest 里逐条断言。
2. **不猜**：锚点/目标解析不出来就记 ``problems``，不编坐标（"不猜代词"的
   同一条纪律，见 ``SceneBrief``）。
3. **输出形状与现有 ``actions[]`` 逐字段兼容**——``shot_builder`` /
   ``rule_checker`` / ``R003`` 一行都不用改。
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ..contracts.beats import BEAT_VERBS, MAX_BEATS, ShotBeat
from ..motion.model import (
    ENTRANCE_ACTIONS,
    LAYER_HEAD,
    LAYER_OF,
    PROP_ACTIONS,
    head_track_angles,
)

#: 动词 → 缺省帧长（**设计表：调表不动结构**）。
#: 走位类不走这张表（按距离估，见 :func:`_walk_frames`）。
BEAT_DURATION_TABLE: Dict[str, int] = {
    "turn_body": 18, "jump": 18, "body_tilt": 15, "fall_down": 30,
    "sit": 24, "stand": 24,
    "look_at": 12, "turn_head": 12, "nod": 12, "shake_head": 12,
    "place_prop": 18, "pick_up": 18, "hand_to": 18,
}

#: 走位的**米/帧**（与 ``config.animation.walk_speed`` 的缺省值同源；
#: 只在"按距离估时长"这一处使用，不参与任何验收判据）。
WALK_METRES_PER_FRAME = 0.05

#: 走位时长的上下限（帧）：太短不像走，太长会吃掉整镜。
WALK_MIN_FRAMES = 12

#: ``pace`` → 引擎速度词表的折叠（引擎只有 walk/run 两档，见
#: ``motion/model.py::_SPEED_RATE``）。映射是**设计表**，不是判据。
PACE_TO_SPEED: Dict[str, str] = {"slow": "walk", "normal": "walk",
                                 "brisk": "run"}

#: ``face_to`` 里那几个**屏幕方向**的取值：它们没有世界坐标，折算成
#: ``look_at`` 的固定偏角（正 = 向画面右侧偏）。
FACE_TO_SCREEN_YAW: Dict[str, float] = {
    "screen_right": 30.0, "screen_left": -30.0,
}


def _as_xyz(value: Any) -> Optional[Tuple[float, float, float]]:
    """把"位置"容忍地读成三元组；读不出来返回 ``None``（**不猜**）。"""
    if value is None:
        return None
    if isinstance(value, dict):
        for key in ("position", "location", "initial_location"):
            if key in value:
                return _as_xyz(value[key])
        return None
    try:
        values = [float(item) for item in value]
    except (TypeError, ValueError):
        return None
    if len(values) < 2:
        return None
    while len(values) < 3:
        values.append(0.0)
    return (values[0], values[1], values[2])


def _catalogue(cast: Any) -> Dict[str, Tuple[float, float, float]]:
    """``cast`` → ``{character_id: 位置}``（容忍 dict / CastMember / 序列）。"""
    out: Dict[str, Tuple[float, float, float]] = {}
    if cast is None:
        return out
    if isinstance(cast, dict):
        items = cast.items()
    else:
        items = []
        for member in cast:
            character_id = str(getattr(member, "id", "") or "")
            if character_id:
                items.append((character_id, member))
    for key, value in items:
        position = _as_xyz(value)
        if position is not None:
            out[str(key)] = position
    return out


def _facing_catalogue(cast: Any) -> Dict[str, Tuple[float, float]]:
    out: Dict[str, Tuple[float, float]] = {}
    members: Sequence[Any]
    if isinstance(cast, dict):
        members = list(cast.values())
        keys = list(cast.keys())
    else:
        members = list(cast or [])
        keys = [str(getattr(m, "id", "") or "") for m in members]
    for key, member in zip(keys, members):
        raw = None
        if isinstance(member, dict):
            raw = member.get("facing") or member.get("initial_facing")
        else:
            raw = getattr(member, "initial_facing", None)
        if raw is None:
            continue
        try:
            values = [float(item) for item in raw]
        except (TypeError, ValueError):
            continue
        if len(values) >= 2:
            out[str(key)] = (values[0], values[1])
    return out


def _anchor_catalogue(anchors: Any) -> Dict[str, Tuple[float, float, float]]:
    """``anchors`` → ``{名字: 位置}``（dict / ``SDLAnchor`` 序列都认）。"""
    out: Dict[str, Tuple[float, float, float]] = {}
    if anchors is None:
        return out
    if isinstance(anchors, dict):
        for key, value in anchors.items():
            position = _as_xyz(value)
            if position is not None:
                out[str(key)] = position
        return out
    for anchor in anchors:
        name = str(getattr(anchor, "name", "") or "")
        if not name:
            continue
        position = _as_xyz(getattr(anchor, "position", None))
        if position is not None:
            out[name] = position
    return out


def _walk_frames(distance: float) -> int:
    frames = int(round(float(distance) / WALK_METRES_PER_FRAME))
    return max(frames, WALK_MIN_FRAMES)


def _duration_for(verb: str, start: int, end: int, span: int,
                  distance: float = 0.0) -> int:
    """动词在本镜里占几帧（走位按距离，其余查表），最后夹进镜内。"""
    if verb in ("walk_to", "run_to", "enter_from", "exit_frame"):
        frames = _walk_frames(distance)
    else:
        frames = int(BEAT_DURATION_TABLE.get(verb, 12))
    return max(min(int(frames), max(span - start + 1, 1)), 1)


def compile_beats(shot, anchors: Any = None, cast: Any = None,
                  *, current_positions: Any = None
                  ) -> Tuple[List[Dict[str, Any]], List[str]]:
    """把 ``shot.beats`` 编译成 ``actions[]``，返回 ``(actions, problems)``。

    ``anchors`` 是**已解算好的锚点坐标**（``{名: (x,y,z)}`` 或
    ``SDLAnchor`` 序列）；``cast`` 是角色位置表（``{id: 位置}`` 或
    ``CastMember`` 序列）。``current_positions`` 覆盖 ``cast`` 的位置——
    "这一镜开始时人实际站在哪"（§六十四 的起点接力），构建期会传它。
    """
    problems: List[str] = []
    beats = _coerce(shot)
    if not beats:
        return [], problems

    duration = max(int(getattr(shot, "duration_frames", 0) or 0), 1)
    shot_id = str(getattr(shot, "shot_id", "") or "")
    anchor_pos = _anchor_catalogue(anchors)
    cast_pos = _catalogue(cast)
    cast_pos.update({str(k): v for k, v in
                     _catalogue(current_positions).items()})
    facings = _facing_catalogue(cast)

    actions: List[Dict[str, Any]] = []
    for index, beat in enumerate(beats, start=1):
        where = f"{shot_id} 第 {index} 个拍点"
        if beat.verb not in BEAT_VERBS:
            problems.append(f"{where}：verb={beat.verb!r} 不在动词闭集内，已跳过")
            continue
        subject = str(beat.subject or "")
        if not subject:
            problems.append(f"{where}：缺少 subject，已跳过")
            continue
        start = max(1, int(round(float(beat.t) * duration)))
        distance = 0.0
        params: Dict[str, Any] = {}

        if beat.verb in ("walk_to", "run_to") + ENTRANCE_ACTIONS:
            destination, source, why = _resolve_walk(beat, anchor_pos, cast_pos,
                                                     subject)
            if why:
                problems.append(f"{where}：{why}")
                if destination is None:
                    continue
            if source is None:
                source = cast_pos.get(subject, (0.0, 0.0, 0.0))
            distance = math.hypot(destination[0] - source[0],
                                  destination[1] - source[1])
            params["from"] = list(source)
            params["target_position"] = list(destination)
            params["speed"] = PACE_TO_SPEED.get(str(beat.pace or "normal"),
                                                "walk")
        elif beat.verb in PROP_ACTIONS:
            prop = str(beat.target or "")
            if prop:
                params["prop"] = prop
            elif beat.react:
                params["prop"] = str(beat.react)

        frames = _duration_for(beat.verb, start, start, duration, distance)
        end = min(start + frames - 1, duration)
        #: `face_to` 折算：角色 id → 用两人的真实位置算头部偏角（几何来自
        #: `motion/model.py::head_track_angles`，单一真源）；屏幕方向 → 固定偏角。
        look = _look_at_params(beat, subject, cast_pos, facings, problems, where)
        head_verb = LAYER_OF.get(beat.verb) == LAYER_HEAD
        if look is not None and beat.verb == "look_at":
            #: 动词本身就是 look_at：`face_to` 是它的**参数**，不是第二条动作
            #: （否则同一条头层动作会被排两次，§9.7 的串行当场报重叠）。
            params = dict(look)
        elif look is not None and head_verb:
            #: 头层动词（turn_head/nod/shake_head）带 `face_to`：头层一次只能有
            #: 一条动作，所以把"看向"排在它**之后**（先点头、再转头），而**不是**
            #: 叠在同一段帧上由串行器去错开（那会多报一条重叠）。
            look_start = min(end + 1, duration)
            look_end = min(look_start + int(BEAT_DURATION_TABLE["look_at"]) - 1,
                           duration)
            actions.append({"character_id": subject, "action_type": "look_at",
                            "start_frame": look_start, "end_frame": look_end,
                            "params": dict(look)})
        elif look is not None:
            #: 非头层动词（走位/坐下/交互）带 `face_to`：那是**另一层**的轨道，
            #: 与身体动作同时发生是合法的（§9.6 的分层并行）。
            actions.append({"character_id": subject, "action_type": "look_at",
                            "start_frame": start, "end_frame": end,
                            "params": dict(look)})
        action_type = "walk_to" if beat.verb in ENTRANCE_ACTIONS else beat.verb
        if beat.verb in ("walk_to", "run_to") or beat.verb in ENTRANCE_ACTIONS:
            entry: Dict[str, Any] = {
                "character_id": subject, "action_type": action_type,
                "start_frame": start, "end_frame": end,
                "params": params,
            }
        else:
            entry = {"character_id": subject, "action_type": action_type,
                     "start_frame": start, "end_frame": end}
            if params:
                entry["params"] = params
        actions.append(entry)

    #: **同 subject 串行**（§9.7）：同层动作不得时间重叠；这里按帧排序后
    #: 把被压住的窗口往后推，留痕说明（不丢拍点）。
    actions = _serialise_same_subject(actions, duration, problems, shot_id)
    problems.extend(_dialogue_window_findings(shot, actions))
    return actions, problems


def _coerce(shot) -> List[ShotBeat]:
    raw = getattr(shot, "beats", None) or []
    out: List[ShotBeat] = []
    for item in list(raw)[:MAX_BEATS]:
        if isinstance(item, ShotBeat):
            out.append(item)
        elif isinstance(item, dict):
            out.append(ShotBeat.from_dict(item))
    return sorted(out, key=lambda beat: (float(beat.t), beat.subject, beat.verb))


def _resolve_walk(beat: ShotBeat, anchors, cast_pos, subject):
    """走位的 ``(终点, 起点, 说明)``。解析不出就 ``(None, None, 原因)``。"""
    verb = beat.verb
    target = str(beat.target or "")
    destination: Optional[Tuple[float, float, float]] = None
    if target:
        if target in anchors:
            destination = anchors[target]
        elif target in cast_pos:
            destination = cast_pos[target]
        else:
            return (None, None,
                    f"target={target!r} 既不在锚点表也不在角色表里，"
                    f"不猜坐标，已跳过这个拍点")
    else:
        #: 没有目标 = 不想动。用当前位置当终点（**不猜目的地**）。
        destination = cast_pos.get(subject)
        if destination is None:
            return (None, None, "既没有 target、角色位置也未知，已跳过这个拍点")

    source: Optional[Tuple[float, float, float]] = None
    if verb == "enter_from":
        #: 入场：起点在画外锚点（有具名锚点就用它）；没有就用当前位置——
        #: 那是"原地不动"，不会把人瞬移到编出来的坐标上。
        source = destination if target and target in anchors else None
        if source is not None:
            source = anchors[target]
    elif verb == "exit_frame":
        #: 出场：终点在画外锚点（target）；起点 = 角色当前位置（起点接力）。
        source = cast_pos.get(subject)
    else:
        source = None                    # walk_to/run_to：起点由调用方接力
    return (destination, source, "")


def _look_at_params(beat: ShotBeat, subject: str, cast_pos, facings,
                    problems: List[str],
                    where: str) -> Optional[Dict[str, Any]]:
    face_to = str(beat.face_to or "")
    if not face_to:
        return None
    if face_to in FACE_TO_SCREEN_YAW:
        return {"yaw_deg": FACE_TO_SCREEN_YAW[face_to], "pitch_deg": 0.0}
    if face_to == "camera":
        return {"yaw_deg": 0.0, "pitch_deg": 0.0}
    if face_to == "away":
        return {"yaw_deg": 90.0, "pitch_deg": 0.0}
    origin = cast_pos.get(subject)
    target = cast_pos.get(face_to)
    if origin is None or target is None:
        problems.append(
            f"{where}：face_to={face_to!r} 的位置未知（缺角色位置），"
            f"不猜朝向，只落地动作不落地视线")
        return None
    facing = facings.get(subject, (0.0, 1.0))
    yaw, pitch, note = head_track_angles(origin, facing, target)
    if note:
        problems.append(f"{where}：{note}")
    return {"yaw_deg": float(yaw), "pitch_deg": float(pitch)}


def _serialise_same_subject(actions: List[Dict[str, Any]], duration: int,
                            problems: List[str], shot_id: str
                            ) -> List[Dict[str, Any]]:
    """同 subject 的动作按起始帧串行：重叠就把后者整体后移（不丢拍点）。"""
    by_subject: Dict[str, List[Dict[str, Any]]] = {}
    for action in actions:
        by_subject.setdefault(str(action.get("character_id") or ""),
                              []).append(action)
    out: List[Dict[str, Any]] = list(actions)
    for subject, entries in by_subject.items():
        ordered = sorted(entries, key=lambda item: (int(item.get("start_frame", 1)),
                                                    int(item.get("end_frame", 1))))
        cursor = 0
        for action in ordered:
            start = int(action.get("start_frame", 1))
            end = int(action.get("end_frame", start))
            if cursor and start <= cursor:
                shift = cursor + 1 - start
                new_start = start + shift
                new_end = end + shift
                if new_start > duration:
                    problems.append(
                        f"{shot_id}：{subject} 的同层动作已排满整镜，"
                        f"第 {new_start} 帧起的动作落不进镜头，原样保留由规则报出")
                    new_start, new_end = start, end
                else:
                    problems.append(
                        f"{shot_id}：{subject} 的同层动作时间重叠，"
                        f"已把 {start}–{end} 后移到 {new_start}–{new_end}（§9.7 串行）")
                    action["start_frame"] = new_start
                    action["end_frame"] = min(new_end, duration)
                cursor = min(max(new_end, int(action.get("end_frame", end))),
                             duration)
            else:
                cursor = end
    return out


def _dialogue_window_findings(shot, actions: Sequence[Dict[str, Any]]
                              ) -> List[str]:
    """对白优先（§4.1）：**整段盖住**说话人对白窗的拍点要如实报出。

    口径沿用 `dialogue_budget`：对白窗 = 该句的 ``start_frame``–``end_frame``
    （缺失时按"整镜"算，保守）。判据是"拍点窗口**完整包含**对白窗口"——
    只压住一半不算（那可能正是"边说话边抬手"的合法表演）。
    """
    problems: List[str] = []
    shot_id = str(getattr(shot, "shot_id", "") or "")
    windows: Dict[str, List[Tuple[int, int]]] = {}
    for dialogue in getattr(shot, "dialogues", None) or []:
        if not isinstance(dialogue, dict):
            continue
        speaker = str(dialogue.get("character_id") or "")
        if not speaker:
            continue
        start = int(dialogue.get("start_frame") or 1)
        end = int(dialogue.get("end_frame")
                  or getattr(shot, "duration_frames", 0) or start)
        if end < start:
            continue
        windows.setdefault(speaker, []).append((start, end))
    for action in actions:
        subject = str(action.get("character_id") or "")
        start = int(action.get("start_frame") or 1)
        end = int(action.get("end_frame") or start)
        for window_start, window_end in windows.get(subject, []):
            if start <= window_start and end >= window_end:
                problems.append(
                    f"{shot_id}：{subject} 的 {action.get('action_type')} "
                    f"（{start}–{end}）整段盖住了它的对白窗"
                    f"（{window_start}–{window_end}）——对白优先，请错开")
    return problems


def merge_with_actions(compiled: Sequence[Dict[str, Any]],
                       written: Sequence[Dict[str, Any]], *,
                       overlap_ratio: float = 0.5
                       ) -> List[Dict[str, Any]]:
    """TDD §4.2：同镜同时有拍点编译结果与直写 ``actions`` 时的合并。

    判据：**同 subject 同动词、帧窗重叠 > ``overlap_ratio``** 视为重复，
    **编译结果优先**（它是语义层）；其余直写动作原样保留。输出顺序 =
    编译结果在前、保留下来的直写动作在后（确定性）。
    """
    kept: List[Dict[str, Any]] = [dict(item) for item in (compiled or [])]
    for candidate in (written or []):
        if not isinstance(candidate, dict):
            continue
        if any(_is_duplicate(candidate, existing, overlap_ratio)
               for existing in kept):
            continue
        kept.append(dict(candidate))
    return kept


def _is_duplicate(a: Dict[str, Any], b: Dict[str, Any],
                  overlap_ratio: float) -> bool:
    if str(a.get("character_id") or "") != str(b.get("character_id") or ""):
        return False
    if str(a.get("action_type") or "") != str(b.get("action_type") or ""):
        return False
    a_start, a_end = int(a.get("start_frame") or 1), int(a.get("end_frame") or 1)
    b_start, b_end = int(b.get("start_frame") or 1), int(b.get("end_frame") or 1)
    overlap = min(a_end, b_end) - max(a_start, b_start) + 1
    if overlap <= 0:
        return False
    shorter = max(min(a_end - a_start + 1, b_end - b_start + 1), 1)
    return overlap / shorter > float(overlap_ratio)


def compiled_verb_set(beats: Iterable[Any]) -> List[str]:
    """拍点表里出现过的动词（按序去重）——给提示词/审计看"这一镜要演什么"。"""
    out: List[str] = []
    for beat in _coerce_beats(beats):
        if beat.verb and beat.verb not in out:
            out.append(beat.verb)
    return out


def _coerce_beats(beats: Iterable[Any]) -> List[ShotBeat]:
    out: List[ShotBeat] = []
    for item in beats or []:
        if isinstance(item, ShotBeat):
            out.append(item)
        elif isinstance(item, dict):
            out.append(ShotBeat.from_dict(item))
    return out


__all__ = [
    "BEAT_DURATION_TABLE", "WALK_METRES_PER_FRAME", "WALK_MIN_FRAMES",
    "PACE_TO_SPEED", "FACE_TO_SCREEN_YAW",
    "compile_beats", "merge_with_actions", "compiled_verb_set",
]
