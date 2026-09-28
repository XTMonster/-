"""检查点与回滚（执行文档 v1.2 §11.2）。

`Transaction` 管的是**单次操作**的失败回滚；检查点管的是**跨多步**的撤回：
越轴重排、全量重生成、人工审批被拒这类操作之前先拍一张快照，不满意就整体
回退到那一刻。

快照内容：所有 ``BD_`` 对象的变换、动画关键帧、时间轴标记与帧范围。
关键帧要跨越 4.x/5.x 两套 Action 结构，统一走 ``blender_compat.action_fcurves``。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import bpy
from bpy.types import Object

from ..utils.blender_compat import action_fcurves
from ..utils.logger import get_logger
from ..utils.threading_guard import main_thread_only

log = get_logger("checkpoint")

BD_PREFIX = "BD_"


@dataclass
class CurveRecord:
    data_path: str
    index: int
    keys: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class Checkpoint:
    name: str
    created_at: float = field(default_factory=time.time)
    transforms: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    curves: Dict[str, List[CurveRecord]] = field(default_factory=dict)
    markers: List[Dict[str, Any]] = field(default_factory=list)
    frame_start: int = 1
    frame_end: int = 1
    camera: str = ""

    @property
    def object_count(self) -> int:
        return len(self.transforms)

    @property
    def curve_count(self) -> int:
        return sum(len(items) for items in self.curves.values())

    def summary(self) -> Dict[str, Any]:
        return {"name": self.name, "objects": self.object_count,
                "curves": self.curve_count, "markers": len(self.markers),
                "frames": [self.frame_start, self.frame_end]}


def _bd_objects() -> List[Object]:
    return [obj for obj in bpy.data.objects if obj.name.startswith(BD_PREFIX)]


def _capture_curves(obj: Object) -> List[CurveRecord]:
    animation = obj.animation_data
    if animation is None:
        return []
    records: List[CurveRecord] = []
    for curve in action_fcurves(animation.action):
        records.append(CurveRecord(
            data_path=curve.data_path,
            index=int(curve.array_index),
            keys=[{"frame": float(point.co[0]), "value": float(point.co[1]),
                   "interpolation": str(point.interpolation)}
                  for point in curve.keyframe_points]))
    return records


@main_thread_only("CheckpointManager.capture")
def _capture(name: str) -> Checkpoint:
    scene = bpy.context.scene
    checkpoint = Checkpoint(name=name, frame_start=int(scene.frame_start),
                            frame_end=int(scene.frame_end),
                            camera=scene.camera.name if scene.camera else "")
    for obj in _bd_objects():
        checkpoint.transforms[obj.name] = {
            "location": list(obj.location),
            "rotation_euler": list(obj.rotation_euler),
            "scale": list(obj.scale),
            "hide_render": bool(obj.hide_render),
            "hide_viewport": bool(obj.hide_viewport),
            "parent": obj.parent.name if obj.parent else "",
        }
        curves = _capture_curves(obj)
        if curves:
            checkpoint.curves[obj.name] = curves
    checkpoint.markers = [
        {"name": marker.name, "frame": int(marker.frame),
         "camera": marker.camera.name if marker.camera else ""}
        for marker in scene.timeline_markers]
    return checkpoint


def _restore_curves(obj: Object, records: List[CurveRecord]) -> int:
    if obj.animation_data is not None:
        obj.animation_data_clear()
    restored = 0
    for record in records:
        for key in record.keys:
            obj.keyframe_insert(data_path=record.data_path, index=record.index,
                                frame=key["frame"])
        # 再按记录把插值写回去（keyframe_insert 只写值）
        for curve in action_fcurves(obj.animation_data.action
                                    if obj.animation_data else None):
            if curve.data_path != record.data_path:
                continue
            if int(curve.array_index) != record.index:
                continue
            for point, key in zip(curve.keyframe_points, record.keys):
                try:
                    point.interpolation = key["interpolation"]
                except (AttributeError, TypeError):
                    pass
            restored += len(record.keys)
    return restored


@main_thread_only("CheckpointManager.restore")
def _restore(checkpoint: Checkpoint) -> int:
    scene = bpy.context.scene
    touched = 0

    for name, state in checkpoint.transforms.items():
        obj = bpy.data.objects.get(name)
        if obj is None:
            continue
        obj.location = state["location"]
        obj.rotation_euler = state["rotation_euler"]
        obj.scale = state["scale"]
        obj.hide_render = state["hide_render"]
        obj.hide_viewport = state["hide_viewport"]
        touched += 1

        records = checkpoint.curves.get(name, [])
        if records:
            _restore_curves(obj, records)
        elif obj.animation_data is not None:
            obj.animation_data_clear()      # 快照时没有动画，现在有 → 清掉

    scene.frame_start = checkpoint.frame_start
    scene.frame_end = checkpoint.frame_end

    for marker in list(scene.timeline_markers):
        scene.timeline_markers.remove(marker)
    for record in checkpoint.markers:
        marker = scene.timeline_markers.new(record["name"],
                                            frame=int(record["frame"]))
        camera = bpy.data.objects.get(record["camera"]) if record["camera"] else None
        if camera is not None:
            marker.camera = camera

    if checkpoint.camera:
        camera = bpy.data.objects.get(checkpoint.camera)
        if camera is not None:
            scene.camera = camera
    bpy.context.view_layer.update()
    return touched


class CheckpointManager:
    """命名检查点的内存栈（按需拍、按需回）。"""

    def __init__(self, limit: int = 8) -> None:
        self.limit = limit
        self._checkpoints: List[Checkpoint] = []

    def capture(self, name: str) -> Checkpoint:
        checkpoint = _capture(name)
        self._checkpoints.append(checkpoint)
        while len(self._checkpoints) > self.limit:
            self._checkpoints.pop(0)
        log.info("已拍检查点 %s：%s", name, checkpoint.summary())
        return checkpoint

    def restore(self, name: str) -> int:
        checkpoint = self.get(name)
        if checkpoint is None:
            raise KeyError(f"没有名为 {name} 的检查点")
        touched = _restore(checkpoint)
        log.info("已回滚到检查点 %s（%d 个对象）", name, touched)
        return touched

    def get(self, name: str) -> Optional[Checkpoint]:
        for checkpoint in reversed(self._checkpoints):
            if checkpoint.name == name:
                return checkpoint
        return None

    def latest(self) -> Optional[Checkpoint]:
        return self._checkpoints[-1] if self._checkpoints else None

    def names(self) -> List[str]:
        return [checkpoint.name for checkpoint in self._checkpoints]

    def drop(self, name: str) -> bool:
        before = len(self._checkpoints)
        self._checkpoints = [c for c in self._checkpoints if c.name != name]
        return len(self._checkpoints) != before
