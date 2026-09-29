"""站位与取景参考系（v1.3 P0-2）。

把"这个镜头从哪里拍"拆成两件**互相独立**的事：

1. **焦点主体**：镜头对准谁——决定锚点与目标高度；
2. **轴线**：对话两人的连线——决定机位能落在哪一侧。

v1.2 把两件事混成一件：锚点取镜头内全部角色的重心，方向取第一个角色的朝向。
当两人相对而立（也就是"互相看向对方"这条语义）时，重心落在两人中点、朝向
沿着连线，于是 ``side="front"`` 把相机放在**轴线上**：``cinema/axis.py`` 的
``Axis.side_of`` 返回 ``SIDE_UNKNOWN``，R001 判越轴、画面方向感塌陷。
也就是说，**只修正朝向而不改这里，会把一个隐藏缺陷变成一个每次都会触发的
显性错误**。这就是本模块存在的理由。

纯函数，不依赖 bpy，因此可以在 pytest 里逐条断言。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from .framing import side_vector

EPS = 1e-9

#: 以"一组人"为被摄对象的景别：锚点取组重心，才能真的把多人框进来。
#: 更紧的景别（ECU/CU/MCU）以焦点主体为锚点，否则特写会框到两个人中间。
GROUP_SHOT_TYPES = frozenset({"MS", "MLS", "LS", "ELS", "OTS"})

#: 双人镜头里各 side 相对"轴线法线"的偏转量（单位：轴线方向的倍数）。
#: 约定：正值朝轴线**终点**（第二个角色）一侧偏，负值朝**起点**一侧偏。
_AXIS_OFFSETS = {
    "front": 0.0,
    "front_right": 0.4,
    "front_left": -0.4,
    "right": 1.0,
    "left": -1.0,
}

#: 过肩镜头在轴线上的偏移系数：足够小，保持"近轴"而不是变成侧面双人。
OVER_SHOULDER_AXIS = 0.35


def _normalise(vec: Sequence[float],
               fallback: Tuple[float, float] = (0.0, 1.0)) -> Tuple[float, float]:
    x, y = float(vec[0]), float(vec[1])
    norm = math.hypot(x, y)
    if norm < EPS:
        return fallback
    return (x / norm, y / norm)


def right_of(direction: Sequence[float]) -> Tuple[float, float]:
    """方向的右手边，与 :func:`block_director.cinema.framing.side_vector`
    里 ``right`` 的定义完全一致（X=右、Y=前时，朝 +Y 的右手边是 +X）。"""
    dx, dy = _normalise(direction)
    return (dy, -dx)


@dataclass(frozen=True)
class SubjectFrame:
    """一次取景的主体参考系。"""

    anchor: Tuple[float, float, float]
    facing: Tuple[float, float, float]
    focus_id: str = ""
    group: bool = False
    axis_start_id: str = ""
    axis_start: Optional[Tuple[float, float]] = None
    axis_end_id: str = ""
    axis_end: Optional[Tuple[float, float]] = None

    @property
    def has_axis(self) -> bool:
        return self.axis_start is not None and self.axis_end is not None

    def axis_direction(self) -> Tuple[float, float]:
        """轴线方向（起点 → 终点，单位向量）。"""
        if not self.has_axis:
            return (0.0, 0.0)
        return _normalise((self.axis_end[0] - self.axis_start[0],
                           self.axis_end[1] - self.axis_start[1]),
                          fallback=(0.0, 0.0))

    def partner_of_focus(self) -> Optional[Tuple[float, float]]:
        """焦点主体在轴线上的搭档位置（没有轴线时为 None）。"""
        if not self.has_axis:
            return None
        if self.focus_id and self.focus_id == self.axis_end_id:
            return self.axis_start
        return self.axis_end

    def to_dict(self) -> dict:
        return {"anchor": list(self.anchor), "facing": list(self.facing),
                "focus_id": self.focus_id, "group": self.group,
                "axis_start": list(self.axis_start) if self.axis_start else None,
                "axis_end": list(self.axis_end) if self.axis_end else None}


def subject_frame(entries: Sequence[Sequence[object]], *,
                  shot_type: str = "MS",
                  speaker_id: str = "") -> SubjectFrame:
    """由镜头的角色条目推导取景参考系。

    ``entries`` 是 ``(character_id, position, facing)`` 的序列，顺序即
    ``shot.characters`` 的顺序；轴线取**前两位**，与
    ``cinema_engine.axis_controller.establish_axis_from_speakers`` 的
    ``characters[:2]`` 一致。

    ``speaker_id`` 是本镜第一个说话的角色；它决定：

    * 焦点主体（特写对准谁）；
    * 轴线法线取哪一侧（朝焦点主体的正面）。
    """
    items = [(str(entry[0]),
              (float(entry[1][0]), float(entry[1][1])),
              (float(entry[2][0]), float(entry[2][1])))
             for entry in entries]
    if not items:
        return SubjectFrame(anchor=(0.0, 0.0, 0.0), facing=(0.0, 1.0, 0.0))

    focus_id = str(speaker_id or "")
    focus = next((item for item in items if item[0] == focus_id), items[0])
    facing3 = (focus[2][0], focus[2][1], 0.0)

    if len(items) == 1:
        return SubjectFrame(anchor=(focus[1][0], focus[1][1], 0.0),
                            facing=facing3, focus_id=focus[0])

    group = str(shot_type).upper() in GROUP_SHOT_TYPES
    if group:
        x = sum(item[1][0] for item in items) / len(items)
        y = sum(item[1][1] for item in items) / len(items)
        anchor = (x, y, 0.0)
    else:
        anchor = (focus[1][0], focus[1][1], 0.0)

    first, second = items[0], items[1]
    return SubjectFrame(anchor=anchor, facing=facing3, focus_id=focus[0],
                        group=group,
                        axis_start_id=first[0], axis_start=first[1],
                        axis_end_id=second[0], axis_end=second[1])


def camera_direction(frame: SubjectFrame, side: str = "front"
                     ) -> Tuple[float, float]:
    """解析 ``side``，返回**单位**机位方向。

    单人镜头沿用 §10.1 / §10.5 的语义（相对角色朝向，由
    :func:`side_vector` 提供）；两人及以上的镜头改相对**轴线法线**——
    相对焦点主体朝向会把机位放到轴线上（见模块 docstring）。
    """
    key = str(side or "front")
    if not frame.has_axis:
        return side_vector(frame.facing, key)

    axis = frame.axis_direction()
    if axis == (0.0, 0.0):
        # 两人位置重合：轴线退化，按单人处理而不是产生 NaN 方向。
        return side_vector(frame.facing, key)

    normal = right_of(axis)
    facing_xy = _normalise(frame.facing)
    # 取"指向焦点主体正面"的那一条法线。两人正对彼此（点积≈0）时保持
    # 确定性的右侧法线——得到标准的侧面双人构图，且机位不在轴线上。
    if facing_xy[0] * normal[0] + facing_xy[1] * normal[1] < 0.0:
        normal = (-normal[0], -normal[1])

    if key == "over_shoulder":
        partner = frame.partner_of_focus()
        if partner is None:
            return normal
        # 站在搭档一侧、略微偏离轴线：这才是"过肩"，而不是纯侧面。
        toward = _normalise((partner[0] - frame.anchor[0],
                             partner[1] - frame.anchor[1]), fallback=axis)
        return _normalise((toward[0] + OVER_SHOULDER_AXIS * normal[0],
                           toward[1] + OVER_SHOULDER_AXIS * normal[1]),
                          fallback=toward)

    if key == "back":
        return (-normal[0], -normal[1])

    if key.startswith("back_"):
        offset = _AXIS_OFFSETS.get(key.replace("back_", "front_"), 0.0)
        base = (-normal[0], -normal[1])
        return _normalise((base[0] + offset * axis[0],
                           base[1] + offset * axis[1]), fallback=base)

    offset = _AXIS_OFFSETS.get(key, 0.0)
    return _normalise((normal[0] + offset * axis[0],
                       normal[1] + offset * axis[1]), fallback=normal)
