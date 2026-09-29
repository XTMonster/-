"""SDL 版本迁移（执行文档 v1.2 §5.3）。

v1.0 的 SDL 没有 fps、把绝对帧号当输入、也没有 prompt；
v1.1 起 shot 只声明 duration，帧号由排片器回填。迁移必须**只补结构、
不改时长与镜头顺序**，否则旧项目的观感会被悄悄改掉。
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from ..contracts.cast import DEFAULT_COLORS, default_station
from ..contracts.sdl import SDL_VERSION

#: 显式列出每一个**曾经的**版本，而不是只写"1.0/1.1/当前"：
#: v1.4 升级时若把 1.3 漏掉，v1.3 的项目会被当成未知版本"尽力读取"，
#: 迁移说明里就会多出一条误导性的告警（ADR-0005）。
KNOWN_VERSIONS = ("1.0", "1.1", "1.2", "1.3", SDL_VERSION)

#: 写入器从 1.2 起就会把完整的 ``characters`` 名册写进文件。比这更老的文件
#: 才需要"补名册"这种结构修复；1.2 及以后引用了不存在的角色，那是**真错误**，
#: 迁移不许替它打掩护（否则坏项目会被悄悄补全成一个看似能用的半成品）。
ROSTER_COMPLETE_FROM = "1.2"


def _version_key(text: str) -> Tuple[int, ...]:
    """``"1.2"`` → ``(1, 2)``；无法解析的版本按 (0,) 处理（最老）。"""
    parts: List[int] = []
    for chunk in str(text or "").split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            break
    return tuple(parts) or (0,)


def _referenced_characters(payload: Dict[str, Any]) -> List[str]:
    """按出现顺序收集 SDL 里被引用到的全部角色 id。

    镜头、动作、对白、在场说话人、连贯性台账都可能提到某个角色；旧项目
    只要有一处引用没进 ``characters`` 名单，加载时就会被 S2 判为坏数据。
    """
    ordered: List[str] = []
    seen = set()

    def add(value: Any) -> None:
        character_id = str(value or "")
        if character_id and character_id not in seen:
            seen.add(character_id)
            ordered.append(character_id)

    for scene in payload.get("scenes") or []:
        for shot in (scene or {}).get("shots") or []:
            shot = shot or {}
            for character_id in shot.get("characters") or []:
                add(character_id)
            for character_id in shot.get("active_speakers") or []:
                add(character_id)
            for action in shot.get("actions") or []:
                add((action or {}).get("character_id"))
            for dialogue in shot.get("dialogues") or []:
                add((dialogue or {}).get("character_id"))
    pose = (payload.get("continuity") or {}).get("character_pose") or {}
    if isinstance(pose, dict):
        for character_id in pose:
            add(character_id)
    return ordered


def _heal_cast(payload: Dict[str, Any], notes: List[str]) -> None:
    """把被引用却不在名单里的角色补进 ``characters``（只补结构，不动已有序位）。

    v1.3：补进来的角色用**默认站位**（两人相对而立），而不是 v1.2 的
    "并排朝前"。补站位不补坐标——已存在的角色保持它们自己的位置，
    迁移的职责是让旧文件能加载，不是替用户重新调度。
    """
    raw = payload.get("characters")
    known = [member for member in raw if isinstance(member, dict)] \
        if isinstance(raw, list) else []
    have = {str(member.get("id") or "") for member in known}
    missing = [character_id for character_id in _referenced_characters(payload)
               if character_id not in have]
    payload["characters"] = known
    if not missing:
        return

    total = len(known) + len(missing)
    stations = default_station(total)
    base = len(known)            # known 在循环里会变长，索引基准必须先固定
    for offset, character_id in enumerate(missing):
        index = base + offset
        location, facing = stations[index]
        padded = tuple(float(v) for v in facing) + (0.0, 0.0, 0.0)
        known.append({
            "id": character_id,
            "name": character_id,
            "color": DEFAULT_COLORS[index % len(DEFAULT_COLORS)],
            "initial_location": [round(float(v), 3) for v in location],
            "initial_facing": [round(value, 3) for value in padded[:3]],
        })
    notes.append("补齐角色表：" + ", ".join(missing))


def _migrate_shot(shot: Dict[str, Any], notes: List[str]) -> None:
    start = int(shot.get("start_frame") or 0)
    end = int(shot.get("end_frame") or 0)
    duration = int(shot.get("duration_frames") or 0)

    if not duration and start and end:
        duration = end - start + 1
        notes.append(f"镜头 {shot.get('id')}：由帧范围折算出时长 {duration}")
    if duration and not end:
        end = (start or 1) + duration - 1
    shot["duration_frames"] = max(duration, 1)
    # 帧号归排片器：源里没有帧号就不要编一个，留 0 让 §10.2 统一回填，
    # 否则会造出"start=0 但 end=48"这种自相矛盾的半成品。
    if start and end:
        shot["start_frame"] = start
        shot["end_frame"] = end
    elif start:
        shot["start_frame"] = start
        shot["end_frame"] = start + shot["duration_frames"] - 1
    else:
        shot["start_frame"] = 0
        shot["end_frame"] = 0

    shot.setdefault("intent", "")
    shot.setdefault("prompt", "")
    shot.setdefault("characters", [])
    shot.setdefault("actions", [])
    shot.setdefault("dialogues", [])
    shot.setdefault("active_speakers", [])
    shot.setdefault("transition_in", "cut")
    shot.setdefault("transition_out", "cut")
    shot.setdefault("camera", {})


def migrate_sdl(data: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """把任意已知版本的 SDL 升到当前版本，返回 ``(新数据, 迁移说明)``。"""
    payload = dict(data or {})
    notes: List[str] = []
    version = str(payload.get("version") or "1.0")
    if version not in KNOWN_VERSIONS:
        notes.append(f"未知版本 {version}：按当前结构尽力读取")
    if version == SDL_VERSION:
        return payload, notes

    payload.setdefault("name", "BlockDirector")
    payload.setdefault("fps", 24)
    payload.setdefault("characters", [])
    payload.setdefault("continuity", {})
    payload.setdefault("warnings", [])

    for index, scene in enumerate(payload.get("scenes", []) or [], start=1):
        scene.setdefault("id", f"scene_{index:03d}")
        scene.setdefault("number", index)
        scene.setdefault("heading", "")
        scene.setdefault("environment", {})
        for shot in scene.setdefault("shots", []):
            _migrate_shot(shot, notes)

    if _version_key(version) < _version_key(ROSTER_COMPLETE_FROM):
        _heal_cast(payload, notes)
    payload["version"] = SDL_VERSION
    notes.append(f"已从 {version} 迁移到 {SDL_VERSION}")
    return payload, notes
