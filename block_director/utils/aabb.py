"""轴对齐包围盒（执行文档 v1.2 §11.1 R002 空间碰撞 / §17.7）。

纯计算，不依赖 bpy，便于单测。旋转墙体的包围盒按其世界包围盒近似
（预演精度足够，调用方需在日志里标注为近似）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence, Tuple

Vec3 = Tuple[float, float, float]


@dataclass(frozen=True)
class AABB:
    minimum: Vec3
    maximum: Vec3

    @classmethod
    def from_center_size(cls, center: Sequence[float],
                         size: Sequence[float]) -> "AABB":
        half = [float(s) / 2.0 for s in size]
        c = [float(v) for v in center]
        return cls(minimum=(c[0] - half[0], c[1] - half[1], c[2] - half[2]),
                   maximum=(c[0] + half[0], c[1] + half[1], c[2] + half[2]))

    def expanded(self, amount: float) -> "AABB":
        a = float(amount)
        return AABB(minimum=(self.minimum[0] - a, self.minimum[1] - a,
                             self.minimum[2] - a),
                    maximum=(self.maximum[0] + a, self.maximum[1] + a,
                             self.maximum[2] + a))

    @property
    def center(self) -> Vec3:
        return ((self.minimum[0] + self.maximum[0]) / 2.0,
                (self.minimum[1] + self.maximum[1]) / 2.0,
                (self.minimum[2] + self.maximum[2]) / 2.0)

    @property
    def size(self) -> Vec3:
        return (self.maximum[0] - self.minimum[0],
                self.maximum[1] - self.minimum[1],
                self.maximum[2] - self.minimum[2])

    @property
    def volume(self) -> float:
        sx, sy, sz = self.size
        return max(sx, 0.0) * max(sy, 0.0) * max(sz, 0.0)

    def overlaps(self, other: "AABB", margin: float = 0.0) -> bool:
        """三轴都发生重叠才算相交（仅接触面不算）。"""
        target = other.expanded(margin) if margin else other
        return (self.minimum[0] < target.maximum[0]
                and self.maximum[0] > target.minimum[0]
                and self.minimum[1] < target.maximum[1]
                and self.maximum[1] > target.minimum[1]
                and self.minimum[2] < target.maximum[2]
                and self.maximum[2] > target.minimum[2])


def union(boxes: Iterable[AABB]) -> AABB:
    items = list(boxes)
    if not items:
        raise ValueError("union 至少需要一个包围盒")
    minimum = (min(b.minimum[0] for b in items),
               min(b.minimum[1] for b in items),
               min(b.minimum[2] for b in items))
    maximum = (max(b.maximum[0] for b in items),
               max(b.maximum[1] for b in items),
               max(b.maximum[2] for b in items))
    return AABB(minimum=minimum, maximum=maximum)
