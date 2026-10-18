"""前向空间设计快照转换器（spatial-understanding-json Ticket 02；纯层，禁 bpy）。

在阶段 S（SceneBrief 散文语义）之后、规划与建模之前，把
``SceneBrief`` + ``Plan`` + ``cast``（剧组站位数据，可选）确定性转换成一版
版本化的「空间设计快照」（``contracts/spatial_snapshot.py::DesignSnapshot``）：

* 每个角色：position / rotation / motion / gaze / facing，逐镜一份；
* 每个剧本参与物品：position / rotation / motion / owner / parent / kind；
* 环境锚点：``label -> 世界坐标``，由 ``cinema/staging.solve_anchor_positions``
  程序解算（``algorithmic_measurement``）；
* 每镜机位设计值：position / target / lens / fov / rotation，由
  ``cinema/framing.solve_framing`` 求解（``algorithmic_measurement``）。

纪律：

* **坐标可追溯、不得脑补**：锚点=锚点求解器（``algorithmic_measurement``）；
  机位=framing 求解器（``algorithmic_measurement``）；角色/物品站位=计划动作
  或 cast（``plan_intent``）。解不出一律 ``None`` 并把字段名写进该条目的
  ``unresolved[]``——**不采用** ``solve_anchor_positions`` 的"未解析缺省环坐标"
  （那会让"未解析"看起来像设计值，破坏可追溯原则）；
* **确定性**：同一输入两次转换逐位一致（坐标 4 位小数、方向向量 4 位小数）；
* **空镜合法**：characters[]/props[] 为空 + camera_intents 有值，不报错。
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..cinema.framing import (
    ASPECT_16_9,
    SENSOR_WIDTH,
    solve_framing,
    vertical_fov,
)
from ..cinema.staging import solve_anchor_positions
from ..contracts.spatial_snapshot import (
    DESIGN_SNAPSHOT_SCHEMA,
    DIFF_THRESHOLDS,
    DesignSnapshot,
)

Vector3 = Tuple[float, float, float]

_MOTION_ACTIONS = frozenset({"walk_to", "run_to", "enter_from", "exit_frame"})


def _vec3(value: Any) -> Optional[Tuple[float, float, float]]:
    """长度 3 的可数向量；非法返回 ``None``（不猜）。"""
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    try:
        return (float(value[0]), float(value[1]), float(value[2]))
    except (TypeError, ValueError):
        return None


def _r3(value: Vector3) -> List[float]:
    return [round(float(item), 4) for item in value]


def _norm(value: Vector3) -> Optional[Vector3]:
    length = math.sqrt(sum(item * item for item in value))
    if length <= 1e-9:
        return None
    return tuple(item / length for item in value)


def _fv(value: Any, unit: str, provenance: str) -> Dict[str, Any]:
    return {"value": value, "unit": unit, "provenance": provenance}


def _cast_map(cast: Any) -> Dict[str, Dict[str, Any]]:
    """cast 输入归一为 ``{id: {"position", "facing"}}``（dict 或 CastMember 类）。"""
    out: Dict[str, Dict[str, Any]] = {}
    if isinstance(cast, Mapping):
        for cid, entry in cast.items():
            if isinstance(entry, Mapping):
                out[str(cid)] = {"position": entry.get("position"),
                                 "facing": entry.get("facing")}
    else:
        for member in cast or []:
            cid = str(getattr(member, "id", "") or getattr(member, "name", "")
                      or "")
            if not cid:
                continue
            location = getattr(member, "initial_location", None)
            facing = getattr(member, "initial_facing", None)
            out[cid] = {"position": list(location) if location else None,
                        "facing": list(facing) if facing else None}
    return out


def _position_of(cast_map: Mapping[str, Dict[str, Any]],
                 cid: str) -> Optional[Vector3]:
    entry = cast_map.get(cid)
    if not entry:
        return None
    return _vec3(entry.get("position"))


def _facing_of(cast_map: Mapping[str, Dict[str, Any]],
               cid: str) -> Optional[Vector3]:
    entry = cast_map.get(cid)
    if not entry:
        return None
    return _vec3(entry.get("facing"))


# --------------------------------------------------------------------------- #
# 锚点
# --------------------------------------------------------------------------- #
def _build_anchors(plan, cast_positions: Mapping[str, Dict[str, Any]],
                   origin: Vector3) -> List[Dict[str, Any]]:
    """环境锚点：求解器解算 → ``algorithmic_measurement``；解不出 → unresolved。"""
    anchors = list((getattr(plan, "environment", None) or {}).get("anchors")
                   or [])
    if not anchors:
        return []
    positions, problems = solve_anchor_positions(
        anchors, cast_positions, origin=origin)
    reasons = {str(item.get("anchor") or ""): str(item.get("reason") or "")
               for item in problems if item.get("anchor")}
    entries: List[Dict[str, Any]] = []
    for anchor in anchors:
        if not isinstance(anchor, Mapping):
            continue
        name = str(anchor.get("name") or "")
        if not name:
            continue
        #: 求解器对"未解析锚点"也会填充确定性缺省环坐标——设计侧**不采纳**
        #: 这份缺省位（那会把"未解析"伪装成设计值），凡是带 problem 的一律
        #: 记 unresolved 且不带 position（不猜）。
        if name in reasons:
            entries.append({
                "label": name,
                "position": None,
                "status": "unresolved",
                "reason": reasons[name],
                "unresolved": ["position"],
            })
            continue
        if name in positions:
            entries.append({
                "label": name,
                "position": _fv(_r3(tuple(positions[name])), "m",
                                "algorithmic_measurement"),
                "status": "resolved",
                "reason": "",
                "unresolved": [],
            })
    return entries


# --------------------------------------------------------------------------- #
# 角色（逐镜）
# --------------------------------------------------------------------------- #
def _action_source(action: Mapping[str, Any]) -> Optional[Vector3]:
    params = action.get("params") or {}
    return _vec3(params.get("from", params.get("from_")))


def _shot_motion(shot, cid: str) -> Optional[Dict[str, Any]]:
    """该镜里 cid 的运动意图（plan_intent）。"""
    for action in shot.actions or []:
        if not isinstance(action, Mapping):
            continue
        kind = str(action.get("type") or "")
        if kind not in _MOTION_ACTIONS:
            continue
        params = action.get("params") or {}
        source = _vec3(params.get("from", params.get("from_")))
        target = _vec3(params.get("target_position", params.get("to")))
        return {
            "action_type": kind,
            "from": _r3(source) if source else None,
            "to": _r3(target) if target else None,
            "speed": str(params.get("speed") or "walk"),
            "start_frame": int(action.get("start_frame") or 0),
            "end_frame": int(action.get("end_frame") or 0),
            "provenance": "plan_intent",
        }
    return None


def _gaze_target(shot, brief, cid: str) -> str:
    for gaze in shot.gaze or []:
        if isinstance(gaze, Mapping) and str(gaze.get("from") or "") == cid:
            return str(gaze.get("to") or "")
    if brief is not None:
        for gaze in brief.gazes_in(str(shot.shot_id), int(shot.order or 0)):
            if str(gaze.get("from") or "") == cid:
                return str(gaze.get("to") or "")
    return ""


def _build_characters(plan, brief, cast_map: Mapping[str, Dict[str, Any]]
                      ) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for shot in plan.shots or []:
        for cid in shot.characters or []:
            entry: Dict[str, Any] = {
                "id": str(cid),
                "shot_id": str(shot.shot_id),
                "position": None,
                "facing": None,
                "rotation": None,
                "motion": None,
                "gaze": None,
                "unresolved": [],
            }
            # 站位：优先计划动作起点（plan_intent），否则 cast（plan_intent）。
            position: Optional[Vector3] = None
            for action in shot.actions or []:
                if not isinstance(action, Mapping):
                    continue
                source = _action_source(action)
                if source is not None:
                    position = source
                    break
            if position is None:
                position = _position_of(cast_map, str(cid))
            if position is not None:
                entry["position"] = _fv(_r3(position), "m", "plan_intent")
            else:
                entry["unresolved"].append("position")

            # 朝向：cast initial_facing（plan_intent）。
            facing = _facing_of(cast_map, str(cid))
            if facing is not None:
                entry["facing"] = _fv(_r3(facing), "none", "plan_intent")
            else:
                entry["unresolved"].append("facing")

            # 运动意图。
            motion = _shot_motion(shot, str(cid))
            if motion is not None:
                entry["motion"] = motion

            # 视线：目标 id + 世界方向向量（两者位置已知才算得出来）。
            target = _gaze_target(shot, brief, str(cid))
            if target:
                direction: Optional[Vector3] = None
                target_pos = _position_of(cast_map, target)
                if position is not None and target_pos is not None:
                    delta = _norm(tuple(target_pos[i] - position[i]
                                        for i in range(3)))
                    if delta is not None:
                        direction = tuple(round(item, 4) for item in delta)
                if direction is None:
                    entry["unresolved"].append("gaze_direction")
                entry["gaze"] = {
                    "target_id": target,
                    "direction": (_fv(list(direction), "none", "plan_intent")
                                  if direction is not None else None),
                    "provenance": "plan_intent",
                }
            entries.append(entry)
    return entries


# --------------------------------------------------------------------------- #
# 物品
# --------------------------------------------------------------------------- #
def _build_props(brief, anchors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """剧本参与物品：kind/owner 取自 brief.props，position 只认已解析坐标。"""
    resolved = {str(a["label"]): a["position"]
                for a in anchors if a.get("status") == "resolved"}
    entries: List[Dict[str, Any]] = []
    for prop in (getattr(brief, "props", None) or [] if brief else []) or []:
        if not isinstance(prop, Mapping):
            continue
        pid = str(prop.get("id") or "")
        if not pid:
            continue
        entry: Dict[str, Any] = {
            "id": pid,
            "kind": str(prop.get("kind") or "prop"),
            "owner": str(prop.get("owner") or ""),
            "parent": None,
            "position": None,
            "rotation": None,
            "motion": None,
            "unresolved": ["position", "parent"],
        }
        if pid in resolved:
            entry["position"] = resolved[pid]
            entry["unresolved"] = [name for name in entry["unresolved"]
                                   if name != "position"]
        entries.append(entry)
    return entries


# --------------------------------------------------------------------------- #
# 机位（逐镜）
# --------------------------------------------------------------------------- #
def _fov_degrees(lens: float) -> Dict[str, float]:
    """水平/垂直视场角（度），口径与 framing.vertical_fov 一致。"""
    vertical = math.degrees(vertical_fov(lens, SENSOR_WIDTH, ASPECT_16_9))
    horizontal = math.degrees(
        2.0 * math.atan(SENSOR_WIDTH / (2.0 * lens)))
    return {"horizontal": round(horizontal, 4),
            "vertical": round(vertical, 4)}


def _look_at_rotation(position: Vector3, target: Vector3) -> Dict[str, Any]:
    """由 position→target 的视线方向确定性折出相机旋转（四元数 + 欧拉）。

    右手系 Z 向上：``f = normalize(target - position)`` 是相机**视向**（=相机
    局部 -Z 的世界方向）。选参考上向量求正交基，再走"四元数 ← 旋转矩阵"的
    标准迹算法。纯数学、确定性，不依赖 bpy。
    """
    forward = _norm(tuple(target[i] - position[i] for i in range(3)))
    if forward is None:
        return {"quaternion": [1.0, 0.0, 0.0, 0.0],
                "euler": [0.0, 0.0, 0.0], "order": "XYZ"}
    up_ref = (0.0, 1.0, 0.0)
    if abs(forward[0] * up_ref[0] + forward[1] * up_ref[1]
           + forward[2] * up_ref[2]) > 0.99:
        up_ref = (0.0, 0.0, 1.0)

    def cross(a: Vector3, b: Vector3) -> Vector3:
        return (a[1] * b[2] - a[2] * b[1],
                a[2] * b[0] - a[0] * b[2],
                a[0] * b[1] - a[1] * b[0])

    right = _norm(cross(forward, up_ref))
    if right is None:
        right = (1.0, 0.0, 0.0)
    up2 = _norm(cross(right, forward))
    if up2 is None:
        up2 = (0.0, 1.0, 0.0)
    back = tuple(-item for item in forward)
    # 旋转矩阵 R 的列 = [局部 X, 局部 Y, 局部 Z] 的世界坐标。
    m = (right, up2, back)
    trace = m[0][0] + m[1][1] + m[2][2]
    if trace > 0.0:
        s = math.sqrt(trace + 1.0) * 2.0
        w = 0.25 * s
        x = (m[2][1] - m[1][2]) / s
        y = (m[0][2] - m[2][0]) / s
        z = (m[1][0] - m[0][1]) / s
    elif m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2.0
        w = (m[2][1] - m[1][2]) / s
        x = 0.25 * s
        y = (m[0][1] + m[1][0]) / s
        z = (m[0][2] + m[2][0]) / s
    elif m[1][1] > m[2][2]:
        s = math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2.0
        w = (m[0][2] - m[2][0]) / s
        x = (m[0][1] + m[1][0]) / s
        y = 0.25 * s
        z = (m[1][2] + m[2][1]) / s
    else:
        s = math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2.0
        w = (m[1][0] - m[0][1]) / s
        x = (m[0][2] + m[2][0]) / s
        y = (m[1][2] + m[2][1]) / s
        z = 0.25 * s
    norm = math.sqrt(w * w + x * x + y * y + z * z)
    if norm <= 1e-12:
        quaternion = [1.0, 0.0, 0.0, 0.0]
    else:
        quaternion = [round(w / norm, 4), round(x / norm, 4),
                      round(y / norm, 4), round(z / norm, 4)]
    euler = [math.atan2(2.0 * (w * x + y * z),
                        1.0 - 2.0 * (x * x + y * y)),
             math.asin(max(-1.0, min(1.0,
                                     2.0 * (w * y - z * x)))),
             math.atan2(2.0 * (w * z + x * y),
                        1.0 - 2.0 * (y * y + z * z))]
    return {"quaternion": quaternion,
            "euler": [round(item, 4) for item in euler], "order": "XYZ"}


def _build_camera_intents(plan, characters: List[Dict[str, Any]]
                          ) -> List[Dict[str, Any]]:
    """每镜机位设计值：framing 求解器（algorithmic_measurement）。"""
    char_by_shot: Dict[str, List[Dict[str, Any]]] = {}
    for char in characters:
        char_by_shot.setdefault(str(char["shot_id"]), []).append(char)

    intents: List[Dict[str, Any]] = []
    for shot in plan.shots or []:
        camera = shot.camera or {}
        entry: Dict[str, Any] = {
            "shot_id": str(shot.shot_id),
            "position": None,
            "target": None,
            "lens_mm": None,
            "fov_degrees": None,
            "rotation": None,
            "movement": None,
            "unresolved": [],
        }
        chars = char_by_shot.get(str(shot.shot_id)) or []
        resolved = [c for c in chars if c.get("position") is not None]
        if resolved:
            center = tuple(
                sum(c["position"]["value"][axis] for c in resolved)
                / len(resolved) for axis in range(3))
            facing: Vector3 = (0.0, 1.0, 0.0)
            for c in chars:
                if c.get("facing") is not None:
                    if c["facing"]["value"] is not None:
                        vec = _vec3(c["facing"]["value"])
                        if vec is not None and _norm(vec) is not None:
                            facing = vec
                            break
            side = str(camera.get("side") or "front")
            lens = camera.get("lens")
            direction = _vec3(camera.get("direction"))
            try:
                result = solve_framing(
                    center, facing=facing, shot_type=str(shot.shot_type),
                    side=side, lens=(float(lens) if lens else None),
                    direction=direction)
            except (TypeError, ValueError):
                result = None
            if result is not None:
                lens_value = float(result.lens)
                entry["position"] = _fv(
                    _r3(tuple(result.position)), "m", "algorithmic_measurement")
                entry["target"] = _fv(
                    _r3(tuple(result.target)), "m", "algorithmic_measurement")
                entry["rotation"] = _fv(
                    _look_at_rotation(tuple(result.position),
                                      tuple(result.target)),
                    "none", "algorithmic_measurement")
                entry["lens_mm"] = _fv(
                    lens_value, "mm",
                    "plan_intent" if lens is not None
                    else "algorithmic_measurement")
                entry["fov_degrees"] = _fv(
                    _fov_degrees(lens_value), "deg", "algorithmic_measurement")
            else:
                entry["unresolved"].extend(["position", "target", "rotation"])
        else:
            lens = camera.get("lens")
            if lens:
                lens_value = float(lens)
                entry["lens_mm"] = _fv(lens_value, "mm", "plan_intent")
                entry["fov_degrees"] = _fv(
                    _fov_degrees(lens_value), "deg", "algorithmic_measurement")
            entry["unresolved"].extend(["position", "target", "rotation"])
        movements = camera.get("movements") or None
        if movements:
            entry["movement"] = {
                "value": [dict(m) for m in movements],
                "unit": "none",
                "provenance": "plan_intent",
            }
        intents.append(entry)
    return intents


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
def build_design_snapshot(*, brief=None, plan, cast=None, run_id: str = "",
                          origin: Vector3 = (0.0, 0.0, 0.0)
                          ) -> DesignSnapshot:
    """brief + plan + cast（可选）→ 版本化设计快照（确定性、可追溯）。"""
    cast_map = _cast_map(cast)
    anchors = _build_anchors(plan, cast_map, origin)
    characters = _build_characters(plan, brief, cast_map)
    props = _build_props(brief, anchors)
    camera_intents = _build_camera_intents(plan, characters)
    data: Dict[str, Any] = {
        "$schema": f"blockdirector://spatial-snapshot/{DESIGN_SNAPSHOT_SCHEMA}",
        "schema_version": DESIGN_SNAPSHOT_SCHEMA,
        "run_context": {
            "run_id": run_id,
            "generator": "blockdirector.design_snapshot",
            "source_states": ["script_declaration", "plan_intent",
                              "algorithmic_measurement"],
        },
        "shot_ids": [str(shot.shot_id) for shot in plan.shots or []],
        "characters": characters,
        "props": props,
        "anchors": anchors,
        "camera_intents": camera_intents,
        "registry": {
            "diff_thresholds": dict(DIFF_THRESHOLDS),
            "units": {"m": "meters", "deg": "degrees",
                      "m_s": "meters/second"},
        },
        "notes": [
            "设计值是剧本声明/计划意图/程序解算（algorithmic）的可追溯值，"
            "不是实测；未解析字段为 None 且列入 unresolved[]，不猜。",
        ],
    }
    return DesignSnapshot.from_dict(data)
