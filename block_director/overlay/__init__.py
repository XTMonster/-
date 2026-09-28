"""视口叠加的纯几何（执行文档 v1.2 §13.4）。"""

from .geometry import (
    FLASH_HIGH,
    FLASH_LOW,
    FLASH_PERIOD,
    OverlayGeometry,
    build_overlay,
    dashed_segments,
    flash_alpha,
    frustum_lines,
    safe_area_rects,
    screen_rect,
    thirds_grid,
)

__all__ = ["OverlayGeometry", "build_overlay", "dashed_segments",
           "frustum_lines", "safe_area_rects", "screen_rect", "thirds_grid",
           "flash_alpha", "FLASH_PERIOD", "FLASH_LOW", "FLASH_HIGH"]
