"""动作库的落地实现：把合成好的姿态轨迹写成关键帧（执行文档 v1.2 §9.6）。

纯计算部分在 ``block_director/motion/model.py``；本模块只负责
"通道 → 具体对象属性"的映射与 keyframe 写入。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import bpy
from bpy.types import Object

from ...motion.model import (
    CH_BODY_ROT_X,
    CH_BODY_ROT_Y,
    CH_HEAD_ROT_X,
    CH_HEAD_ROT_Z,
    CH_LEG_L,
    CH_LEG_R,
    CH_ROOT_LOC,
    CH_ROOT_ROT_Z,
    ActionRequest,
    check_conflicts,
    compose,
)
from ...utils.logger import get_logger
from ...utils.threading_guard import main_thread_only
from ...utils.blender_compat import set_keyframe_interpolation

log = get_logger("motion")

# 通道 → (取对象的函数, 属性名, 分量索引或 None 表示整体)
ChannelTarget = Tuple[Callable[[object], Optional[Object]], str, Optional[int]]

CHANNEL_TARGETS: Dict[str, ChannelTarget] = {
    CH_ROOT_LOC: (lambda c: c.root, "location", None),
    CH_ROOT_ROT_Z: (lambda c: c.root, "rotation_euler", 2),
    CH_BODY_ROT_X: (lambda c: c.body_pivot, "rotation_euler", 0),
    CH_BODY_ROT_Y: (lambda c: c.body_pivot, "rotation_euler", 1),
    CH_HEAD_ROT_X: (lambda c: c.head_pivot, "rotation_euler", 0),
    CH_HEAD_ROT_Z: (lambda c: c.head_pivot, "rotation_euler", 2),
    CH_LEG_L: (lambda c: c.leg_pivots[0] if c.leg_pivots else None, "rotation_euler", 0),
    CH_LEG_R: (lambda c: c.leg_pivots[1] if len(c.leg_pivots) > 1 else None,
               "rotation_euler", 0),
}


@dataclass
class BakeResult:
    frames: int = 0
    keyframes: int = 0
    channels: List[str] = field(default_factory=list)
    start_frame: int = 0
    end_frame: int = 0
    #: v1.4 US-17：本次烘焙里被**自动错开**的同层动作（写进 shots.json）。
    action_conflicts: List[Dict[str, object]] = field(default_factory=list)


@main_thread_only("clear_animation")
def clear_animation(character, base_pose: Optional[Dict[str, object]] = None
                    ) -> int:
    """清掉角色各部件上的动画数据，并复位到**基准姿态**。

    v1.3 修正：v1.2 把 root 的 ``rotation_euler`` 也一并清零，于是
    "创建时设定的身体朝向"在角色第一次烘焙动作时就被抹掉——两人相对而立
    会一起弹回面朝 +Y。root 的朝向是**角色的摆位**，不是动画残留。

    ``base_pose`` 给出时按它复位（那是角色此刻真实的摆位与朝向）；
    不给时才退回旧行为（位置保留、其余归零）。
    """
    removed = 0
    for obj in character.all_objects():
        if obj.animation_data is not None:
            obj.animation_data_clear()
            removed += 1
        obj.scale = (1.0, 1.0, 1.0)

    base = dict(base_pose) if base_pose is not None else None

    def channel(channel_id: str, fallback: float) -> float:
        if base is None:
            return fallback
        return float(base.get(channel_id, fallback))

    if character.root is not None:
        if base is not None and CH_ROOT_LOC in base:
            character.root.location = tuple(base[CH_ROOT_LOC])
        # root 的位置保留（那是角色的摆位）；旋转按基准还原。
        character.root.rotation_euler = (0.0, 0.0,
                                         channel(CH_ROOT_ROT_Z, 0.0))
    if character.body_pivot is not None:
        character.body_pivot.rotation_euler = (
            channel(CH_BODY_ROT_X, 0.0), channel(CH_BODY_ROT_Y, 0.0), 0.0)
    if character.head_pivot is not None:
        character.head_pivot.rotation_euler = (
            channel(CH_HEAD_ROT_X, 0.0), 0.0, channel(CH_HEAD_ROT_Z, 0.0))
    if len(character.leg_pivots) >= 2:
        character.leg_pivots[0].rotation_euler = (
            channel(CH_LEG_L, 0.0), 0.0, 0.0)
        character.leg_pivots[1].rotation_euler = (
            channel(CH_LEG_R, 0.0), 0.0, 0.0)
    return removed


@main_thread_only("bake_trace")
def bake_trace(character, trace: Dict[int, Dict[str, object]]) -> BakeResult:
    """把逐帧姿态写成关键帧。"""
    if not trace:
        return BakeResult()

    used_channels = sorted({ch for pose in trace.values() for ch in pose})
    frames = sorted(trace)
    inserted = 0

    for frame in frames:
        pose = trace[frame]
        touched: Dict[str, set] = {}
        for channel, value in pose.items():
            target = CHANNEL_TARGETS.get(channel)
            if target is None:
                log.warning("未知通道 %s，已跳过", channel)
                continue
            getter, attribute, index = target
            obj = getter(character)
            if obj is None:
                continue
            if index is None:
                setattr(obj, attribute, tuple(value))       # type: ignore[arg-type]
                touched.setdefault(obj.name, set()).add(attribute)
            else:
                current = list(getattr(obj, attribute))
                current[index] = float(value)               # type: ignore[arg-type]
                setattr(obj, attribute, current)
                touched.setdefault(obj.name, set()).add(f"{attribute}:{index}")

        for object_name, attributes in touched.items():
            obj = bpy.data.objects.get(object_name)
            if obj is None:
                continue
            for key in attributes:
                if ":" in key:
                    attribute, index_text = key.split(":")
                    obj.keyframe_insert(data_path=attribute,
                                        index=int(index_text), frame=frame)
                else:
                    obj.keyframe_insert(data_path=key, frame=frame)
                inserted += 1

    return BakeResult(frames=len(frames), keyframes=inserted,
                      channels=used_channels,
                      start_frame=frames[0], end_frame=frames[-1])


@main_thread_only("set_interpolation")
def set_interpolation(character, interpolation: str = "BEZIER") -> int:
    """统一关键帧插值（§9.7：BEZIER + 缓入缓出）。"""
    changed = 0
    for obj in character.all_objects():
        animation = obj.animation_data
        if animation is None or animation.action is None:
            continue
        changed += set_keyframe_interpolation(animation.action, interpolation)
    return changed


@main_thread_only("apply_motions")
def apply_motions(character, requests: List[ActionRequest], *,
                  clear: bool = True,
                  interpolation: str = "BEZIER",
                  base_pose: Optional[Dict[str, object]] = None,
                  stagger: bool = True) -> BakeResult:
    """校验冲突 → 合成姿态 → 烘焙关键帧。冲突会抛 ValueError。

    v1.4 US-17：先走一次**确定性错开**（同层重叠自动后移，见
    ``motion.model.stagger_conflicts``）。语义禁忌（§9.7 的
    ``FORBIDDEN_PAIRS``）不参与错开，仍然抛错——那是"换动作"的事，
    不是"挪几帧"的事。错开留痕写进 :class:`BakeResult`。
    """
    if stagger:
        from ...motion.model import stagger_conflicts

        requests, events = stagger_conflicts(requests)
    else:
        events = []
    problems = check_conflicts(requests)
    if problems:
        raise ValueError("动作冲突：\n" + "\n".join(problems))
    if base_pose is None:
        # 必须在清除**之前**读基姿态：clear_animation 会把各部件复位，
        # 读得晚会拿到"中立姿态"，角色的摆位与朝向就丢了（v1.2 的缺陷）。
        base_pose = character_base_pose(character)
    if clear:
        clear_animation(character, base_pose)
    trace = compose(requests, base_pose=base_pose)
    result = bake_trace(character, trace)
    set_interpolation(character, interpolation)
    log.info("动作烘焙完成：%d 帧 / %d 个关键帧（%d-%d）",
             result.frames, result.keyframes,
             result.start_frame, result.end_frame)
    result.action_conflicts = list(events)
    return result


@main_thread_only("character_base_pose")
def character_base_pose(character) -> Dict[str, object]:
    """读取角色当前姿态，作为动作合成的初始基线。

    没有它，"坐下""跳跃""摔倒"这类只改高度的动作会把角色的 X/Y 摆位清零。
    """
    pose: Dict[str, object] = {}
    if character.root is not None:
        pose[CH_ROOT_LOC] = tuple(character.root.location)
        pose[CH_ROOT_ROT_Z] = float(character.root.rotation_euler[2])
    if character.body_pivot is not None:
        pose[CH_BODY_ROT_X] = float(character.body_pivot.rotation_euler[0])
        pose[CH_BODY_ROT_Y] = float(character.body_pivot.rotation_euler[1])
    if character.head_pivot is not None:
        pose[CH_HEAD_ROT_X] = float(character.head_pivot.rotation_euler[0])
        pose[CH_HEAD_ROT_Z] = float(character.head_pivot.rotation_euler[2])
    if len(character.leg_pivots) >= 2:
        pose[CH_LEG_L] = float(character.leg_pivots[0].rotation_euler[0])
        pose[CH_LEG_R] = float(character.leg_pivots[1].rotation_euler[0])
    return pose
