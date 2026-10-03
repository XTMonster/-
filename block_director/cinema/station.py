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

#: 单主体镜头落在轴线上时的默认偏角（度）。
#: 两人相对而立时，B 的正面机位恰好是 A 站着的地方——距离一旦大于两人间距，
#: 相机就跑到 A 背后，把 A 拍进画面并挡住 B（实测构图 39.4、遮挡项 0.3）。
#: 常规做法是把"干净单人"扭开 30°（dirty single）。当方向与轴线夹角小于
#: OFF_AXIS_MIN_COS 对应的角度时，就按本值扭开。
OFF_AXIS_DEG = 30.0
OFF_AXIS_MIN_COS = 0.94          # ≈ 20°

#: 视线留白（§10.4 的 `lead_room`）要求朝向侧占 ≥64.5% 的空白，三分线交点在
#: 1/3 与 2/3——把**主体放到背向视线的那条三分线**上，两个分项同时满足。
#: 1/6 幅宽正好是"画面中心 → 三分线"的距离。
LEAD_ROOM_OFFSET = 1.0 / 6.0

#: 单主体镜头把**对准点抬高**的米数（v1.8，2026-10-04 实测）。
#: `composition.py::_thirds` 要主体盒中心靠近 1/3 或 2/3 交点，而实测
#: （`work/_box_center_probe.py`，三份冻结工程）主体盒中心的**中位纵向偏差**是
#: 0.13（≈ 停在画面正中），于是`rule_of_thirds` 在 **61–63/64** 镜里都是弱项，
#: 也是红镜头里出现最多的那一项。`work/_aim_sweep_probe.py` 把对准点按
#: −0.4…+0.4 m 扫了一遍（long12 的 40 个单主体镜）：抬高 +0.1 / +0.2 m 的
#: 合计增益分别是 **+130 / +214 分**，而压低是 +34 / +38 ⇒ 取 +0.15 m
#: （介于两个最优步长之间，避免贴着扫描点选参）。
#: **不动 §2.2 D2 的 `SHOT_FRAME.target_z`**（那是冻结常量），只加这一层
#: 可测的取景偏移。
HEAD_ROOM_AIM_M = 0.15


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


def _rotate(vec: Tuple[float, float], degrees: float) -> Tuple[float, float]:
    angle = math.radians(float(degrees))
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    x, y = vec
    return (x * cos_a - y * sin_a, x * sin_a + y * cos_a)


def _off_axis(base: Tuple[float, float], *,
              axis_dir: Optional[Sequence[float]],
              axis_side: int = 0,
              subject_facing: Sequence[float] = (0.0, 1.0, 0.0)
              ) -> Optional[Tuple[float, float]]:
    """主体正对搭档时，把机位从轴线上扭开一档。

    返回扭开后的方向；方向本来就不在轴线附近时返回 ``None``（不动）。
    选哪一侧：优先匹配**已确立的轴侧**（否则会被判越轴）；还没有轴线时
    选主体自己的右手边，保证确定性。
    """
    if axis_dir is None:
        return None
    direction = _normalise(axis_dir, fallback=(0.0, 0.0))
    if direction == (0.0, 0.0):
        return None
    if abs(base[0] * direction[0] + base[1] * direction[1]) < OFF_AXIS_MIN_COS:
        return None                      # 已经明显离开轴线，保持原样

    candidates = (_rotate(base, OFF_AXIS_DEG), _rotate(base, -OFF_AXIS_DEG))
    if axis_side:
        for candidate in candidates:
            cross = direction[0] * candidate[1] - direction[1] * candidate[0]
            if (cross > 0) == (axis_side > 0):
                return _normalise(candidate, fallback=base)
    # 还没有轴线基准：选主体右手边（确定性，且不会与自身朝向打架）
    right = right_of(subject_facing)
    picked = max(candidates,
                 key=lambda item: item[0] * right[0] + item[1] * right[1])
    return _normalise(picked, fallback=base)


def _honour_the_established_side(base: Tuple[float, float],
                                 facing: Sequence[float], *,
                                 axis_dir: Optional[Sequence[float]],
                                 axis_side: int,
                                 notes: Optional[list] = None
                                 ) -> Tuple[float, float]:
    """单人镜头也要待在**已确立的轴侧**（v1.6，2026-10-03 真跑实测）。

    现场（`docs/evidence/20261003_chunked_long9/`，64 镜真跑）：**61 条 R001
    错误、21/64 镜，全部是单人镜头**；同跑里两人镜头一条都没有。翻实现：
    `side` 是**相对被摄主体朝向**的（§10.1/§10.5），而"两人相对而立"时两个
    角色的朝向相反——同一个 `front_right` 在两人的单人镜头里落在**世界轴线
    的两侧**。R001 的判据却是世界轴侧（`Axis.established_side`），于是模型
    写"同侧机位、不越轴"，引擎却把一半的单人镜头摆到另一侧。两人镜头在
    v1.5 已经改成按轴线法线解算（`test_axis_side_wins_over_facing.py`），
    单人镜头这条路当时没接上。

    处置：把方向关于**轴线**镜像一次——保持与轴线的夹角，只翻侧别。
    镜像**只在不改变前/后关系时**才做：否则"正面机位"会被悄悄换成背拍，
    那是换了一镜，不是修轴侧。真正无法同时满足的请求原样返回，留给 R001
    如实报错，而不是在这里吞掉。
    """
    if not axis_side or axis_dir is None:
        return base
    axis = _normalise(axis_dir, fallback=(0.0, 0.0))
    if axis == (0.0, 0.0):
        return base
    cross = axis[0] * base[1] - axis[1] * base[0]
    if cross == 0.0 or (cross > 0.0) == (axis_side > 0):
        return base                      # 已经在对的一侧（或正好在轴线上）
    dot = base[0] * axis[0] + base[1] * axis[1]
    mirrored = _normalise((2.0 * dot * axis[0] - base[0],
                           2.0 * dot * axis[1] - base[1]), fallback=base)
    front_before = facing[0] * base[0] + facing[1] * base[1]
    front_after = facing[0] * mirrored[0] + facing[1] * mirrored[1]
    if front_before > 0.0 >= front_after:
        # 镜像会把"正面"变成"背面"：这是模型与轴线真的打架，不在这里改。
        if notes is not None:
            notes.append("该镜的 side 落在已确立轴线的另一侧，且镜像会变成背拍；"
                         "保持模型要的方向，由 R001 如实报出")
        return base
    if notes is not None:
        notes.append(f"side={base} 落在已确立轴线的另一侧，"
                     f"已关于轴线镜像为 {mirrored} 以保持银幕方向连续")
    return mirrored


def aim_offset_for_lead_room(direction: Sequence[float],
                             facing: Sequence[float]) -> float:
    """**单主体镜头**的对准点横向偏移量（单位：幅宽），让 §10.4 得分。

    背景（2026-10-04，`long10` 的账）：终审 49 个未过镜头里 **27 个**带
    `COMPOSITION`，而两个分项的判据是：

    * `lead_room`：朝向侧空白占比 ≥64.5% 才满分（主体居中时只有 ~0.29）；
    * `rule_of_thirds`：主体要靠近 1/3 交点（居中时 ~0.05）。

    而求解器一直把主体**摆在画面正中**（`solve_framing` 的 target 就是主体），
    等于求解器不读自己的评分模型。这里给出"看哪"的偏移量：
    把对准点朝**视线方向**推 1/6 幅宽 ⇒ 主体落在**背向视线**的那条三分线上，
    朝向侧留白变成 2/3（>64.5%）、主体同时靠近 1/3 交点。

    ``direction`` 是"主体 → 机位"的单位方向（`camera_direction` 的返回值），
    ``facing`` 是被摄主体的世界朝向。主体正对镜头（`facing` 与视线平行）时
    偏移为 0——正对着镜头没有"视线留白"可言。
    """
    dx, dy = _normalise((direction[0], direction[1]), fallback=(0.0, 0.0))
    if (dx, dy) == (0.0, 0.0):
        return 0.0
    screen_right = right_of((-dx, -dy))          # 机位 → 主体 的右手边
    fx, fy = _normalise((facing[0], facing[1]), fallback=(0.0, 0.0))
    if (fx, fy) == (0.0, 0.0):
        return 0.0
    facing_screen = fx * screen_right[0] + fy * screen_right[1]
    if abs(facing_screen) < 1e-6:
        return 0.0
    return LEAD_ROOM_OFFSET if facing_screen > 0 else -LEAD_ROOM_OFFSET


def camera_direction(frame: SubjectFrame, side: str = "front", *,
                     axis_dir: Optional[Sequence[float]] = None,
                     axis_side: int = 0,
                     notes: Optional[list] = None) -> Tuple[float, float]:
    """解析 ``side``，返回**单位**机位方向。

    单人镜头沿用 §10.1 / §10.5 的语义（相对角色朝向，由
    :func:`side_vector` 提供）；两人及以上的镜头改相对**轴线法线**——
    相对焦点主体朝向会把机位放到轴线上（见模块 docstring）。

    ``axis_dir`` 是**整场**的轴线方向（由首镜确立，``Axis.direction``）。
    单人镜头落在轴线上时会按 :func:`_off_axis` 扭开一档：否则相机正好站在
    搭档的位置上，会把搭档拍进画面并挡住被摄主体。

    ``notes`` 是可选的可变列表：解算过程中**真的改了模型要的角度**时，往里面
    追加一条中文说明（目前只有"按已确立轴侧镜像"，见
    :func:`_honour_the_established_side`）。调用方把它并进取景警告，
    于是这段改动会进审计日志，而不是悄悄发生。
    """
    key = str(side or "front")
    if not frame.has_axis:
        base = side_vector(frame.facing, key)
        adjusted = _off_axis(base, axis_dir=axis_dir, axis_side=axis_side,
                             subject_facing=frame.facing)
        if adjusted is not None:
            return adjusted
        return _honour_the_established_side(base, frame.facing,
                                            axis_dir=axis_dir,
                                            axis_side=axis_side, notes=notes)

    axis = frame.axis_direction()
    if axis == (0.0, 0.0):
        # 两人位置重合：轴线退化，按单人处理而不是产生 NaN 方向。
        return side_vector(frame.facing, key)

    normal = right_of(axis)
    facing_xy = _normalise(frame.facing)
    #: **已确立的轴侧优先**（v1.5，2026-10-03 的真跑实测）：`axis_side` 此前
    #: 只在单人镜头的 `_off_axis` 分支被用到，两人镜头一律按"焦点主体朝向"挑
    #: 那一条法线——于是模型要的角度与已确立的轴侧打架时**必然越轴**，而
    #: R001 的判据恰恰就是 `Axis.established_side`（`axis_violation`）。
    #: 实测代价：64 镜真跑里 R001 从 0 涨到 **79** 次（机位不再被静默折成 front
    #: 之后，"摆错一侧"第一次真的发生），其中相当一部分是这里挑反了法线。
    #: 还没有轴线基准（`axis_side == 0`）时才退回"指向焦点主体正面"的旧口径。
    if axis_side:
        cross = axis[0] * normal[1] - axis[1] * normal[0]
        if (cross > 0) != (axis_side > 0):
            normal = (-normal[0], -normal[1])
    elif facing_xy[0] * normal[0] + facing_xy[1] * normal[1] < 0.0:
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
