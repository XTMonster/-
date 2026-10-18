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

from dataclasses import asdict, is_dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..contracts.plan import Plan
from ..contracts.blockout import MANIFEST_VERSION
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
}

#: 未命中尺寸档时的默认体块（米）。
DEFAULT_BLOCK_SIZE: Tuple[float, float, float] = (0.9, 0.9, 1.2)


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
    key = "character" if is_character else kind.lower()
    return KIND_SIZE_BANDS.get(key, DEFAULT_BLOCK_SIZE)


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


def build_blockout_manifest(*, design: Mapping[str, Any], plan: Any,
                            scene_id: str = "") -> Dict[str, Any]:
    """空间设计快照 + 计划 -> BlockoutManifest（确定性、可追溯、版本化）。

    ``design`` 是 ``cinema.spatial_design.build_design_snapshot`` 的输出形状；
    ``plan`` 接受 ``Plan`` 或 dict 形状（shots[]）。体块只覆盖已解析条目；
    未解析锚点/道具照实记 note，不落坐标。
    """
    design = dict(design)
    shots = _shots(plan)
    ranges = _ranges(plan)
    intents = _camera_intents(design)
    notes: List[str] = [str(note) for note in (design.get("notes") or [])]
    primitives: List[Dict[str, Any]] = []
    cameras: List[Dict[str, Any]] = []
    shot_table: List[Dict[str, Any]] = []
    asset_registry: List[Dict[str, Any]] = []
    scene_prop_ids: List[str] = []

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
        size = _size_band(kind)
        asset_id = f"{kind.lower()}_{pid}"
        if kind.lower() not in KIND_SIZE_BANDS and kind.lower() != "character":
            notes.append(f"道具 {pid} 尺寸档未命中（{kind}），用默认体块")
        primitives.append({
            "id": f"prop_{pid}", "kind": "prop", "shape": BLOCKOUT_SHAPE,
            "position": _position_dict(position),
            "size": _size_dict(size),
            "color": BLOCKOUT_COLOR,
            "z_anchor": "center",
            "asset_ref": asset_id,
            "provenance": str(prop.get("provenance") or "plan_intent"),
            "source": {"type": "prop", "id": pid},
        })
        if all(a["asset_id"] != asset_id for a in asset_registry):
            asset_registry.append({
                "asset_id": asset_id, "kind": kind.lower(),
                "shape": BLOCKOUT_SHAPE, "dims": _size_dict(size),
                "source_checkpoint": "scene_01_blockout.blend",
                "provenance": str(prop.get("provenance") or "plan_intent"),
            })
        if not prop.get("owner"):
            scene_prop_ids.append(pid)

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

    return {
        "schema_version": BLOCKOUT_MANIFEST_SCHEMA,
        "scene_id": str(scene_id or design.get("scene_id") or ""),
        "primitives": primitives,
        "cameras": cameras,
        "shot_table": shot_table,
        "asset_registry": asset_registry,
        "scene_prop_ids": scene_prop_ids,
        "checkpoints": checkpoints,
        "notes": notes,
    }


__all__ = ["build_blockout_manifest", "BLOCKOUT_MANIFEST_SCHEMA",
           "KIND_SIZE_BANDS", "DEFAULT_BLOCK_SIZE", "BLOCKOUT_COLOR"]
