"""后向观测快照装配器（Ticket 03，纯层，不 import bpy）。

把 Blender 构建后采样回读的一组 `SpatialFrame`（含 rotation / motion /
gaze 新字段，来源一律 ``blender_geometry``）确定性装配成版本化「观测快照」：
逐镜、逐角色/物品、逐采样帧。运动（位移/速度/路径折线）由采样帧间位置差分
计算（不依赖 fcurve API 细节，保证可重放）。

差分式运动回读的哲学：采样帧已足够稀疏（首/中/末 + guard step），帧间直线
位移是**确定性的描述**；真正的逐帧关键帧曲线不属于本快照（Out of Scope：
避免数据爆炸），由需要的人去聊 fcurve。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from ..contracts.plan import FPS
from .spatial_digest import SpatialFrame

#: 快照版本（契约演进时逐代升）。
OBSERVATION_SNAPSHOT_SCHEMA = "spatial-observation/v1"

#: 观测侧来源恒定：只来自 Blender 几何实测。
PROVENANCE = "blender_geometry"


def _position_of(element) -> List[float]:
    center = getattr(element, "center", None)
    if center is None:
        return []
    return [float(v) for v in center]


def frame_displacements(positions: Mapping[int, Sequence[float]],
                        fps: int = FPS,
                        ) -> Dict[str, Any]:
    """按采样帧号排序，把逐帧位置折成位移/速度/路径。

    ``positions``：``{frame: [x, y, z]}``（同一元素）。返回：``waypoints``
    （按帧序的位置点）、``displacements``（相邻采样点点间位移向量）、
    ``speed_m_s``（相邻采样点间速度，按帧距/fps）、``total_travel``（累计
    路径长度）。单点 -> 空位移/速度；确定性：同一输入两次逐位一致。
    """
    frames = sorted(int(frame) for frame in positions)
    waypoints: List[List[float]] = []
    displacements: List[List[float]] = []
    speeds: List[float] = []
    total = 0.0
    prev_frame: Optional[int] = None
    prev_pos = None
    for frame in frames:
        pos = [float(v) for v in (positions[frame] or [])]
        waypoints.append(pos)
        if prev_frame is not None and prev_pos is not None:
            delta = [pos[i] - prev_pos[i] for i in range(min(len(pos),
                                                             len(prev_pos)))]
            distance = sum(c * c for c in delta) ** 0.5
            span_s = max(frame - prev_frame, 1) / float(fps)
            displacements.append(delta)
            speeds.append(round(distance / span_s, 4))
            total += distance
        prev_frame = frame
        prev_pos = pos
    return {
        "frames": frames,
        "waypoints": waypoints,
        "displacements": displacements,
        "speed_m_s": [round(v, 4) for v in speeds],
        "total_travel": round(total, 4),
        "unit": {"position": "m", "speed": "m/s", "frame": "frame"},
    }


def _element_dict(element, motion: Dict[str, Any]) -> Dict[str, Any]:
    center = _position_of(element)
    rotation = getattr(element, "rotation", None)
    gaze = getattr(element, "gaze", None)
    return {
        "id": str(getattr(element, "id", "")),
        "kind": str(getattr(element, "kind", "")),
        "center": center,
        "aabb_min": list(getattr(element, "aabb_min", []) or []),
        "aabb_max": list(getattr(element, "aabb_max", []) or []),
        "facing": list(getattr(element, "facing", None) or []) or None,
        "rotation": dict(rotation) if isinstance(rotation, Mapping) else None,
        "motion": dict(motion) if motion else None,
        "gaze": (dict(gaze) if isinstance(gaze, Mapping) else None),
        "provenance": PROVENANCE,
        "unit": {"position": "m", "rotation": "rad",
                 "speed": "m/s", "angle": "deg"},
    }


def _camera_dict(camera) -> Dict[str, Any]:
    rotation = getattr(camera, "rotation", None)
    return {
        "position": list(getattr(camera, "position", []) or []),
        "forward": list(getattr(camera, "forward", []) or []),
        "up": list(getattr(camera, "up", []) or []),
        "lens_mm": float(getattr(camera, "lens_mm", 0.0) or 0.0),
        "rotation": dict(rotation) if isinstance(rotation, Mapping) else None,
        "provenance": PROVENANCE,
        "unit": {"position": "m", "lens": "mm", "rotation": "rad"},
    }


def _sample_dict(frame: SpatialFrame,
                 element_motions: Mapping[str, Dict[str, Any]],
                 ) -> Dict[str, Any]:
    elements = []
    for element in getattr(frame, "elements", []) or []:
        el_id = str(getattr(element, "id", ""))
        elements.append(_element_dict(element, element_motions.get(el_id)))
    return {
        "frame": int(getattr(frame, "frame", 0)),
        "camera": _camera_dict(getattr(frame, "camera", None)),
        "elements": elements,
    }


def build_observation_snapshot(frames: Iterable[SpatialFrame]) -> Dict[str, Any]:
    """把一组采样帧装配成观测快照。

    ``frames``：同一镜像的多个 `SpatialFrame`（可多镜混入，按 shot_id 分组）。
    运动差分按「镜头内同元素跨采样帧中心点」计算；运动跨镜不混算。空镜合法
    （元素列表为空）。确定性：同输入两次逐位一致。
    """
    by_shot: Dict[str, List[SpatialFrame]] = {}
    for frame in frames or []:
        shot_id = str(getattr(frame, "shot_id", ""))
        by_shot.setdefault(shot_id, []).append(frame)

    shots = []
    for shot_id in sorted(by_shot):
        ordered = sorted(by_shot[shot_id], key=lambda item: int(
            getattr(item, "frame", 0)))
        # 镜头内逐元素跨帧运动差分
        center_by_el: Dict[str, Dict[int, List[float]]] = {}
        for frame in ordered:
            for element in getattr(frame, "elements", []) or []:
                el_id = str(getattr(element, "id", ""))
                pos = _position_of(element)
                if not pos:
                    continue
                center_by_el.setdefault(el_id, {})[
                    int(getattr(frame, "frame", 0))] = pos
        motions = {el_id: frame_displacements(frames_map)
                   for el_id, frames_map in center_by_el.items()}
        shots.append({
            "shot_id": shot_id,
            "samples": [_sample_dict(frame, motions) for frame in ordered],
        })
    return {
        "schema_version": OBSERVATION_SNAPSHOT_SCHEMA,
        "shots": shots,
    }


__all__ = ["build_observation_snapshot", "frame_displacements",
           "OBSERVATION_SNAPSHOT_SCHEMA"]
