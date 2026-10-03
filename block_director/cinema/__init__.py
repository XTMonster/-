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
    AXIS_DRIFT_DEG,
    CROSSING_MIN_DEG,
    MIN_ANGLE_DEG,
    SIDE_NEGATIVE,
    SIDE_POSITIVE,
    SIDE_UNKNOWN,
    Axis,
    axis_for_speakers,
    axis_from_points,
    axis_neutral_note,
    axis_status,
    axis_state,
    axis_violation,
    camera_side_of,
    current_line,
    drift_is_bridged,
    pair_spans,
    camera_angle_deg,
    establish_axis,
    shot_size_changed,
    shot_size_index,
    thirty_degree_violation,
)
from .station import (
    GROUP_SHOT_TYPES,
    SubjectFrame,
    camera_direction,
    right_of,
    subject_frame,
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
    "current_line",
    "axis_state",
    "drift_is_bridged", "AXIS_DRIFT_DEG", "CROSSING_MIN_DEG",
    "camera_side_of",
    "pair_spans",
    "axis_violation", "axis_status", "axis_neutral_note", "camera_angle_deg",
    "shot_size_index",
    "shot_size_changed", "thirty_degree_violation",
    "MIN_ANGLE_DEG", "SIDE_POSITIVE", "SIDE_NEGATIVE", "SIDE_UNKNOWN",
    "SubjectFrame", "subject_frame", "camera_direction", "right_of",
    "GROUP_SHOT_TYPES",
    "evaluate_composition", "CompositionReport", "CompositionItem",
    "SubjectBox", "WEIGHTS", "PASS_SCORE",
]
