"""纯 Python 的 mask 交付自检。

Mask pass 已经把每帧写成 PNG；这里不依赖 Blender，只检查同一镜的
帧文件是否逐字节完全相同。全帧同字节是空画/静止画面的预警信号，
不会替代构图门或把镜头伪判为通过。
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional, Union

from ..cinema.blockout_report import E_EMPTY_FRAME

PathLike = Union[str, Path]


def empty_mask_warning(shot_id: str, files: Iterable[PathLike]) -> Optional[str]:
    """Return an ``E_EMPTY_FRAME`` warning when every mask frame is identical.

    Empty and single-frame sequences are not enough evidence for a *sequence*
    warning. Missing/unreadable files are likewise left to the existing mask
    frame-count validation rather than being conflated with empty content.
    """
    paths = [Path(item) for item in files]
    if len(paths) < 2:
        return None
    try:
        first = paths[0].read_bytes()
        if not first:
            return None
        if any(path.read_bytes() != first for path in paths[1:]):
            return None
    except (OSError, ValueError):
        return None
    return (f"{E_EMPTY_FRAME}: {shot_id}: mask 全帧同字节（{len(paths)} 帧），"
            "疑似空画/静止画面")


__all__ = ["empty_mask_warning"]
