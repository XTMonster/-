"""摄影解算（执行文档 v1.2 §10.1 / §10.5 / §10.6）。

与 ``block_director/motion/`` 同理：纯计算放在这里（不依赖 bpy，可单测），
bpy 侧只负责把解算结果落到相机对象上。
"""

from __future__ import annotations

from .framing import (
    ASPECT_16_9,
    SENSOR_WIDTH,
    SHOT_FRAME,
    FramingResult,
    required_distance,
    side_vector,
    solve_framing,
    vertical_fov,
)
from .axis import (
    MIN_ANGLE_DEG,
    SIDE_NEGATIVE,
    SIDE_POSITIVE,
    Axis,
    axis_for_speakers,
    axis_from_points,
    axis_violation,
    camera_angle_deg,
    establish_axis,
    shot_size_changed,
    shot_size_index,
    thirty_degree_violation,
)
from .composition import (
    PASS_SCORE,
    WEIGHTS,
    CompositionItem,
    CompositionReport,
    SubjectBox,
    evaluate_composition,
)

__all__ = [
    "solve_framing", "required_distance", "side_vector", "vertical_fov",
    "FramingResult", "SHOT_FRAME", "SENSOR_WIDTH", "ASPECT_16_9",
    "Axis", "axis_from_points", "axis_for_speakers", "establish_axis",
    "axis_violation", "camera_angle_deg", "shot_size_index",
    "shot_size_changed", "thirty_degree_violation",
    "MIN_ANGLE_DEG", "SIDE_POSITIVE", "SIDE_NEGATIVE",
    "evaluate_composition", "CompositionReport", "CompositionItem",
    "SubjectBox", "WEIGHTS", "PASS_SCORE",
]
