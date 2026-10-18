"""纯几何/颜色工具（不依赖 bpy，因此可在 Blender 外单测）。

这些函数原本长在 character_factory 里，被 bpy 的 import 挡住了测试路径；
抽到这里之后既有单测覆盖，也能被将来的 layer1/2 复用。
"""

from __future__ import annotations

import math
from typing import Any, Dict, Sequence, Tuple


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

    坐标系：Z-up，X=右，Y=前（§1.4）。

    角色的正面是它的**局部 +Y**：`character_factory` 把眼睛放在 HeadPivot
    局部坐标 ``(±0.12, 0.30, 0)``，外缘指向 +Y。绕 Z 旋转 θ 之后，
    局部 +Y 映射到世界向量 ``(-sin θ, cos θ)``。要让世界朝向等于传入的
    ``(x, y)``，必须取 ``θ = atan2(-x, y)``——注意负号。

    历史缺陷（v1.3 修正）：v1.2 用的是 ``atan2(x, y)``，把 X 分量镜像了。
    实测传入 ``facing=(1, 0, 0)`` 时 ``get_facing()`` 返回 ``(-1, 0, 0)``，
    而 ``facing=(0.5, 0.86, 0)`` 返回 ``(-0.5026, 0.8645, 0)``。
    后果是"机位相对被摄者朝向"的解算在含 X 分量时落到角色背面。
    """
    if len(facing) < 2:
        return 0.0
    x, y = float(facing[0]), float(facing[1])
    if abs(x) < 1e-9 and abs(y) < 1e-9:
        return 0.0
    return math.atan2(-x, y)


def rotation_z_to_facing(theta: float) -> Tuple[float, float, float]:
    """``facing_to_rotation_z`` 的逆运算：绕 Z 的旋转角 → 世界面朝向量。

    这两个函数必须成对使用。只修一侧会让"写入朝向"与"回读朝向"互为镜像，
    而它们互相抵消时缺陷在往返测试里看不出来（v1.2 的 `scene_sync` 回读
    写的是 ``(sin θ, cos θ)``，恰好是旧 ``atan2(x, y)`` 的逆）。
    """
    return (round(-math.sin(theta), 6), round(math.cos(theta), 6), 0.0)


def rotation_payload(quaternion: Sequence[float],
                     euler: Sequence[float],
                     order: str = "XYZ") -> Dict[str, Any]:
    """构造观测/设计快照用的旋转负载（纯层，可测）。

    输入通常是 Blender 的 ``matrix_world.to_quaternion()`` /
    ``matrix_world.to_euler()`` 数值；这里只做归一化（float 化 + 4 位取整，
    与观测契约的数值口径一致），不 import bpy。四元数按 Blender 约定
    ``(w, x, y, z)``，欧拉按 ``(x, y, z)`` 弧度 + 顺序字符串。
    """
    return {
        "quaternion": [round(float(value), 4) for value in quaternion],
        "euler": [round(float(value), 4) for value in euler],
        "order": str(order or "XYZ"),
    }
