"""摄影与构图引擎（执行文档 v1.2 §10）。Phase 1 只含相机创建。"""

from __future__ import annotations

from .camera_manager import (
    DEFAULT_LENS,
    DEFAULT_SENSOR_WIDTH,
    CameraBundle,
    create_camera,
)
from .framing_solver import place_camera_for_shot
from .axis_controller import (
    check_camera_axis,
    establish_axis_from_speakers,
    visualize_axis,
)
from .composition_guide import evaluate_camera_composition

__all__ = ["create_camera", "place_camera_for_shot", "CameraBundle",
           "DEFAULT_LENS", "DEFAULT_SENSOR_WIDTH",
           "establish_axis_from_speakers", "check_camera_axis", "visualize_axis",
           "evaluate_camera_composition"]
