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
from ..cinema.camera_motion import SUBJECT_TRACKING, movement_spec
from ..cinema.station import SubjectFrame, camera_direction, subject_frame
from ..cinema.schedule import action_frame_window, shot_ranges, total_frames
from ..motion.model import ActionRequest
from ..utils.geometry import rotation_z_to_facing
from ..utils.logger import get_logger
from ..utils.threading_guard import main_thread_only
from .character_system import MotionBlender, create_character, create_label
from .character_system.character_label import create_render_label, hex_rgba
from .cinema_engine import (
    apply_camera_movement,
    establish_axis_from_speakers,
    place_camera_for_shot,
)
from .collection_router import (
    clear_blockdirector_objects,
    clear_scene_objects,
    ensure_collections,
    purge_orphan_data,
)
from .scene_executor import build_crowd, build_environment, create_vfx
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
    #: v1.3 P7：声明式运镜落地的条数（相机关键帧由它生成）
    movements: int = 0
    #: v1.3 §3.6：群众实例数与特效代理数
    crowd: int = 0
    vfx: int = 0
    #: 渲染标签的烘焙摘要（v1.3 诉求 4）；没有标签时为空字典
    label_report: Dict[str, Any] = field(default_factory=dict)
    #: v1.4 US-17：被自动错开的同层动作（写进 shots.json.action_conflicts）。
    action_conflicts: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "shots": self.shots, "characters": self.characters,
            "cameras": self.cameras, "motions": self.motions,
            "keyframes": self.keyframes, "total_frames": self.total_frames,
            "warnings": list(self.warnings),
            "movements": self.movements,
            "crowd": self.crowd, "vfx": self.vfx,
            "label_report": dict(self.label_report),
            "action_conflicts": [dict(item) for item in self.action_conflicts],
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


def live_subject_entries(shot: ShotPlan, characters: Dict[str, Any]
                         ) -> List[Tuple[str, Tuple[float, float, float],
                                         Tuple[float, float, float]]]:
    """这一镜**此刻**的（角色 id, 世界位置, 世界朝向）。

    与 :func:`subject_frame_for` 的区别是**时间点**：后者读
    ``CastMember.initial_location``（剧本开始时的站位），而角色在**前面的镜头里
    已经走动过**。实测（2026-10-04，`work/_anchor_probe.py`，`long9` 工程）：
    64 镜里 **20 镜**的单主体与起始站位差 > 1 m，最远 **7.7 m**（`shot_059`：
    伊恩实际在 (8.6, −6.0)，机位却按 (0.9, 0.0) 摆）⇒ 那些镜头本来就把主体
    拍在画框边缘/画外，构图分因此常年在 50–60。

    朝向用 :func:`block_director.utils.geometry.rotation_z_to_facing` 从根节点
    的 yaw 回读——与构图评分模型（`composition_guide._screen_facing`）**同一处
    真源**，两边不会再互相镜像。
    """
    entries: List[Tuple[str, Tuple[float, float, float],
                        Tuple[float, float, float]]] = []
    for character_id in shot.characters:
        character = characters.get(character_id)
        root = getattr(character, "root", None)
        if root is None:
            continue
        location = root.matrix_world.translation
        facing = rotation_z_to_facing(root.matrix_world.to_euler().z)
        entries.append((character_id,
                        (float(location.x), float(location.y), float(location.z)),
                        (float(facing[0]), float(facing[1]), 0.0)))
    return entries


def place_shot_camera(shot: ShotPlan, cast: Dict[str, CastMember],
                      spec: Optional[SceneSpec] = None, *,
                      request: Optional[Dict[str, Any]] = None,
                      axis: Optional[Any] = None,
                      entries: Optional[Sequence[Any]] = None):
    """**唯一的机位解算入口**：主构建与单镜再生共用。

    v1.2 里 :mod:`shot_regenerator` 自己又写了一遍解算，而且写死
    ``side="front"``、丢掉 ``lens``——两条路径必然漂移。v1.3 收敛到这里，
    并让 ``side`` 经 :func:`cinema.station.camera_direction` 解析
    （双人镜头相对两人连线，而不是相对焦点主体的朝向）。
    """
    resolved = dict(request if request is not None
                    else (getattr(shot, "camera", None) or {}))
    #: `entries` 给了就用**实时**参考系（该镜首帧人在哪、朝哪），否则退回
    #: 剧本的起始站位（`CastMember.initial_location`）。
    frame = (subject_frame(entries, shot_type=str(shot.shot_type),
                           speaker_id=speaker_of(shot))
             if entries else subject_frame_for(shot, cast))
    side = str(resolved.get("side") or "front")
    axis_dir = None
    axis_side = 0
    axis_notes: List[str] = []
    if axis is not None:
        # 单人镜头落在轴线上时要把机位扭开（否则相机站在搭档的位置上）
        axis_dir = axis.direction
        axis_side = int(getattr(axis, "established_side", 0))
    direction = camera_direction(frame, side, axis_dir=axis_dir,
                                 axis_side=axis_side,
                                 #: 解算时若真的改了模型要的方向（按已确立
                                 #: 轴侧镜像），说明必须进这一镜的警告里——
                                 #: 悄悄改角度会让"计划写了 side=front_right、
                                 #: 场景里却不是"这种漂移无人发现。
                                 notes=axis_notes)
    #: **视线留白暂时不在这里开**（2026-10-04 的实测负结果）：把单主体镜头的
    #: 对准点横移 1/6 幅宽，在 `long9` 的工程上重建复评是**净负**——构图分中位
    #: 64.7 → 55.8、25 镜降 / 16 镜升，掉得最狠的（−48、−44、−40）全部是
    #: **主体本来就不在画面中心**的镜头：`place_shot_camera` 用的是
    #: `CastMember.initial_location`（计划里的起始站位），而角色在**前面的镜头里
    #: 已经走动过**——`work/_anchor_probe.py` 量到 64 镜里 **20 镜**的单主体与
    #: 起始站位差 >1 m，最远 **7.7 m**（`shot_059`：伊恩实际在 (8.6, −6.0)，
    #: 机位却按 (0.9, 0.0) 摆）。那些镜头再横移 1/6 就直接把主体推出画外。
    #: 所以顺序是**先修站位（锚点）再开留白**；机制本身已经就位并有测试：
    #: `cinema/station.aim_offset_for_lead_room` ＋ `solve_framing(aim_offset_x=…)`，
    #: 见 `tests/test_lead_room_aim.py`。
    bundle, solution = place_camera_for_shot(
        shot.shot_id, frame.anchor, facing=frame.facing,
        shot_type=str(shot.shot_type), side=side,
        lens=resolved.get("lens"), room=(spec.room if spec else None),
        direction=direction)
    solution.warnings.extend(axis_notes)
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
        #: 折帧走**单一真源**（`cinema/schedule.py`）——规则（R003 的动作区间）
        #: 与构建器必须问同一个函数，否则"写到时长的外面"会被规则当成跨镜重叠。
        start, end = action_frame_window(
            shot_start, int(shot.duration_frames),
            int(raw.get("start_frame") or 1),
            int(raw.get("end_frame") or shot.duration_frames))

        params = dict(raw.get("params") or {})
        if action_type in ("walk_to", "run_to"):
            #: **契约一致性**（2026-10-04 真跑实测）：草案 schema
            #: （`editor.EMIT_SHOT_DRAFT_PARAMETERS`）把 `target_position` 声明成
            #: 动作项的**顶层**字段，而这里原来只读 `params.target_position`
            #: ⇒ 模型按 schema 写的目的地被整条丢掉、只留一句
            #: "walk_to 缺少 target_position，已跳过"（`long10`/`long11` 各有
            #: 10 处）。两个合法位置都要认，优先 `params`（更细的那份）。
            if not params.get("target_position") and raw.get("target_position"):
                params["target_position"] = list(raw["target_position"])
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
                clear_scene: bool = False, brief=None,
                crowd=None) -> BuildSummary:
    """按计划重建整个白模场景。

    ``clear_scene=True`` 时连非本插件对象（Blender 启动场景自带的 Cube 等）
    一起清掉——批处理入口必须开这个，否则默认方块会挡在角色前面。

    ``brief`` 是阶段 S 的剧本理解（§3.2）：只用来决定站位（``space``）。
    给了显式 ``spec`` 时它不参与——用户改过的设定永远优先。
    """
    spec = spec or SceneSpec.from_plan(plan, brief=brief, crowd=crowd)
    scene = bpy.context.scene
    summary = BuildSummary()
    # 帧范围先定下来：群众的走位关键帧、标签的采样表都要用它。
    scene.frame_start = 1
    scene.frame_end = max(total_frames(plan), 1)

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
    app_config = get_config()
    label_config = app_config.character
    show_labels = bool(app_config.ui.show_labels)
    render_labels = bool(getattr(label_config, "label_render", False))
    label_entries: List[Dict[str, Any]] = []
    for member in spec.cast:
        character = create_character(member.id, member.name, member.color,
                                     location=member.initial_location,
                                     facing=member.initial_facing)
        if spec.with_labels:
            if render_labels:
                # v1.3 诉求 4：进参考视频的白字黑描边标签（构建期烘焙）。
                fill, stroke = create_render_label(
                    character, member.name,
                    font_path=label_config.label_font_path,
                    size=float(label_config.label_size),
                    fill_color=hex_rgba(label_config.label_color),
                    stroke_color=hex_rgba(label_config.label_stroke_color))
                label_entries.append({"character_id": member.id,
                                      "fill": fill, "stroke": stroke,
                                      "anchor": character.label_anchor})
            else:
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
    movement_tasks: List[Tuple[str, int, int, List[Dict[str, Any]], str]] = []
    #: 第一趟只**排片**（帧区间、动作请求、运镜任务），不摆机位：机位必须等动作
    #: 烘焙完之后再按"这一镜首帧人在哪"来摆（v1.6，见 `live_subject_entries`）。
    planned: Dict[str, Dict[str, Any]] = {}
    for shot in plan.shots:
        start, end = ranges[shot.shot_id]
        context.schedule[shot.shot_id] = (start, end)
        planned_warnings: List[str] = []
        requests = action_requests(shot, start, cast_map, planned_warnings)
        planned_warnings.extend(
            thirty for thirty in conflict_warnings(requests, shot.shot_id))
        for request in requests:
            motion_requests.setdefault(request.character_id, []).append(request)
        # §3.6 声明式消费：计划里写了运镜就自动生成相机关键帧（登记在第二趟之后
        # 执行——跟拍要读主体逐帧的位置）。
        declared_moves = [dict(item) for item in
                          (getattr(shot, "camera", None) or {}).get("movements", [])
                          if isinstance(item, dict)]
        if declared_moves:
            default_subject = (speaker_of(shot)
                               or (shot.characters[0] if shot.characters else ""))
            movement_tasks.append((shot.shot_id, start, end, declared_moves,
                                   default_subject))
        planned[shot.shot_id] = {"start": start, "end": end,
                                 "warnings": planned_warnings,
                                 "requests": requests}

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
        # v1.4 US-17：错开留痕（apply_motions 里的确定性错开）。
        for event in getattr(result, "action_conflicts", []) or []:
            record = dict(event)
            # shots.json 的该字段按**镜**聚合，这里补上镜头 id：
            # 事件本身只有"哪一层、哪两个动作"，用动作的起始帧反查排片表。
            if not record.get("shot_id"):
                frame = int(record.get("frame") or 0)
                record["shot_id"] = next(
                    (key for key, span in context.schedule.items()
                     if int(span[0]) <= frame <= int(span[1])), "")
            summary.action_conflicts.append(record)

    #: 第二趟：摆机位。先 `frame_set(该镜首帧)` 再读角色的世界位置/朝向——
    #: 这是"机位瞄的是这一镜人在哪"唯一成立的地方。
    for shot in plan.shots:
        info = planned[shot.shot_id]
        start, end = int(info["start"]), int(info["end"])
        scene.frame_set(start)
        bpy.context.view_layer.update()

        # 阶段 B1 可以给这一镜一个"相对取景请求"（§16.1 的 CameraRequest）：
        # side 与 lens 由取景解算器消费；距离/高度仍按 §10.6/§10.5 推导。
        # v1.3：side 经 cinema.station 解析——双人镜头相对两人连线，
        # 而不是相对焦点主体的朝向（否则机位会落在轴线上）。
        bundle, solution, frame = place_shot_camera(shot, cast_map, spec,
                                                    axis=context.axis,
                                                    entries=live_subject_entries(
                                                        shot, characters))
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

        shot_warnings = list(solution.warnings) + list(info["warnings"])
        requests = info["requests"]

        # §3.6 特效代理：只在声明的时间窗内可见（关键帧控制 hide_render），
        # 否则火焰会一路烧到别的镜头里去。
        for index, raw in enumerate(getattr(shot, "vfx", None) or [], start=1):
            if not isinstance(raw, dict):
                shot_warnings.append(f"{shot.shot_id}: 第 {index} 个特效不是对象，已跳过")
                continue
            vfx_id = str(raw.get("id") or f"{shot.shot_id}_vfx{index}")
            kind = str(raw.get("type") or "glow")
            position = raw.get("position") or _vfx_fallback_position(frame.anchor)
            if not app_config.vfx.enabled:
                shot_warnings.append(
                    f"{shot.shot_id}: vfx.enabled=false，特效 {vfx_id} 已跳过")
                continue
            try:
                object_ = create_vfx(vfx_id, kind, position,
                                     raw.get("size") or (0.0, 0.0, 0.0))
            except Exception as exc:  # noqa: BLE001 - 单个特效失败不该拖垮构建
                shot_warnings.append(
                    f"{shot.shot_id}: 特效 {vfx_id} 创建失败（{exc}）")
                continue
            local_start = int(raw.get("start_frame") or 1)
            local_end = int(raw.get("end_frame") or (end - start + 1))
            _window_visibility(object_, start + local_start - 1,
                               start + max(local_end, local_start) - 1,
                               scene_end=scene.frame_end)
            context.vfx[vfx_id] = object_
            summary.vfx += 1

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

    for shot_id, start, end, declared_moves, default_subject in movement_tasks:
        camera = context.cameras.get(shot_id)
        target = bpy.data.objects.get(f"BD_CamTarget_{shot_id}")
        if camera is None:
            summary.warnings.append(f"{shot_id}: 没有相机，运镜声明已跳过")
            continue
        for raw in declared_moves:
            try:
                # 变量名不能叫 spec——那会盖住上面的 SceneSpec（函数后面还要用）
                move = movement_spec(raw, shot_start=start, shot_end=end,
                                     default_subject=default_subject)
            except ValueError as exc:
                summary.warnings.append(
                    f"{shot_id}: 运镜声明无效（{exc}），已跳过")
                continue
            subject = characters.get(str(move["subject"]))
            if move["type"] in SUBJECT_TRACKING and subject is None:
                summary.warnings.append(
                    f"{shot_id}: {move['type']} 找不到被摄主体"
                    f"（{move['subject'] or '未指定'}），已跳过")
                continue
            try:
                report = apply_camera_movement(
                    camera, target, str(move["type"]), float(move["amount"]),
                    int(move["start_frame"]), int(move["end_frame"]),
                    subject=subject, seed=int(move["seed"]))
            except ValueError as exc:
                summary.warnings.append(f"{shot_id}: {exc}")
                continue
            summary.movements += 1
            summary.keyframes += int(report["keyframes"])
            log.info("%s: 运镜 %s（%s 帧）", shot_id, move["type"],
                     f"{move['start_frame']}-{move['end_frame']}")

    # §3.6 群众：声明式代理，独立于 cast（不进角色面板、构图与场景状态）。
    if spec.crowd:
        crowd_objects = build_crowd(spec.crowd,
                                    height=float(app_config.crowd.height),
                                    spacing=float(app_config.crowd.spacing),
                                    walk_frames=(1, scene.frame_end))
        context.crowd = list(crowd_objects)
        summary.crowd = len(crowd_objects)
        if app_config.delivery.render_backend.value == "workbench":
            summary.warnings.append(
                f"群众代理 {len(crowd_objects)} 个（Workbench 下为不透明实色）")

    if label_entries:
        # v1.3 诉求 4：标签的公告板与"屏幕恒定字号"在**构建期**烘焙，
        # 不依赖渲染期的 frame_change handler（headless 渲染下不可靠）。
        from .label_baking import bake_labels

        label_report = bake_labels(
            scene, label_entries, context.schedule, context.cameras,
            target_pixels=float(label_config.label_pixels),
            min_pixels=float(label_config.label_min_pixels),
            max_ratio=float(label_config.label_max_ratio),
            resolution=app_config.delivery.resolution)
        summary.label_report = label_report
        for item in label_report.get("unreadable", [])[:5]:
            summary.warnings.append(
                f"{item['character_id']} 在第 {item['frame']} 帧的标签低于"
                f"可读下限（{label_config.label_min_pixels:g}px）")

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


def _vfx_fallback_position(anchor) -> Tuple[float, float, float]:
    """声明里没给坐标时的落点：主体正前方偏上一点。"""
    return (float(anchor[0]) + 0.5, float(anchor[1]), float(anchor[2]) + 1.0)


def _window_visibility(obj, start: int, end: int, *, scene_end: int) -> None:
    """让对象**只在**这段时间窗里渲染（其余帧硬切掉，不做淡入淡出）。"""
    start = max(int(start), 1)
    end = max(int(end), start)
    obj.hide_render = True
    if start > 1:
        obj.keyframe_insert(data_path="hide_render", frame=max(start - 1, 1))
    obj.hide_render = False
    obj.keyframe_insert(data_path="hide_render", frame=start)
    obj.keyframe_insert(data_path="hide_render", frame=end)
    if end < int(scene_end):
        obj.hide_render = True
        obj.keyframe_insert(data_path="hide_render", frame=end + 1)
    for curve in _action_curves(obj):
        for point in curve.keyframe_points:
            if curve.data_path == "hide_render":
                point.interpolation = 'CONSTANT'


def _action_curves(obj) -> List[object]:
    if obj.animation_data is None or obj.animation_data.action is None:
        return []
    from ..utils.blender_compat import action_fcurves
    return list(action_fcurves(obj.animation_data.action))


def conflict_warnings(requests: Sequence[ActionRequest],
                       shot_id: str) -> List[str]:
    from ..motion.model import check_conflicts
    return [f"{shot_id}: {problem}" for problem in check_conflicts(requests)]


class BpySceneBuilder:
    """驱动器用的构建器实现（满足 ``SceneBuilder`` 协议）。"""

    def __init__(self, spec: Optional[SceneSpec] = None,
                 clear_scene: bool = False, crowd=None) -> None:
        self.spec = spec
        self.clear_scene = clear_scene
        self.crowd = crowd

    def build(self, plan: Plan, brief=None) -> Dict[str, Any]:
        return build_scene(plan, self.spec, clear_scene=self.clear_scene,
                           brief=brief, crowd=self.crowd).to_dict()
