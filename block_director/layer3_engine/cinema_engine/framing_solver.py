"""把取景解算落到真实相机上（执行文档 v1.2 §10.1 / §10.6）。

纯计算在 ``block_director/cinema/framing.py``；本模块只做"解算 → 建相机"。
"""

from __future__ import annotations

from typing import Optional, Sequence

from ...cinema.framing import ASPECT_16_9, SENSOR_WIDTH, FramingResult, solve_framing
from ...utils.logger import get_logger
from ...utils.threading_guard import main_thread_only
from .camera_manager import CameraBundle, create_camera

log = get_logger("framing-solver")


@main_thread_only("place_camera_for_shot")
def place_camera_for_shot(shot_id: str,
                          subject_pos: Sequence[float],
                          facing: Sequence[float] = (0.0, 1.0, 0.0),
                          shot_type: str = "MS",
                          side: str = "front",
                          lens: Optional[float] = None,
                          room: Optional[Sequence[float]] = None,
                          margin: float = 0.5,
                          use_constraint: bool = True,
                          make_scene_camera: bool = True,
                          direction: Optional[Sequence[float]] = None,
                          aim_offset_x: float = 0.0,
                          aim_offset_y: float = 0.0):
    """解算机位并创建相机。返回 ``(CameraBundle, FramingResult)``。

    ``direction`` 由 :mod:`block_director.cinema.station` 解算（双人镜头相对
    两人连线），给出时覆盖 ``side``。

    ``aim_offset_x`` 由同一处解算（单主体镜头的视线留白，§10.4）：只把对准点
    横向挪到三分线，机位与焦距不动。
    """
    solution: FramingResult = solve_framing(
        subject_pos=subject_pos, facing=facing, shot_type=shot_type, side=side,
        lens=lens, room=room, margin=margin, direction=direction,
        aim_offset_x=aim_offset_x, aim_offset_y=aim_offset_y)
    for warning in solution.warnings:
        log.warning("取景 %s: %s", shot_id, warning)

    bundle: CameraBundle = create_camera(
        camera_id=shot_id, location=solution.position, look_at=solution.target,
        lens=solution.lens, sensor_width=SENSOR_WIDTH,
        use_constraint=use_constraint, make_scene_camera=make_scene_camera)
    bundle.camera["bd_shot_type"] = solution.shot_type
    bundle.camera["bd_frame_height"] = solution.frame_height
    return bundle, solution


def aspect_ratio() -> float:
    return ASPECT_16_9
