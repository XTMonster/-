"""SDL 结构校验（执行文档 v1.2 §5.2 的七条规则）。

纯计算：不碰 bpy，因此能在存储前后各校验一次。
"""

from __future__ import annotations

from typing import Dict, List, Set, Tuple

from ..contracts.audit import AuditError
from ..contracts.enums import Severity
from ..contracts.sdl import SDLProject
from ..layer1_input.dialogue_timing import DIALOGUE_TAIL_FRAMES
from ..utils.aabb import AABB

WALL_MARGIN = 0.2
CHARACTER_BOX = (0.5, 0.5, 1.45)
CAMERA_BOX = (0.2, 0.2, 0.2)


def _error(rule: str, code: str, message: str, target: str = "",
           suggestion: str = "") -> AuditError:
    return AuditError(rule=rule, code=code, severity=Severity.ERROR,
                      target=target, message=message, suggestion=suggestion)


def _warning(rule: str, code: str, message: str, target: str = "",
             suggestion: str = "") -> AuditError:
    return AuditError(rule=rule, code=code, severity=Severity.WARNING,
                      target=target, message=message, suggestion=suggestion)


def _check_references(sdl: SDLProject, findings: List[AuditError]) -> None:
    known: Set[str] = {member.id for member in sdl.characters}
    for scene in sdl.scenes:
        for shot in scene.shots:
            for character_id in shot.characters:
                if character_id not in known:
                    findings.append(_error(
                        "S2", "E_SDL_001",
                        f"镜头 {shot.id} 引用了未定义角色 {character_id}",
                        target=shot.id, suggestion="补进 characters，或改用在场角色"))
            for action in shot.actions:
                character_id = str(action.get("character_id") or "")
                if character_id and character_id not in known:
                    findings.append(_error(
                        "S2", "E_SDL_001",
                        f"镜头 {shot.id} 的动作引用了未定义角色 {character_id}",
                        target=shot.id, suggestion="修正动作的 character_id"))
            for dialogue in shot.dialogues:
                character_id = str(dialogue.get("character_id") or "")
                if character_id and character_id not in known:
                    findings.append(_error(
                        "S2", "E_SDL_001",
                        f"镜头 {shot.id} 的对白引用了未定义角色 {character_id}",
                        target=shot.id, suggestion="修正对白的 character_id"))


def _check_shot_timing(shot, findings: List[AuditError]) -> None:
    if shot.duration_frames <= 0:
        findings.append(_error(
            "S5", "E_SDL_001",
            f"镜头 {shot.id} 时长非法：{shot.duration_frames}",
            target=shot.id, suggestion="时长必须为正整数帧"))
    if shot.start_frame and shot.end_frame:
        if shot.end_frame <= shot.start_frame:
            findings.append(_error(
                "S5", "E_SDL_001",
                f"镜头 {shot.id} 的帧范围非法：{shot.start_frame}-{shot.end_frame}",
                target=shot.id, suggestion="end 必须大于 start"))
        elif shot.duration_frames and \
                shot.end_frame - shot.start_frame + 1 != shot.duration_frames:
            findings.append(_error(
                "S5", "E_SDL_001",
                f"镜头 {shot.id} 的时长与帧范围不一致"
                f"（{shot.duration_frames} vs "
                f"{shot.end_frame - shot.start_frame + 1}）",
                target=shot.id, suggestion="以 duration_frames 为唯一真源重新排片"))

    latest = 0
    for dialogue in shot.dialogues:
        latest = max(latest, int(dialogue.get("end_frame") or 0))
    if latest and latest + DIALOGUE_TAIL_FRAMES > shot.duration_frames:
        findings.append(_error(
            "S6", "E_SDL_001",
            f"镜头 {shot.id} 装不下对白：最晚第 {latest} 帧 + "
            f"{DIALOGUE_TAIL_FRAMES} 帧余量 > {shot.duration_frames} 帧",
            target=shot.id, suggestion="加长镜头或前移对白"))

    ranges: Dict[str, List[Tuple[int, int]]] = {}
    for action in shot.actions:
        character_id = str(action.get("character_id") or "")
        start = int(action.get("start_frame") or 1)
        end = int(action.get("end_frame") or shot.duration_frames)
        for other_start, other_end in ranges.get(character_id, []):
            if start < other_end and other_start < end:
                findings.append(_error(
                    "S3", "E_SDL_001",
                    f"角色 {character_id} 在镜头 {shot.id} 内动作重叠"
                    f"（{other_start}-{other_end} 与 {start}-{end}）",
                    target=shot.id, suggestion="错开起止帧"))
        ranges.setdefault(character_id, []).append((start, end))


def _check_spatial(scene, sdl: SDLProject, findings: List[AuditError]) -> None:
    walls = scene.environment.walls or []
    if not walls:
        return
    wall_boxes = [AABB.from_center_size(wall.get("position", (0, 0, 0)),
                                        wall.get("size", (1, 1, 1)))
                  for wall in walls]
    for member in sdl.characters:
        box = AABB.from_center_size(member.initial_location, CHARACTER_BOX)
        for index, wall_box in enumerate(wall_boxes, start=1):
            if box.overlaps(wall_box, margin=WALL_MARGIN):
                findings.append(_error(
                    "S4", "E_SPACE_001",
                    f"角色 {member.id} 与第 {index} 面墙穿模",
                    target=member.id, suggestion="挪开角色或调整墙体"))
    for shot in scene.shots:
        if not shot.camera.position:
            continue
        box = AABB.from_center_size(shot.camera.position, CAMERA_BOX)
        for index, wall_box in enumerate(wall_boxes, start=1):
            if box.overlaps(wall_box, margin=WALL_MARGIN):
                findings.append(_error(
                    "S4", "E_SPACE_001",
                    f"镜头 {shot.id} 的相机与第 {index} 面墙穿模",
                    target=shot.id, suggestion="把机位移进房间内"))


def _check_scene_totals(scene, findings: List[AuditError]) -> int:
    """回填缺失的帧号，并校验总时长自洽（规则 7）。"""
    cursor = 1
    total = 0
    for shot in scene.shots:
        duration = max(shot.duration_frames, 1)
        if not shot.start_frame or not shot.end_frame:
            shot.start_frame = cursor
            shot.end_frame = cursor + duration - 1
        cursor = (shot.end_frame or cursor) + 1
        total += duration
    if total != scene.total_frames:
        findings.append(_error(
            "S7", "E_SDL_001",
            f"场景 {scene.id} 的镜头时长合计 {total} 与声明 {scene.total_frames} 不一致",
            target=scene.id, suggestion="以各镜 duration_frames 之和为准"))
    return total


def validate_sdl(sdl: SDLProject) -> List[AuditError]:
    """返回全部问题；空列表表示 SDL 可用。"""
    findings: List[AuditError] = []

    if not sdl.scenes:
        findings.append(_error("S1", "E_SDL_001", "SDL 里没有任何场景",
                               suggestion="至少需要一个场景与一个镜头"))
    if sdl.fps <= 0:
        findings.append(_error("S1", "E_SDL_001", f"帧率非法：{sdl.fps}",
                               suggestion="帧率必须为正整数"))
    if not sdl.version:
        findings.append(_warning("S1", "E_SDL_002", "SDL 缺少版本号",
                                 suggestion="写入 version 字段以便将来迁移"))

    _check_references(sdl, findings)
    for scene in sdl.scenes:
        for shot in scene.shots:
            _check_shot_timing(shot, findings)
        _check_scene_totals(scene, findings)
        _check_spatial(scene, sdl, findings)
    return findings
