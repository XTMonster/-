"""Blockout 清单生成器（Ticket 01，纯层，不 import bpy）。

在「空间设计快照」之后、逐分镜细排之前，把设计快照（角色/道具/锚点/机位的
世界坐标 + provenance）与计划（帧调度/相机运动/动作）确定性转换成一份版本化
``BlockoutManifest``：

* ``primitives[]``：体块条目（形状/真实尺度/颜色占位/asset 引用/来源），角色
  体块按 human scale（默认 1.7 m，脚底锚定），道具/锚点按尺寸档表；
* ``cameras[]``：相机先行——逐镜 position/target/lens/fov + 运动轨迹 + 帧范围，
  全部来自设计快照与计划，不脑补；
* ``shot_table[]``：分镜清单（shot_id/起止帧/相机/角色/道具/转场重叠/出入画/
  下游映射）；
* ``asset_registry[]``：共享资产登记（同一资产只登记一次，供逐分镜引用不重建）；
* ``checkpoints[]``：检查点声明（scene_01_blockout.blend 全局 + 逐分镜）。

坐标纪律：**一切坐标可追溯**，沿用设计快照的 provenance 四态；未解析锚点/道具
不落体块（照实记 note，不猜）。确定性：同一输入两次构建逐位一致。
"""

from __future__ import annotations

import copy
import re
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..contracts.plan import Plan
from ..contracts.blockout import MANIFEST_VERSION
from ..contracts.coarse_reference import effective_shot_reference
from .schedule import shot_ranges

#: 快照版本（契约演进时逐代升）。
#: 版本常量单一真源在 ``contracts/blockout.py``（Schema const 同源）。
BLOCKOUT_MANIFEST_SCHEMA = MANIFEST_VERSION

#: 体块占位颜色（中性灰，与白模参考视频同口径）。
BLOCKOUT_COLOR = "#8f8f8f"

#: 体块形状（当前全部用长方体，圆柱/立方体由 bpy 侧按 shape 扩展）。
BLOCKOUT_SHAPE = "box"

#: 尺寸档表（米，确定性设计默认；kind 未命中档 -> 默认体块 + note）。
#: character 为 human scale：默认 1.7 m 高、0.5 m 见方。
KIND_SIZE_BANDS: Dict[str, Tuple[float, float, float]] = {
    "character": (0.5, 0.5, 1.7),
    "prop": (0.9, 0.9, 1.2),
    "table": (1.5, 0.9, 0.75),
    "stall": (2.0, 1.2, 1.6),
    "door": (1.0, 0.2, 2.1),
    "chair": (0.5, 0.5, 0.9),
    "counter": (1.8, 0.6, 1.0),
    "anchor": (1.0, 1.0, 1.0),
    "货币": (0.12, 0.12, 0.03),
    "coin": (0.12, 0.12, 0.03),
}

#: 自由文本 kind -> 尺寸档的显式别名。只允许这里列出的词命中；先做
#: 精确档位匹配，再按命中词长度从长到短解析，禁止模糊相似度猜测。
#: 中文词按子串命中；英文按完整词/词组命中，避免 ``coin`` 吃掉
#: ``coin-operated`` 之外更长的非货币词（如 ``vegetable`` 中的 ``table``）。
KIND_SIZE_ALIASES: Dict[str, Tuple[str, ...]] = {
    "coin": (
        "货币", "硬币", "银币", "金币", "铜币", "钱币",
        "coin", "gold coin", "silver coin", "copper coin", "currency",
    ),
    "table": ("桌子", "桌面", "table", "desk"),
    "stall": ("摊位", "摊子", "货摊", "stall", "booth"),
    "door": ("门口", "门框", "门", "door", "doorway"),
    "chair": ("椅子", "座椅", "chair", "seat"),
    "counter": ("柜台", "吧台", "收银台", "counter", "bar counter"),
}

#: 未命中尺寸档时的默认体块（米）。
DEFAULT_BLOCK_SIZE: Tuple[float, float, float] = (0.9, 0.9, 1.2)


class KindSizeResolution:
    """自由文本 kind 的确定性尺寸档解析结果（可审计、不可模糊猜测）。"""

    __slots__ = ("raw_kind", "canonical_kind", "matched_alias",
                 "match_mode", "size")

    def __init__(self, raw_kind: str, canonical_kind: str,
                 matched_alias: str, match_mode: str,
                 size: Tuple[float, float, float]) -> None:
        self.raw_kind = raw_kind
        self.canonical_kind = canonical_kind
        self.matched_alias = matched_alias
        self.match_mode = match_mode
        self.size = size

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, KindSizeResolution):
            return NotImplemented
        return (
            self.raw_kind,
            self.canonical_kind,
            self.matched_alias,
            self.match_mode,
            self.size,
        ) == (
            other.raw_kind,
            other.canonical_kind,
            other.matched_alias,
            other.match_mode,
            other.size,
        )

    def __repr__(self) -> str:
        return (
            "KindSizeResolution("
            f"raw_kind={self.raw_kind!r}, "
            f"canonical_kind={self.canonical_kind!r}, "
            f"matched_alias={self.matched_alias!r}, "
            f"match_mode={self.match_mode!r}, size={self.size!r})"
        )


def _normalize_kind_text(value: Any) -> str:
    text = str(value or "prop").strip().casefold()
    text = re.sub(r"[_/\\-]+", " ", text)
    return " ".join(text.split())


def _alias_matches(text: str, alias: str) -> bool:
    """英文别名按完整词/词组匹配，中文别名按显式子串匹配。"""
    if alias.isascii():
        words = re.findall(r"[a-z0-9]+", text)
        wanted = alias.split()
        if not wanted or len(wanted) > len(words):
            return False
        return any(
            words[index:index + len(wanted)] == wanted
            for index in range(len(words) - len(wanted) + 1))
    return alias in text


_KIND_ALIAS_INDEX: Tuple[Tuple[str, str], ...] = tuple(sorted(
    ((_normalize_kind_text(alias), canonical)
     for canonical, aliases in KIND_SIZE_ALIASES.items()
     for alias in aliases),
    key=lambda item: (-len(item[0]), item[1], item[0]),
))


def resolve_prop_kind(kind: Any) -> KindSizeResolution:
    """把自由文本道具 kind 解析为尺寸档，并保留命中依据。

    顺序固定为：精确档位 -> 显式别名（最长命中优先）-> 默认体块。
    ``match_mode`` 的 ``exact`` / ``alias`` / ``fallback`` 三态用于在
    manifest note 与资产登记中审计“为什么是这个大小”。
    """
    raw_kind = str(kind or "prop").strip() or "prop"
    normalized = _normalize_kind_text(raw_kind)
    if normalized in KIND_SIZE_BANDS:
        return KindSizeResolution(
            raw_kind=raw_kind, canonical_kind=normalized,
            matched_alias="", match_mode="exact",
            size=KIND_SIZE_BANDS[normalized])
    for alias, canonical in _KIND_ALIAS_INDEX:
        if _alias_matches(normalized, alias):
            return KindSizeResolution(
                raw_kind=raw_kind, canonical_kind=canonical,
                matched_alias=alias, match_mode="alias",
                size=KIND_SIZE_BANDS[canonical])
    return KindSizeResolution(
        raw_kind=raw_kind, canonical_kind="prop", matched_alias="",
        match_mode="fallback", size=DEFAULT_BLOCK_SIZE)


def _norm_input(value: Any) -> Any:
    """把 dataclass / dict / 其他统一成 dict 或原样。"""
    if is_dataclass(value) and not isinstance(value, type):
        try:
            return asdict(value)
        except Exception:  # noqa: BLE001 - 异常形状也不致命，保持原样
            return value
    return value


def _as_dict(item: Any) -> Dict[str, Any]:
    if isinstance(item, Mapping):
        return dict(item)
    return dict(_norm_input(item) or {})


def _plan_dict(plan: Any) -> Dict[str, Any]:
    norm = _norm_input(plan)
    if not isinstance(norm, Mapping):
        return {}
    return dict(norm)


def _shots(plan: Any) -> List[Dict[str, Any]]:
    norm = _plan_dict(plan)
    shots = norm.get("shots")
    if isinstance(shots, list) and shots:
        return [_as_dict(shot) for shot in shots]
    if norm.get("shot_id"):
        return [_as_dict(norm)]
    return []


def _ranges(plan: Any) -> Dict[str, Tuple[int, int]]:
    """逐镜起止帧：Plan 走既有帧调度器；dict 形状回退同算法。

    帧调度的单一真源是 ``cinema/schedule.py::shot_ranges``；dict 回退只
    服务于离线/dict 输入，算法与其一致（cursor 累加），不另立一套。
    """
    if isinstance(plan, Plan):
        return shot_ranges(plan)
    ranges: Dict[str, Tuple[int, int]] = {}
    cursor = 1
    for shot in sorted(_shots(plan), key=lambda s: int(s.get("order") or 0)):
        end = cursor + max(int(shot.get("duration_frames") or 1), 1) - 1
        ranges[str(shot.get("shot_id") or "")] = (cursor, end)
        cursor = end + 1
    return ranges


def _size_band(kind: str, is_character: bool = False) -> Tuple[float, float, float]:
    if is_character:
        return KIND_SIZE_BANDS["character"]
    return resolve_prop_kind(kind).size


def _vec3(value: Any) -> Optional[List[float]]:
    if isinstance(value, Mapping):
        if value.get("x") is None:
            return None
        return [float(value.get("x")), float(value.get("y")),
                float(value.get("z"))]
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        return [float(value[0]), float(value[1]), float(value[2])]
    return None


def _size_dict(size: Tuple[float, float, float]) -> Dict[str, float]:
    return {"x": round(size[0], 4), "y": round(size[1], 4),
            "z": round(size[2], 4)}


def _position_dict(position: Sequence[float]) -> Dict[str, float]:
    return {"x": round(float(position[0]), 4),
            "y": round(float(position[1]), 4),
            "z": round(float(position[2]), 4)}


def _camera_intents(design: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for raw in design.get("camera_intents") or []:
        intent = _as_dict(raw)
        out[str(intent.get("shot_id") or "")] = intent
    return out


def _camera_entry(shot: Dict[str, Any], intent: Optional[Dict[str, Any]],
                  start: int, end: int) -> Dict[str, Any]:
    shot_id = str(shot.get("shot_id") or "")
    camera = _as_dict(shot.get("camera") or {})
    if not intent or intent.get("position") is None:
        reason = (intent or {}).get("unresolved_reason") or "无设计机位"
        return {
            "shot_id": shot_id, "camera_id": f"cam_{shot_id}",
            "position": None, "target": None, "lens_mm": None,
            "fov_deg": None,
            "movements": list(camera.get("movements") or []),
            "start_frame": start, "end_frame": end,
            "provenance": (intent or {}).get("provenance", "plan_intent"),
            "resolved": False, "unresolved_reason": reason,
        }
    return {
        "shot_id": shot_id, "camera_id": f"cam_{shot_id}",
        "position": [round(float(v), 4) for v in intent["position"]],
        "target": [round(float(v), 4) for v in (intent.get("target") or [])],
        "lens_mm": round(float(intent.get("lens") or 0.0), 4),
        "fov_deg": round(float(intent.get("fov_deg") or 0.0), 4),
        "movements": list(camera.get("movements") or []),
        "start_frame": start, "end_frame": end,
        "provenance": str(intent.get("provenance") or "algorithmic_measurement"),
        "resolved": True,
    }


def _enter_exit(shot: Dict[str, Any]) -> Dict[str, List[str]]:
    enter: List[str] = []
    exit_: List[str] = []
    for raw in shot.get("actions") or []:
        action = _as_dict(raw)
        action_type = str(action.get("type") or action.get("action_type") or "")
        if action_type.startswith("enter"):
            enter.append(action_type)
        elif action_type.startswith("exit"):
            exit_.append(action_type)
    return {"enter": enter, "exit": exit_}


def _downstream_map(shot_id: str) -> Dict[str, str]:
    """下游资产映射（确定性占位键，细排阶段按真实资产覆盖）。"""
    return {
        "reference_video": f"{shot_id}.mp4",
        "geometry": f"{shot_id}_geometry",
        "materials": f"{shot_id}_materials",
        "video_generation": f"{shot_id}_video_prompt",
    }


def _shot_positions_for_character(
    *,
    design: Mapping[str, Any],
    shots: Sequence[Mapping[str, Any]],
    ranges: Mapping[str, Tuple[int, int]],
    name: str,
) -> List[Dict[str, Any]]:
    """Resolve a character's auditable staging entry for every shot."""
    rows: List[Dict[str, Any]] = []
    for shot in shots:
        shot_id = str(shot.get("shot_id") or "")
        if not shot_id:
            continue
        declared = {str(item) for item in (shot.get("characters") or [])}
        framing = shot.get("framing_target")
        if isinstance(framing, Mapping) \
                and str(framing.get("kind") or "") == "character":
            declared.add(str(framing.get("ref") or ""))
        if name not in declared:
            continue
        effective = effective_shot_reference(design, shot_id)
        character = next(
            (item for item in effective.get("characters") or []
             if str(item.get("name") or "") == name),
            None,
        )
        if not isinstance(character, Mapping):
            continue
        position = _vec3(character.get("position"))
        if position is None:
            continue
        overlay = (
            ((design.get("shot_staging") or {}).get(shot_id) or {}).get(name)
            if isinstance(design.get("shot_staging"), Mapping) else None
        )
        overlay = overlay if isinstance(overlay, Mapping) else {}
        start, end = ranges.get(shot_id, (1, 1))
        rows.append({
            "shot_id": shot_id,
            "position": _position_dict(position),
            "start_frame": int(start),
            "end_frame": int(end),
            "provenance": str(
                overlay.get("provenance")
                or character.get("provenance")
                or "plan_intent"),
            "reason": str(overlay.get("reason") or ""),
        })
    return rows


def build_blockout_manifest(*, design: Mapping[str, Any], plan: Any,
                            scene_id: str = "") -> Dict[str, Any]:
    """空间设计快照 + 计划 -> BlockoutManifest（确定性、可追溯、版本化）。

    ``design`` 是 ``cinema.spatial_design.build_design_snapshot`` 的输出形状；
    ``plan`` 接受 ``Plan`` 或 dict 形状（shots[]）。体块只覆盖已解析条目；
    未解析锚点/道具照实记 note，不落坐标。

    R10（Ticket 07）：``design.shots[]``（粗排参考世界坐标 JSON 的语义层，
    单一真源）**优先**于 ``plan.shots[]`` 决定分镜表——粗排 agent 改过参考
    JSON 的分镜顺序/时长后，manifest 必须跟随，粗排 gate 才能拦下错改；
    ``design`` 未携带 shots[] 时回退 plan（旧调用方零行为差）。
    """
    design = dict(design)
    design_shots = design.get("shots")
    from_design = isinstance(design_shots, list) and bool(design_shots)
    shots = design_shots if from_design else _shots(plan)
    ranges = _ranges({"shots": shots} if from_design else plan)
    intents = _camera_intents(design)
    notes: List[str] = [str(note) for note in (design.get("notes") or [])]
    primitives: List[Dict[str, Any]] = []
    cameras: List[Dict[str, Any]] = []
    shot_table: List[Dict[str, Any]] = []
    asset_registry: List[Dict[str, Any]] = []
    scene_prop_ids: List[str] = []
    routes: List[Dict[str, Any]] = []

    #: 已解析角色 -> 体块（human scale，脚底锚定）
    characters = design.get("characters") or []
    for char in characters:
        entry = _as_dict(char)
        name = str(entry.get("name") or "")
        position = _vec3(entry.get("position"))
        if position is None:
            notes.append(f"角色 {name} 无站位声明，不落体块（不猜）")
            continue
        size = _size_band("character", is_character=True)
        primitives.append({
            "id": f"char_{name}", "kind": "character",
            "shape": BLOCKOUT_SHAPE,
            "position": _position_dict(position),
            "size": _size_dict(size),
            "color": BLOCKOUT_COLOR,
            "z_anchor": "foot",
            "asset_ref": None,
            "provenance": str(entry.get("provenance") or "plan_intent"),
            "source": {"type": "character", "id": name},
            "shot_positions": _shot_positions_for_character(
                design=design, shots=shots, ranges=ranges, name=name),
        })

    #: 已解析道具 -> 体块（中心锚定）+ 资产登记（同一资产只登记一次）
    for raw in design.get("props") or []:
        prop = _as_dict(raw)
        pid = str(prop.get("id") or "")
        kind = str(prop.get("kind") or "prop")
        position = _vec3(prop.get("position"))
        if position is None:
            notes.append(f"道具 {pid} 无位置声明，不落体块（不猜）")
            continue
        resolution = resolve_prop_kind(kind)
        size = resolution.size
        asset_kind = (
            _normalize_kind_text(kind)
            if resolution.match_mode == "fallback"
            else resolution.canonical_kind)
        asset_id = f"{asset_kind}_{pid}"
        if resolution.match_mode == "alias":
            notes.append(
                f"道具 {pid} kind {kind!r} 经显式别名 "
                f"{resolution.matched_alias!r} 归一为尺寸档 "
                f"{resolution.canonical_kind!r}")
        elif resolution.match_mode == "fallback":
            notes.append(
                f"道具 {pid} 尺寸档未命中（{kind}），用默认体块；"
                f"解析记录 raw={kind!r}, canonical='prop', "
                f"matched_alias='', match_mode='fallback'")
        primitives.append({
            "id": f"prop_{pid}", "kind": "prop", "shape": BLOCKOUT_SHAPE,
            "position": _position_dict(position),
            "rotation": copy.deepcopy(prop.get("rotation")),
            "size": _size_dict(size),
            "color": BLOCKOUT_COLOR,
            "z_anchor": "center",
            "asset_ref": asset_id,
            "provenance": str(prop.get("provenance") or "plan_intent"),
            "source": {"type": "prop", "id": pid, "kind": kind},
        })
        if all(a["asset_id"] != asset_id for a in asset_registry):
            asset_registry.append({
                "asset_id": asset_id, "kind": resolution.canonical_kind,
                "source_kind": kind,
                "kind_match": resolution.match_mode,
                "matched_alias": resolution.matched_alias,
                "shape": BLOCKOUT_SHAPE, "dims": _size_dict(size),
                "source_checkpoint": "scene_01_blockout.blend",
                "provenance": str(prop.get("provenance") or "plan_intent"),
            })
        if not prop.get("owner"):
            scene_prop_ids.append(pid)

    #: 走位路线（R10 walk_path check 的 actual 侧）：来自参考世界 JSON 的
    #: 角色 motion_by_shot（plan_intent 源），与计划 move 指令逐段对拍。
    for char in characters:
        name = str(char.get("name") or "")
        for raw_motion in char.get("motion_by_shot") or []:
            motion = _as_dict(raw_motion)
            if not motion.get("shot_id"):
                continue
            start = _vec3(motion.get("start"))
            end = _vec3(motion.get("end"))
            if start is None or end is None:
                continue
            routes.append({
                "character": name,
                "shot_id": str(motion["shot_id"]),
                "start": [round(float(v), 4) for v in start],
                "end": [round(float(v), 4) for v in end],
                "speed_m_s": round(float(motion.get("speed_m_s") or 0.0), 4),
                "provenance": "plan_intent",
            })

    #: 已解析锚点 -> 标记体块（中心锚定）；未解析照实 note
    for raw in design.get("anchors") or []:
        anchor = _as_dict(raw)
        label = str(anchor.get("label") or "")
        position = _vec3(anchor.get("position"))
        if position is None:
            notes.append(f"锚点 {label} 未解析"
                         f"（{anchor.get('unresolved_reason', '')}），不落体块")
            continue
        size = _size_band("anchor")
        primitives.append({
            "id": f"anchor_{label}", "kind": "anchor",
            "shape": BLOCKOUT_SHAPE,
            "position": _position_dict(position),
            "size": _size_dict(size),
            "color": BLOCKOUT_COLOR,
            "z_anchor": "center",
            "asset_ref": None,
            "provenance": str(anchor.get("provenance") or "algorithmic_measurement"),
            "source": {"type": "anchor", "id": label},
        })

    #: 相机先行：逐镜机位 + 运动轨迹 + 帧范围
    for index, shot in enumerate(shots, start=1):
        shot_id = str(shot.get("shot_id") or "")
        start, end = ranges.get(shot_id, (1, 1))
        intent = intents.get(shot_id)
        cameras.append(_camera_entry(shot, intent, start, end))

        shot_characters = [str(name) for name in (shot.get("characters") or [])]
        #: 角色持有道具（owner ∈ 本镜角色）进本镜 prop_ids；场景级道具走
        #: scene_prop_ids（资产表全局引用）。
        owned_props = [str(prop.get("id") or "")
                       for raw in design.get("props") or []
                       for prop in [_as_dict(raw)]
                       if str(prop.get("owner") or "") in shot_characters]
        order = int(shot.get("order") or index)
        shot_table.append({
            "shot_id": shot_id, "order": order,
            "start_frame": start, "end_frame": end,
            "camera_id": f"cam_{shot_id}",
            "character_ids": shot_characters,
            "prop_ids": owned_props,
            "transition_overlap_frames": 0,
            "enter_exit": _enter_exit(shot),
            "downstream_map": _downstream_map(shot_id),
        })

    if not shot_table:
        notes.append("计划为空，未生成分镜表")
    notes.append("转场重叠默认 0（硬切），细排阶段按实际转场填充")

    checkpoints = [{
        "id": "scene_01_blockout.blend", "scope": "global", "shot_id": None,
    }]
    for row in shot_table:
        checkpoints.append({
            "id": f"scene_s{int(row['order']):02d}_blockout.blend",
            "scope": "shot", "shot_id": row["shot_id"],
        })

    manifest = {
        "schema_version": BLOCKOUT_MANIFEST_SCHEMA,
        "scene_id": str(scene_id or design.get("scene_id") or ""),
        "primitives": primitives,
        "cameras": cameras,
        "shot_table": shot_table,
        "routes": routes,
        "asset_registry": asset_registry,
        "scene_prop_ids": scene_prop_ids,
        "checkpoints": checkpoints,
        "notes": notes,
    }
    if isinstance(design.get("shot_staging"), Mapping):
        manifest["shot_staging"] = copy.deepcopy(design["shot_staging"])
    return manifest


__all__ = ["build_blockout_manifest", "BLOCKOUT_MANIFEST_SCHEMA",
           "KIND_SIZE_BANDS", "KIND_SIZE_ALIASES",
           "KindSizeResolution", "resolve_prop_kind",
           "DEFAULT_BLOCK_SIZE", "BLOCKOUT_COLOR"]
