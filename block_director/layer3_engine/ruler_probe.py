"""空间尺测量采集（Ticket 04）：把 Blender 实测序列化成契约记录。

这是"几何级空间尺"的插件侧接缝：在场景构建之后、审核/交付之前，把
相机参数、构图评分、逐主体包围盒/可见性、相邻镜角差整理成
``contracts/spatial_ruler.py`` 的 measurement 形状。本模块允许 `bpy`，
采到的都是只读几何事实（来源 ``blender_geometry``）；声明/计划侧的
时长测量也从这里一并带出（``script_declaration`` / ``plan_intent``）。

纪律：
* 顶层不 import `bpy`（pytest 环境可安全收集本模块）；
* 采样失败（``SamplingError``）不回传、不伪造——测量缺失时如实缺；
* 采样/构图评估前后还原当前帧，不改场景状态（与 ``check_shot`` 同纪律）。
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence

from ..cinema.ruler_measure import measurements_for_shot
from ..utils.threading_guard import main_thread_only


def _angle_between(previous: Any, current: Any, center: Any) -> float:
    """以 center 为顶点，两相机位置向量的夹角（度，0–180）。"""
    from mathutils import Vector

    a = Vector(previous) - Vector(center)
    b = Vector(current) - Vector(center)
    la = a.length
    lb = b.length
    if la <= 1e-6 or lb <= 1e-6:
        return 0.0
    cosine = max(-1.0, min(1.0, a.dot(b) / (la * lb)))
    return math.degrees(math.acos(cosine))


@main_thread_only("ruler_probe.collect_shot_measurements")
def collect_shot_measurements(shot_id: str,
                              context: Any = None) -> List[Dict[str, Any]]:
    """采集一镜的观测测量（契约 measurement 形状列表）。

    `context` 缺省取当前活动的 ``SceneContext``；镜头无相机时返回空表
    （不猜、不伪造）。
    """
    from .cinema_engine import evaluate_camera_composition
    from .frustum_sampler import SamplingError, sample_shot
    from .rule_checker import audit_frames
    from .scene_context import get_context
    from ..settings import get_config
    import bpy
    from mathutils import Vector

    context = context or get_context()
    if context is None:
        return []
    shot_id = str(shot_id)
    camera = context.camera_for(shot_id)
    if camera is None or getattr(camera, "data", None) is None:
        return []
    shot = context.shot(shot_id)
    fps = int(getattr(getattr(get_config(), "animation", None), "fps", 24)
              or 24)
    planned_frames = int(getattr(shot, "duration_frames", 0) or 0)
    declared_frames = int(getattr(shot, "declared_duration_frames", 0) or 0)
    declared_seconds = (float(declared_frames) / fps
                        if declared_frames > 0 else None)

    scene = bpy.context.scene
    original_frame = int(scene.frame_current)
    characters = context.subjects_for(shot_id) if shot is not None else []
    positions = [
        getattr(character, "root", None).matrix_world.translation
        for character in characters
        if getattr(getattr(character, "root", None), "matrix_world", None)
        is not None
    ]
    center = None
    if positions:
        center = sum(positions, Vector()) / len(positions)

    camera_pos = camera.matrix_world.translation.copy()
    distance = (camera_pos - center).length if center is not None else None
    camera_info: Dict[str, Any] = {
        "lens": float(camera.data.lens),
        "position": [float(camera_pos.x), float(camera_pos.y),
                     float(camera_pos.z)],
        "target": ([float(center.x), float(center.y), float(center.z)]
                   if center is not None else None),
        "distance": distance,
        "shot_type": str(context.shot_types.get(shot_id, "MS")),
    }

    composition_score = None
    composition_items = None
    if characters:
        try:
            if original_frame != scene.frame_current:
                pass                     # evaluate 用当前帧；静止场景无影响
            report = evaluate_camera_composition(
                camera, characters,
                shot_type=str(context.shot_types.get(shot_id, "MS")))
            composition_score = float(report.score)
            composition_items = {
                name: {"score": item.score, "weight": item.weight,
                       "suggestion": item.suggestion}
                for name, item in report.items.items()
            }
        except Exception:                # noqa: BLE001 - 构图失败不回传伪造测量
            composition_score = None
            composition_items = None

    frame_samples: Sequence[Any] = []
    try:
        frame_samples = sample_shot(
            shot_id, step=4,
            extra_frames=tuple(audit_frames(shot_id, context)))
    except SamplingError:
        frame_samples = []               # 采样失败如实缺，不写 0 值冒充

    transition_angle: Optional[float] = None
    transition_prev: Optional[str] = None
    plan = getattr(context, "plan", None)
    order = [item.shot_id for item in getattr(plan, "shots", []) or []]
    if shot_id in order and order.index(shot_id) > 0 and center is not None:
        previous_id = order[order.index(shot_id) - 1]
        previous_camera = context.camera_for(previous_id)
        if previous_camera is not None:
            transition_angle = _angle_between(
                previous_camera.matrix_world.translation.copy(),
                camera_pos, center)
            transition_prev = previous_id

    return measurements_for_shot(
        shot_id=shot_id,
        declared_seconds=declared_seconds,
        planned_frames=planned_frames or None,
        fps=fps,
        camera=camera_info,
        composition_score=composition_score,
        composition_items=composition_items,
        frame_samples=frame_samples,
        transition_angle_deg=transition_angle,
        transition_prev_id=transition_prev,
    )
