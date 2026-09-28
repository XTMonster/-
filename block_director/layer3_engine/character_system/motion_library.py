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


@main_thread_only("clear_animation")
def clear_animation(character) -> int:
    """清掉角色各部件上的动画数据（重复烘焙前先归零，避免叠加）。"""
    removed = 0
    for obj in character.all_objects():
        if obj.animation_data is not None:
            obj.animation_data_clear()
            removed += 1
        # 复位旋转/缩放到中立姿态；root 的**位置**保留（那是角色的摆位）
        obj.rotation_euler = (0.0, 0.0, 0.0)
        obj.scale = (1.0, 1.0, 1.0)
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
                  interpolation: str = "BEZIER") -> BakeResult:
    """校验冲突 → 合成姿态 → 烘焙关键帧。冲突会抛 ValueError。"""
    problems = check_conflicts(requests)
    if problems:
        raise ValueError("动作冲突：\n" + "\n".join(problems))
    if clear:
        clear_animation(character)
    trace = compose(requests)
    result = bake_trace(character, trace)
    set_interpolation(character, interpolation)
    log.info("动作烘焙完成：%d 帧 / %d 个关键帧（%d-%d）",
             result.frames, result.keyframes,
             result.start_frame, result.end_frame)
    return result
