"""SDL 结构校验（执行文档 v1.2 §5.2 的七条规则）。

纯计算：不碰 bpy，因此能在存储前后各校验一次。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from ..contracts.audit import AuditError
from ..contracts.enums import CROWD_MODES, VFX_TYPES, Severity
from ..contracts.sdl import SDLProject
from ..cinema.anchor import DEFAULT_PROFILE
from ..layer1_input.dialogue_timing import DIALOGUE_TAIL_FRAMES
from ..utils.aabb import AABB

WALL_MARGIN = 0.2
#: 角色碰撞盒（宽 / 深 / 高）。高度必须跟着 §2.1 的冻结几何走——
#: v1.3 写死的 1.45 会让"角色与墙穿模"的判定整条偏移（§1.6 的量错项）。
CHARACTER_BOX = (0.5, 0.5, DEFAULT_PROFILE.total_height)
CAMERA_BOX = (0.2, 0.2, 0.2)

#: S8/S9 的合法取值来自契约层枚举（v1.4 X8/S8 单一真源）：
#: ``contracts/enums.py`` 的 ``CROWD_MODES`` / ``VFX_TYPES``。这里不再各写一份
#: 字面量——两份枚举一旦漂移，校验器会拒收引擎真的支持的特效。
VFX_KINDS = VFX_TYPES

#: 群众实例的默认硬上限。**唯一真源** = ``crowd.max_instances``（校验器由
#: ``validate_sdl(..., crowd_limit=)`` 注入；缺省时才回落到这个默认值）。
DEFAULT_CROWD_LIMIT = 40


def _as_int(value, default: int = 0) -> Tuple[bool, int]:
    """把可能来自坏数据的值转成整数；失败时返回 ``(False, default)``。

    v1.4 X2：SDL 是**外部输入**（旧工程、手改文件、别的工具写的），
    校验器必须报 finding 而不是抛异常——否则坏数据会让加载直接崩掉。
    """
    if value is None or value == "":
        return True, default
    if isinstance(value, bool):
        return True, int(value)
    if isinstance(value, int):
        return True, value
    if isinstance(value, float):
        return True, int(value)
    try:
        return True, int(str(value).strip())
    except (TypeError, ValueError):
        return False, default


def _check_v13_fields(sdl: SDLProject, findings: List[AuditError],
                      crowd_limit: int) -> None:
    """S8 群众引用、S9 特效引用、S10 声明时长自洽（v1.3 新增）。"""
    characters = {member.id for member in sdl.characters}
    for scene in sdl.scenes:
        crowd = getattr(scene.environment, "crowd", None) or []
        total = 0
        for index, entry in enumerate(crowd, start=1):
            if not isinstance(entry, dict):
                findings.append(_error(
                    "S8", "E_SDL_001",
                    f"场景 {scene.id} 的第 {index} 条群众声明不是对象",
                    target=scene.id, suggestion="写成 {count, mode, seed} 形式"))
                continue
            ok, count = _as_int(entry.get("count"), 0)
            if not ok:
                findings.append(_error(
                    "S8", "E_SDL_001",
                    f"场景 {scene.id} 的第 {index} 条群众数量不是整数："
                    f"{entry.get('count')!r}",
                    target=scene.id, suggestion="数量必须是正整数"))
                continue
            if count <= 0:
                findings.append(_error(
                    "S8", "E_SDL_001",
                    f"场景 {scene.id} 的第 {index} 条群众声明的数量非法：{count}",
                    target=scene.id, suggestion="数量必须是正整数"))
            mode = str(entry.get("mode") or "static")
            if mode not in CROWD_MODES:
                findings.append(_error(
                    "S8", "E_SDL_001",
                    f"场景 {scene.id} 的第 {index} 条群众声明的 mode 非法：{mode}",
                    target=scene.id,
                    suggestion=f"只能是 {'/'.join(CROWD_MODES)}"))
            total += max(count, 0)
        if total > crowd_limit:
            findings.append(_error(
                "S8", "E_SDL_001",
                f"场景 {scene.id} 声明了 {total} 个群众实例，超过上限 "
                f"{crowd_limit}",
                target=scene.id,
                suggestion="降低 crowd.max_instances 或减少声明的人数"))

        for shot in scene.shots:
            for index, item in enumerate(getattr(shot, "vfx", None) or [],
                                         start=1):
                if not isinstance(item, dict):
                    findings.append(_error(
                        "S9", "E_SDL_001",
                        f"镜头 {shot.id} 的第 {index} 条特效不是对象",
                        target=shot.id, suggestion="写成 {id, type} 形式"))
                    continue
                if not str(item.get("id") or "").strip():
                    findings.append(_error(
                        "S9", "E_SDL_001",
                        f"镜头 {shot.id} 的第 {index} 条特效缺少 id",
                        target=shot.id, suggestion="给特效一个唯一 id"))
                kind = str(item.get("type") or "")
                if kind not in VFX_KINDS:
                    findings.append(_error(
                        "S9", "E_SDL_001",
                        f"镜头 {shot.id} 的特效类型非法：{kind!r}",
                        target=shot.id,
                        suggestion=f"只能是 {'/'.join(VFX_KINDS)}"))
            # S10：声明的运镜必须落在本镜的帧范围里
            span = (shot.end_frame or shot.duration_frames
                    or 1) - (shot.start_frame or 1) + 1
            for index, move in enumerate(
                    getattr(shot.camera, "movements", None) or [], start=1):
                ok, duration = _as_int(move.get("end_frame"), span)
                if not ok:
                    findings.append(_error(
                        "S10", "E_SDL_001",
                        f"镜头 {shot.id} 的第 {index} 条运镜的 end_frame "
                        f"不是整数：{move.get('end_frame')!r}",
                        target=shot.id, suggestion="把起止帧写成整数"))
                    continue
                if duration > span:
                    findings.append(_error(
                        "S10", "E_SDL_001",
                        f"镜头 {shot.id} 的第 {index} 条运镜声明到第 "
                        f"{duration} 帧，超出镜头时长 {span} 帧",
                        target=shot.id,
                        suggestion="把运镜的起止帧缩回镜头内"))


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
        ok, value = _as_int(dialogue.get("end_frame"), 0)
        if ok:
            latest = max(latest, value)
    if latest and latest + DIALOGUE_TAIL_FRAMES > shot.duration_frames:
        findings.append(_error(
            "S6", "E_SDL_001",
            f"镜头 {shot.id} 装不下对白：最晚第 {latest} 帧 + "
            f"{DIALOGUE_TAIL_FRAMES} 帧余量 > {shot.duration_frames} 帧",
            target=shot.id, suggestion="加长镜头或前移对白"))

    ranges: Dict[str, List[Tuple[int, int]]] = {}
    for action in shot.actions:
        character_id = str(action.get("character_id") or "")
        ok_start, start = _as_int(action.get("start_frame"), 1)
        ok_end, end = _as_int(action.get("end_frame"), shot.duration_frames)
        if not (ok_start and ok_end):
            findings.append(_error(
                "S3", "E_SDL_001",
                f"镜头 {shot.id} 的动作帧号不是整数："
                f"{action.get('start_frame')!r}-{action.get('end_frame')!r}",
                target=shot.id, suggestion="把动作起止帧写成整数"))
            continue
        for other_start, other_end in ranges.get(character_id, []):
            if start < other_end and other_start < end:
                findings.append(_error(
                    "S3", "E_SDL_001",
                    f"角色 {character_id} 在镜头 {shot.id} 内动作重叠"
                    f"（{other_start}-{other_end} 与 {start}-{end}）",
                    target=shot.id, suggestion="错开起止帧"))
        ranges.setdefault(character_id, []).append((start, end))


def _box_or_none(center, size):
    """把可能损坏的 center/size 转成 AABB；失败返回 None（v1.4 X2 守卫）。"""
    try:
        values_c = [float(v) for v in center]
        values_s = [float(v) for v in size]
    except (TypeError, ValueError):
        return None
    if len(values_c) != 3 or len(values_s) != 3:
        return None
    return AABB.from_center_size(values_c, values_s)


def _check_spatial(scene, sdl: SDLProject, findings: List[AuditError]) -> None:
    walls = scene.environment.walls or []
    if not walls:
        return
    wall_boxes = []
    for index, wall in enumerate(walls, start=1):
        if not isinstance(wall, dict):
            findings.append(_error(
                "S4", "E_SDL_001",
                f"场景 {scene.id} 的第 {index} 面墙不是对象",
                target=scene.id, suggestion="写成 {position, size} 形式"))
            continue
        box = _box_or_none(wall.get("position", (0, 0, 0)),
                           wall.get("size", (1, 1, 1)))
        if box is None:
            findings.append(_error(
                "S4", "E_SDL_001",
                f"场景 {scene.id} 的第 {index} 面墙的 position/size 非法",
                target=scene.id, suggestion="写成三个数值的数组"))
            continue
        wall_boxes.append(box)
    for member in sdl.characters:
        box = _box_or_none(member.initial_location, CHARACTER_BOX)
        if box is None:
            findings.append(_error(
                "S4", "E_SPACE_001",
                f"角色 {member.id} 的 initial_location 非法",
                target=member.id, suggestion="写成三个数值的数组"))
            continue
        for index, wall_box in enumerate(wall_boxes, start=1):
            if box.overlaps(wall_box, margin=WALL_MARGIN):
                findings.append(_error(
                    "S4", "E_SPACE_001",
                    f"角色 {member.id} 与第 {index} 面墙穿模",
                    target=member.id, suggestion="挪开角色或调整墙体"))
    for shot in scene.shots:
        if not shot.camera.position:
            continue
        box = _box_or_none(shot.camera.position, CAMERA_BOX)
        if box is None:
            findings.append(_error(
                "S4", "E_SPACE_001",
                f"镜头 {shot.id} 的相机位置非法",
                target=shot.id, suggestion="写成三个数值的数组"))
            continue
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


def _default_crowd_limit() -> int:
    """``crowd.max_instances`` 的当前配置值；缺配置时回落到 40（v1.4 X8）。"""
    try:
        from ..contracts.config import AppConfig
        return int(AppConfig().crowd.max_instances)
    except Exception:  # noqa: BLE001 - 取不到配置不该让校验器崩掉
        return DEFAULT_CROWD_LIMIT


def validate_sdl(sdl: SDLProject, *,
                 crowd_limit: Optional[int] = None) -> List[AuditError]:
    """返回全部问题；空列表表示 SDL 可用。

    ``crowd_limit`` 缺省时取 ``crowd.max_instances``（v1.4 X8：上限是配置的
    单一真源，不再硬编码 40）。
    """
    findings: List[AuditError] = []
    limit = DEFAULT_CROWD_LIMIT if crowd_limit is None else int(crowd_limit)

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
    _check_v13_fields(sdl, findings, limit)
    for scene in sdl.scenes:
        for shot in scene.shots:
            _check_shot_timing(shot, findings)
        _check_scene_totals(scene, findings)
        _check_spatial(scene, sdl, findings)
    return findings
