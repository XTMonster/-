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

from ..cinema.axis import (
    flipped_screen_directions,
    shared_characters,
    thirty_degree_violation,
)
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


def _crossed_the_axis(axis, character) -> bool:
    """这个角色是不是已经站到**轴线的另一侧**（相对已确立的基准侧）。

    只看角色**自己**站在哪：轴线上（``SIDE_UNKNOWN``）不算跨线——两人相对而立
    时单人机位本来就落在轴线上（§6.2 的 `axis_neutral`）。
    """
    root = getattr(character, "root", None)
    if root is None or axis is None:
        return False
    side = axis.side_of((float(root.matrix_world.translation.x),
                         float(root.matrix_world.translation.y)))
    return side != 0 and side != int(axis.established_side)


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
            #: 与构建器**同一个**折帧函数（单一真源）：动作被夹进它自己那一镜，
            #: 否则这里会报出场景里并不存在的"跨镜重叠"（实测 run8：64/64 镜、
            #: 487 条 R003，样例是 shot_055 的动作"溢出"到 shot_056）。
            from ..cinema.schedule import action_frame_window

            absolute_start, absolute_end = action_frame_window(
                start, int(shot.duration_frames), int(raw.get("start_frame") or 1),
                int(raw.get("end_frame") or shot.duration_frames))
            label = f"{shot.shot_id}#{index} {raw.get('action_type')}"
            ranges.setdefault(character_id, []).append(
                (absolute_start, absolute_end, label))
    return ranges


def _overlapping_pairs(items: List[Tuple[int, int, str]]):
    ordered = sorted(items)
    for index, (start_a, end_a, label_a) in enumerate(ordered):
        for start_b, end_b, label_b in ordered[index + 1:]:
            if start_b < end_a and start_b <= end_b:
                yield label_a, label_b


@main_thread_only("check_shot")
def shot_frame_span(shot_id: str, context=None) -> Tuple[int, int]:
    """这一镜在时间轴上的 ``(起, 止)``；拿不到就退回 ``(1, 1)``。

    带运镜的镜头在不同帧上的机位不同，规则必须说明"在**哪一帧**上判"。
    """
    context = context or get_context()
    if context is not None:
        span = context.schedule.get(shot_id)
        if span:
            return int(span[0]), int(span[1])
    return 1, 1


def audit_frames(shot_id: str, context=None) -> List[int]:
    """镜头首 / 中 / 尾三帧（去重，单帧镜头只返回一帧）。"""
    start, end = shot_frame_span(shot_id, context)
    middle = start + max((end - start) // 2, 0)
    return sorted({int(start), int(middle), int(end)})


def screen_facing_for(shot, *, context=None, camera=None):
    """本镜**显式声明**的每个角色在屏幕上的朝向（相机右轴的投影点积）。

    v1.4 §3.4：R012（同框正反打）与新增的 R019（银幕方向连续性）**共用**这一
    份计算，不再各自算一遍局部变量。返回值是 ``{character_id: dot}``：
    ``dot > 0`` 表示角色朝向画面右侧，``< 0`` 朝左，``≈ 0`` 中性。

    只统计 ``shot.characters`` 里**显式声明**、且真的在场景里的角色——
    v1.3 的 R012 走 ``SceneContext.subjects_for``，后者在镜头没写角色时
    回退成整个剧组（X9），于是"没声明角色"的空镜也会被拉进正反打判定。
    """
    from .character_system import get_facing

    if shot is None or context is None:
        return {}
    camera = camera or context.camera_for(getattr(shot, "shot_id", ""))
    if camera is None:
        return {}
    right = camera.matrix_world.to_quaternion() @ Vector((1.0, 0.0, 0.0))
    flat_right = Vector((right.x, right.y, 0.0))
    if flat_right.length <= 1e-6:
        return {}
    flat_right.normalize()
    result: Dict[str, float] = {}
    for character_id in (getattr(shot, "characters", None) or []):
        character = context.character(character_id)
        if character is None:
            continue
        facing = get_facing(character)
        flat = Vector((float(facing[0]), float(facing[1]), 0.0))
        if flat.length <= 1e-6:
            continue
        flat.normalize()
        result[str(character_id)] = flat.dot(flat_right)
    return result


@main_thread_only("check_shot")
def check_shot(shot_id: str, *, context=None,
               composition_threshold: float = 70.0,
               strict: bool = False) -> AuditResult:
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
    # v1.3：带运镜的镜头在不同帧上机位不同，规则必须说明判在哪一帧。
    # 判定统一落在**本镜首帧**，构图的通过门槛再额外取首/中/尾的最小值
    # （详见下方），结束后把帧号还原，绝不把审核的副作用留给渲染。
    original_frame = int(scene.frame_current)
    frame_start, frame_end = shot_frame_span(shot_id, context)
    if frame_start != original_frame:
        scene.frame_set(frame_start)
    bpy.context.view_layer.update()

    shot = context.shot(shot_id) if context else None
    camera = context.camera_for(shot_id) if context else None
    shot_type = context.shot_types.get(shot_id, "MS") if context else "MS"

    def finish(result: AuditResult) -> AuditResult:
        """规则评估完必须还原帧号——审核不该改变场景的状态。"""
        if scene.frame_current != original_frame:
            scene.frame_set(original_frame)
            bpy.context.view_layer.update()
        return result

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
        return finish(AuditResult.from_findings(findings, target=shot_id))

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
            #: 把**根因**说清楚（2026-10-04 实测）：这条错误有两种完全不同的来源——
            #: ① 机位自己摆错（把机位移回去就行）；② **角色走位跨过了轴线**，
            #: 于是"要拍到这张脸"与"待在轴线同侧"不可能同时满足（`station._honour_
            #: the_established_side` 的边界就是这种情况：镜像会把正面变成背拍，
            #: 所以它保持模型要的方向、把冲突留给 R001 如实报）。修复回路按旧文案
            #: 只会去挪机位，白烧回合；这里点出"谁已经站到另一侧"。
            crossed = [character.id for character in characters
                       if _crossed_the_axis(context.axis, character)]
            if crossed:
                message += ("（{} 已经站到轴线的另一侧：这一镜的走位跨线，"
                            "只挪机位修不动——请改这一镜的走位或机位角度，"
                            "或按 §6.2 插入中性镜头过渡）"
                            .format("、".join(crossed)))
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
        else:
            # v1.4 BW-4a：R008 必须是**双向**的。旧实现只看 root.z < -0.02，
            # 于是"站立的角色根节点被抬到地面上方"这种**悬空**完全抓不到
            # （BW-4 的现象就是它）。这里用网格的实际最低点判上界。
            box = _character_aabb(character)
            if box is not None and box.minimum[2] > GROUND_EPS:
                findings.append(_warning(
                    "R008", "E_SPACE_001",
                    f"角色 {character.id} 悬空：网格最低点 z="
                    f"{box.minimum[2]:.3f} 高于地面 {GROUND_EPS}",
                    target=character.id,
                    suggestion="把站姿的末关键帧写回绝对地面（z=0）"))
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

    # R012 视线匹配（v1.3）：两人同框时必须形成正反打 ------------------------
    # v1.4 X9：只算**本镜显式声明**的角色（不再回退全剧组）。
    declared = [str(item) for item in (shot.characters if shot else [])]
    facing_map = screen_facing_for(shot, context=context, camera=camera)
    if len(declared) == 2 and len(facing_map) == 2:
        values = [facing_map[cid] for cid in declared]
        if values[0] * values[1] > 0:
            findings.append(_warning(
                "R012", "E_CAM_001",
                f"两人同框但屏幕朝向同号（{values[0]:+.2f} / "
                f"{values[1]:+.2f}），没有形成正反打",
                target=shot_id,
                suggestion="让两人相对而立（face_character），或改用单人镜"))
        heights = []
        for character_id in declared:
            head = getattr(context.character(character_id), "head_pivot", None) \
                if context is not None else None
            if head is not None:
                heights.append(head.matrix_world.translation.z)
        if len(heights) == 2 and abs(heights[0] - heights[1]) > 0.15:
            findings.append(_warning(
                "R012", "E_CAM_001",
                f"两人眼高差 {abs(heights[0] - heights[1]):.2f} m 超过 0.15 m，"
                f"正反打会看出高低差",
                target=shot_id, suggestion="把两人放在同一地面高度上"))

    # R019 银幕方向连续性（v1.4 §3.4，替代死字段 screen_direction） -----------
    # 相邻两镜、**同一角色**、且**两镜都显式声明了该角色**：屏幕朝向符号翻转
    # 且中间没有中性机位 → 观众会看到角色突然换边（越轴）。只在一镜里声明的
    # 角色**不参与**判定（负例见 RK-19）。
    if shot is not None and context is not None and context.plan is not None:
        order = [s.shot_id for s in context.plan.shots]
        if shot_id in order and order.index(shot_id) > 0:
            previous = context.plan.shots[order.index(shot_id) - 1]
            shared = shared_characters(previous.characters or [],
                                       shot.characters or [])
            previous_camera = context.camera_for(previous.shot_id)
            if shared and previous_camera is not None:
                previous_start, _ = shot_frame_span(previous.shot_id, context)
                scene.frame_set(previous_start)
                bpy.context.view_layer.update()
                previous_facing = screen_facing_for(previous, context=context,
                                                    camera=previous_camera)
                previous_neutral = (context.axis is not None
                                    and check_camera_neutral(context.axis,
                                                             previous_camera))
                scene.frame_set(frame_start)
                bpy.context.view_layer.update()
                if not (previous_neutral or neutral_here):
                    for character_id in flipped_screen_directions(
                            previous_facing, facing_map, shared):
                        before = previous_facing[character_id]
                        now = facing_map[character_id]
                        findings.append((_error if strict else _warning)(
                            "R019", "E_AXIS_001",
                            f"{character_id} 的银幕方向在第 "
                            f"{previous.shot_id} 与 {shot_id} 之间翻转"
                            f"（{before:+.2f} → {now:+.2f}），且中间没有"
                            f"中性机位过渡",
                            target=shot_id,
                            suggestion="让该角色保持同一侧，或插入一个"
                                       "中性（骑轴）机位再换边"))

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
        # v1.3：在**首帧**评估。带运镜的镜头其余帧的机位是刻意变化的，
        # 拿它们去比"景别期望距离"只会把合法的运动判成错误。
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
                # v1.3：两个镜头各自取**自己首帧**的机位。带运镜时拿同一帧
                # 比较等于在比两个不相干的时刻，30° 规则会得出错误结论。
                previous_start, _ = shot_frame_span(previous_id, context)
                scene.frame_set(previous_start)
                bpy.context.view_layer.update()
                previous_position = \
                    previous_camera.matrix_world.translation.copy()
                previous_neutral = (context.axis is not None
                                    and check_camera_neutral(context.axis,
                                                             previous_camera))
                scene.frame_set(frame_start)
                bpy.context.view_layer.update()
                message = thirty_degree_violation(
                    previous_position,
                    camera.matrix_world.translation, center,
                    context.shot_types.get(previous_id, "MS"), shot_type)
                if message:
                    findings.append(_warning(
                        "R010", "E_AXIS_001", message, target=shot_id,
                        suggestion="改变机位角度，或至少变化一档景别"))
                # 连续中性镜头：单次中性是合法桥梁，连着用就没有左右关系了。
                if neutral_here and previous_neutral:
                    findings.append(_warning(
                        "R001", "E_AXIS_001",
                        f"{previous_id} 与 {shot_id} 都是中性机位（落在轴线上），"
                        f"连续使用会让观众失去左右关系的连续性",
                        target=shot_id,
                        suggestion="至少给其中一镜一个明确的轴线侧别"))

    # 构图质量门（§7.1 B3 把构图列为通过条件） -----------------------------
    composition = None
    if characters:
        # v1.3：取首 / 中 / 尾三帧的**最小值**。只看首帧，运镜后段把主体
        # 挤出画面的镜头照样能通过——那正是"运动"最容易出事的地方。
        if frame_start != frame_end:
            scene.frame_set(frame_start)
            bpy.context.view_layer.update()
        worst = None
        for sample in audit_frames(shot_id, context):
            scene.frame_set(sample)
            bpy.context.view_layer.update()
            report = evaluate_camera_composition(camera, characters,
                                                 shot_type=shot_type)
            if worst is None or report.score < worst.score:
                worst = report
        composition = worst
        if composition is not None and composition.score < composition_threshold:
            detail = "；".join(composition.suggestions[:2]) or "请调整构图"
            findings.append(_error(
                "COMPOSITION", "E_CAM_001",
                f"构图评分 {composition.score:.1f}（首/中/尾最小值）低于阈值 "
                f"{composition_threshold:.0f}",
                target=shot_id, suggestion=detail))

    return finish(AuditResult.from_findings(
        findings, target=shot_id,
        score=composition.score if composition else None))
