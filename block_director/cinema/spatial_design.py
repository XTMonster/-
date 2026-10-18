"""前向空间设计快照转换器（Ticket 02，纯层，不 import bpy）。

在阶段 S 理解剧本之后、规划与建模之前，把 ``SceneBrief`` 的散文语义
（``space[]`` / ``environment[]`` / ``gaze[]`` / ``props[]``）与计划意图
（角色站位 / 动作 / 机位声明）确定性转换成一版**版本化空间设计快照**：

* ``characters[]``：position / rotation / motion / gaze / facing，逐镜变化
  存进 ``motion_by_shot`` / ``gaze_by_shot``；
* ``props[]``：id / kind / position / rotation / motion / owner / parent；
* ``anchors[]``：label -> 世界坐标（relation 锚点走
  :func:`block_director.cinema.staging.solve_anchor_positions`；只有
  direction+distance 的用场景中心确定性锚定）；解不出如实标
  ``resolved=False`` ＋ ``unresolved_reason``，不伪造精确解；
* ``camera_intents[]``：逐镜 position / target / lens / fov_deg，
  来自 :func:`block_director.cinema.framing.solve_framing`。

坐标纪律：**一切坐标可追溯**，来源四态沿观测契约
（``script_declaration`` / ``plan_intent`` / ``algorithmic_measurement`` /
``blender_geometry``）；设计层只允许前三态，实测层才是
``blender_geometry``。确定性：同一输入两次构建逐位一致。
"""

from __future__ import annotations

import math
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .framing import SENSOR_WIDTH, solve_framing
from .staging import solve_anchor_positions

#: 快照版本（契约演进时逐代升，consumers 用它做迁移）。
DESIGN_SNAPSHOT_SCHEMA = "spatial-design-snapshot/v1"

#: environment[] 的 direction 闭集 -> 世界方向向量（相对场景中心，XY 平面）。
#: 与 `contracts/brief.py::SPACE_DIRECTIONS` 对齐；合法值=front/back/left/right/
#: above/ground，非法值走 unresolved（不猜）。
DIRECTION_VECTORS: Dict[str, Tuple[float, float, float]] = {
    "front": (0.0, 1.0, 0.0),
    "back": (0.0, -1.0, 0.0),
    "left": (-1.0, 0.0, 0.0),
    "right": (1.0, 0.0, 0.0),
    "above": (0.0, 0.0, 1.0),
    "ground": (0.0, 0.0, -1.0),
}

#: environment[] 的 distance 档 -> 米（near/mid/far，确定性设计默认）。
#: 与 `contracts/brief.py::SPACE_DISTANCES` 对齐；档位归一为设计距离，
#: 记进 provenance 与 notes，可被后续实测覆盖。
DISTANCE_METERS: Dict[str, float] = {"near": 2.0, "mid": 6.0, "far": 12.0}

#: 动作类型 -> 速度档（m/s，设计意图；mark 走位档，不做物理仿真）。
ACTION_SPEED: Dict[str, float] = {"walk_to": 1.0, "run_to": 3.0}

#: 角色默认 facing（+Y；无声明时不猜朝向，取引擎默认）。
DEFAULT_FACING: Tuple[float, float, float] = (0.0, 1.0, 0.0)


def _norm_input(value: Any) -> Any:
    """把 dataclass / dict / 其他统一成 dict 或原样。

    转换器同时接受 ``SceneBrief``/``ShotPlan``/``Plan``（dataclass）与它们的
    dict 形状，避免调用方被迫预转换。
    """
    if is_dataclass(value) and not isinstance(value, type):
        try:
            return asdict(value)
        except Exception:  # noqa: BLE001 - dataclass 异常形状也不致命
            return value
    return value


def _as_dict(item: Any) -> Dict[str, Any]:
    if isinstance(item, Mapping):
        return dict(item)
    return dict(_norm_input(item) or {})


def _shots(plan: Any) -> List[Dict[str, Any]]:
    """把 plan 归一成逐镜 dict 列表（Plan.shots[] 或单镜 ShotPlan）。"""
    norm = _norm_input(plan)
    if isinstance(norm, Mapping):
        shots = norm.get("shots")
        if isinstance(shots, list) and shots:
            return [_as_dict(shot) for shot in shots]
        if norm.get("shot_id"):
            return [_as_dict(norm)]
    return []


def _brief_dict(brief: Any) -> Dict[str, Any]:
    norm = _norm_input(brief)
    if not isinstance(norm, Mapping):
        return {}
    return dict(norm)


def _vec(value: Any) -> Tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        return (0.0, 0.0, 0.0)
    return (float(value[0]), float(value[1]), float(value[2]))


def _normalize(v: Sequence[float]) -> Tuple[float, float, float]:
    length = math.sqrt(sum(float(c) * float(c) for c in v[:3]))
    if length < 1e-9:
        return (0.0, 0.0, 0.0)
    return (float(v[0]) / length, float(v[1]) / length, float(v[2]) / length)


def _unit(position: Tuple[float, float, float]) -> Dict[str, Any]:
    return {"position": "m", "rotation": "rad", "angle": "deg",
            "speed": "m/s"}


def _character_entry(name: str, position: Sequence[float],
                     provenance: str) -> Dict[str, Any]:
    pos = _vec(position)
    return {
        "name": str(name),
        "position": {"x": pos[0], "y": pos[1], "z": pos[2]},
        "rotation": None,          # 设计层无真实旋转；实测层才回读
        "facing": list(DEFAULT_FACING),
        "motion": None,            # 单镜便捷视图（有走位时填充）
        "gaze": None,              # 单镜便捷视图（有视线时填充）
        "motion_by_shot": [],
        "gaze_by_shot": [],
        "provenance": provenance,
        "unit": _unit(pos),
    }


def _gaze_direction(from_pos: Sequence[float],
                    target_pos: Sequence[float]) -> List[float]:
    fx, fy, fz = _vec(from_pos)
    tx, ty, tz = _vec(target_pos)
    dx, dy, dz = tx - fx, ty - fy, tz - fz
    norm = math.sqrt(dx * dx + dy * dy + dz * dz)
    if norm < 1e-9:
        return []
    return [round(dx / norm, 4), round(dy / norm, 4), round(dz / norm, 4)]


def _resolve_gaze(gaze_raw: Any, cast_positions: Mapping[str, Sequence[float]],
                  anchor_positions: Mapping[str, Sequence[float]],
                  ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """从 brief/plan 的 gaze 项解析 {target_id + direction}。

    目标位置已知（角色站位或锚点）-> 方向向量由两点几何算出；
    目标位置未知 -> target_id 保留、direction=None，不猜。
    """
    if not isinstance(gaze_raw, Mapping):
        return None, None
    target = str(gaze_raw.get("to") or "")
    if not target:
        return None, None
    target_pos = cast_positions.get(target) or anchor_positions.get(target)
    direction: Optional[List[float]] = None
    if target_pos is not None:
        direction = _gaze_direction(cast_positions.get(
            str(gaze_raw.get("from") or ""), (0.0, 0.0, 0.0)), target_pos)
    return {"target_id": target, "direction": direction or None}, target


def _motion_from_actions(actions: Sequence[Any],
                         cast_positions: Mapping[str, Sequence[float]],
                         name: str) -> Optional[Dict[str, Any]]:
    """该镜 walk_to/run_to -> motion（起点/终点/速度档）。"""
    for raw in actions or []:
        action = _as_dict(raw)
        if str(action.get("character_id") or "") != name:
            continue
        action_type = str(action.get("action_type") or "")
        if action_type not in ACTION_SPEED:
            continue
        params = _as_dict(action.get("params") or {})
        target = params.get("target_position")
        if target is None and isinstance(action.get("target_position"), list):
            target = action["target_position"]
        if not isinstance(target, (list, tuple)) or len(target) < 2:
            continue
        start = cast_positions.get(name, (0.0, 0.0, 0.0))
        return {
            "start": list(_vec(start)),
            "end": [float(target[0]), float(target[1]), float(target[2])],
            "speed_m_s": ACTION_SPEED[action_type],
            "provenance": "plan_intent",
        }
    return None


def _anchor_from_environment(item: Mapping[str, Any],
                             cast_positions: Mapping[str, Sequence[float]],
                             aliases: Mapping[str, str],
                             solved: Mapping[str, Sequence[float]],
                             notes: List[str]) -> Dict[str, Any]:
    label = str(item.get("label") or "")
    explicit = item.get("position")
    relation = str(item.get("relation") or "")
    direction = str(item.get("direction") or "")
    distance = str(item.get("distance") or "")
    # 1) 显式坐标（剧本/上游直接给）——script_declaration，最可信
    if isinstance(explicit, (list, tuple)) and len(explicit) >= 2:
        return {
            "label": label, "position": list(_vec(explicit)),
            "provenance": "script_declaration", "resolved": True,
            "unit": {"position": "m"},
        }
    # 2) relation 锚点 -> 锚点求解器（behind/between/left_of/right_of，相对角色）
    if relation:
        positions, problems = solve_anchor_positions(
            [{"name": label, "relation": relation}],
            cast_positions={k: {"position": v} for k, v in cast_positions.items()},
            aliases=aliases)
        if positions.get(label) is not None:
            return {
                "label": label, "position": positions[label],
                "provenance": "algorithmic_measurement", "resolved": True,
                "unit": {"position": "m"},
            }
        for problem in problems:
            notes.append(f"锚点 {label}: {problem.get('reason', '解析不出')}")
        return {
            "label": label, "position": None,
            "provenance": "plan_intent", "resolved": False,
            "unresolved_reason": "; ".join(str(p.get("reason") or "")
                                           for p in problems) or "解析不出",
        }
    # 3) direction + distance：场景中心确定性锚定（算法性，非模型猜）
    if direction in DIRECTION_VECTORS and distance in DISTANCE_METERS:
        dx, dy, dz = DIRECTION_VECTORS[direction]
        meters = DISTANCE_METERS[distance]
        return {
            "label": label,
            "position": [round(dx * meters, 4), round(dy * meters, 4),
                         round(dz * meters, 4)],
            "provenance": "algorithmic_measurement", "resolved": True,
            "note": f"场景中心锚定（{direction} {distance}={meters}m）",
            "unit": {"position": "m"},
        }
    # 4) 非法/缺失语义：如实 unresolved，不猜
    reason = ("direction 非法" if direction and direction not in DIRECTION_VECTORS
              else "distance 非法" if distance and distance not in DISTANCE_METERS
              else "缺 position/relation/direction")
    notes.append(f"锚点 {label}: {reason}")
    return {
        "label": label, "position": None,
        "provenance": "plan_intent", "resolved": False,
        "unresolved_reason": reason,
    }


def _camera_intent(shot: Dict[str, Any], cast_positions: Mapping[str, Sequence[float]]
                   ) -> Optional[Dict[str, Any]]:
    shot_id = str(shot.get("shot_id") or "")
    if not shot_id:
        return None
    characters = shot.get("characters") or []
    subject_pos = (cast_positions.get(str(characters[0]))
                   if characters else None) or (0.0, 0.0, 0.0)
    camera = _as_dict(shot.get("camera") or {})
    side = str(camera.get("side") or "front")
    lens = camera.get("lens")
    shot_type = str(shot.get("shot_type") or "MS")
    try:
        result = solve_framing(
            subject_pos=subject_pos, facing=DEFAULT_FACING,
            shot_type=shot_type, side=side,
            lens=float(lens) if lens else None)
    except Exception as exc:  # noqa: BLE001 - 记 note，不给假机位
        return {
            "shot_id": shot_id, "position": None, "target": None,
            "lens": None, "fov_deg": None,
            "provenance": "plan_intent", "resolved": False,
            "unresolved_reason": f"机位求解失败：{exc}",
        }
    fov_deg = math.degrees(2.0 * math.atan(SENSOR_WIDTH / (2.0 * result.lens)))
    return {
        "shot_id": shot_id,
        "position": list(result.position),
        "target": list(result.target),
        "lens": round(result.lens, 4),
        "fov_deg": round(fov_deg, 4),
        "provenance": "algorithmic_measurement", "resolved": True,
        "unit": {"position": "m", "lens": "mm", "fov": "deg"},
    }


def build_design_snapshot(*, brief: Any, plan: Any,
                          cast_positions: Optional[Mapping[str, Sequence[float]]] = None,
                          scene_id: str = "",
                          ) -> Dict[str, Any]:
    """构建前向空间设计快照（确定性、可追溯、版本化）。

    ``brief`` 接受 ``SceneBrief`` 或 dict；``plan`` 接受 ``Plan``（多个
    ``shot``）或单镜 ``ShotPlan``/dict；``cast_positions`` 是角色站位声明
    （``plan_intent`` 源：initial_location）。坐标只来自声明/意图/求解器，
    一律不脑补。
    """
    briefd = _brief_dict(brief)
    shot_list = _shots(plan)
    cast = {str(k): list(_vec(v)) for k, v in (cast_positions or {}).items()}
    notes: List[str] = []

    # 1) 场级角色清单（并集，按首见稳定排序）
    character_names: List[str] = []
    for shot in shot_list:
        for name in (shot.get("characters") or []):
            if str(name) not in character_names:
                character_names.append(str(name))

    # 2) 锚点（brief.environment[] 与显式 anchors 并集）
    anchors: List[Dict[str, Any]] = []
    for raw in (briefd.get("environment") or []) + (briefd.get("anchors") or []):
        item = _as_dict(raw)
        anchors.append(_anchor_from_environment(
            item, cast, aliases={}, solved={}, notes=notes))
    anchor_positions = {
        str(a["label"]): a["position"] for a in anchors
        if a.get("resolved") and a.get("position") is not None}

    # 3) 角色条目（站位 + 逐镜 motion/gaze）
    characters: List[Dict[str, Any]] = []
    for name in character_names:
        entry = _character_entry(name, cast.get(name, (0.0, 0.0, 0.0)),
                                 "plan_intent")
        if name not in cast:
            entry["position"] = None
            entry["provenance"] = "plan_intent"
            notes.append(f"角色 {name} 在计划里但无站位声明，未落坐标（不猜）")
        for shot in shot_list:
            shot_id = str(shot.get("shot_id") or "")
            if name not in (shot.get("characters") or []):
                continue
            motion = _motion_from_actions(shot.get("actions") or [],
                                          cast, name)
            if motion is not None:
                entry.setdefault("motion_by_shot", []).append(
                    {"shot_id": shot_id, **motion})
                if entry["motion"] is None:
                    entry["motion"] = dict(motion)
            gaze_items = (shot.get("gaze") or []) + (briefd.get("gaze") or [])
            for raw_gaze in gaze_items:
                gz = _as_dict(raw_gaze)
                if str(gz.get("from") or "") != name:
                    continue
                resolved, _ = _resolve_gaze(gz, cast, anchor_positions)
                if resolved is not None:
                    entry.setdefault("gaze_by_shot", []).append(
                        {"shot_id": shot_id, **resolved})
                    if entry["gaze"] is None:
                        entry["gaze"] = dict(resolved)
        characters.append(entry)

    # 4) 物品（brief.props[]；位置缺省留痕，不猜）
    props: List[Dict[str, Any]] = []
    for raw in briefd.get("props") or []:
        item = _as_dict(raw)
        pid = str(item.get("id") or "")
        props.append({
            "id": pid,
            "kind": str(item.get("kind") or ""),
            "owner": str(item.get("owner") or "") or None,
            "parent": item.get("parent"),
            "position": None,
            "rotation": None,
            "motion": None,
            "provenance": "plan_intent",
            "unit": _unit((0.0, 0.0, 0.0)),
        })
        if pid and item.get("position") is None:
            notes.append(f"物品 {pid} 无位置声明，未落坐标（不猜）")

    # 5) 逐镜机位设计
    camera_intents = [intent for intent in
                      (_camera_intent(shot, cast) for shot in shot_list)
                      if intent is not None]

    return {
        "schema_version": DESIGN_SNAPSHOT_SCHEMA,
        "scene_id": str(scene_id),
        "characters": characters,
        "props": props,
        "anchors": anchors,
        "camera_intents": camera_intents,
        "notes": notes,
    }


__all__ = ["build_design_snapshot", "DESIGN_SNAPSHOT_SCHEMA",
           "DIRECTION_VECTORS", "DISTANCE_METERS"]
