"""把分镜计划落成场景（执行文档 v1.2 §7.1 阶段 B2 / §10.2 排片）。

这是"剧本 → 可看的白模动画"最后一个断点：驱动器产出 :class:`Plan`，
本模块把它变成真实的角色、环境、机位、关键帧与剪切标记。

设计约束：
- 全部 bpy 操作在主线程（入口带 ``@main_thread_only``）；
- **不替 LLM 编造内容**：计划里没给动作就拍静态镜头，缺关键参数的动作
  记警告并跳过，而不是猜一个目标位置。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import bpy

from ..contracts.plan import Plan, ShotPlan
from ..contracts.cast import CastMember, SceneSpec
from ..cinema.station import SubjectFrame, camera_direction, subject_frame
from ..cinema.schedule import shot_ranges, total_frames
from ..motion.model import ActionRequest
from ..utils.logger import get_logger
from ..utils.threading_guard import main_thread_only
from .character_system import MotionBlender, create_character, create_label
from .cinema_engine import establish_axis_from_speakers, place_camera_for_shot
from .collection_router import (
    clear_blockdirector_objects,
    clear_scene_objects,
    ensure_collections,
    purge_orphan_data,
)
from .scene_executor import build_environment
from .scene_context import SceneContext, set_context

log = get_logger("shot-builder")

@dataclass
class ShotBuildResult:
    shot_id: str
    shot_type: str
    start_frame: int
    end_frame: int
    camera: str
    camera_position: Tuple[float, float, float]
    camera_target: Tuple[float, float, float] = (0.0, 0.0, 1.0)
    lens: float = 50.0
    characters: List[str] = field(default_factory=list)
    motions: int = 0
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "shot_id": self.shot_id, "shot_type": self.shot_type,
            "start_frame": self.start_frame, "end_frame": self.end_frame,
            "camera": self.camera,
            "camera_position": [round(v, 3) for v in self.camera_position],
            "camera_target": [round(v, 3) for v in self.camera_target],
            "lens": round(self.lens, 2),
            "characters": list(self.characters), "motions": self.motions,
            "warnings": list(self.warnings),
        }


@dataclass
class BuildSummary:
    shots: int = 0
    characters: int = 0
    cameras: int = 0
    motions: int = 0
    keyframes: int = 0
    total_frames: int = 0
    results: List[ShotBuildResult] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "shots": self.shots, "characters": self.characters,
            "cameras": self.cameras, "motions": self.motions,
            "keyframes": self.keyframes, "total_frames": self.total_frames,
            "warnings": list(self.warnings),
            "results": [r.to_dict() for r in self.results],
        }


def speaker_of(shot: ShotPlan) -> str:
    """本镜第一个说话的角色 id；没有对白时返回空串。

    焦点主体用它来定：把特写对准说话的人，而不是永远对准 characters[0]。
    """
    for item in getattr(shot, "dialogues", None) or []:
        character_id = str((item or {}).get("character_id") or "")
        if character_id:
            return character_id
    return ""


def subject_frame_for(shot: ShotPlan,
                      cast: Dict[str, CastMember]) -> SubjectFrame:
    """把镜头里出场的角色整理成取景参考系（焦点主体 + 轴线）。

    v1.2 的 ``subject_anchor`` 只返回"全体重心 + 第一个角色的朝向"，
    两人相对而立时会把相机放到轴线上（见 ``cinema/station.py`` 的说明）。
    """
    entries: List[Tuple[str, Tuple[float, float, float],
                        Tuple[float, float, float]]] = []
    for character_id in shot.characters:
        member = cast.get(character_id)
        if member is None:
            continue
        entries.append((character_id, tuple(member.initial_location),
                        tuple(member.initial_facing)))
    return subject_frame(entries, shot_type=str(shot.shot_type),
                         speaker_id=speaker_of(shot))


def place_shot_camera(shot: ShotPlan, cast: Dict[str, CastMember],
                      spec: Optional[SceneSpec] = None, *,
                      request: Optional[Dict[str, Any]] = None):
    """**唯一的机位解算入口**：主构建与单镜再生共用。

    v1.2 里 :mod:`shot_regenerator` 自己又写了一遍解算，而且写死
    ``side="front"``、丢掉 ``lens``——两条路径必然漂移。v1.3 收敛到这里，
    并让 ``side`` 经 :func:`cinema.station.camera_direction` 解析
    （双人镜头相对两人连线，而不是相对焦点主体的朝向）。
    """
    resolved = dict(request if request is not None
                    else (getattr(shot, "camera", None) or {}))
    frame = subject_frame_for(shot, cast)
    side = str(resolved.get("side") or "front")
    bundle, solution = place_camera_for_shot(
        shot.shot_id, frame.anchor, facing=frame.facing,
        shot_type=str(shot.shot_type), side=side,
        lens=resolved.get("lens"), room=(spec.room if spec else None),
        direction=camera_direction(frame, side))
    return bundle, solution, frame


def action_requests(shot: ShotPlan, shot_start: int,
                     cast: Dict[str, CastMember],
                     warnings: List[str]) -> List[ActionRequest]:
    """把计划里的动作转成全局帧号的动作请求。"""
    requests: List[ActionRequest] = []
    for index, raw in enumerate(shot.actions or [], start=1):
        if not isinstance(raw, dict):
            warnings.append(f"{shot.shot_id}: 第 {index} 个动作不是对象，已跳过")
            continue
        action_type = str(raw.get("action_type") or "")
        character_id = str(raw.get("character_id") or "")
        if not action_type or not character_id:
            warnings.append(f"{shot.shot_id}: 第 {index} 个动作缺 action_type/character_id，已跳过")
            continue
        if character_id not in cast:
            warnings.append(f"{shot.shot_id}: 动作引用了不在场的角色 {character_id}，已跳过")
            continue
        local_start = int(raw.get("start_frame") or 1)
        local_end = int(raw.get("end_frame") or shot.duration_frames)
        start = shot_start + max(local_start, 1) - 1
        end = shot_start + min(max(local_end, local_start), shot.duration_frames) - 1

        params = dict(raw.get("params") or {})
        if action_type in ("walk_to", "run_to"):
            if not params.get("target_position"):
                warnings.append(
                    f"{shot.shot_id}: {action_type} 缺少 target_position，已跳过"
                    "（不替 LLM 猜目的地）")
                continue
            params.setdefault("from", cast[character_id].initial_location)
        requests.append(ActionRequest(action_type=action_type,
                                      start_frame=start, end_frame=end,
                                      params=params, character_id=character_id,
                                      action_id=f"{shot.shot_id}_{index}"))
    return requests


@main_thread_only("build_scene")
def build_scene(plan: Plan, spec: Optional[SceneSpec] = None,
                clear_scene: bool = False) -> BuildSummary:
    """按计划重建整个白模场景。

    ``clear_scene=True`` 时连非本插件对象（Blender 启动场景自带的 Cube 等）
    一起清掉——批处理入口必须开这个，否则默认方块会挡在角色前面。
    """
    spec = spec or SceneSpec.from_plan(plan)
    scene = bpy.context.scene
    summary = BuildSummary()

    removed = (clear_scene_objects() if clear_scene
               else clear_blockdirector_objects())
    if removed:
        log.info("清理旧对象 %d 个", removed)
    ensure_collections(scene)
    purge_orphan_data()

    build_environment(ground_size=spec.ground_size, walls=spec.walls,
                      props=spec.props, lighting=spec.lighting)

    cast_map: Dict[str, CastMember] = {}
    characters: Dict[str, Any] = {}
    # 标签的字体/字号/视口开关必须从配置读出来再传下去：
    # v1.2 定义了 character.label_font_path 与 ui.show_labels 却从没接线，
    # 配置项是死的（启动时那句"未指定中文字体"的提示也就成了误导）。
    from ..settings import get_config
    label_config = get_config().character
    show_labels = bool(get_config().ui.show_labels)
    for member in spec.cast:
        character = create_character(member.id, member.name, member.color,
                                     location=member.initial_location,
                                     facing=member.initial_facing)
        if spec.with_labels:
            create_label(character, member.name,
                         font_path=label_config.label_font_path,
                         size=float(label_config.label_size),
                         show_in_viewport=show_labels)
        cast_map[member.id] = member
        characters[member.id] = character
    summary.characters = len(characters)

    context = SceneContext(plan=plan, characters=characters, spec=spec)
    context.shot_types = {shot.shot_id: str(shot.shot_type)
                          for shot in plan.shots}
    context.current_shot_id = plan.shots[0].shot_id if plan.shots else ""

    ranges = shot_ranges(plan)
    motion_requests: Dict[str, List[ActionRequest]] = {}
    for shot in plan.shots:
        start, end = ranges[shot.shot_id]

        # 阶段 B1 可以给这一镜一个"相对取景请求"（§16.1 的 CameraRequest）：
        # side 与 lens 由取景解算器消费；距离/高度仍按 §10.6/§10.5 推导。
        # v1.3：side 经 cinema.station 解析——双人镜头相对两人连线，
        # 而不是相对焦点主体的朝向（否则机位会落在轴线上）。
        bundle, solution, frame = place_shot_camera(shot, cast_map, spec)
        marker = scene.timeline_markers.new(f"BD_Cut_{shot.shot_id}", frame=start)
        marker.camera = bundle.camera
        context.cameras[shot.shot_id] = bundle.camera
        context.schedule[shot.shot_id] = (start, end)

        # §10.3：轴线由**第一个**含两名角色的镜头确立，后续镜头继承
        if context.axis is None and len(shot.characters) >= 2:
            speakers = [characters[cid] for cid in shot.characters[:2]
                        if cid in characters]
            if len(speakers) == 2:
                context.axis = establish_axis_from_speakers(speakers,
                                                           bundle.camera)

        shot_warnings = list(solution.warnings)
        requests = action_requests(shot, start, cast_map, shot_warnings)
        shot_warnings.extend(
            thirty for thirty in conflict_warnings(requests, shot.shot_id))
        for request in requests:
            motion_requests.setdefault(request.character_id, []).append(request)

        summary.results.append(ShotBuildResult(
            shot_id=shot.shot_id, shot_type=str(shot.shot_type),
            start_frame=start, end_frame=end, camera=bundle.camera.name,
            camera_position=tuple(bundle.camera.location),
            camera_target=tuple(solution.target),
            lens=float(bundle.lens),
            characters=list(shot.characters), motions=len(requests),
            warnings=shot_warnings))
        summary.cameras += 1
        summary.warnings.extend(shot_warnings)

    for character_id, requests in motion_requests.items():
        character = characters.get(character_id)
        if character is None:
            continue
        blender = MotionBlender(character)
        blender.requests.extend(requests)
        try:
            result = blender.bake(clear=True)
        except ValueError as exc:
            summary.warnings.append(f"{character_id}: 动作烘焙失败（{exc}）")
            continue
        summary.motions += len(requests)
        summary.keyframes += result.keyframes

    scene.frame_start = 1
    scene.frame_end = max(total_frames(plan), 1)
    scene.frame_set(1)
    set_context(context)
    # §8.3：把这次插件写入记为基线，之后才分得清"哪些是用户改的"。
    from .scene_sync import note_build
    note_build()
    summary.shots = len(plan.shots)
    summary.total_frames = scene.frame_end
    log.info("场景构建完成：%d 镜 / %d 角色 / %d 相机 / %d 关键帧 / 共 %d 帧",
             summary.shots, summary.characters, summary.cameras,
             summary.keyframes, summary.total_frames)
    return summary


def conflict_warnings(requests: Sequence[ActionRequest],
                       shot_id: str) -> List[str]:
    from ..motion.model import check_conflicts
    return [f"{shot_id}: {problem}" for problem in check_conflicts(requests)]


class BpySceneBuilder:
    """驱动器用的构建器实现（满足 ``SceneBuilder`` 协议）。"""

    def __init__(self, spec: Optional[SceneSpec] = None,
                 clear_scene: bool = False) -> None:
        self.spec = spec
        self.clear_scene = clear_scene

    def build(self, plan: Plan) -> Dict[str, Any]:
        return build_scene(plan, self.spec,
                           clear_scene=self.clear_scene).to_dict()
