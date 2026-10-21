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

from .framing import (
    SENSOR_WIDTH,
    required_distance,
    shot_frame_for,
    solve_framing,
)
from .staging import solve_anchor_positions
from .anchor import coarse_local_bounds
from .blockout import KIND_SIZE_BANDS, resolve_prop_kind
from .composition import FRAMING_SIZE_TOLERANCE
from .schedule import travelled_facings, travelled_positions
from .station import (
    LEAD_ROOM_OFFSET,
    aim_offset_for_composition,
    aim_offset_for_lead_room,
    camera_direction,
    subject_frame,
)
from .framing import side_vector

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

#: 局部拍对象（手/脸/道具）的目标占画高度。取构图尺允许偏差的下界：
#: 距离再近也不会进入评分扣分区，同时保留足够环境上下文，避免镜头贴到
#: 体块表面。数值由评分单一真源派生，不另写一份容差。
LOCAL_SUBJECT_COVERAGE = 1.0 - FRAMING_SIZE_TOLERANCE


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
        "facing_by_shot": [],
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
            #: R2 06/S1：相对朝向的关系（左/右/旁/前方/深处/对面/背后）需要
            #: 参照物的 facing。设计层没有真实朝向（纯站位声明），用与
            #: ``_character_entry`` 同一引擎默认 facing（+Y），保证确定性且
            #: 与角色条目读到的朝向同源——否则这些锚点在粗排 reference 阶段
            #: 会全部 unresolved（S1 根因）。
            cast_positions={
                k: {"position": v, "facing": list(DEFAULT_FACING)}
                for k, v in cast_positions.items()},
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


def _two_person_axis_sides(
    shots: Sequence[Mapping[str, Any]],
    positions_by_shot: Mapping[str, Mapping[str, Sequence[float]]],
) -> Dict[str, int]:
    """首个双人镜确立轴线，后续同组镜头保持同一世界侧位。

    ``camera_direction`` 的双人分支以**当前 shot.characters 顺序**构造轴线。
    角色列表一旦反序（正反打常见），同一个 ``axis_side`` 会落到世界坐标的
    另一侧。这里把首个双人镜的轴线作为场景基准，并按当前镜头轴与基准轴的
    点积翻转侧别符号，使镜头列表顺序变化不再改变银幕方向。
    """
    axis_pair: Optional[Tuple[str, str]] = None
    baseline: Optional[Tuple[float, float]] = None
    for shot in shots:
        shot_id = str(shot.get("shot_id") or "")
        positions = positions_by_shot.get(shot_id) or {}
        names = [
            str(name) for name in (shot.get("characters") or [])
            if str(name) in positions
        ]
        if len(names) != 2:
            continue
        start = positions[names[0]]
        end = positions[names[1]]
        dx = float(end[0]) - float(start[0])
        dy = float(end[1]) - float(start[1])
        length = math.hypot(dx, dy)
        if length < 1e-9:
            continue
        axis_pair = (names[0], names[1])
        baseline = (dx / length, dy / length)
        break
    if axis_pair is None or baseline is None:
        return {}

    sides: Dict[str, int] = {}
    for shot in shots:
        shot_id = str(shot.get("shot_id") or "")
        positions = positions_by_shot.get(shot_id) or {}
        names = [
            str(name) for name in (shot.get("characters") or [])
            if str(name) in positions
        ]
        if len(names) != 2 or not all(name in names for name in axis_pair):
            continue
        #: 机位求解读取的是本镜前两位角色构成的轴线；只有基准配对正好
        #: 位于这两端时才复用场景基准，避免把另一组人物误当同一条轴线。
        if tuple(names[:2]) not in (axis_pair, axis_pair[::-1]):
            continue
        start = positions[names[0]]
        end = positions[names[1]]
        dx = float(end[0]) - float(start[0])
        dy = float(end[1]) - float(start[1])
        if math.hypot(dx, dy) < 1e-9:
            continue
        dot = dx * baseline[0] + dy * baseline[1]
        sides[shot_id] = 1 if dot >= 0.0 else -1
    return sides


def _camera_intent(
    shot: Dict[str, Any],
    cast_positions: Mapping[str, Sequence[float]],
    cast_facings: Optional[Mapping[str, Sequence[float]]] = None,
    shot_facings: Optional[Mapping[str, Sequence[float]]] = None,
    props: Optional[Sequence[Mapping[str, Any]]] = None,
    auto_axis_side: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    shot_id = str(shot.get("shot_id") or "")
    if not shot_id:
        return None
    cast_facings = cast_facings or {}
    shot_facings = shot_facings or {}
    characters = shot.get("characters") or []
    declared_positions = [cast_positions.get(str(name)) for name in characters]
    declared_positions = [p for p in declared_positions if p is not None]
    framing_target = shot.get("framing_target")
    focus_ref = ""
    local_center: Optional[Tuple[float, float, float]] = None
    local_z: Optional[float] = None
    local_cover_height: Optional[float] = None
    subject_facing: Tuple[float, float, float] = DEFAULT_FACING
    if characters:
        focus_name = str(characters[0])
        facing_raw = shot_facings.get(focus_name) \
            or cast_facings.get(focus_name) or DEFAULT_FACING
        if isinstance(facing_raw, (list, tuple)) and len(facing_raw) >= 2:
            subject_facing = _normalize(facing_raw)
    if (isinstance(framing_target, Mapping)
            and str(framing_target.get("kind") or "") == "character"
            and str(framing_target.get("ref") or "")):
        ref = str(framing_target["ref"])
        focus_ref = ref
        if ref in cast_positions:
            #: 拍对象是声明主体：机位必须瞄该角色，而不是全组质心。
            #: final12 shot_003（MCU，三人镜，拍偷盗者）：旧实现按组质心
            #: (−0.6,2.13) 求解且 MCU 放宽为 MLS，相机落到 [−0.6,6.79,..]，
            #: 米迦尔/伊恩恰在相机与主体之间 -> 空墙+前景遮挡恒报、处方
            #: 拉远也消不掉。这里把组列表收窄为只含主体，多人 MLS 放宽
            #: 分支（见下）自然不触发，景别与距离按单人近景解。
            declared_positions = [cast_positions[ref]]
            facing_raw = shot_facings.get(ref) or cast_facings.get(ref) \
                or DEFAULT_FACING
            if isinstance(facing_raw, (list, tuple)) and len(facing_raw) >= 2:
                subject_facing = _normalize(facing_raw)
            else:
                subject_facing = DEFAULT_FACING
        #: 局部拍对象（hand/face）时，机位必须瞄被摄局部而不是整身。
        #: 旧实现一律瞄 EYE_Z/HEAD_TOP 带（shot_001 CU 拍手、shot_002 ECU
        #: 拍银币），target z 落在脸高 1.31-1.41，手/银币在 z=0.91 出画，
        #: 局部主体框投影后 inside_ratio≈0 -> 构图硬闸 20 分。这里把
        #: target 与相机高度同时落到 ``coarse_local_bounds`` 的局部中心，
        #: 不再出现"target 在手/脸、相机仍按整身表俯拍"的错位。
        part = str(framing_target.get("part") or "none")
        if part in {"hand", "face"}:
            char_pos = cast_positions.get(ref, (0.0, 0.0, 0.0))
            width, depth, height = KIND_SIZE_BANDS["character"]
            bounds = coarse_local_bounds(
                kind="character", part=part,
                low=(float(char_pos[0]) - width / 2.0,
                     float(char_pos[1]) - depth / 2.0,
                     float(char_pos[2])),
                high=(float(char_pos[0]) + width / 2.0,
                      float(char_pos[1]) + depth / 2.0,
                      float(char_pos[2]) + height),
                facing=subject_facing)
            if bounds is not None:
                derived_center = tuple(
                    (float(bounds[0][axis]) + float(bounds[1][axis])) / 2.0
                    for axis in range(3))
                local_z = derived_center[2]
                local_cover_height = (
                    float(bounds[1][2]) - float(bounds[0][2]))
                if ref in cast_positions:
                    local_center = derived_center
    elif (isinstance(framing_target, Mapping)
          and str(framing_target.get("kind") or "") == "prop"
          and str(framing_target.get("ref") or "")):
        ref = str(framing_target["ref"])
        prop_entries = [
            dict(prop) for prop in (props or [])
            if isinstance(prop, Mapping)]
        from .coarse_revision import resolve_prop_ref
        resolved_prop_id = resolve_prop_ref(
            ref, [str(prop.get("id") or "") for prop in prop_entries])
        if resolved_prop_id is not None:
            prop = next(
                (entry for entry in prop_entries
                 if str(entry.get("id") or "") == resolved_prop_id),
                None)
            prop_position = prop.get("position") if prop is not None else None
            position_xyz: Optional[Tuple[float, float, float]] = None
            if isinstance(prop_position, Mapping):
                try:
                    position_xyz = (
                        float(prop_position.get("x", 0.0)),
                        float(prop_position.get("y", 0.0)),
                        float(prop_position.get("z", 0.0)),
                    )
                except (TypeError, ValueError):
                    position_xyz = None
            elif isinstance(prop_position, (list, tuple)) \
                    and len(prop_position) >= 3:
                try:
                    position_xyz = tuple(
                        float(prop_position[axis]) for axis in range(3))
                except (TypeError, ValueError):
                    position_xyz = None
            if prop is not None and position_xyz is not None:
                size = resolve_prop_kind(prop.get("kind")).size
                bounds = coarse_local_bounds(
                    kind="prop", part="none",
                    low=(position_xyz[0] - size[0] / 2.0,
                         position_xyz[1] - size[1] / 2.0,
                         position_xyz[2] - size[2] / 2.0),
                    high=(position_xyz[0] + size[0] / 2.0,
                          position_xyz[1] + size[1] / 2.0,
                          position_xyz[2] + size[2] / 2.0))
                if bounds is not None:
                    local_center = tuple(
                        (float(bounds[0][axis]) + float(bounds[1][axis]))
                        / 2.0 for axis in range(3))
                    local_z = local_center[2]
                    local_cover_height = (
                        float(bounds[1][2]) - float(bounds[0][2]))
                    owner = str(prop.get("owner") or "")
                    focus_ref = owner or resolved_prop_id
                    if owner:
                        facing_raw = shot_facings.get(owner) \
                            or cast_facings.get(owner) or DEFAULT_FACING
                        if isinstance(facing_raw, (list, tuple)) \
                                and len(facing_raw) >= 2:
                            subject_facing = _normalize(facing_raw)
    if declared_positions:
        #: 多人同框必须以主体组中心求解，不能只瞄准 characters[0]；否则
        #: 第二个角色会被挤出画面，形成“单个巨大体块占满”的假通过构图。
        subject_pos = tuple(sum(float(p[i]) for p in declared_positions)
                           / len(declared_positions) for i in range(3))
        if local_center is not None:
            subject_pos = local_center
    else:
        subject_pos = (0.0, 0.0, 0.0)
    camera = _as_dict(shot.get("camera") or {})
    requested_side = str(camera.get("side") or "").strip().lower()
    side = requested_side or "front"
    lens = camera.get("lens")
    shot_type = str(shot.get("shot_type") or "MS")
    if len(declared_positions) > 1 and shot_type in {"CU", "MCU", "MS"}:
        #: 多主体中景自动退到 MLS，保证组体块在 16:9 视锥内；这是机位
        #: 求解，不是放宽构图门槛。
        shot_type = "MLS"
    candidate_frame = shot_frame_for(shot_type)
    candidate_lens = float(lens or candidate_frame.lens)
    local_distance = None
    if local_cover_height is not None and local_cover_height > 0.0:
        local_distance = required_distance(
            local_cover_height / LOCAL_SUBJECT_COVERAGE,
            candidate_lens, SENSOR_WIDTH)
    candidate_distance = (
        local_distance if local_distance is not None
        else required_distance(candidate_frame.frame_height, candidate_lens))
    support_positions = [
        tuple(float(value) for value in cast_positions[str(name)])
        for name in (shot.get("characters") or [])
        if str(name) != focus_ref and str(name) in cast_positions
    ]

    def blocked_on(candidate_side: str) -> bool:
        dx, dy = side_vector(subject_facing, candidate_side)
        support_radius = KIND_SIZE_BANDS["character"][0] / 2.0
        for support in support_positions:
            rel_x = float(support[0]) - float(subject_pos[0])
            rel_y = float(support[1]) - float(subject_pos[1])
            along = rel_x * dx + rel_y * dy
            if along <= 0.0 or along >= candidate_distance + support_radius:
                continue
            lateral = abs(dx * rel_y - dy * rel_x)
            if lateral <= support_radius + 1e-6:
                return True
        return False

    side_provenance = "plan_intent" if requested_side else "auto_front"
    #: final12 shot_005/006/007：被摄者与同镜角色在同一直线上，纯正面机位
    #: 必然穿过后者。模型没有声明 side 时，先用 over_shoulder 作为
    #: 过肩绕行；只在候选方向确实避开所有同镜角色后采用，并记录来源。
    #: 显式 side 视为导演意图，不在设计层静默改写。
    if focus_ref and not requested_side and blocked_on(side):
        for candidate_side in (
                "over_shoulder", "front_left", "front_right", "left", "right"):
            if not blocked_on(candidate_side):
                side = candidate_side
                side_provenance = "occlusion_avoidance"
                break
    resolved_direction: Optional[Tuple[float, float]] = None
    if (len(declared_positions) == 2 and not requested_side
            and not focus_ref and local_center is None
            and auto_axis_side is not None):
        entries = [
            (
                str(name),
                cast_positions[str(name)],
                shot_facings.get(str(name))
                or cast_facings.get(str(name))
                or DEFAULT_FACING,
            )
            for name in characters
            if str(name) in cast_positions
        ]
        frame = subject_frame(
            entries, shot_type=shot_type,
            speaker_id=str(characters[0]) if characters else "")
        resolved_direction = camera_direction(
            frame, side, axis_side=int(auto_axis_side))
        side_provenance = "auto_axis_normal"
    #: 单主体镜头的构图横移（§10.4 lead_room / rule_of_thirds）：细排空间
    #: 求解经 ``station.aim_offset_for_composition`` 读 plan 的构图声明把主体
    #: 放到三分线；粗排空间设计必须用**同一入口**（``shot.composition`` 的
    #: subject_position/rule），否则粗排求解出的机位让主体居中、
    #: rule_of_thirds≈0.06、构图分卡在 77-80 过不了细排 gate。direction 是
    #: "主体 -> 机位"的单位方向（``side_vector`` 返回值），与细排
    #: ``camera_direction`` 同语义。
    camera_to_subject = (
        resolved_direction if resolved_direction is not None
        else side_vector(subject_facing, side))
    default_aim = 0.0
    if len(declared_positions) == 1:
        default_aim = aim_offset_for_lead_room(camera_to_subject,
                                                subject_facing)
    if local_center is not None and abs(default_aim) < 1e-9:
        #: 局部主体正对镜头时 lead_room 没有左右语义；空构图声明仍把
        #: 主体放到一条三分线上，避免"六项全对但中心构图恰好 80 分"
        #: 被严格门永远拦住。显式 composition=center 仍由下面覆盖为 0。
        default_aim = LEAD_ROOM_OFFSET
    aim_offset_x = aim_offset_for_composition(
        camera.get("composition") or shot.get("composition"),
        camera_to_subject, subject_facing,
        default=default_aim)
    try:
        result = solve_framing(
            subject_pos=subject_pos, facing=subject_facing,
            shot_type=shot_type, side=side,
            lens=float(lens) if lens else None,
            aim_offset_x=aim_offset_x,
            distance_override=local_distance,
            direction=resolved_direction)
    except Exception as exc:  # noqa: BLE001 - 记 note，不给假机位
        return {
            "shot_id": shot_id, "position": None, "target": None,
            "lens": None, "fov_deg": None,
            "provenance": "plan_intent", "resolved": False,
            "unresolved_reason": f"机位求解失败：{exc}",
        }
    target = list(result.target)
    position = list(result.position)
    if local_z is not None:
        #: ``solve_framing`` 的 target/camera z 属于整身景别表；局部拍对象
        #: 必须把两者一起替换成同一局部中心，避免保留整身俯仰角。
        target[2] = float(local_z)
        position[2] = float(local_z)
    fov_deg = math.degrees(2.0 * math.atan(SENSOR_WIDTH / (2.0 * result.lens)))
    return {
        "shot_id": shot_id,
        "position": position,
        "target": target,
        "lens": round(result.lens, 4),
        "fov_deg": round(fov_deg, 4),
        "side": side,
        "side_provenance": side_provenance,
        "provenance": "algorithmic_measurement", "resolved": True,
        "unit": {"position": "m", "lens": "mm", "fov": "deg"},
    }


def build_design_snapshot(*, brief: Any, plan: Any,
                          cast_positions: Optional[Mapping[str, Sequence[float]]] = None,
                          cast_facings: Optional[
                              Mapping[str, Sequence[float]]] = None,
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
    declared_facings: Dict[str, Tuple[float, float, float]] = {}
    for name, facing in (cast_facings or {}).items():
        if isinstance(facing, (list, tuple)) and len(facing) >= 2:
            declared_facings[str(name)] = _normalize(facing)
    notes: List[str] = []

    # 1) 场级角色清单（并集，按首见稳定排序）
    character_names: List[str] = []
    for shot in shot_list:
        for name in (shot.get("characters") or []):
            if str(name) not in character_names:
                character_names.append(str(name))

    # 2) 锚点（brief.environment[]、plan.environment.anchors[] 与显式
    # anchors 并集）。粗排 headless 路径没有把 brief 传进来，但 Stage A
    # 的 Plan 已包含闭集方位锚点；只读 brief 会让粗排 reference 的 anchors
    # 为空，进而让银币摊/海面等明确主体丢失。两种契约形状都接受：
    # ``{label, direction, distance, size}`` 与 SDL 的
    # ``{name, relation}``，后者规整为 ``label`` 后复用同一解析器。
    anchors: List[Dict[str, Any]] = []
    plan_environment: Mapping[str, Any] = {}
    if isinstance(plan, Mapping):
        plan_environment = _as_dict(plan.get("environment") or {})
    else:
        plan_environment = _as_dict(getattr(plan, "environment", None) or {})

    raw_anchor_items = list(briefd.get("environment") or [])
    raw_anchor_items += list(briefd.get("anchors") or [])
    raw_anchor_items += list(plan_environment.get("anchors") or [])
    #: 同标签去重（R2 真跑 20261020-market-real-final2）：同一物理锚点会以
    #: 两种契约形状各来一次（brief.environment 的 {direction, distance} 与
    #: plan.environment.anchors 的 SDL {name, relation}），不清重会在 manifest
    #: 生成两个同名体块（anchor_海面），场景构建 `_place_box` 第二次即抛
    #: "体块对象已存在"。规则：首个 resolved 生效、不覆盖；未 resolved 的
    #: 旧条目允许被后续 resolved 条目替换；未命名条目原样保留。
    seen_labels: set = set()
    for raw in raw_anchor_items:
        item = _as_dict(raw)
        if not item.get("label") and item.get("name"):
            item["label"] = str(item["name"])
        label = str(item.get("label") or "")
        entry = _anchor_from_environment(
            item, cast, aliases={}, solved={}, notes=notes)
        if not label:
            anchors.append(entry)
            continue
        if label in seen_labels:
            for index, existing in enumerate(anchors):
                if str(existing.get("label") or "") != label:
                    continue
                if existing.get("resolved") or not entry.get("resolved"):
                    break
                anchors[index] = entry
            continue
        seen_labels.add(label)
        anchors.append(entry)
    anchor_positions = {
        str(a["label"]): a["position"] for a in anchors
        if a.get("resolved") and a.get("position") is not None}

    # 3) 角色条目（站位 + 逐镜 motion/gaze）
    projected_facings: Dict[str, Dict[str, Tuple[float, float, float]]] = {}
    if isinstance(plan, Mapping) or hasattr(plan, "shots"):
        initial_facings = {
            name: declared_facings.get(name, DEFAULT_FACING)
            for name in character_names
        }
        projected_facings = travelled_facings(plan, initial_facings, cast)

    characters: List[Dict[str, Any]] = []
    for name in character_names:
        entry = _character_entry(name, cast.get(name, (0.0, 0.0, 0.0)),
                                 "plan_intent")
        if name in declared_facings:
            entry["facing"] = list(declared_facings[name])
        if name not in cast:
            entry["position"] = None
            entry["provenance"] = "plan_intent"
            notes.append(f"角色 {name} 在计划里但无站位声明，未落坐标（不猜）")
        for shot in shot_list:
            shot_id = str(shot.get("shot_id") or "")
            if name not in (shot.get("characters") or []):
                continue
            shot_facing = list(
                projected_facings.get(shot_id, {}).get(name, entry["facing"]))
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
                    direction = resolved.get("direction")
                    default_facing = list(DEFAULT_FACING)
                    if direction is not None and name not in declared_facings:
                        shot_facing = _normalize(direction)
                    if direction is not None and name not in declared_facings \
                            and list(entry["facing"]) == default_facing:
                        #: facing 由显式 gaze 回填：米迦尔 gaze->偷盗者这类
                        #: "看着谁"是剧本显式声明 + 站位已知，方向可由两点
                        #: 几何推出（不是猜）。facing 用于粗排局部主锚的
                        #: lead_room / 手部锚点侧向——旧实现恒 (+Y) 让
                        #: lead_room 永远拿 0.75 基准分、构图卡在 80 附近。
                        entry["facing"] = [
                            round(float(direction[0]), 4),
                            round(float(direction[1]), 4),
                            round(float(direction[2]), 4),
                        ]
            entry.setdefault("facing_by_shot", []).append(
                {"shot_id": shot_id, "direction": list(shot_facing)})
        characters.append(entry)

    # 4) 物品（brief.props[]；位置缺省留痕，不猜）
    # 手持道具（owner 已声明且有站位）：用 owner 站位 + 冻结手部几何
    # （chest_z / HAND_PROXY_FORWARD / HAND_PROXY_SIDE）确定性解析——
    # 剧本"偷盗者掌中银币"这类归属是明确声明，不是脑补；推导来源记
    # provenance=algorithmic_measurement 并留 note，可被后续实测覆盖。
    props: List[Dict[str, Any]] = []
    from .anchor import DEFAULT_PROFILE, hand_world_position
    for raw in briefd.get("props") or []:
        item = _as_dict(raw)
        pid = str(item.get("id") or "")
        owner = str(item.get("owner") or "") or None
        position: Optional[List[float]] = None
        provenance = "plan_intent"
        explicit = item.get("position")
        if (isinstance(explicit, (list, tuple))
                and len(explicit) >= 3):
            position = [round(float(v), 4) for v in explicit[:3]]
            provenance = "script_declaration"
        elif pid and owner in cast:
            owner_pos = cast[owner]
            owner_facing = next(
                (tuple(character["facing"]) for character in characters
                 if str(character.get("name") or "") == owner),
                declared_facings.get(owner, DEFAULT_FACING),
            )
            position = [
                round(float(value), 4)
                for value in hand_world_position(
                    owner_pos,
                    owner_facing,
                    profile=DEFAULT_PROFILE,
                    side=1.0,
                )
            ]
            provenance = "algorithmic_measurement"
            notes.append(
                f"物品 {pid} 由归属 {owner} 的站位 + 冻结手部几何"
                f"（chest_z={DEFAULT_PROFILE.chest_z:.3f}）解析手持坐标，"
                f"可被实测覆盖")
        props.append({
            "id": pid,
            "kind": str(item.get("kind") or ""),
            "owner": owner,
            "parent": item.get("parent"),
            "position": position,
            "rotation": None,
            "motion": None,
            "provenance": provenance,
            "unit": _unit((0.0, 0.0, 0.0)),
        })
        if pid and item.get("position") is None:
            if position is None:
                notes.append(f"物品 {pid} 无位置声明，未落坐标（不猜）")

    # 5) 逐镜机位设计
    positions_by_shot = travelled_positions(plan, cast)
    auto_axis_sides = _two_person_axis_sides(shot_list, positions_by_shot)
    cast_facings = {
        str(char.get("name") or ""): tuple(char.get("facing") or DEFAULT_FACING)
        for char in characters
    }
    shot_facings = {
        str(shot.get("shot_id") or ""): {
            str(char.get("name") or ""): tuple(
                next((item.get("direction") for item in
                      (char.get("facing_by_shot") or [])
                      if str(item.get("shot_id") or "")
                      == str(shot.get("shot_id") or "")),
                     char.get("facing") or DEFAULT_FACING))
            for char in characters
        }
        for shot in shot_list
    }
    camera_intents = [intent for intent in
                      (_camera_intent(
                          shot,
                          positions_by_shot.get(
                              str(shot.get("shot_id") or ""), cast),
                          cast_facings,
                          shot_facings.get(str(shot.get("shot_id") or "")),
                          props=props,
                          auto_axis_side=auto_axis_sides.get(
                              str(shot.get("shot_id") or "")))
                       for shot in shot_list)
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


def resolve_camera_intents(reference: Mapping[str, Any]) -> Dict[str, Any]:
    """只重解 reference 的相机意图（角色/道具/锚点原样保留）。

    细排 gate 必须用同一把构图尺子重测冻结空间；冻结 baseline 的
    camera_intents 是旧实现（整身对准、target z 落在脸高带）生成的，
    局部拍对象（hand/face）时手/银币出画。本函数从 reference 的
    characters[].position 与 shots[].framing_target 重新解相机，**不移动
    任何角色/道具站位**——相机是被摄观测关系，不是冻结空间的一部分。
    """
    out = dict(reference)
    raw_chars = [dict(c) for c in (reference.get("characters") or [])]
    #: 旧冻结 reference 的 characters[].facing 恒为 (+Y)（design 层默认）。
    #: 局部主锚（hand/face）的 lead_room 依赖 facing：剧本显式 gaze
    #: （米迦尔->偷盗者）可由两点几何推出方向，回填 facing 让粗排和细排
    #: 用同一套视线留白语义，否则 lead_room 永远 0.75 基准分、构图卡 80。
    for char in raw_chars:
        if list(char.get("facing") or []) != list(DEFAULT_FACING):
            continue
        for gaze in char.get("gaze_by_shot") or []:
            direction = gaze.get("direction")
            if not isinstance(direction, (list, tuple)) or len(direction) < 2:
                continue
            char["facing"] = [
                round(float(direction[0]), 4),
                round(float(direction[1]), 4),
                round(float(direction[2]) if len(direction) > 2 else 0.0, 4),
            ]
            break
    out["characters"] = raw_chars
    chars = {str(c.get("name") or ""): c.get("position")
             for c in raw_chars}
    cast: Dict[str, Sequence[float]] = {}
    facings: Dict[str, Sequence[float]] = {}
    shot_facings: Dict[str, Dict[str, Sequence[float]]] = {}
    for name, pos in chars.items():
        if isinstance(pos, Mapping) and pos.get("x") is not None:
            cast[name] = (float(pos["x"]), float(pos["y"]),
                          float(pos.get("z") or 0.0))
        elif isinstance(pos, (list, tuple)) and len(pos) >= 3:
            cast[name] = tuple(float(v) for v in pos[:3])
        char = next((item for item in raw_chars
                     if str(item.get("name") or "") == name), {})
        facing = char.get("facing")
        if isinstance(facing, (list, tuple)) and len(facing) >= 2:
            facings[name] = facing
        for item in char.get("facing_by_shot") or []:
            direction = item.get("direction")
            shot_id = str(item.get("shot_id") or "")
            if shot_id and isinstance(direction, (list, tuple)) \
                    and len(direction) >= 2:
                shot_facings.setdefault(shot_id, {})[name] = direction
    reference_shots = [dict(shot) for shot in (reference.get("shots") or [])]
    auto_axis_sides = _two_person_axis_sides(
        reference_shots,
        {str(shot.get("shot_id") or ""): cast for shot in reference_shots},
    )
    intents = [_camera_intent(
        shot, cast, facings,
        shot_facings.get(str(shot.get("shot_id") or "")),
        props=reference.get("props") or [],
        auto_axis_side=auto_axis_sides.get(
            str(shot.get("shot_id") or "")),
    )
               for shot in reference_shots]
    intents = [i for i in intents if i is not None]
    out["camera_intents"] = intents
    out["notes"] = list(reference.get("notes") or []) + [
        "细排构图重测：相机意图按局部拍对象重新求解（站位不动）"]
    return out


def render_design_summary(design: Mapping[str, Any], *,
                          max_chars: int = 1200) -> str:
    """把设计快照渲染成提示文本（计划提示注入用）。

    优先级：未解析留痕 > 角色 > 锚点 > 机位；整行追加，放不下的那行起
    整行舍弃（绝不截半行），与 :func:`render_spatial_digest` 同机制。
    回退：设计快照为空 -> 空串。
    """
    if max_chars <= 0 or not isinstance(design, Mapping) or not design:
        return ""
    lines: List[str] = [f"【空间设计快照｜{design.get('scene_id', '')}】"]

    def fits(line: str) -> bool:
        current = len("\n".join(lines)) if lines else 0
        return current + len(line) + (1 if lines else 0) <= max_chars

    unresolved_notes = [str(note) for note in (design.get("notes") or [])
                        if "未" in str(note) or "不猜" in str(note)
                        or "解析" in str(note)]
    for note in unresolved_notes:
        if fits(f"- {note}"):
            lines.append(f"- {note}")
    for char in design.get("characters") or []:
        name = str(char.get("name") or "?")
        position = char.get("position")
        if isinstance(position, Mapping) and position.get("x") is not None:
            pos_text = (f"pos=({position.get('x')},{position.get('y')},"
                        f"{position.get('z')})")
        else:
            pos_text = "pos=未解析（不猜）"
        facing = char.get("facing")
        facing_text = (f"facing={tuple(facing)}" if facing else "")
        gaze = char.get("gaze") or {}
        gaze_text = (f"gaze->{gaze.get('target_id')}" if gaze.get("target_id")
                     else "")
        line = f"- {name} {pos_text} {facing_text} {gaze_text}".rstrip()
        if fits(line):
            lines.append(line)
    for anchor in design.get("anchors") or []:
        position = anchor.get("position")
        if position is None:
            line = (f"- 锚点 {anchor.get('label')} 未解析"
                    f"（{anchor.get('unresolved_reason', '')}）")
        else:
            line = (f"- 锚点 {anchor.get('label')} "
                    f"pos={tuple(position)}（{anchor.get('provenance')}）")
        if fits(line):
            lines.append(line)
    for intent in design.get("camera_intents") or []:
        if intent.get("position") is None:
            line = (f"- 机位 {intent.get('shot_id')} 未解析"
                    f"（{intent.get('unresolved_reason', '')}）")
        else:
            line = (f"- 机位 {intent.get('shot_id')} "
                    f"pos={tuple(intent['position'])} "
                    f"target={tuple(intent.get('target') or [])} "
                    f"lens={intent.get('lens')}mm（{intent.get('provenance')}）")
        if fits(line):
            lines.append(line)
    return "\n".join(lines)


__all__ = ["build_design_snapshot", "render_design_summary",
           "DESIGN_SNAPSHOT_SCHEMA", "DIRECTION_VECTORS", "DISTANCE_METERS"]
