"""细排节拍落场（bpy 侧）。"""
from __future__ import annotations

from typing import Any, List, Mapping

import bpy


def apply_detail_beats(detail_shots: List[Mapping[str, Any]],
                       manifest: Mapping[str, Any]) -> None:
    """把 DetailShotContract 节拍写入 Blender 时间轴标记。"""
    for shot in detail_shots:
        shot_id = str(shot.get("shot_id") or "")
        marker = f"BD_DetailBeat_{shot_id}"
        for beat in shot.get("beats") or []:
            frame = int(beat.get("frame") or 1)
            if bpy.context.scene.timeline_markers.get(marker) is None:
                bpy.context.scene.timeline_markers.new(marker, frame=frame)


__all__ = ["apply_detail_beats"]
