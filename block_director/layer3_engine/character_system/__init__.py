"""角色系统（执行文档 v1.2 §9）。"""

from __future__ import annotations

from .character_factory import (
    BODY_HEIGHT,
    BODY_RADIUS,
    EXPECTED_TOTAL_HEIGHT,
    HEAD_RADIUS,
    LEG_HEIGHT,
    LEG_RADIUS,
    PIVOT_Z,
    Character,
    create_character,
    measure_height,
)
from .character_label import (
    CJK_FONT_CANDIDATES,
    create_label,
    find_cjk_font,
    has_cjk,
)
from .motion_blender import MotionBlender
from .motion_library import (
    CHANNEL_TARGETS,
    BakeResult,
    apply_motions,
    bake_trace,
    clear_animation,
)

__all__ = [
    "Character", "create_character", "measure_height",
    "create_label", "find_cjk_font", "has_cjk", "CJK_FONT_CANDIDATES",
    "MotionBlender", "apply_motions", "bake_trace", "clear_animation",
    "BakeResult", "CHANNEL_TARGETS",
    "PIVOT_Z", "EXPECTED_TOTAL_HEIGHT",
    "HEAD_RADIUS", "BODY_RADIUS", "BODY_HEIGHT", "LEG_RADIUS", "LEG_HEIGHT",
]
