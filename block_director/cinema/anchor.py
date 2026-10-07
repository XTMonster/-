"""角色竖直锚点（v1.4 §2.1 的冻结几何）。**纯计算，不依赖 bpy。**

**为什么单独成一个模块**：``layer3_engine/__init__.py`` 顶层就 ``import
bpy``（它把 ``shot_builder`` 拉进来），所以任何 anchor 只要放进
``layer3_engine/`` 就会把纯层的 ``cinema/*`` 与 ``tests/test_framing.py``
一起拖进 bpy。方向必须是 **layer3_engine → cinema.anchor 单向**。

冻结几何（§2.1，比例即真源）::

    total_height = 1.70
    head_ratio   = 0.37  → head_d = 0.629  → head_r = 0.3145
    torso_ratio  = 0.44  → torso_h = 0.748
    leg_ratio    = 0.19  → leg_h   = 0.323

    头球与躯干顶**相切**：head_center_z = leg_h + torso_h + head_r

v1.3 的 ``head_center_z = 1.10`` 正好等于躯干顶（0.40 + 0.70），于是头球的
下半埋进躯干——渲染出来"看不到整个球"（BW-5）。本模块用"相切"这条硬约束
把五个消费者（角色工厂 / 取景 / 构图 / 校验器 / 知识卡）收敛到同一份推导。

眼睛（§2.1）：``d = head_r - eye_r + p``，``y = sqrt(d² - eye_dx²)``；
旧式 ``sqrt((head_r-eye_r)² - eye_dx²)`` 让眼球与头球内切、突出量恒为 0，
Workbench 下根本渲染不出眼睛（BW-5 的眼睛部分）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Tuple

#: 默认几何（与 ``contracts/config.py`` 的 ``character`` 段逐字段一致）。
DEFAULT_TOTAL_HEIGHT = 1.70
DEFAULT_HEAD_RATIO = 0.37
DEFAULT_TORSO_RATIO = 0.44
DEFAULT_LEG_RATIO = 0.19
DEFAULT_EYE_R = 0.035
DEFAULT_EYE_DX = 0.11
DEFAULT_EYE_PROTRUSION = 0.015
DEFAULT_NECK_GAP = 0.0

#: 躯干内部的高度比例（沿用 v1.3 的相对位置：胸口 0.55/0.70、腰 0.30/0.70）
CHEST_RATIO_OF_TORSO = 0.55 / 0.70
WAIST_RATIO_OF_TORSO = 0.30 / 0.70
#: 膝盖在腿高的中点（v1.3 也是 0.20/0.40）
KNEE_RATIO_OF_LEG = 0.5
#: 标签锚点在头顶之上留多少（v1.3：1.75 - 1.45 = 0.30）
LABEL_MARGIN = 0.30

#: 脖子间隙的验收容差（RK-14 的输入侧：``neck_gap = 0 ± 0.005``）
NECK_GAP_TOLERANCE = 0.005

#: v1.5 §4.4：**手部代理**的局部偏移（相对躯干轴心 BodyPivot 的 ``(x, y, z)``）。
#: 道具交互（``place_prop``/``pick_up``/``hand_to``）需要一个跟随目标，而 Q 版
#: 白模角色没有手臂网格。这里不去加几何（会动到冻结几何与角色部件计数），
#: 只给一个**空对象**的落点：躯干半径之外一点点、胸口高度。
#:   * 前向 ``0.25`` 略大于躯干半径（``BODY_RADIUS = 0.25``），即"手在身前"；
#:   * 侧向 ``0.22`` = 躯干半径 − 一点，读起来像"身侧的手"；
#:   * 高度取 ``chest_z``（由冻结比例派生，不另写数字）。
#: 这三个量是**设计选择**、不是冻结几何：改它们不动头顶/头球/眼睛任何一条。
HAND_PROXY_FORWARD = 0.25
HAND_PROXY_SIDE = 0.22


@dataclass(frozen=True)
class CharacterProfile:
    """角色几何 profile：由比例推导出**全部**竖直锚点。"""

    total_height: float = DEFAULT_TOTAL_HEIGHT
    head_ratio: float = DEFAULT_HEAD_RATIO
    torso_ratio: float = DEFAULT_TORSO_RATIO
    leg_ratio: float = DEFAULT_LEG_RATIO
    eye_r: float = DEFAULT_EYE_R
    eye_dx: float = DEFAULT_EYE_DX
    eye_protrusion: float = DEFAULT_EYE_PROTRUSION
    neck_gap: float = DEFAULT_NECK_GAP

    # ---------------------------------------------------------------- 尺寸
    @property
    def head_d(self) -> float:
        return float(self.head_ratio) * float(self.total_height)

    @property
    def head_r(self) -> float:
        return self.head_d / 2.0

    @property
    def torso_h(self) -> float:
        return float(self.torso_ratio) * float(self.total_height)

    @property
    def leg_h(self) -> float:
        return float(self.leg_ratio) * float(self.total_height)

    # ---------------------------------------------------------------- 锚点
    @property
    def ground_z(self) -> float:
        return 0.0

    @property
    def hip_z(self) -> float:
        return self.leg_h

    @property
    def torso_center_z(self) -> float:
        return self.leg_h + self.torso_h / 2.0

    @property
    def torso_top_z(self) -> float:
        return self.leg_h + self.torso_h

    @property
    def head_center_z(self) -> float:
        """头球中心：与躯干顶**相切**（``neck_gap`` 是刻意的容差）。"""
        return self.torso_top_z + self.head_r + float(self.neck_gap)

    @property
    def head_top_z(self) -> float:
        return self.head_center_z + self.head_r

    @property
    def eye_z(self) -> float:
        """眼睛中心高度（头球中心；眼睛挂在头球赤道上）。"""
        return self.head_center_z

    @property
    def chest_z(self) -> float:
        return self.hip_z + CHEST_RATIO_OF_TORSO * self.torso_h

    @property
    def waist_z(self) -> float:
        return self.hip_z + WAIST_RATIO_OF_TORSO * self.torso_h

    @property
    def knee_z(self) -> float:
        return KNEE_RATIO_OF_LEG * self.leg_h

    @property
    def label_anchor_z(self) -> float:
        return self.head_top_z + LABEL_MARGIN

    # ---------------------------------------------------------------- 眼睛
    def eye_offset(self) -> Tuple[float, float]:
        """返回 ``(eye_dx, y)``：眼心在头球局部坐标里的水平偏移与前向距离。

        ``y = sqrt(d² - eye_dx²)``，``d = head_r - eye_r + p``。
        若 ``d <= eye_dx``（几何自相矛盾）则抛 ``ValueError``——宁可失败，
        也不静默把眼睛塞回头球里。
        """
        d = self.head_r - float(self.eye_r) + float(self.eye_protrusion)
        dx = float(self.eye_dx)
        if d <= dx:
            raise ValueError(
                f"眼球几何自相矛盾：d={d:.4f} <= eye_dx={dx:.4f}；"
                f"请调大 eye_protrusion 或调小 eye_dx")
        return dx, math.sqrt(d * d - dx * dx)

    def neck_gap_error(self) -> float:
        """``head_center_z`` 与"相切"理想值的偏差（RK-14 的输入侧判据）。"""
        ideal = self.leg_h + self.torso_h + self.head_r
        return self.head_center_z - ideal

    # ---------------------------------------------------------------- 序列化
    def to_dict(self) -> dict:
        return {
            "total_height": self.total_height,
            "head_ratio": self.head_ratio,
            "torso_ratio": self.torso_ratio,
            "leg_ratio": self.leg_ratio,
            "eye_r": self.eye_r,
            "eye_dx": self.eye_dx,
            "eye_protrusion": self.eye_protrusion,
            "neck_gap": self.neck_gap,
            "head_r": round(self.head_r, 6),
            "torso_h": round(self.torso_h, 6),
            "leg_h": round(self.leg_h, 6),
            "hip_z": round(self.hip_z, 6),
            "torso_center_z": round(self.torso_center_z, 6),
            "head_center_z": round(self.head_center_z, 6),
            "head_top_z": round(self.head_top_z, 6),
            "eye_z": round(self.eye_z, 6),
            "chest_z": round(self.chest_z, 6),
            "waist_z": round(self.waist_z, 6),
            "knee_z": round(self.knee_z, 6),
            "label_anchor_z": round(self.label_anchor_z, 6),
        }


#: 默认 profile（唯一实例；``profile_for()`` 从配置派生时另建）。
DEFAULT_PROFILE = CharacterProfile()


def hand_offset(profile: CharacterProfile = DEFAULT_PROFILE,
                side: float = 1.0) -> Tuple[float, float, float]:
    """手部代理在**躯干轴心局部坐标**里的落点 ``(x, y, z)``。

    ``side = -1`` 是角色的左手侧、``+1`` 是右手侧。坐标是**躯干轴心局部**的，
    所以它跟着角色的朝向与上身旋转走（BodyPivot 是身体旋转的父级）。
    """
    return (float(side) * HAND_PROXY_SIDE, HAND_PROXY_FORWARD,
            profile.chest_z - profile.hip_z)


def profile_from(config=None) -> CharacterProfile:
    """从 ``AppConfig.character`` 派生 profile；拿不到配置时用默认值。"""
    section = getattr(config, "character", None) if config is not None else None
    if section is None:
        return DEFAULT_PROFILE
    return CharacterProfile(
        total_height=float(getattr(section, "total_height",
                                   DEFAULT_TOTAL_HEIGHT)),
        head_ratio=float(getattr(section, "head_ratio", DEFAULT_HEAD_RATIO)),
        torso_ratio=float(getattr(section, "torso_ratio", DEFAULT_TORSO_RATIO)),
        leg_ratio=float(getattr(section, "leg_ratio", DEFAULT_LEG_RATIO)),
        eye_r=float(getattr(section, "eye_r", DEFAULT_EYE_R)),
        eye_dx=float(getattr(section, "eye_dx", DEFAULT_EYE_DX)),
        eye_protrusion=float(getattr(section, "eye_protrusion",
                                     DEFAULT_EYE_PROTRUSION)),
        neck_gap=float(getattr(section, "neck_gap", DEFAULT_NECK_GAP)),
    )


def resolved_profile(config=None) -> CharacterProfile:
    """``profile_from`` 的别名，供"这里要的是解析后的值"的调用点自述。"""
    return profile_from(config)
