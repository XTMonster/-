"""相机创建（执行文档 v1.2 §10.1 的 Phase 1 子集）。

按文档采用 **Track To 约束 + 目标 Empty** 对准；因此读取相机朝向之前
必须让 depsgraph 求值（§7.3 规则 1，该风险已由架构审核实测确认）。
取景解算（景别/焦距 → 距离/机位）属于 Phase 3。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import bpy
from bpy.types import Object

from ...utils.logger import get_logger
from ...utils.threading_guard import main_thread_only
from ..collection_router import route_to_content

log = get_logger("camera")

DEFAULT_LENS = 50.0
DEFAULT_SENSOR_WIDTH = 36.0


@dataclass
class CameraBundle:
    camera: Object
    target: Optional[Object] = None
    lens: float = DEFAULT_LENS
    sensor_width: float = DEFAULT_SENSOR_WIDTH


@main_thread_only("create_camera")
def create_camera(camera_id: str, location: Sequence[float],
                  look_at: Sequence[float] = (0.0, 0.0, 1.0),
                  lens: float = DEFAULT_LENS,
                  sensor_width: float = DEFAULT_SENSOR_WIDTH,
                  use_constraint: bool = True,
                  make_scene_camera: bool = True) -> CameraBundle:
    """建相机并对准目标；默认走 Track To 约束（与 §10.1 一致）。"""
    camera_data = bpy.data.cameras.new(f"BD_Cam_{camera_id}")
    camera_data.lens = float(lens)
    camera_data.sensor_width = float(sensor_width)
    camera = bpy.data.objects.new(f"BD_Cam_{camera_id}", camera_data)
    bpy.context.scene.collection.objects.link(camera)
    camera.location = tuple(location)
    camera["bd_sdl_id"] = camera_id
    camera["bd_element_type"] = "camera"

    target: Optional[Object] = None
    if use_constraint:
        target = bpy.data.objects.new(f"BD_CamTarget_{camera_id}", None)
        target.empty_display_type = 'SPHERE'
        target.empty_display_size = 0.2
        bpy.context.scene.collection.objects.link(target)
        target.location = tuple(look_at)
        route_to_content(target)

        constraint = camera.constraints.new('TRACK_TO')
        constraint.target = target
        constraint.track_axis = 'TRACK_NEGATIVE_Z'
        constraint.up_axis = 'UP_Y'
    else:
        from mathutils import Vector
        direction = Vector(look_at) - Vector(location)
        camera.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()

    route_to_content(camera)
    if make_scene_camera or bpy.context.scene.camera is None:
        bpy.context.scene.camera = camera
    bpy.context.view_layer.update()

    log.info("相机已创建：%s @ %s（%smm）", camera_id, tuple(location), lens)
    return CameraBundle(camera=camera, target=target, lens=lens,
                        sensor_width=sensor_width)
