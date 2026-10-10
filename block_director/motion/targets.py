"""结构化 look/hand 目标（卡 G8-C）的单一真源。**纯计算，不 import bpy。**

背景（v10–v13 真跑，``work/_g2_ds_run/blender_v1*.log``）：模型反复把
``look_at.to`` / ``look_at.toward`` / ``look_at.target_position`` 写成角色名、
把拍点 ``target`` 写成场外角色或坐标字符串 ``'[2,0,0]'``、把 ``hand_to.to``
写成角色名。用户裁决（2026-10-09）：把这些**结构化目标**提成一等公民——
屏幕相对词（``screen_left`` / ``screen_right`` / ``front`` / ``画面中心`` /
``left_third`` / ``左侧三分位``）照旧拒绝。

一个目标是以下三种形状之一：

* 全剧组内的角色 id 字符串：``"伊恩"``；
* ``{"character": id}``；
* ``{"point": [x, y, z]}``——**恰好 3 个数字**，与 ``target_position`` 同一帧/
  单位（世界米；``z`` 是离地高度，地面 = 0）。

几何口径（与 ``model.head_track_angles`` 逐字节同源）：角色面朝局部 +Y、
世界朝向 ``(-sin θ, cos θ)``；头部 yaw 正 = 向左、俯仰正 = 向上，均被钳位到
头部活动范围（±90° / ±30°）。眼睛高度从 ``cinema/anchor.py`` 的冻结 profile
派生，**不另写常量**。
"""

from __future__ import annotations

import math
from typing import Mapping, Optional, Sequence, Tuple

from ..cinema.anchor import DEFAULT_PROFILE
from ..utils.geometry import facing_to_rotation_z


class TargetError(ValueError):
    """目标无法解析（名字、形状或位置缺失）。**绝不静默取默认值。**"""


def target_kind(target) -> Optional[str]:
    """目标形状判别：``'character'`` / ``'point'`` / ``None``（不是合法形状）。

    这是目标形状的**单一真源**：校验器与编译层都问它，不各抄一份形状判断。
    """
    if isinstance(target, str):
        return "character" if target.strip() else None
    if isinstance(target, dict):
        if set(target) == {"character"}:
            value = target["character"]
            return "character" if isinstance(value, str) and value.strip() \
                else None
        if set(target) == {"point"}:
            value = target["point"]
            if isinstance(value, (list, tuple)) and len(value) == 3:
                try:
                    for item in value:
                        float(item)
                except (TypeError, ValueError):
                    return None
                return "point"
        return None
    return None


def looks_like_coordinate_string(text: str) -> bool:
    """字符串是否**看起来像坐标**（如 ``'[2,0,0]'`` / ``'1.15,0'``）。

    这类写法必须被拒绝并提示改用 ``{"point": [x, y, z]}``——字符串不是坐标，
    而角色 id 不含逗号数字串。
    """
    if not isinstance(text, str):
        return False
    body = text.strip()
    if len(body) >= 2 and body[0] in "[(" and body[-1] in "])":
        body = body[1:-1].strip()
    if "," not in body:
        return False
    parts = [part.strip() for part in body.split(",")]
    if len(parts) < 2:
        return False
    try:
        for part in parts:
            float(part)
    except (TypeError, ValueError):
        return False
    return True


def _as_position(position) -> Tuple[float, float, float]:
    """位置表里的条目 → ``(x, y, z)``；读不出来抛 :class:`TargetError`。"""
    try:
        values = [float(item) for item in position]
    except (TypeError, ValueError) as exc:
        raise TargetError(f"位置不是坐标：{position!r}") from exc
    if len(values) < 2:
        raise TargetError(f"位置不是坐标（少于 2 个分量）：{position!r}")
    while len(values) < 3:
        values.append(0.0)
    return (values[0], values[1], values[2])


def resolve_target(target,
                   cast_positions: Mapping[str, Sequence[float]]
                   ) -> Tuple[float, float, float]:
    """把目标解析成场景位置 ``(x, y, z)``；解析不出就抛 :class:`TargetError`。

    角色目标返回它在 ``cast_positions`` 里的**存储位置**（地面位，``z=0``）；
    ``{"point": ...}`` 原样返回。字符目标是否抬到眼高由消费方决定
    （``layer5_orchestrator/beat_compiler.resolve_action_targets``）。
    """
    kind = target_kind(target)
    if kind == "character":
        if isinstance(target, str):
            character_id = target.strip()
        else:
            character_id = str(target["character"]).strip()
        position = cast_positions.get(character_id)
        if position is None:
            raise TargetError(
                f"目标角色 {character_id!r} 不在场景位置表里（target={target!r}），"
                f"不允许默认为原点")
        try:
            return _as_position(position)
        except TargetError as exc:
            raise TargetError(
                f"目标角色 {character_id!r} 的位置非法（target={target!r}）：{exc}"
            ) from exc
    if kind == "point":
        return _as_position(target["point"])
    raise TargetError(
        f"无法理解的目标 {target!r}：合法形状是角色 id 字符串、"
        f"{{'character': id}} 或 {{'point': [x, y, z]}}")


def facing_degrees(facing: Sequence[float]) -> float:
    """面朝向量 → 绝对朝向角（度）。0 = 面朝 +Y，与
    ``utils.geometry.facing_to_rotation_z`` / ``head_track_angles`` 同源。"""
    return math.degrees(facing_to_rotation_z(facing))


def yaw_pitch_to(from_pos: Sequence[float], facing_deg: float,
                 target_pos: Sequence[float],
                 eye_height: float = DEFAULT_PROFILE.eye_z
                 ) -> Tuple[float, float]:
    """目标相对身体朝向的头部偏角 ``(yaw_deg, pitch_deg)``。

    **逐字节复用 ``model.head_track_angles`` 的约定**（0 方向、符号、钳位）：
    头部 yaw 正 = 向左、俯仰正 = 向上；超出 ±90° / ±30° 照旧钳位。眼睛高度
    参数化（缺省值派生自 ``cinema/anchor.py`` 的冻结 profile），供
    ``head_track_angles`` 使用，不另写常量。
    """
    from .model import head_track_angles

    theta = math.radians(float(facing_deg))
    facing = (-math.sin(theta), math.cos(theta))
    yaw, pitch, _note = head_track_angles(from_pos, facing, target_pos,
                                          eye_height=float(eye_height))
    return float(yaw), float(pitch)


__all__ = [
    "TargetError",
    "target_kind",
    "looks_like_coordinate_string",
    "resolve_target",
    "facing_degrees",
    "yaw_pitch_to",
]
