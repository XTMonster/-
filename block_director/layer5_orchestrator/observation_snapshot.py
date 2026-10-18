"""后向空间观测快照装配器（spatial-understanding-json Ticket 03；纯层，禁 bpy）。

把 ``frustum_sampler.sample_spatial`` 采到的 ``SpatialFrame`` 序列（已含
Ticket 01 的 rotation / gaze 字段）确定性折成版本化的「空间观测快照」：

* 逐镜、逐采样帧：相机（position/forward/up/rotation/lens/fov）与元素
  （position/aabb/center/facing/rotation/gaze），来源一律
  ``blender_geometry``；
* 运动差分：帧间位置差分 → 位移/速度/路径向量（首/中/末帧口径，差分式回读，
  不依赖 fcurve API）；``frame_delta<=0`` 的段跳过（不除零、不产生 NaN）；
* gaze 目标 id：采样侧只回读方向（``get_facing``），这里用
  ``plan.gaze``（from→to）做纯层映射，不猜；
* 空镜合法：相机 + 空元素列表 + 空 motion。
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..cinema.spatial_digest import (
    SpatialCamera,
    SpatialElement,
    SpatialFrame,
    camera_fov_degrees,
)
from ..contracts.plan import FPS
from ..contracts.spatial_snapshot import (
    OBSERVATION_SNAPSHOT_SCHEMA,
    ObservationSnapshot,
)


def _fv(value: Any, unit: str) -> Dict[str, Any]:
    return {"value": value, "unit": unit, "provenance": "blender_geometry"}


def _vec(value: Sequence[float]) -> List[float]:
    return [round(float(item), 4) for item in value]


def _camera_entry(camera: SpatialCamera) -> Dict[str, Any]:
    horizontal, vertical = camera_fov_degrees(camera)
    rotation = (dict(camera.rotation)
                if isinstance(camera.rotation, dict) else None)
    return {
        "position": _fv(_vec(camera.position), "m"),
        "forward": _fv(_vec(camera.forward), "none"),
        "up": _fv(_vec(camera.up), "none"),
        "rotation": _fv(rotation, "none"),
        "lens_mm": _fv(round(float(camera.lens_mm), 4), "mm"),
        "fov_degrees": _fv(
            {"horizontal": round(horizontal, 4),
             "vertical": round(vertical, 4)}, "deg"),
    }


def _gaze_entry(element: SpatialElement) -> Dict[str, Any]:
    if not isinstance(element.gaze, dict):
        return {"target_id": None, "direction": None}
    target_id = element.gaze.get("target_id")
    direction = element.gaze.get("direction")
    return {
        "target_id": str(target_id) if target_id else None,
        "direction": (_fv(_vec(direction), "none")
                      if direction is not None else None),
    }


def _element_entry(element: SpatialElement) -> Dict[str, Any]:
    rotation = (dict(element.rotation)
                if isinstance(element.rotation, dict) else None)
    facing = _fv(_vec(element.facing), "none") if element.facing else None
    return {
        "id": element.id,
        "kind": element.kind,
        "position": _fv(_vec(element.center), "m"),
        "aabb": {"min": _vec(element.aabb_min), "max": _vec(element.aabb_max)},
        "center": _fv(_vec(element.center), "m"),
        "facing": facing,
        "rotation": _fv(rotation, "none"),
        "gaze": _gaze_entry(element),
    }


def _frame_entry(frame: SpatialFrame) -> Dict[str, Any]:
    return {
        "frame": int(frame.frame),
        "camera": _camera_entry(frame.camera),
        "elements": [_element_entry(element)
                     for element in frame.elements],
    }


def _distance(a: Sequence[float], b: Sequence[float]) -> float:
    return math.sqrt(sum((float(a[i]) - float(b[i])) ** 2
                         for i in range(3)))


def _motion_for(frames: Sequence[SpatialFrame], element_id: str
                ) -> Optional[Dict[str, Any]]:
    """单元素跨采样帧的运动差分（无段/单段也合法）。"""
    points: List[Dict[str, Any]] = []
    for frame in frames:
        for element in frame.elements:
            if element.id == element_id:
                points.append({"frame": int(frame.frame),
                               "position": tuple(element.center)})
                break
    if len(points) < 2:
        #: 少于两个不同采样帧＝没有可差分的运动段：不出运动条目（空镜/单帧
        #: 镜头的 motion[] 为空，与"首/中/末帧"采样在 1 帧镜上退化为单帧一致）。
        return None
    displacements: List[float] = []
    speeds: List[float] = []
    path = [list(p["position"]) for p in points]
    total = 0.0
    for first, second in zip(points, points[1:]):
        dt_frames = second["frame"] - first["frame"]
        dt_s = dt_frames / float(FPS)
        if dt_s <= 0.0:
            continue                     # 同帧/时间倒流：跳过，绝不除零
        displacement = _distance(first["position"], second["position"])
        displacements.append(round(displacement, 4))
        speeds.append(round(displacement / dt_s, 4))
        total += displacement
    return {
        "subject_id": element_id,
        "frames": [p["frame"] for p in points],
        "path": path,
        "displacement_m": displacements,
        "speed_m_s": speeds,
        "total_displacement_m": round(total, 4),
    }


def _gaze_targets(plan, shot_id: str) -> Dict[str, str]:
    """该镜计划声明/推理出的 from→to 视线映射（纯层，不猜）。"""
    mapping: Dict[str, str] = {}
    for shot in (getattr(plan, "shots", None) or []):
        if str(getattr(shot, "shot_id", "")) != shot_id:
            continue
        for gaze in shot.gaze or []:
            if not isinstance(gaze, Mapping):
                continue
            source = str(gaze.get("from") or "")
            target = str(gaze.get("to") or "")
            if source and target:
                mapping[source] = target
    return mapping


def build_observation_snapshot(*, frames: Sequence[SpatialFrame],
                               plan=None, run_id: str = ""
                               ) -> ObservationSnapshot:
    """SpatialFrame 序列 → 观测快照（确定性、逐镜分组、差分运动）。"""
    #: 同镜同帧去重（保留首见）：sample_spatial 已保证无重复，这里兜底。
    by_shot: Dict[str, List[SpatialFrame]] = {}
    for frame in frames:
        shot_id = str(frame.shot_id)
        existing = {f.frame for f in by_shot.get(shot_id, [])}
        if frame.frame in existing:
            continue
        by_shot.setdefault(shot_id, []).append(frame)

    shots: List[Dict[str, Any]] = []
    for shot_id in sorted(by_shot):
        shot_frames = sorted(by_shot[shot_id], key=lambda f: f.frame)
        element_ids: List[str] = []
        for frame in shot_frames:
            for element in frame.elements:
                if element.id not in element_ids:
                    element_ids.append(element.id)
        gaze_map = _gaze_targets(plan, shot_id)
        rendered_frames = [_frame_entry(frame) for frame in shot_frames]
        if gaze_map:
            for rendered in rendered_frames:
                for element in rendered["elements"]:
                    target = gaze_map.get(str(element["id"]))
                    if target:
                        element["gaze"]["target_id"] = target
        motion = [_motion_for(shot_frames, element_id)
                  for element_id in element_ids]
        shots.append({
            "shot_id": shot_id,
            "frames": rendered_frames,
            "motion": [entry for entry in motion if entry is not None],
        })

    data: Dict[str, Any] = {
        "$schema": f"blockdirector://spatial-snapshot/"
                   f"{OBSERVATION_SNAPSHOT_SCHEMA}",
        "schema_version": OBSERVATION_SNAPSHOT_SCHEMA,
        "run_context": {
            "run_id": run_id,
            "generator": "blockdirector.observation_snapshot",
            "source_states": ["blender_geometry"],
        },
        "shots": shots,
        "notes": [
            "观测快照全部来自 Blender 实测（blender_geometry），"
            "运动为采样帧间位置差分，不依赖 fcurve。",
        ],
    }
    return ObservationSnapshot.from_dict(data)
