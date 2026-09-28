"""摄影与构图引擎（执行文档 v1.2 §10）。Phase 1 只含相机创建。"""

from __future__ import annotations

from .camera_manager import (
    DEFAULT_LENS,
    DEFAULT_SENSOR_WIDTH,
    CameraBundle,
    create_camera,
)

__all__ = ["create_camera", "CameraBundle", "DEFAULT_LENS", "DEFAULT_SENSOR_WIDTH"]
