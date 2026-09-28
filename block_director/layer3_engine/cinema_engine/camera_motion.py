"""把运镜采样写成关键帧（执行文档 v1.2 §10.2）。

纯计算在 ``block_director/cinema/camera_motion.py``；本模块只负责把采样点
插到相机的 ``location`` 与对准 Empty 的 ``location`` 上。**不旋转相机对象**：
朝向由 Track To 约束推出来，插值因此不会出现欧拉角翻滚。
"""

from __future__ import annotations

from typing import Dict, List, Optional

import bpy
from mathutils import Vector

from ...cinema.camera_motion import LOOK_AT_DISTANCE, movement_samples
from ...utils.logger import get_logger
from ...utils.threading_guard import main_thread_only

log = get_logger("camera-motion")


def _current_look_at(camera, target) -> Vector:
    if target is not None:
        return target.matrix_world.translation.copy()
    rotation = camera.matrix_world.to_quaternion()
    forward = rotation @ Vector((0.0, 0.0, -1.0))
    return camera.matrix_world.translation + forward * LOOK_AT_DISTANCE


@main_thread_only("apply_camera_movement")
def apply_camera_movement(camera, target, movement: str, amount: float,
                          start_frame: int, end_frame: int,
                          samples: int = 3) -> Dict[str, object]:
    """给相机加一段运镜，返回插入的关键帧数与首末位置。"""
    position = tuple(camera.matrix_world.translation)
    look_at = tuple(_current_look_at(camera, target))
    plan = movement_samples(position, look_at, movement, amount,
                            start_frame, end_frame, samples=samples)

    inserted = 0
    for sample in plan:
        frame = int(sample["frame"])
        camera.location = Vector(sample["position"])
        camera.keyframe_insert(data_path="location", frame=frame)
        inserted += 1
        if target is not None:
            target.location = Vector(sample["look_at"])
            target.keyframe_insert(data_path="location", frame=frame)
            inserted += 1

    for obj in (camera, target):
        if obj is None or obj.animation_data is None:
            continue
        action = obj.animation_data.action
        for curve in _fcurves(action):
            for point in curve.keyframe_points:
                point.interpolation = 'BEZIER'
    bpy.context.view_layer.update()
    log.info("运镜 %s：%d 个采样点 / %d 个关键帧", movement, len(plan), inserted)
    return {"movement": movement, "samples": len(plan), "keyframes": inserted,
            "start": list(plan[0]["position"]),
            "end": list(plan[-1]["position"])}


def _fcurves(action) -> List[object]:
    from ...utils.blender_compat import action_fcurves
    return list(action_fcurves(action))
