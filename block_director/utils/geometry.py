"""纯几何/颜色工具（不依赖 bpy，因此可在 Blender 外单测）。

这些函数原本长在 character_factory 里，被 bpy 的 import 挡住了测试路径；
抽到这里之后既有单测覆盖，也能被将来的 layer1/2 复用。
"""

from __future__ import annotations

import math
from typing import Sequence, Tuple


def hex_to_rgb(color: str) -> Tuple[float, float, float]:
    """``#RRGGBB`` / ``#RGB`` → 0..1 三元组；非法输入回退为白色。"""
    text = (color or "").lstrip("#").strip()
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        return (1.0, 1.0, 1.0)
    try:
        return (int(text[0:2], 16) / 255.0,
                int(text[2:4], 16) / 255.0,
                int(text[4:6], 16) / 255.0)
    except ValueError:
        return (1.0, 1.0, 1.0)


def facing_to_rotation_z(facing: Sequence[float]) -> float:
    """把面朝向量转成绕 Z 的旋转角（默认面朝 +Y 时为 0）。

    坐标系：Z-up，X=右，Y=前（§1.4）。因此 (0,1,0) → 0，(1,0,0) → π/2。
    """
    if len(facing) < 2:
        return 0.0
    x, y = float(facing[0]), float(facing[1])
    if abs(x) < 1e-9 and abs(y) < 1e-9:
        return 0.0
    return math.atan2(x, y)
