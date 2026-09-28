"""从计划 + 构建结果组装 SDL（执行文档 v1.2 §5）。

SDL 是"这个项目长什么样"的完整描述；组装好之后既能落盘（§14），也能反向
还原成构建器的入参（:func:`sdl_to_plan` / :func:`sdl_to_spec`），
于是"保存 → 重新加载 → 重建场景"成为一条闭合回路。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..contracts.cast import CastMember, SceneSpec
from ..contracts.plan import Plan, ShotPlan
from ..contracts.sdl import (
    SDL_VERSION,
    SDLCamera,
    SDLEnvironment,
    SDLProject,
    SDLScene,
    SDLShot,
)


def _environment(spec: SceneSpec) -> SDLEnvironment:
    return SDLEnvironment(
        ground_size=[float(spec.ground_size[0]), float(spec.ground_size[1])],
        walls=[dict(wall) for wall in spec.walls],
        props=[dict(prop) for prop in spec.props],
        lighting=spec.lighting,
        room=list(spec.room) if spec.room else None,
    )


def build_sdl(plan: Plan, *,
              build_summary: Optional[Dict[str, Any]] = None,
              spec: Optional[SceneSpec] = None,
              project_name: str = "BlockDirector",
              fps: int = 24,
              scene_id: str = "scene_001") -> SDLProject:
    """把分镜计划与构建结果组装成一份 SDL。"""
    spec = spec or SceneSpec.from_plan(plan)
    results = {item.get("shot_id"): item
               for item in (build_summary or {}).get("results", [])}

    shots: List[SDLShot] = []
    for order, planned in enumerate(plan.shots, start=1):
        result = results.get(planned.shot_id, {})
        start = int(result.get("start_frame") or 0)
        end = int(result.get("end_frame") or 0)
        duration = planned.duration_frames or (end - start + 1 if end else 1)
        if not start:
            start = 1 if order == 1 else 0
        if not end and start:
            end = start + duration - 1
        position = result.get("camera_position") or [0.0, 0.0, 0.0]
        target = result.get("camera_target") or [0.0, 0.0, 1.0]
        shots.append(SDLShot(
            id=planned.shot_id,
            intent=planned.intent,
            shot_type=str(planned.shot_type),
            duration_frames=max(int(duration), 1),
            start_frame=start,
            end_frame=end,
            camera=SDLCamera(id=result.get("camera", f"BD_Cam_{planned.shot_id}"),
                             position=list(position), target=list(target),
                             lens=float(result.get("lens") or 50.0),
                             movement="static", request={}),
            axis_line=None,
            active_speakers=list(planned.characters),
            characters=list(planned.characters),
            actions=[dict(action) for action in planned.actions],
            dialogues=[dict(item) for item in planned.dialogues],
            prompt=planned.prompt,
        ))

    scene = SDLScene(id=scene_id, number=1, heading=plan.scene_heading,
                     environment=_environment(spec), shots=shots)
    continuity: Dict[str, Any] = {
        "axis_note": list(plan.continuity_notes),
        "character_pose": {member.id: {"position": list(member.initial_location),
                                       "facing": list(member.initial_facing)}
                           for member in spec.cast},
    }
    return SDLProject(name=project_name, version=SDL_VERSION, fps=fps,
                      characters=list(spec.cast), scenes=[scene],
                      continuity=continuity,
                      warnings=list((build_summary or {}).get("warnings", [])))


def sdl_to_plan(sdl: SDLProject) -> Plan:
    """从 SDL 还原出构建器需要的 :class:`Plan`。"""
    shots: List[ShotPlan] = []
    order = 0
    for scene in sdl.scenes:
        for shot in scene.shots:
            order += 1
            shots.append(ShotPlan.from_dict({
                "shot_id": shot.id,
                "order": order,
                "intent": shot.intent,
                "shot_type": shot.shot_type,
                "duration_frames": max(shot.duration_frames, 1),
                "characters": list(shot.characters),
                "actions": [dict(a) for a in shot.actions],
                "dialogues": [dict(d) for d in shot.dialogues],
                "prompt": shot.prompt,
            }))
    heading = sdl.scenes[0].heading if sdl.scenes else ""
    return Plan(shots=shots, scene_heading=heading,
                continuity_notes=list(sdl.continuity.get("axis_note", [])))


def sdl_to_spec(sdl: SDLProject) -> SceneSpec:
    """从 SDL 还原出构建器需要的 :class:`SceneSpec`。"""
    if not sdl.scenes:
        return SceneSpec(cast=list(sdl.characters))
    environment = sdl.scenes[0].environment
    ground = environment.ground_size or [120.0, 120.0]
    return SceneSpec(
        heading=sdl.scenes[0].heading,
        cast=list(sdl.characters),
        ground_size=(float(ground[0]), float(ground[1])),
        walls=[dict(wall) for wall in environment.walls],
        props=[dict(prop) for prop in environment.props],
        lighting=environment.lighting,
        room=tuple(environment.room) if environment.room else None,
    )
