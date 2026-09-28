"""视口叠加的纯几何（执行文档 v1.2 §13.4）。"""

from .geometry import (
    OverlayGeometry,
    build_overlay,
    dashed_segments,
    frustum_lines,
    safe_area_rects,
    screen_rect,
    thirds_grid,
)

__all__ = ["OverlayGeometry", "build_overlay", "dashed_segments",
           "frustum_lines", "safe_area_rects", "screen_rect", "thirds_grid"]
