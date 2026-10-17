"""从计划 + 构建结果组装 SDL（执行文档 v1.2 §5）。

SDL 是"这个项目长什么样"的完整描述；组装好之后既能落盘（§14），也能反向
还原成构建器的入参（:func:`sdl_to_plan` / :func:`sdl_to_spec`），
于是"保存 → 重新加载 → 重建场景"成为一条闭合回路。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..contracts.cast import CastMember, SceneSpec
from ..contracts.plan import Plan, ShotPlan
from ..contracts.serde import to_plain
from ..contracts.sdl import (
    SDL_VERSION,
    SDLAnchor,
    SDLCamera,
    SDLEnvironment,
    SDLProject,
    SDLScene,
    SDLShot,
)


def _movement_list(camera: Dict[str, Any]) -> List[Dict[str, Any]]:
    """计划里的 ``camera.movements`` → SDL 的 ``movements``。"""
    raw = (camera or {}).get("movements")
    return [dict(item) for item in raw or [] if isinstance(item, dict)]


def _movement_name(camera: Dict[str, Any]) -> str:
    """旧的单值 ``movement`` 字段：只有一次运镜时写它，多个时留 ``static``。"""
    items = _movement_list(camera)
    if len(items) == 1:
        return str(items[0].get("type") or "static")
    return "static"


def _camera_side_request(camera: Dict[str, Any]) -> Dict[str, Any]:
    """取景请求（side/lens）单独放 ``request``，运镜另有 ``movements``。"""
    payload = {key: value for key, value in (camera or {}).items()
               if key != "movements"}
    return payload


def _camera_request(camera: SDLCamera) -> Dict[str, Any]:
    """把 SDL 的相机描述还原成计划的 ``ShotPlan.camera`` 形态。

    v1.3 的运镜是**声明式**的：重建场景时 ``camera.movements`` 会被自动
    消费成关键帧，所以它必须跟着项目文件一起回来，否则"存了再打开"就丢运动。
    """
    request = dict(camera.request or {})
    if camera.lens:
        request.setdefault("lens", float(camera.lens))
    if camera.movements:
        request["movements"] = [dict(item) for item in camera.movements]
    elif camera.movement and camera.movement != "static":
        request.setdefault("movements", [{"type": camera.movement}])
    return request


def _anchors(raw: Any) -> List[SDLAnchor]:
    """计划里的场级锚点（dict 表）→ ``SDLAnchor`` 表。

    ``position`` 是求解器回填的结果（可能缺席 = 未求解），这里原样搬运，
    不替它编坐标。
    """
    anchors: List[SDLAnchor] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        anchors.append(SDLAnchor(
            name=str(item.get("name") or ""),
            depth=str(item.get("depth") or "mid"),
            relation=str(item.get("relation") or ""),
            position=[float(v) for v in (item.get("position") or [])],
        ))
    return anchors


def _environment(spec: SceneSpec, plan: Optional[Plan] = None
                 ) -> SDLEnvironment:
    environment = dict(getattr(plan, "environment", None) or {}) \
        if plan is not None else {}
    return SDLEnvironment(
        ground_size=[float(spec.ground_size[0]), float(spec.ground_size[1])],
        walls=[dict(wall) for wall in spec.walls],
        props=[dict(prop) for prop in spec.props],
        lighting=spec.lighting,
        room=list(spec.room) if spec.room else None,
        crowd=[dict(item) for item in (getattr(spec, "crowd", None) or [])],
        anchors=_anchors(environment.get("anchors")),
        light=dict(environment.get("light") or {}),
    )


def build_sdl(plan: Plan, *,
              build_summary: Optional[Dict[str, Any]] = None,
              spec: Optional[SceneSpec] = None,
              project_name: str = "BlockDirector",
              fps: int = 24,
              scene_id: str = "scene_001",
              brief=None, crowd=None, polish=None) -> SDLProject:
    """把分镜计划与构建结果组装成一份 SDL。"""
    spec = spec or SceneSpec.from_plan(plan, brief=brief, crowd=crowd)
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
                             movement=str(_movement_name(planned.camera)),
                             movements=_movement_list(planned.camera),
                             request=_camera_side_request(planned.camera)),
            axis_line=None,
            active_speakers=list(planned.characters),
            characters=list(planned.characters),
            actions=[dict(action) for action in planned.actions],
            dialogues=[dict(item) for item in planned.dialogues],
            gaze=[dict(item) for item in (getattr(planned, "gaze", []) or [])],
            vfx=[dict(item) for item in (getattr(planned, "vfx", []) or [])],
            beats=[dict(item) for item in (planned.beats or [])],
            composition=dict(planned.composition or {}),
            rule_justifications=[dict(item)
                                 for item in (planned.rule_justifications or [])],
            prompt=planned.prompt,
            responsibility=getattr(planned, "responsibility", None),
        ))

    scene = SDLScene(id=scene_id, number=1, heading=plan.scene_heading,
                     environment=_environment(spec, plan), shots=shots)
    continuity: Dict[str, Any] = {
        "axis_note": list(plan.continuity_notes),
        "character_pose": {member.id: {"position": list(member.initial_location),
                                       "facing": list(member.initial_facing)}
                           for member in spec.cast},
    }
    return SDLProject(name=project_name, version=SDL_VERSION, fps=fps,
                      characters=list(spec.cast), scenes=[scene],
                      continuity=continuity,
                      warnings=list((build_summary or {}).get("warnings", [])),
                      brief=(brief.to_dict() if brief is not None else {}),
                      polish=(polish.to_dict() if polish is not None else {}),
                      with_labels=bool(getattr(spec, "with_labels", True)))


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
                "camera": _camera_request(shot.camera),
                "gaze": [dict(item) for item in shot.gaze],
                "vfx": [dict(item) for item in shot.vfx],
                "beats": [dict(item) for item in (shot.beats or [])],
                "composition": dict(shot.composition or {}),
                "rule_justifications": [dict(item)
                                        for item in (shot.rule_justifications
                                                     or [])],
                "prompt": shot.prompt,
                "responsibility": to_plain(
                    getattr(shot, "responsibility", None)),
            }))
    heading = sdl.scenes[0].heading if sdl.scenes else ""
    # v1.5 §3.2：场级环境（anchors/light）必须跟着项目文件回来，否则
    # "存了再打开"会丢掉锚点与灯光声明，重建场景就没有摆位依据。
    environment: Dict[str, Any] = {}
    if sdl.scenes:
        source = sdl.scenes[0].environment
        environment = {
            "anchors": [to_plain(anchor)
                        for anchor in (getattr(source, "anchors", None) or [])],
            "light": dict(getattr(source, "light", None) or {}),
        }
    return Plan(shots=shots, scene_heading=heading,
                continuity_notes=list(sdl.continuity.get("axis_note", [])),
                environment=environment)


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
        crowd=[dict(item) for item in (getattr(environment, "crowd", None)
                                       or [])],
        with_labels=bool(getattr(sdl, "with_labels", True)),
    )
