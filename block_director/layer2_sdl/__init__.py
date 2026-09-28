"""SDL 场景描述层（执行文档 v1.2 §5）。纯 Python，不依赖 bpy。"""

from __future__ import annotations

from .sdl_builder import build_sdl, sdl_to_plan, sdl_to_spec
from .sdl_migrate import migrate_sdl
from .sdl_validator import validate_sdl

__all__ = ["build_sdl", "sdl_to_plan", "sdl_to_spec", "validate_sdl",
           "migrate_sdl"]
