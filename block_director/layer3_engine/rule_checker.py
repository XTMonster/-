"""Level 1 确定性规则校验（执行文档 v1.2 §11.1）。

零延迟、不可跳过，返回结构化 :class:`AuditError` 供定向修复回灌（§18.3）。

已实现：R001 轴线、R004 视锥、R005 在画、R006 帧范围、R007 引用、
R002 空间碰撞、R003 动作时间轴、R008 地面、R009 景别距离、R010 30° 规则，
以及构图质量门（§7.1 B3 明确把"构图"列为通过条件，因此低于阈值按 ERROR
处理，而不是只给警告）。

**待补（依赖 Layer 1）**：R011 对白容纳——它需要对白计时（§4.4），而计划里
目前只带 dialogue_ids、不带对白的时间轴。
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

from ..cinema.axis import thirty_degree_violation
from ..cinema.framing import SHOT_FRAME, required_distance
from ..layer1_input.dialogue_timing import DIALOGUE_TAIL_FRAMES
from ..contracts.audit import AuditError, AuditResult
from ..contracts.enums import Severity
from ..utils.aabb import AABB, union
from ..utils.logger import get_logger
from ..utils.threading_guard import main_thread_only

log = get_logger("rules")

GROUND_EPS = 0.02
DISTANCE_TOLERANCE = 0.25
FRAME_MARGIN = 0.05
COLLISION_MARGIN = 0.2
OBSTACLE_PREFIXES = ("BD_Wall_", "BD_Prop_")


def _finding(severity: Severity, rule: str, code: str, message: str,
             target: str = "", suggestion: str = "") -> AuditError:
    return AuditError(rule=rule, code=code, severity=severity, target=target,
                      message=message, suggestion=suggestion)


def _error(rule: str, code: str, message: str, target: str = "",
           suggestion: str = "") -> AuditError:
    return _finding(Severity.ERROR, rule, code, message, target, suggestion)


def _warning(rule: str, code: str, message: str, target: str = "",
             suggestion: str = "") -> AuditError:
    return _finding(Severity.WARNING, rule, code, message, target, suggestion)


def _in_frame(point) -> bool:
    return (-FRAME_MARGIN <= point.x <= 1.0 + FRAME_MARGIN
            and -FRAME_MARGIN <= point.y <= 1.0 + FRAME_MARGIN)


def _character_positions(characters):
    positions = []
    for character in characters:
        root = getattr(character, "root", None)
        if root is not None:
            positions.append(root.matrix_world.translation.copy())
    return positions


def _world_aabb(obj) -> AABB:
    corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    return AABB(minimum=(min(c.x for c in corners), min(c.y for c in corners),
                         min(c.z for c in corners)),
                maximum=(max(c.x for c in corners), max(c.y for c in corners),
                         max(c.z for c in corners)))


def _character_aabb(character):
    boxes = [_world_aabb(obj) for obj in getattr(character, "meshes", [])
             if obj.type == "MESH"]
    return union(boxes) if boxes else None


def _obstacles() -> Dict[str, AABB]:
    """墙体与道具的包围盒（按 §21.1 命名约定识别）。"""
    found: Dict[str, AABB] = {}
    for obj in bpy.data.objects:
        if obj.type != "MESH" or obj.hide_render:
            continue
        if obj.name.startswith(OBSTACLE_PREFIXES):
            found[obj.name] = _world_aabb(obj)
    return found


def _action_ranges(context) -> Dict[str, List[Tuple[int, int, str]]]:
    """逐角色的全局动作区间：``{character_id: [(start, end, label)]}``。"""
    ranges: Dict[str, List[Tuple[int, int, str]]] = {}
    if context is None or context.plan is None:
        return ranges
    for shot in context.plan.shots:
        start, end = context.schedule.get(shot.shot_id, (1, shot.duration_frames))
        for index, raw in enumerate(shot.actions or [], start=1):
            if not isinstance(raw, dict):
                continue
            character_id = str(raw.get("character_id") or "")
            if not character_id:
                continue
            local_start = int(raw.get("start_frame") or 1)
            local_end = int(raw.get("end_frame") or shot.duration_frames)
            label = f"{shot.shot_id}#{index} {raw.get('action_type')}"
            ranges.setdefault(character_id, []).append(
                (start + local_start - 1, start + local_end - 1, label))
    return ranges


def _overlapping_pairs(items: List[Tuple[int, int, str]]):
    ordered = sorted(items)
    for index, (start_a, end_a, label_a) in enumerate(ordered):
        for start_b, end_b, label_b in ordered[index + 1:]:
            if start_b < end_a and start_b <= end_b:
                yield label_a, label_b


@main_thread_only("check_shot")
def check_shot(shot_id: str, *, context=None,
               composition_threshold: float = 70.0) -> AuditResult:
    """对单个镜头跑全部已实现的 Level 1 规则。"""
    from .cinema_engine import (
        check_camera_axis,
        check_camera_neutral,
        evaluate_camera_composition,
    )
    from .scene_context import get_context

    context = context or get_context()
    scene = bpy.context.scene
    findings: List[AuditError] = []
    bpy.context.view_layer.update()

    shot = context.shot(shot_id) if context else None
    camera = context.camera_for(shot_id) if context else None
    shot_type = context.shot_types.get(shot_id, "MS") if context else "MS"

    # 判定必须基于**本镜头的角色**：特写镜头不该因为"另一个角色不在画里"
    # 而被判失败（Phase 5 首次跑 R003 的回归测试时就踩到了这个）。
    characters = []
    if shot is not None and context is not None:
        characters = context.subjects_for(shot_id)
    elif context is not None:
        characters = context.character_list

    # R007 引用完整 ---------------------------------------------------------
    for character_id in (shot.characters if shot else []):
        if context is None or context.character(character_id) is None:
            findings.append(_error(
                "R007", "E_SDL_001", f"镜头引用了不存在的角色 {character_id}",
                target=shot_id, suggestion="改用在场角色，或先把该角色加入场景"))
    if camera is None:
        findings.append(_error(
            "R007", "E_SDL_001", "该镜头没有可用相机", target=shot_id,
            suggestion="用 setup_camera 为该镜头建立机位"))
        return AuditResult.from_findings(findings, target=shot_id)

    # R006 帧范围 -----------------------------------------------------------
    if shot is not None and shot.duration_frames <= 0:
        findings.append(_error(
            "R006", "E_SDL_001",
            f"镜头时长非法：{shot.duration_frames} 帧", target=shot_id,
            suggestion="时长必须为正整数帧"))

    # R001 轴线合规 ---------------------------------------------------------
    neutral_here = False
    if context is not None and context.axis is not None:
        message = check_camera_axis(context.axis, camera)
        if message:
            findings.append(_error(
                "R001", "E_AXIS_001", message, target=shot_id,
                suggestion="将相机移到轴线另一侧，或插入中性镜头过渡"))
        # 中性机位（正好落在轴线上）不是越轴：§6.2 的 axis_neutral 卡片把它
        # 定义为合法的跨轴桥梁，而且两人相对而立时单人正反打的机位必然落在
        # 轴线上。v1.2 把它判成 R001 错误，等于让这类镜头永远无法通过审核。
        neutral_note = check_camera_neutral(context.axis, camera)
        if neutral_note:
            neutral_here = True
            findings.append(_warning(
                "R001", "E_AXIS_001", neutral_note, target=shot_id,
                suggestion="需要明确左右关系时把机位移离轴线；"
                           "中性机位适合作为跨轴过渡，不宜连续使用"))

    positions = _character_positions(characters)

    # R008 地面约束 + R005 角色在画 -----------------------------------------
    for character in characters:
        root = getattr(character, "root", None)
        if root is None:
            continue
        if root.matrix_world.translation.z < -GROUND_EPS:
            findings.append(_warning(
                "R008", "E_SPACE_001",
                f"角色 {character.id} 位于地面以下"
                f"（z={root.matrix_world.translation.z:.3f}）",
                target=character.id, suggestion="把角色抬回 z ≥ 0"))
        point = world_to_camera_view(scene, camera,
                                     root.matrix_world.translation
                                     + Vector((0.0, 0.0, 0.9)))
        if not _in_frame(point):
            findings.append(_warning(
                "R005", "E_CAM_001",
                f"角色 {character.id} 不在画面内"
                f"（屏幕 {point.x:.2f}, {point.y:.2f}）",
                target=character.id,
                suggestion="调整机位，或让角色回到画面内"))

    # R004 相机视锥 ---------------------------------------------------------
    center = None
    if positions:
        center = sum(positions, Vector()) / len(positions)
        target_point = world_to_camera_view(scene, camera,
                                            center + Vector((0.0, 0.0, 0.9)))
        if not _in_frame(target_point):
            findings.append(_warning(
                "R004", "E_CAM_001", "镜头对准点落在相机视锥之外",
                target=shot_id, suggestion="重新对准被摄主体"))

    # R002 空间碰撞（角色 vs 墙体/道具，AABB 膨胀 0.2） --------------------
    obstacles = _obstacles()
    for character in characters:
        box = _character_aabb(character)
        if box is None:
            continue
        for name, obstacle_box in obstacles.items():
            if box.overlaps(obstacle_box, margin=COLLISION_MARGIN):
                findings.append(_error(
                    "R002", "E_SPACE_001",
                    f"角色 {character.id} 与 {name} 发生穿模",
                    target=character.id,
                    suggestion=f"把 {character.id} 移开，或缩小 {name} / 调整摆位"))

    # R003 动作时间轴（同一角色的动作不得重叠） ----------------------------
    for character_id, items in _action_ranges(context).items():
        if shot is not None and shot.characters \
                and character_id not in shot.characters:
            continue
        for label_a, label_b in _overlapping_pairs(items):
            findings.append(_error(
                "R003", "E_SDL_001",
                f"角色 {character_id} 的动作时间重叠：{label_a} 与 {label_b}",
                target=character_id,
                suggestion="同一个角色的动作必须串行，请错开起止帧"))

    # R011 对白容纳：镜头时长必须装得下最晚的一句对白 + 收尾余量 -----------
    if shot is not None and shot.dialogues:
        latest = 0
        for item in shot.dialogues:
            if not isinstance(item, dict):
                continue
            latest = max(latest, int(item.get("end_frame") or 0))
        if latest and latest + DIALOGUE_TAIL_FRAMES > shot.duration_frames:
            findings.append(_error(
                "R011", "E_SDL_001",
                f"对白排到第 {latest} 帧，加上 {DIALOGUE_TAIL_FRAMES} 帧收尾余量"
                f"超出镜头时长 {shot.duration_frames} 帧",
                target=shot_id,
                suggestion="加长该镜头，或把对白前移/删减"))

    # R009 镜头距离与景别匹配 ----------------------------------------------
    frame = SHOT_FRAME.get(str(shot_type).upper())
    if frame is not None and center is not None:
        actual = (camera.matrix_world.translation - center).length
        expected = required_distance(frame.frame_height, float(camera.data.lens))
        if expected > 0 and abs(actual - expected) / expected > DISTANCE_TOLERANCE:
            findings.append(_warning(
                "R009", "E_CAM_001",
                f"机位距离 {actual:.2f} 与 {shot_type} 的期望距离 "
                f"{expected:.2f} 相差超过 {DISTANCE_TOLERANCE:.0%}",
                target=shot_id, suggestion="按景别重新取景（setup_camera）"))

    # R010 30° 规则 ---------------------------------------------------------
    if context is not None and context.plan is not None and center is not None:
        order = [s.shot_id for s in context.plan.shots]
        if shot_id in order and order.index(shot_id) > 0:
            previous_id = order[order.index(shot_id) - 1]
            previous_camera = context.camera_for(previous_id)
            if previous_camera is not None:
                message = thirty_degree_violation(
                    previous_camera.matrix_world.translation,
                    camera.matrix_world.translation, center,
                    context.shot_types.get(previous_id, "MS"), shot_type)
                if message:
                    findings.append(_warning(
                        "R010", "E_AXIS_001", message, target=shot_id,
                        suggestion="改变机位角度，或至少变化一档景别"))
                # 连续中性镜头：单次中性是合法桥梁，连着用就没有左右关系了。
                if (neutral_here and context.axis is not None
                        and check_camera_neutral(context.axis,
                                                 previous_camera)):
                    findings.append(_warning(
                        "R001", "E_AXIS_001",
                        f"{previous_id} 与 {shot_id} 都是中性机位（落在轴线上），"
                        f"连续使用会让观众失去左右关系的连续性",
                        target=shot_id,
                        suggestion="至少给其中一镜一个明确的轴线侧别"))

    # 构图质量门（§7.1 B3 把构图列为通过条件） -----------------------------
    composition = None
    if characters:
        composition = evaluate_camera_composition(camera, characters,
                                                  shot_type=shot_type)
        if composition.score < composition_threshold:
            detail = "；".join(composition.suggestions[:2]) or "请调整构图"
            findings.append(_error(
                "COMPOSITION", "E_CAM_001",
                f"构图评分 {composition.score:.1f} 低于阈值 "
                f"{composition_threshold:.0f}",
                target=shot_id, suggestion=detail))

    return AuditResult.from_findings(
        findings, target=shot_id,
        score=composition.score if composition else None)
