"""把运镜采样写成关键帧（执行文档 v1.2 §10.2 / v1.3 P7）。

纯计算在 ``block_director/cinema/camera_motion.py``；本模块只负责把采样点
插到相机的 ``location`` 与对准 Empty 的 ``location`` 上。**不旋转相机对象**：
朝向由 Track To 约束推出来，插值因此不会出现欧拉角翻滚。

v1.3 补齐两件让"全量运镜"真正落地的东西：

* **焦距通道**——变焦与推拉变焦靠 ``camera.data.lens`` 的关键帧，只写位置
  等于没动；
* **被摄主体路径**——跟拍/前导/斯坦尼康需要主体逐帧的位置，主体在别的时间
  轴上有自己的动作关键帧，所以这条路径只能在**动作烘焙之后**采样。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import bpy
from mathutils import Vector

from ...cinema.camera_motion import (
    LOOK_AT_DISTANCE,
    movement_samples,
    sample_frames,
)
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
                          samples: int = 3, *, subject=None,
                          subject_path: Optional[List[Sequence[float]]] = None,
                          seed: int = 0) -> Dict[str, object]:
    """给相机加一段运镜，返回插入的关键帧数与首末位置。

    ``subject`` 给了就会**自己采样**它的逐帧位置（调用方不必先算好）；
    ``subject_path`` 则留给"路径已经算好"的场合（测试与重放）。
    """
    position = tuple(camera.matrix_world.translation)
    look_at = tuple(_current_look_at(camera, target))
    lens = float(camera.data.lens)
    if subject_path is None and subject is not None:
        subject_path = _sample_subject_path(subject, look_at,
                                            movement, start_frame, end_frame,
                                            samples)
    plan = movement_samples(position, look_at, movement, amount,
                            start_frame, end_frame, samples=samples,
                            lens=lens, subject_path=subject_path, seed=seed)

    inserted = 0
    lens_varies = any(abs(float(sample["lens"]) - lens) > 1e-9
                      for sample in plan)
    for sample in plan:
        frame = int(sample["frame"])
        camera.location = Vector(sample["position"])
        camera.keyframe_insert(data_path="location", frame=frame)
        inserted += 1
        if target is not None:
            target.location = Vector(sample["look_at"])
            target.keyframe_insert(data_path="location", frame=frame)
            inserted += 1
        if lens_varies:
            camera.data.lens = float(sample["lens"])
            # 焦距属于**相机数据块**：关键帧要插在 data 自己身上。
            # 在对象上插 "data.lens" 会报 "path spans ID blocks"，
            # 而对象上的 "lens" 根本不存在的（BlockDirector 实测）。
            camera.data.keyframe_insert(data_path="lens", frame=frame)
            inserted += 1

    for obj in (camera, target, camera.data):
        if obj is None or obj.animation_data is None:
            continue
        action = obj.animation_data.action
        for curve in _fcurves(action):
            for point in curve.keyframe_points:
                point.interpolation = 'BEZIER'
    bpy.context.view_layer.update()
    log.info("运镜 %s：%d 个采样点 / %d 个关键帧", movement, len(plan), inserted)
    return {"movement": movement, "samples": len(plan), "keyframes": inserted,
            "lens_varies": lens_varies,
            "subject": getattr(subject, "name", "") if subject is not None else "",
            "start": list(plan[0]["position"]),
            "end": list(plan[-1]["position"])}


def _sample_subject_path(subject, look_at, movement: str, start_frame: int,
                         end_frame: int,
                         samples: int) -> List[Tuple[float, float, float]]:
    """按运镜采样表取被摄主体逐帧的位置（跟拍用）。

    采样会把场景帧号搬到各个采样点上，结束后**还原**到原帧：调用方（构建器）
    之后还要继续渲染与审核，不能被这次采样留下副作用。
    """
    scene = bpy.context.scene
    original = int(scene.frame_current)
    root = getattr(subject, "root", subject)
    try:
        scene.frame_set(int(start_frame))
        bpy.context.view_layer.update()
        anchor = tuple(root.matrix_world.translation)
        # 主体根点通常在脚下，而 look_at 在胸口/头顶：把这段高度差带上，
        # 相机才会保持与"对准点"的相对关系，而不是贴到地面。
        lift = tuple(float(look_at[i]) - float(anchor[i]) for i in range(3))
        path: List[Tuple[float, float, float]] = []
        for frame in sample_frames(int(start_frame), int(end_frame),
                                   samples, movement):
            scene.frame_set(int(frame))
            bpy.context.view_layer.update()
            here = tuple(root.matrix_world.translation)
            path.append(tuple(round(float(here[i]) + lift[i], 6)
                              for i in range(3)))
        return path
    finally:
        scene.frame_set(original)
        bpy.context.view_layer.update()


def _fcurves(action) -> List[object]:
    from ...utils.blender_compat import action_fcurves
    return list(action_fcurves(action))
