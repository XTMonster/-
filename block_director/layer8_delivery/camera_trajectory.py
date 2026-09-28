"""相机轨迹导出（执行文档 v1.2 §15.7，可选产物）。

逐帧记录外参（位置 + 四元数）与内参，供相机可控视频生成使用。
读取 ``matrix_world`` 前必须先求值 depsgraph（§7.3 规则 1）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

import bpy

from ..utils.logger import get_logger
from ..utils.threading_guard import main_thread_only

log = get_logger("delivery.trajectory")


def _intrinsics(camera, resolution: Sequence[int]) -> Dict[str, float]:
    width, height = float(resolution[0]), float(resolution[1])
    data = camera.data
    sensor = float(getattr(data, "sensor_width", 36.0))
    lens = float(getattr(data, "lens", 50.0))
    focal = lens / sensor * width          # 像素焦距（方形像素）
    return {"fx": round(focal, 3), "fy": round(focal, 3),
            "cx": round(width / 2.0, 3), "cy": round(height / 2.0, 3)}


@main_thread_only("camera_trajectory")
def camera_trajectory(scene, shots: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """``shots`` 为 ``[{"shot_id":…, "start_frame":…, "end_frame":…, "camera": 对象名}]``。"""
    resolution = [scene.render.resolution_x, scene.render.resolution_y]
    payload: Dict[str, Any] = {
        "fps": int(scene.render.fps),
        "resolution": resolution,
        "sensor_width": 36.0,
        "shots": [],
    }

    for shot in shots:
        camera = bpy.data.objects.get(str(shot.get("camera", "")))
        if camera is None:
            continue
        start = int(shot["start_frame"])
        end = int(shot["end_frame"])
        frames: List[Dict[str, Any]] = []
        for frame in range(start, end + 1):
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            matrix = camera.matrix_world
            translation = matrix.translation
            quaternion = matrix.to_quaternion()
            frames.append({
                "frame": frame,
                "position": [round(v, 5) for v in translation],
                "rotation_quaternion": [round(v, 6) for v in quaternion],
                "lens": round(float(camera.data.lens), 3),
                "intrinsics": _intrinsics(camera, resolution),
            })
        payload["shots"].append({"shot_id": shot.get("shot_id"), "frames": frames})
    log.info("相机轨迹已导出：%d 个镜头", len(payload["shots"]))
    return payload
