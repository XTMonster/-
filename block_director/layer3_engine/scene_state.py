"""场景状态采集（执行文档 v1.2 §7.3）——LLM 的眼睛的 bpy 实现。

轻量模式只读位置/朝向；``detailed=True`` 才做屏幕投影（§17.4）。
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

from ..observation.state import (
    CameraState,
    CharacterState,
    SceneState,
)
from ..utils.logger import get_logger
from ..utils.threading_guard import main_thread_only
from .character_system import get_facing
from .scene_context import SceneContext, get_context

log = get_logger("scene-state")


def _screen_bounds(character, scene, camera) -> Optional[Tuple[float, float]]:
    """角色的头部顶与脚底在画面里的归一化 y 范围。"""
    bounds = []
    for obj in getattr(character, "meshes", []):
        bounds.extend(obj.bound_box)
    if not bounds:
        return None
    zs: List[float] = []
    root = character.root
    for obj in getattr(character, "meshes", []):
        for corner in obj.bound_box:
            world = obj.matrix_world @ Vector(corner)
            projected = world_to_camera_view(scene, camera, world)
            zs.append(projected.y)
    if not zs:
        return None
    return (min(zs), max(zs))


def _project_character(character, scene, camera) -> Tuple[bool, Tuple[float, float], float]:
    """返回 (是否在画, 屏幕坐标, 高度占比)。"""
    origin = character.root.matrix_world.translation
    center = world_to_camera_view(scene, camera, origin + Vector((0.0, 0.0, 0.9)))
    span = _screen_bounds(character, scene, camera)
    height_fraction = round(span[1] - span[0], 3) if span else 0.0
    in_frame = -0.05 <= center.x <= 1.05 and -0.05 <= center.y <= 1.05
    return in_frame, (round(center.x, 3), round(center.y, 3)), height_fraction


@main_thread_only("collect_scene_state")
def collect_scene_state(*, detailed: bool = False, context: Optional[SceneContext] = None,
                        frame: Optional[int] = None,
                        notes: Sequence[str] = ()) -> SceneState:
    """采集当前场景状态。``detailed=True`` 才做屏幕投影。"""
    scene = bpy.context.scene
    context = context or get_context()
    current_frame = int(frame if frame is not None else scene.frame_current)
    state = SceneState(frame=current_frame, total_frames=int(scene.frame_end),
                       detailed=detailed, notes=list(notes))

    camera = scene.camera
    if context is not None:
        state.current_shot_id = context.current_shot_id
        if camera is not None:
            state.current_camera_id = camera.name
        state.notes.extend(context.notes)
    elif camera is not None:
        state.current_camera_id = camera.name

    bpy.context.view_layer.update()

    if camera is not None:
        camera_state = CameraState(
            id=camera.name,
            shot_id=state.current_shot_id,
            shot_type=(context.shot_types.get(state.current_shot_id, "")
                       if context else ""),
            position=tuple(camera.matrix_world.translation),
            target=tuple(camera.matrix_world @ Vector((0.0, 0.0, -1.0))),
            lens=float(camera.data.lens),
        )
        state.camera = camera_state

    characters = context.character_list if context else []
    for character in characters:
        root = getattr(character, "root", None)
        if root is None:
            continue
        position = tuple(root.matrix_world.translation)
        entry = CharacterState(id=character.id, name=character.name,
                               position=position, facing=get_facing(character))
        if detailed and camera is not None:
            in_frame, screen, height_fraction = _project_character(
                character, scene, camera)
            entry.in_frame = in_frame
            entry.screen_position = screen
            entry.height_fraction = height_fraction
            if state.camera is not None and in_frame:
                state.camera.visible_characters.append(character.id)
        state.characters.append(entry)

    return state
