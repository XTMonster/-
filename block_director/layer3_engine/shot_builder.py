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

DEFAULT_COLORS = ("#FF6B6B", "#6BC5FF", "#FFD166", "#9B8CFF",
                  "#6BE3A2", "#FF9F6B")
DEFAULT_SPACING = 1.5


@dataclass
class CastMember:
    """一名角色的设定。"""

    id: str
    name: str
    color: str = "#FFFFFF"
    position: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    facing: Tuple[float, float, float] = (0.0, 1.0, 0.0)


@dataclass
class SceneSpec:
    """场景设定：谁在场、环境长什么样。"""

    heading: str = ""
    cast: List[CastMember] = field(default_factory=list)
    # 默认给一大块地面：地面远边缘一旦进入画面，就会在参考视频里留下一条
    # 横贯中景的硬边，视频模型会把它当内容学走。室内场景请显式传小地面/room。
    ground_size: Tuple[float, float] = (120.0, 120.0)
    walls: List[Dict[str, Any]] = field(default_factory=list)
    props: List[Dict[str, Any]] = field(default_factory=list)
    lighting: str = "clay_studio"
    room: Optional[Tuple[float, float, float, float]] = None
    with_labels: bool = True

    @classmethod
    def from_plan(cls, plan: Plan, **overrides) -> "SceneSpec":
        """按计划里出现的角色自动生成一份确定性剧组设定。"""
        character_ids: List[str] = []
        for shot in plan.shots:
            for character_id in shot.characters:
                if character_id not in character_ids:
                    character_ids.append(character_id)
        cast: List[CastMember] = []
        count = len(character_ids)
        for index, character_id in enumerate(character_ids):
            offset = (index - (count - 1) / 2.0) * DEFAULT_SPACING
            cast.append(CastMember(
                id=character_id,
                name=character_id,
                color=DEFAULT_COLORS[index % len(DEFAULT_COLORS)],
                position=(round(offset, 3), 0.0, 0.0),
            ))
        return cls(heading=plan.scene_heading, cast=cast, **overrides)


@dataclass
class ShotBuildResult:
    shot_id: str
    shot_type: str
    start_frame: int
    end_frame: int
    camera: str
    camera_position: Tuple[float, float, float]
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


def _subject_anchor(shot: ShotPlan, cast: Dict[str, CastMember]
                    ) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
    """取镜头内角色的平均位置与首个角色的朝向。"""
    positions = [cast[cid].position for cid in shot.characters if cid in cast]
    if not positions:
        return (0.0, 0.0, 0.0), (0.0, 1.0, 0.0)
    x = sum(p[0] for p in positions) / len(positions)
    y = sum(p[1] for p in positions) / len(positions)
    facing = cast[shot.characters[0]].facing if shot.characters[0] in cast \
        else (0.0, 1.0, 0.0)
    return (x, y, 0.0), facing


def _action_requests(shot: ShotPlan, shot_start: int,
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
            params.setdefault("from", cast[character_id].position)
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
    for member in spec.cast:
        character = create_character(member.id, member.name, member.color,
                                     location=member.position,
                                     facing=member.facing)
        if spec.with_labels:
            create_label(character, member.name)
        cast_map[member.id] = member
        characters[member.id] = character
    summary.characters = len(characters)

    context = SceneContext(plan=plan, characters=characters)
    context.shot_types = {shot.shot_id: str(shot.shot_type)
                          for shot in plan.shots}
    context.current_shot_id = plan.shots[0].shot_id if plan.shots else ""

    cursor = 1
    motion_requests: Dict[str, List[ActionRequest]] = {}
    for shot in plan.shots:
        start = cursor
        end = cursor + max(shot.duration_frames, 1) - 1
        anchor, facing = _subject_anchor(shot, cast_map)

        bundle, solution = place_camera_for_shot(
            shot.shot_id, anchor, facing=facing, shot_type=str(shot.shot_type),
            side="front", room=spec.room)
        marker = scene.timeline_markers.new(f"BD_Cut_{shot.shot_id}", frame=start)
        marker.camera = bundle.camera
        context.cameras[shot.shot_id] = bundle.camera

        # §10.3：轴线由**第一个**含两名角色的镜头确立，后续镜头继承
        if context.axis is None and len(shot.characters) >= 2:
            speakers = [characters[cid] for cid in shot.characters[:2]
                        if cid in characters]
            if len(speakers) == 2:
                context.axis = establish_axis_from_speakers(speakers,
                                                           bundle.camera)

        shot_warnings = list(solution.warnings)
        requests = _action_requests(shot, start, cast_map, shot_warnings)
        shot_warnings.extend(
            thirty for thirty in _conflict_warnings(requests, shot.shot_id))
        for request in requests:
            motion_requests.setdefault(request.character_id, []).append(request)

        summary.results.append(ShotBuildResult(
            shot_id=shot.shot_id, shot_type=str(shot.shot_type),
            start_frame=start, end_frame=end, camera=bundle.camera.name,
            camera_position=tuple(bundle.camera.location),
            lens=float(bundle.lens),
            characters=list(shot.characters), motions=len(requests),
            warnings=shot_warnings))
        summary.cameras += 1
        summary.warnings.extend(shot_warnings)
        cursor = end + 1

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
    scene.frame_end = max(cursor - 1, 1)
    scene.frame_set(1)
    set_context(context)
    summary.shots = len(plan.shots)
    summary.total_frames = scene.frame_end
    log.info("场景构建完成：%d 镜 / %d 角色 / %d 相机 / %d 关键帧 / 共 %d 帧",
             summary.shots, summary.characters, summary.cameras,
             summary.keyframes, summary.total_frames)
    return summary


def _conflict_warnings(requests: Sequence[ActionRequest],
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
