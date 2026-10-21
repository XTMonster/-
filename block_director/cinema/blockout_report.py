"""Ticket 04：Blockout 粗排自检报告生成器（纯层，不 import bpy）。

把 Blender 冒烟侧采到的数值证据（体块比例、构图分/遮挡、出入画、空墙、设计
vs 实测 diff）确定性折成版本化 ``BlockoutReport``，供审批与人工/执行 AI
视觉审查一并消费：

* ``checks[]``：逐项数值结论（check_id / 分数或布尔 / 阈值 / verdict）；
* ``findings[]``：硬伤（如相机对空墙 E_BLOCKOUT_EMPTY_WALL）；
* ``visual_states[]``：每镜每采样帧的渲染帧路径与是否已人工/执行 AI 查看。

判定语义：数值型 ``actual <= threshold`` -> pass（与 spatial_diff 同口径）；
空墙判据：主体投影面积近零或全被遮挡 -> finding。确定性：同一输入两次构建
逐位一致。
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from .axis import E_BLOCKOUT_AXIS_FLIP, camera_direction_findings
from ..contracts.quality import COMPOSITION_PASS_SCORE, composition_decision

COMPOSITION_PASS = COMPOSITION_PASS_SCORE

#: 快照版本（契约演进时逐代升）。
BLOCKOUT_REPORT_SCHEMA = "blockout-report/v1"

#: 空墙硬伤 check_id（spec §决策：相机对准空墙不可静默放行）。
E_BLOCKOUT_EMPTY_WALL = "E_BLOCKOUT_EMPTY_WALL"
# 实际渲染帧所有像素相同（全黑/全白/全灰等）时的预警 finding。
E_EMPTY_FRAME = "E_EMPTY_FRAME"

VISIBLE_RATIO_MIN = 0.5        # 主体可见比例低于该值 -> 遮挡硬伤
#: 前景非主体体块遮挡比例硬门。单个角色有超过 50% 的采样点被另一体块
#: 挡住时，构图分数即使高于 80 也不能放行；这是“灰色大体块盖住角色”
#: 的专门防线。严格大于 0.5 才失败，恰好 0.5 仍保留可审查状态。
FOREGROUND_OCCLUSION_MAX = 0.5
SUBJECT_AREA_MAX = 0.55
ON_SCREEN_MIN = 0.05           # 主体在画面内面积占比低于该值 -> 空墙嫌疑
OFF_SCREEN_LABEL = "off_screen"  # 主体完全出画 -> 出入画 finding 类别


def is_uniform_frame(data: Any) -> bool:
    """判断帧像素是否为同一字节/数值（纯层、无 bpy/numpy 依赖）。

    ``data`` 可为 bytes/bytearray 或数字序列；空数据不判为空帧，避免把
    渲染失败（缺文件）误报成画面内容问题。调用方若已有 Blender 像素采样，
    也可直接传入展平后的 RGBA 数值序列。
    """
    if isinstance(data, (bytes, bytearray, memoryview)):
        values = bytes(data)
    else:
        try:
            values = list(data)
        except TypeError:
            return False
    return bool(values) and all(value == values[0] for value in values[1:])


def empty_frame_finding(shot_id: str, frame: Mapping[str, Any]) -> Dict[str, Any] | None:
    """从一帧的纯层证据折出 E_EMPTY_FRAME 预警。"""
    pixels = frame.get("pixels")
    uniform = bool(frame.get("uniform", False))
    if pixels is not None:
        uniform = uniform or is_uniform_frame(pixels)
    if not uniform:
        return None
    return {
        "check_id": E_EMPTY_FRAME,
        "shot_id": str(shot_id),
        "frame": int(frame.get("frame") or 0),
        "severity": "warning",
        "message": "渲染帧所有像素相同，疑似空画/空帧",
    }

#: R10（Ticket 07）四类 check 的 error check_id（单一真源，粗排 gate 消费）。
E_BLOCKOUT_SHOT_SEQUENCE_MISMATCH = "E_BLOCKOUT_SHOT_SEQUENCE_MISMATCH"
E_BLOCKOUT_WALK_PATH_MISMATCH = "E_BLOCKOUT_WALK_PATH_MISMATCH"
E_BLOCKOUT_WALK_PATH_COLLISION = "E_BLOCKOUT_WALK_PATH_COLLISION"
E_BLOCKOUT_FRAMING_TARGET_OFF_SCREEN = "E_BLOCKOUT_FRAMING_TARGET_OFF_SCREEN"
E_BLOCKOUT_FRAMING_TARGET_OCCLUDED = "E_BLOCKOUT_FRAMING_TARGET_OCCLUDED"
#: 声明拍对象但预览拿不到投影证据（计划与场景脱节）时的硬伤 finding。
#: 粗排 gate 只认 error finding，缺证据必须拦下，不得放行进细排死循环。
E_BLOCKOUT_FRAMING_TARGET_UNRESOLVED = "E_BLOCKOUT_FRAMING_TARGET_UNRESOLVED"

#: 路线终点坐标比较容差（米；manifest 落盘四舍五入到 1e-4，计划目标可为
#: 任意精度，1e-3 视为"逐段一致"，避免浮点噪声误报）。
WALK_PATH_COORD_TOL_M = 1e-3
#: 路线碰撞容差系数（裁决 D5=B：体块半径和 × 0.5，预演体块比真实角色粗，
#: 留一半容差，仍能拦"穿模级"路线错）。
WALK_PATH_COLLISION_FACTOR = 0.5


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def plan_shot_dicts(plan: Any) -> List[Dict[str, Any]]:
    """把 ``Plan`` / dict / 单镜规范成 shot dict 列表（报告与预览共用）。

    纯层（不 import bpy）。``ShotPlan`` 走 ``to_dict()``（含 framing_target /
    actions / duration_frames），dict 形状原样保留——新旧输入统一接缝。
    """
    if plan is None:
        return []
    if hasattr(plan, "shots"):
        raw = list(getattr(plan, "shots") or [])
    elif isinstance(plan, Mapping):
        shots = plan.get("shots")
        if isinstance(shots, list) and shots:
            raw = shots
        elif plan.get("shot_id"):
            raw = [plan]
        else:
            raw = []
    else:
        raw = []
    out: List[Dict[str, Any]] = []
    for shot in raw:
        to_dict = getattr(shot, "to_dict", None)
        if callable(to_dict):
            out.append(dict(to_dict()))
        elif isinstance(shot, Mapping):
            out.append(dict(shot))
        else:
            out.append(dict(shot))
    return out


def _expected_move_ends(expected_shots: Sequence[Mapping[str, Any]]
                        ) -> List[Dict[str, Any]]:
    """plan 的 move 指令 -> ``{shot_id, character, end}``（walk_to/run_to）。

    键口径与 ``cinema/schedule.py::travelled_positions`` 同源（action_type /
    character_id / params.target_position 或顶层 target_position），不另立
    一套语义。
    """
    moves: List[Dict[str, Any]] = []
    for shot in expected_shots:
        shot_id = str(shot.get("shot_id") or "")
        for raw_action in shot.get("actions") or []:
            if not isinstance(raw_action, Mapping):
                continue
            action_type = str(raw_action.get("action_type")
                              or raw_action.get("type") or "")
            if action_type not in ("walk_to", "run_to"):
                continue
            character_id = str(raw_action.get("character_id") or "")
            params = raw_action.get("params")
            target = (params.get("target_position")
                      if isinstance(params, Mapping) else None)
            if target is None:
                target = raw_action.get("target_position")
            if not character_id or not isinstance(target, (list, tuple)) \
                    or len(target) < 2:
                continue
            values = [float(v) for v in target[:3]]
            while len(values) < 3:
                values.append(0.0)
            moves.append({
                "shot_id": shot_id, "character": character_id,
                "end": values,
            })
    return moves


def _shot_sequence_check(rows: Sequence[Mapping[str, Any]],
                         expected_shots: Sequence[Mapping[str, Any]],
                         findings: List[Dict[str, Any]]) -> Dict[str, Any]:
    """分镜数量/顺序/时长：manifest.shot_table vs plan（偏差 0）。"""
    actual = sorted(rows, key=lambda row: int(row.get("order") or 0))
    expected = sorted(expected_shots,
                      key=lambda shot: int(shot.get("order") or 0))

    def signature(row: Mapping[str, Any], duration: Optional[int] = None):
        if duration is None:
            duration = (int(row.get("end_frame") or 0)
                        - int(row.get("start_frame") or 0) + 1)
        return (str(row.get("shot_id") or ""), int(row.get("order") or 0),
                int(duration))

    actual_sig = [signature(row) for row in actual]
    expected_sig = [signature(shot, duration=shot.get("duration_frames"))
                    for shot in expected]

    if len(actual) != len(expected):
        findings.append({
            "check_id": E_BLOCKOUT_SHOT_SEQUENCE_MISMATCH,
            "shot_id": None, "severity": "error",
            "message": (f"分镜数量不符：manifest {len(actual)} 镜 / "
                        f"plan {len(expected)} 镜"),
        })
    for index, (a_row, e_shot) in enumerate(
            zip(actual, expected), start=1):
        a_sig = signature(a_row)
        e_sig = signature(e_shot, duration=e_shot.get("duration_frames"))
        if a_sig != e_sig:
            findings.append({
                "check_id": E_BLOCKOUT_SHOT_SEQUENCE_MISMATCH,
                "shot_id": str(a_row.get("shot_id") or ""),
                "severity": "error",
                "message": (
                    f"第 {index} 镜与 plan 不符：manifest "
                    f"(id={a_sig[0]!r}, order={a_sig[1]}, "
                    f"duration={a_sig[2]}帧) / plan "
                    f"(id={e_sig[0]!r}, order={e_sig[1]}, "
                    f"duration={e_sig[2]}帧)"),
            })
    problems = [f for f in findings
                if f["check_id"] == E_BLOCKOUT_SHOT_SEQUENCE_MISMATCH]
    return {
        "check_id": "shot_sequence", "shot_id": None,
        "actual": actual_sig, "expected": expected_sig,
        "threshold": "偏差 0",
        "verdict": "fail" if problems else "pass",
        "note": "分镜数量/顺序/时长与 plan 逐项一致" if not problems
        else f"{len(problems)} 处分镜序列与 plan 不符",
    }


def _character_radii(manifest: Mapping[str, Any]) -> Dict[str, float]:
    """角色体块水平半径（米）：min(size.x, size.y)/2（box 半宽）。"""
    radii: Dict[str, float] = {}
    for primitive in manifest.get("primitives") or []:
        if primitive.get("kind") != "character":
            continue
        source = primitive.get("source") or {}
        name = str(source.get("id") or "")
        size = primitive.get("size") or {}
        if not name or size.get("x") is None:
            continue
        radii[name] = (min(float(size.get("x")), float(size.get("y")))
                       / 2.0)
    return radii


def _orient(a: Sequence[float], b: Sequence[float],
            c: Sequence[float]) -> int:
    val = ((b[0] - a[0]) * (c[1] - a[1])
           - (b[1] - a[1]) * (c[0] - a[0]))
    if abs(val) < 1e-9:
        return 0
    return 1 if val > 0 else -1


def _on_segment(a: Sequence[float], b: Sequence[float],
                c: Sequence[float]) -> bool:
    return (min(a[0], b[0]) - 1e-9 <= c[0] <= max(a[0], b[0]) + 1e-9
            and min(a[1], b[1]) - 1e-9 <= c[1] <= max(a[1], b[1]) + 1e-9)


def _segments_intersect(p1: Sequence[float], p2: Sequence[float],
                        q1: Sequence[float], q2: Sequence[float]) -> bool:
    o1, o2 = _orient(p1, p2, q1), _orient(p1, p2, q2)
    o3, o4 = _orient(q1, q2, p1), _orient(q1, q2, p2)
    if o1 != o2 and o3 != o4:
        return True
    if o1 == 0 and _on_segment(p1, p2, q1):
        return True
    if o2 == 0 and _on_segment(p1, p2, q2):
        return True
    if o3 == 0 and _on_segment(q1, q2, p1):
        return True
    if o4 == 0 and _on_segment(q1, q2, p2):
        return True
    return False


def _point_segment_distance_2d(p: Sequence[float],
                               a: Sequence[float],
                               b: Sequence[float]) -> float:
    ax, ay = float(a[0]), float(a[1])
    bx, by = float(b[0]), float(b[1])
    px, py = float(p[0]), float(p[1])
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq < 1e-12:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy)


def _route_distance_2d(p1: Sequence[float], p2: Sequence[float],
                       q1: Sequence[float], q2: Sequence[float]) -> float:
    """两段路线（XY 平面）的最小距离；相交 -> 0。"""
    if _segments_intersect(p1, p2, q1, q2):
        return 0.0
    return min(
        _point_segment_distance_2d(p1, q1, q2),
        _point_segment_distance_2d(p2, q1, q2),
        _point_segment_distance_2d(q1, p1, p2),
        _point_segment_distance_2d(q2, p1, p2),
    )


def _walk_path_check(manifest: Mapping[str, Any],
                     expected_shots: Sequence[Mapping[str, Any]],
                     findings: List[Dict[str, Any]]) -> Dict[str, Any]:
    """走位路线：manifest.routes vs plan move/place 指令逐段一致 + 不穿模。

    碰撞容差 = 两体块半径和 × ``WALK_PATH_COLLISION_FACTOR``（D5=B）；
    既查"计划有而 manifest 没有 / 终点被改"（E_BLOCKOUT_WALK_PATH_MISMATCH），
    也查"同镜路线交叉或穿过站定角色"（E_BLOCKOUT_WALK_PATH_COLLISION）。
    """
    actual_routes = [
        dict(route) for route in (manifest.get("routes") or [])
        if isinstance(route, Mapping)
    ]
    expected_moves = _expected_move_ends(expected_shots)
    by_key: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for route in actual_routes:
        by_key[(str(route.get("character") or ""),
                str(route.get("shot_id") or ""))] = route

    def close(a: Sequence[float], b: Sequence[float]) -> bool:
        return (len(a) >= 2 and len(b) >= 2
                and math.hypot(a[0] - b[0], a[1] - b[1])
                <= WALK_PATH_COORD_TOL_M)

    problems: List[str] = []
    for move in expected_moves:
        route = by_key.get((move["character"], move["shot_id"]))
        if route is None:
            problems.append(
                f"{move['shot_id']} 角色 {move['character']} 计划声明走位但"
                " manifest.routes 无该路线")
            findings.append({
                "check_id": E_BLOCKOUT_WALK_PATH_MISMATCH,
                "shot_id": move["shot_id"], "severity": "error",
                "message": problems[-1],
            })
            continue
        actual_end = route.get("end")
        if not isinstance(actual_end, (list, tuple)) \
                or not close(actual_end, move["end"]):
            problems.append(
                f"{move['shot_id']} 角色 {move['character']} 路线终点"
                f"（{actual_end}）与计划指令（{move['end']}）不一致")
            findings.append({
                "check_id": E_BLOCKOUT_WALK_PATH_MISMATCH,
                "shot_id": move["shot_id"], "severity": "error",
                "message": problems[-1],
            })
    for route in actual_routes:
        matched = any(
            move["shot_id"] == route.get("shot_id")
            and move["character"] == route.get("character")
            for move in expected_moves)
        if not matched:
            problems.append(
                f"{route.get('shot_id')} 角色 {route.get('character')} 路线"
                " 不在计划 move 指令中（多出路线）")
            findings.append({
                "check_id": E_BLOCKOUT_WALK_PATH_MISMATCH,
                "shot_id": str(route.get("shot_id") or ""),
                "severity": "error", "message": problems[-1],
            })

    #: 同镜路线交叉 / 路线穿过站定角色（碰撞容差 D5=B）
    radii = _character_radii(manifest)
    rows_by_shot: Dict[str, List[Dict[str, Any]]] = {}
    for row in manifest.get("shot_table") or []:
        rows_by_shot.setdefault(str(row.get("shot_id") or ""), []).append(row)
    by_shot_routes: Dict[str, List[Dict[str, Any]]] = {}
    for route in actual_routes:
        by_shot_routes.setdefault(str(route.get("shot_id") or ""),
                                  []).append(route)
    for shot_id, routes in by_shot_routes.items():
        routes = [route for route in routes
                  if isinstance(route.get("start"), (list, tuple))
                  and isinstance(route.get("end"), (list, tuple))]
        for i, a_route in enumerate(routes):
            for b_route in routes[i + 1:]:
                a_name = str(a_route.get("character") or "")
                b_name = str(b_route.get("character") or "")
                distance = _route_distance_2d(
                    a_route["start"], a_route["end"],
                    b_route["start"], b_route["end"])
                limit = ((radii.get(a_name, 0.25) + radii.get(b_name, 0.25))
                         * WALK_PATH_COLLISION_FACTOR)
                if distance < limit:
                    problems.append(
                        f"{shot_id} 角色 {a_name} 与 {b_name} 路线交叉"
                        f"（最小距离 {distance:.3f} m < 容差 {limit:.3f} m）")
                    findings.append({
                        "check_id": E_BLOCKOUT_WALK_PATH_COLLISION,
                        "shot_id": shot_id, "severity": "error",
                        "message": problems[-1],
                    })
        standing = set()
        for row in rows_by_shot.get(shot_id, []):
            standing.update(str(name) for name
                            in (row.get("character_ids") or []))
        moving_names = {str(route.get("character") or "")
                        for route in routes}
        for route in routes:
            a_name = str(route.get("character") or "")
            for name in standing:
                if name == a_name or name in moving_names:
                    continue
                position = next(
                    (primitive.get("position")
                     for primitive in (manifest.get("primitives") or [])
                     if primitive.get("kind") == "character"
                     and (primitive.get("source") or {}).get("id") == name),
                    None)
                if not isinstance(position, Mapping) \
                        or position.get("x") is None:
                    continue
                distance = _point_segment_distance_2d(
                    (float(position["x"]), float(position["y"])),
                    route["start"], route["end"])
                limit = ((radii.get(a_name, 0.25) + radii.get(name, 0.25))
                         * WALK_PATH_COLLISION_FACTOR)
                if distance < limit:
                    problems.append(
                        f"{shot_id} 角色 {a_name} 路线穿过站定的 {name}"
                        f"（最小距离 {distance:.3f} m < 容差 {limit:.3f} m）")
                    findings.append({
                        "check_id": E_BLOCKOUT_WALK_PATH_COLLISION,
                        "shot_id": shot_id, "severity": "error",
                        "message": problems[-1],
                    })

    walk_findings = [f for f in findings if f["check_id"] in (
        E_BLOCKOUT_WALK_PATH_MISMATCH, E_BLOCKOUT_WALK_PATH_COLLISION)]
    return {
        "check_id": "walk_path", "shot_id": None,
        "actual": [dict(route) for route in actual_routes],
        "expected": [dict(move) for move in expected_moves],
        "threshold": f"逐段一致；碰撞容差=半径和×{WALK_PATH_COLLISION_FACTOR}",
        "verdict": "fail" if walk_findings else "pass",
        "note": "走位路线与计划逐段一致且不相交" if not walk_findings
        else f"{len(walk_findings)} 处走位路线与计划不符/相交",
    }


def _axis_continuity_check(manifest: Mapping[str, Any],
                           findings: List[Dict[str, Any]]) -> Dict[str, Any]:
    """跨镜机位 180° 轴连续性（复用 axis.camera_direction_findings）。"""
    positions: Dict[str, Tuple[float, float]] = {}
    for primitive in manifest.get("primitives") or []:
        if primitive.get("kind") != "character":
            continue
        source = primitive.get("source") or {}
        pos = primitive.get("position") or {}
        name = str(source.get("id") or "")
        if name and pos.get("x") is not None:
            positions[name] = (float(pos["x"]), float(pos["y"]))
    axis = camera_direction_findings(
        rows=list(manifest.get("shot_table") or []),
        cameras=list(manifest.get("cameras") or []),
        character_positions=positions)
    findings.extend(axis)
    return {
        "check_id": "axis_continuity", "shot_id": None,
        "actual": len(axis), "threshold": 0,
        "verdict": "fail" if axis else "pass",
        "note": "跨镜机位未静默越 180° 轴" if not axis
        else f"检测到 {len(axis)} 处越轴（无中性镜桥接）",
    }


def _framing_target_checks(per_shot: Sequence[Mapping[str, Any]],
                           expected_shots: Sequence[Mapping[str, Any]],
                           findings: List[Dict[str, Any]]
                           ) -> List[Dict[str, Any]]:
    """拍对象（角色/道具）落在画面内（复用缺陷 A 局部主体框口径）。

    粗排粒度：以目标体块的画面投影 inside_ratio 判在画/出画；证据缺失
    -> unresolved（不猜通过）。未声明拍对象 -> pass（不适用）。
    """
    checks: List[Dict[str, Any]] = []
    by_shot = {str(shot.get("shot_id") or ""): shot for shot in per_shot}
    declared = [shot for shot in expected_shots
                if isinstance(shot.get("framing_target"), Mapping)]
    if not declared:
        checks.append({
            "check_id": "framing_target", "shot_id": None,
            "actual": 0, "threshold": ON_SCREEN_MIN,
            "verdict": "pass",
            "note": "本场未声明拍对象（framing_target），不适用",
        })
        return checks
    for shot in declared:
        shot_id = str(shot.get("shot_id") or "")
        target = shot["framing_target"]
        responsibility = shot.get("responsibility")
        skip_white_model = (isinstance(responsibility, Mapping)
                             and bool(responsibility.get("skip_white_model")))
        reading = (by_shot.get(shot_id) or {}).get("framing_target")
        if not isinstance(reading, Mapping) \
                or reading.get("on_screen_ratio") is None \
                or reading.get("visible_ratio") is None:
            checks.append({
                "check_id": "framing_target", "shot_id": shot_id,
                "actual": None, "threshold": ON_SCREEN_MIN,
                "verdict": "pass" if skip_white_model else "unresolved",
                "note": (f"镜 {shot_id} skip_white_model 豁免拍对象投影/可见性检查"
                          if skip_white_model
                          else f"镜 {shot_id} 声明拍对象但预览无投影/可见性证据，不猜"),
            })
            if not skip_white_model:
                findings.append({
                    "check_id": E_BLOCKOUT_FRAMING_TARGET_UNRESOLVED,
                    "shot_id": shot_id, "severity": "error",
                    "message": (f"镜 {shot_id} 声明拍对象（{target.get('kind')}/"
                                f"{target.get('ref')}）但粗排预览无投影/可见性证据，"
                                f"计划与场景脱节，未修正不进入细排"),
                })
            continue
        ratio = float(reading["on_screen_ratio"])
        visible = float(reading["visible_ratio"])
        on_screen_ok = ratio >= ON_SCREEN_MIN
        visible_ok = visible >= VISIBLE_RATIO_MIN
        verdict = "pass" if on_screen_ok and visible_ok else "fail"
        checks.append({
            "check_id": "framing_target", "shot_id": shot_id,
            "actual": round(ratio, 4), "threshold": ON_SCREEN_MIN,
            "visible_ratio": round(visible, 4),
            "visible_threshold": VISIBLE_RATIO_MIN,
            "verdict": "pass" if skip_white_model else verdict,
            "note": (f"镜 {shot_id} skip_white_model 豁免拍对象投影/可见性检查"
                      if skip_white_model else
                      (f"镜 {shot_id} 拍对象（{target.get('kind')}/"
                       f"{target.get('ref')}）在画面内且真实可见"
                       if verdict == "pass"
            else f"镜 {shot_id} 拍对象（{target.get('kind')}/"
                 f"{target.get('ref')}）投影或可见性未过门")),
        })
        if not on_screen_ok and not skip_white_model:
            findings.append({
                "check_id": E_BLOCKOUT_FRAMING_TARGET_OFF_SCREEN,
                "shot_id": shot_id, "severity": "error",
                "message": (f"镜 {shot_id} 拍对象（{target.get('kind')}/"
                            f"{target.get('ref')}）投影占比 "
                            f"{ratio:.4f} < {ON_SCREEN_MIN}，不在画面内"),
            })
        if not visible_ok and not skip_white_model:
            findings.append({
                "check_id": E_BLOCKOUT_FRAMING_TARGET_OCCLUDED,
                "shot_id": shot_id, "severity": "error",
                "message": (f"镜 {shot_id} 拍对象（{target.get('kind')}/"
                            f"{target.get('ref')}）真实可见比例 "
                            f"{visible:.4f} < {VISIBLE_RATIO_MIN}，被遮挡"),
            })
    return checks


def _manifest_for_expected_scope(
    manifest: Mapping[str, Any],
    expected_shots: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    """Scope sequence/walk/axis checks without changing report identity.

    A detail candidate renders and measures one shot while retaining the full
    frozen manifest as its restore source.  The report must compare that
    measurement with the same one-shot scope; otherwise the unrendered rows
    look like missing shots.  The caller still supplies the full-manifest
    fingerprint, so observation identity remains tied to the complete world.
    """
    expected_ids = {
        str(shot.get("shot_id") or "")
        for shot in expected_shots
        if isinstance(shot, Mapping) and str(shot.get("shot_id") or "")
    }
    manifest_ids = {
        str(row.get("shot_id") or "")
        for key in ("cameras", "shot_table")
        for row in (manifest.get(key) or [])
        if isinstance(row, Mapping) and str(row.get("shot_id") or "")
    }
    if not expected_ids or manifest_ids == expected_ids:
        return manifest
    scoped = dict(manifest)
    for key in ("cameras", "shot_table", "routes"):
        rows = manifest.get(key)
        if isinstance(rows, list):
            scoped[key] = [
                row for row in rows
                if isinstance(row, Mapping)
                and str(row.get("shot_id") or "") in expected_ids
            ]
    return scoped


def build_blockout_report(*, manifest: Mapping[str, Any],
                          per_shot: List[Mapping[str, Any]],
                          manifest_fingerprint: str = "",
                          notes: List[str] | None = None,
                          expected: Any = None) -> Dict[str, Any]:
    """逐镜数值证据 -> BlockoutReport（确定性、可追溯）。

    ``per_shot`` 每项形状（由 bpy 冒烟侧填充，纯层只消费不生成）：
    ``{shot_id, composition_score, visible_ratio, on_screen_ratio,
    foreground_occlusion_ratio, max_subject_area_ratio,
    blocked, off_screen, design_diff, frames: [{frame, png}]}``。
    任何缺值 -> 对应 check verdict=unresolved（不猜）。
    """
    checks: List[Dict[str, Any]] = []
    findings: List[Dict[str, Any]] = []
    visual_states: List[Dict[str, Any]] = []
    #: R2 Ticket 10：skip_white_model（J3 分工）镜不产白模主体，主体存在性
    #: 类硬伤判据对它不适用——数值证据照记 check，但不进 error finding。
    expected_shots = plan_shot_dicts(expected) if expected is not None else []
    expected_by_shot = {
        str(shot.get("shot_id") or ""): shot for shot in expected_shots}
    report_manifest = _manifest_for_expected_scope(
        manifest, expected_shots)
    skip_by_shot = {
        str(shot.get("shot_id") or ""): shot
        for shot in expected_shots
        if isinstance(shot.get("responsibility"), Mapping)
        and bool(shot.get("responsibility", {}).get("skip_white_model"))
    }
    #: 取景意图豁免（R2 缺陷）：拍对象为道具（framing_target.kind=prop）或
    #: 角色的局部部位（character + part=hand/face）时，主体占满画幅是取景
    #: 构图本身（ECU 拍银币＝银币填满画面），不是"白模关系不可读"。面积
    #: 判据数值照记 check，但不产生面积溢出 hard finding；整身角色拍对象
    #: （part=none）与未声明拍对象的镜照旧按 55% 上限判。
    intent_by_shot = {
        str(shot.get("shot_id") or ""): shot.get("framing_target")
        for shot in expected_shots
        if isinstance(shot.get("framing_target"), Mapping)
    }

    for shot in per_shot:
        shot_id = str(shot.get("shot_id") or "?")
        skip_white_model = shot_id in skip_by_shot
        expected = expected_by_shot.get(shot_id)
        #: 取景意图豁免（与 subject_area 同源、同语义）：拍对象为道具
        #: （kind=prop）或角色局部部位（part=hand/face）时，粗排用整身/
        #: 道具体块采样的可见比与出画占比不是"空墙"的尺子——局部特写
        #: 相机贴得近，整身 box 大部分出画面或被同帧道具挡住，可见比
        #: 天然低于 0.5 会被误报 E_BLOCKOUT_EMPTY_WALL（final16
        #: shot_002/003 粗排 50 轮 retarget/strafe 死循环）。数值照记
        #: check、verdict 照判，但不产生空墙 error finding；整身角色
        #: 拍对象（part=none）与未声明拍对象的镜照旧按 0.5 硬门判。
        framing_intent = intent_by_shot.get(shot_id)
        intent_exempt = (isinstance(framing_intent, Mapping) and (
            str(framing_intent.get("kind") or "") == "prop"
            or (str(framing_intent.get("kind") or "") == "character"
                and str(framing_intent.get("part") or "none")
                not in {"", "none"})))
        #: R2 空计划漏洞（final5 实锤）：计划/剧本声明了拍对象（角色或
        #: 道具），但白模场景里没有任何对应体块——这不是"空镜合法"，而是
        #: 主体丢失（拍对象未建成/未解析）。此时**不得走空镜豁免**：记
        #: error finding 并继续按常规判据跑（缺数值如实 unresolved，不猜）。
        #: 注意：``intent_exempt`` 不豁免这一支——体块根本没建成是真实
        #: 硬伤（主体丢失），不是"尺子量错对象"。
        declared_subject = False
        if expected is not None:
            declared_subject = bool(
                expected.get("characters")
                and any(str(c) for c in expected.get("characters") or []))
            framing_target = expected.get("framing_target")
            if isinstance(framing_target, Mapping) and framing_target.get("ref"):
                declared_subject = True
        if shot.get("empty") and declared_subject:
            checks.append({
                "check_id": "declared_subject_empty",
                "shot_id": shot_id, "actual": 0, "threshold": 1,
                "verdict": "fail",
                "note": "计划声明拍对象但场景无主体体块，空镜豁免不适用",
            })
            findings.append({
                "check_id": E_BLOCKOUT_EMPTY_WALL, "shot_id": shot_id,
                "severity": "error",
                "message": ("计划声明拍对象（角色/道具）但白模场景未建成"
                            "对应体块，相机可能对准空墙"),
            })
        elif shot.get("empty"):
            #: 空镜合法：无被摄主体，不适用构图/遮挡/出入画/空墙判据；
            #: 显式记为 pass，避免"无证据"误判成 fail（也不猜数值）。
            checks.append({
                "check_id": "empty_shot", "shot_id": shot_id,
                "actual": 0, "threshold": 0, "verdict": "pass",
                "note": "空镜：无被摄主体，豁免构图/遮挡/出入画判据",
            })
            for frame in shot.get("frames") or []:
                visual_states.append({
                    "shot_id": shot_id,
                    "frame": int(frame.get("frame") or 0),
                    "png": str(frame.get("png") or ""),
                    "reviewed": False,
                })
            continue

        if skip_white_model:
            checks.append({
                "check_id": "skip_white_model", "shot_id": shot_id,
                "actual": 0, "threshold": 0, "verdict": "pass",
                "note": ("本镜分工声明 skip_white_model：不产白模主体，"
                         "豁免空墙/面积/拍对象硬伤判据（数值证据照记 check）"),
            })

        comp = shot.get("composition_score")
        if comp is None:
            checks.append({"check_id": "composition",
                           "shot_id": shot_id, "actual": None,
                           "threshold": COMPOSITION_PASS,
                           "verdict": "unresolved"})
        else:
            checks.append({"check_id": "composition", "shot_id": shot_id,
                           "actual": round(float(comp), 4),
                           "threshold": COMPOSITION_PASS,
                           "verdict": "pass" if composition_decision(comp)["status"]
                           == "pass"
                           else "fail"})

        visible = shot.get("visible_ratio")
        if visible is None:
            checks.append({"check_id": "occlusion", "shot_id": shot_id,
                           "actual": None, "threshold": VISIBLE_RATIO_MIN,
                           "verdict": "unresolved"})
        else:
            occlusion_verdict = ("pass"
                                 if float(visible) >= VISIBLE_RATIO_MIN
                                 else "fail")
            checks.append({"check_id": "occlusion", "shot_id": shot_id,
                           "actual": round(float(visible), 4),
                           "threshold": VISIBLE_RATIO_MIN,
                           "verdict": occlusion_verdict})
            if float(visible) < VISIBLE_RATIO_MIN \
                    and not skip_white_model and not intent_exempt:
                findings.append({
                    "check_id": E_BLOCKOUT_EMPTY_WALL, "shot_id": shot_id,
                    "severity": "error",
                    "message": ("主体可见比例低于阈值，相机可能对准空墙/"
                                "被完全遮挡"),
                })
            elif float(visible) < VISIBLE_RATIO_MIN and intent_exempt:
                checks[-1]["note"] = (
                    "拍对象为道具/局部部位，主体按取景意图取局部构图，"
                    "整身/道具体块可见比不构成空墙；数值照记 check，"
                    "verdict 照判，不进硬伤 finding")

        on_screen = shot.get("on_screen_ratio")
        if on_screen is None:
            checks.append({"check_id": "on_screen", "shot_id": shot_id,
                           "actual": None, "threshold": ON_SCREEN_MIN,
                           "verdict": "unresolved"})
        else:
            on_screen_verdict = ("pass"
                                 if float(on_screen) >= ON_SCREEN_MIN
                                 else "fail")
            checks.append({"check_id": "on_screen", "shot_id": shot_id,
                           "actual": round(float(on_screen), 4),
                           "threshold": ON_SCREEN_MIN,
                           "verdict": on_screen_verdict})
            if float(on_screen) < ON_SCREEN_MIN \
                    and not skip_white_model and not intent_exempt:
                #: 主体在画面内占比近零（含完全出画）-> 相机对准空墙；
                #: off_screen 只是附加观察，不降级这个硬伤。
                findings.append({
                    "check_id": E_BLOCKOUT_EMPTY_WALL, "shot_id": shot_id,
                    "severity": "error",
                    "message": "主体在画面内占比近零，疑似相机对准空墙",
                })
            elif float(on_screen) < ON_SCREEN_MIN and intent_exempt:
                checks[-1]["note"] = (
                    "拍对象为道具/局部部位，主体按取景意图取局部构图，"
                    "整身/道具体块出画占比不构成空墙；数值照记 check，"
                    "verdict 照判，不进硬伤 finding")

        foreground = shot.get("foreground_occlusion_ratio")
        if foreground is None:
            checks.append({"check_id": "foreground_occlusion",
                           "shot_id": shot_id, "actual": None,
                           "threshold": FOREGROUND_OCCLUSION_MAX,
                           "verdict": "unresolved"})
        else:
            foreground_value = float(foreground)
            foreground_verdict = (
                "pass" if foreground_value <= FOREGROUND_OCCLUSION_MAX
                else "fail")
            checks.append({"check_id": "foreground_occlusion",
                           "shot_id": shot_id,
                           "actual": round(foreground_value, 4),
                           "threshold": FOREGROUND_OCCLUSION_MAX,
                           "verdict": foreground_verdict})
            if foreground_verdict == "fail":
                findings.append({
                    "check_id": "E_FOREGROUND_OCCLUSION",
                    "shot_id": shot_id,
                    "severity": "error",
                    "message": ("非主体前景体块遮挡主体采样点超过 50%，"
                                "构图不可读；必须调整体块/机位后再审核"),
                    "occluders": [str(x) for x in
                                  (shot.get("foreground_occluders") or [])
                                  if x],
                })

        area = shot.get("max_subject_area_ratio")
        if area is None:
            checks.append({"check_id": "subject_area", "shot_id": shot_id,
                           "actual": None, "threshold": SUBJECT_AREA_MAX,
                           "verdict": "unresolved"})
        else:
            area_value = float(area)
            area_verdict = ("pass" if area_value <= SUBJECT_AREA_MAX
                            else "fail")
            checks.append({"check_id": "subject_area", "shot_id": shot_id,
                           "actual": round(area_value, 4),
                           "threshold": SUBJECT_AREA_MAX,
                           "verdict": area_verdict})
            if area_verdict == "fail" and not skip_white_model \
                    and not intent_exempt:
                findings.append({
                    "check_id": "E_SUBJECT_AREA_OVERFLOW",
                    "shot_id": shot_id, "severity": "error",
                    "message": ("主体投影面积超过画面 55%，白模关系不可读；"
                                "应拉远机位或退回多人构图求解"),
                })
            elif area_verdict == "fail" and intent_exempt:
                checks[-1]["note"] = (
                    "拍对象为道具/局部部位，主体占满画幅属取景意图；"
                    "面积数值照记 check，verdict 照判，不进硬伤 finding")

        if shot.get("off_screen"):
            findings.append({
                "check_id": OFF_SCREEN_LABEL, "shot_id": shot_id,
                "severity": "warning",
                "message": "主体完全出画（出入画 check）",
            })

        if "design_diff" in shot:
            diff = shot["design_diff"]
            checks.append({"check_id": "design_vs_observed",
                           "shot_id": shot_id,
                           "actual": diff.get("max_deviation_m")
                           if isinstance(diff, Mapping) else None,
                           "threshold": 0.3, "verdict": "pass"
                           if diff.get("max_deviation_m") is not None
                           and float(diff.get("max_deviation_m")) <= 0.3
                           else "fail" if diff.get("max_deviation_m") is not None
                           else "unresolved"})

        for frame in shot.get("frames") or []:
            empty_finding = empty_frame_finding(shot_id, frame)
            if empty_finding is not None:
                findings.append(empty_finding)
            visual_states.append({
                "shot_id": shot_id,
                "frame": int(frame.get("frame") or 0),
                "png": str(frame.get("png") or ""),
                "reviewed": False,
            })

    #: R10（Ticket 07）：粗排 gate 四类 check（actual == expected）。
    #: 只在管线提供 expected（plan）时追加；旧调用方零行为差。
    if expected is not None:
        checks.append(_shot_sequence_check(
            list(report_manifest.get("shot_table") or []),
            expected_shots, findings))
        checks.append(_walk_path_check(
            report_manifest, expected_shots, findings))
        checks.append(_axis_continuity_check(
            report_manifest, findings))
        checks.extend(_framing_target_checks(per_shot, expected_shots,
                                             findings))

    passed = all(c["verdict"] == "pass" for c in checks)
    return {
        "schema_version": BLOCKOUT_REPORT_SCHEMA,
        "manifest_fingerprint": str(manifest_fingerprint),
        "verdict": "pass" if passed and not
        [f for f in findings if f["severity"] == "error"] else "fail",
        "checks": checks,
        "findings": findings,
        "visual_states": visual_states,
        "notes": list(notes or []),
    }


__all__ = ["build_blockout_report", "BLOCKOUT_REPORT_SCHEMA",
           "E_BLOCKOUT_EMPTY_WALL", "E_EMPTY_FRAME", "is_uniform_frame",
           "empty_frame_finding", "COMPOSITION_PASS",
           "E_BLOCKOUT_SHOT_SEQUENCE_MISMATCH",
           "E_BLOCKOUT_WALK_PATH_MISMATCH",
           "E_BLOCKOUT_WALK_PATH_COLLISION",
           "E_BLOCKOUT_FRAMING_TARGET_OFF_SCREEN",
           "E_BLOCKOUT_FRAMING_TARGET_OCCLUDED",
           "E_BLOCKOUT_FRAMING_TARGET_UNRESOLVED",
           "E_BLOCKOUT_AXIS_FLIP", "plan_shot_dicts"]
