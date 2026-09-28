"""交付内容生成（执行文档 v1.2 §15.4 / §15.5）。

纯计算：镜头清单与 Prompt 表都由数据拼装，不依赖 bpy，因此可单测。
真正的渲染与写盘在 ``layer8_delivery/``。
"""

from __future__ import annotations

from .manifest import build_manifest
from .prompts import SHOT_TYPE_LABELS, compose_prompt, render_prompt_sheet
from .depth import (
    DEPTH_DIR_TEMPLATE,
    DEPTH_FRAME_PREFIX,
    DEPTH_RANGE,
    depth_dir_name,
    depth_manifest_entry,
    depth_range_note,
)

__all__ = ["build_manifest", "render_prompt_sheet", "compose_prompt",
           "SHOT_TYPE_LABELS", "DEPTH_RANGE", "DEPTH_DIR_TEMPLATE",
           "DEPTH_FRAME_PREFIX", "depth_dir_name", "depth_range_note",
           "depth_manifest_entry"]
