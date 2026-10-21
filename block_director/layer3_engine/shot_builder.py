"""把分镜计划落成场景（执行文档 v1.2 §7.1 阶段 B2 / §10.2 排片）。

这是"剧本 → 可看的白模动画"最后一个断点：驱动器产出 :class:`Plan`，
本模块把它变成真实的角色、环境、机位、关键帧与剪切标记。

设计约束：
- 全部 bpy 操作在主线程（入口带 ``@main_thread_only``）；
- **不替 LLM 编造内容**：计划里没给动作就拍静态镜头，缺关键参数的动作
  记警告并跳过，而不是猜一个目标位置。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Sequence, Tuple

import bpy

from ..contracts.plan import Plan, ShotPlan
from ..contracts.cast import CastMember, SceneSpec
from ..cinema.camera_motion import SUBJECT_TRACKING, movement_curve, movement_spec
from ..cinema.axis import (Axis, axis_state, camera_side_of, current_line,
                           axis_status, pair_spans)
from ..cinema.station import (
    HEAD_ROOM_AIM_M,
    SubjectFrame,
    aim_offset_for_composition,
    aim_offset_for_lead_room,
    camera_direction,
    subject_frame,
)
from ..cinema.schedule import (
    action_frame_window,
    out_of_bounds,
    shot_ranges,
    total_frames,
    travelled_positions,
)
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
from .scene_executor import (
    apply_prop_interactions,
    build_crowd,
    build_environment,
    create_vfx,
)
from .scene_context import SceneContext, get_context, set_context

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
    #: v1.5（P14-313，轴族裁决）：**生成器自己算的那两个值**，原样落成字段。
    #: 裁决原话："字段必须写生成器原生值——**有序 pair ＋ Z 符号**（±1/0，可选 status）"；
    #: **刻意不叫 `axis_side`**（那个名字已被索引的 `left/right` 域占用，同名会让人以为两边同域）。
    axis_pair: List[str] = field(default_factory=list)
    axis_side_sign: int = 0
    axis_status: str = ""

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
            #: 只抄不改：不加工、不换名（`left/right` 在约定定案前**不进成片**）。
            "axis_pair": list(self.axis_pair),
            "axis_side_sign": int(self.axis_side_sign),
            "axis_status": str(self.axis_status),
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


def live_positions_by_label(characters: Dict[str, Any]
                            ) -> Dict[str, Tuple[float, float]]:
    """场景里每个角色**此刻**的 XY，键同时给 id 与显示名（轴线标签两种都可能用）。"""
    spots: Dict[str, Tuple[float, float]] = {}
    for character_id, character in (characters or {}).items():
        root = getattr(character, "root", None)
        if root is None:
            continue
        xy = (float(root.matrix_world.translation.x),
              float(root.matrix_world.translation.y))
        spots[str(character_id)] = xy
        name = str(getattr(character, "name", "") or "")
        if name:
            spots[name] = xy
    return spots


def _axis_for_placement(context, plan, cast_map, characters, shot, live_side=None):
    """这一镜摆机位该用的轴线：**线**取两人此刻连线，**侧**取状态机给的侧别。

    状态机只在第一镜（含两名角色的那镜）确立轴线**之后**才算得出来；那之前的镜头
    仍用 `context.axis`（那时它还是 None，求解器会走"相对焦点朝向"的兜底路径）。

    `live_side`（可选）：**顺序状态机**给出的侧别——摆完上一镜、量过"连线扫没扫过
    刚摆好的那台机位"之后，`build_scene` 会把它传进来（§七十三 的收尾）。不传就
    退回"计划期近似"的那张表，这是给别处直接调用本函数时的兼容路径。
    """
    base = getattr(context, "axis", None)
    #: 轴还没确立的镜头**也要留一条记录**：工具层重设同一镜的机位时必须复现
    #: "当时就没有轴线可用"，否则会拿**后来才确立**的轴把相机镜像到另一侧
    #: （实测 `shot_001`：位置 y 由 -4.30 翻成 +4.30、构图 74.6 → 20.0）。
    #: 记在**单独一张集合**里而不是 `_axis_sides_used` 里塞 None——后者被
    #: `rule_checker._axis_sides` 按 int 消费，塞 None 会直接把它打崩。
    if base is None:
        absent = set(getattr(context, "_axis_absent_shots", None) or ())
        absent.add(str(shot.shot_id))
        context._axis_absent_shots = absent
        return None
    live = current_line(base, live_positions_by_label(characters))
    if live_side is None:
        #: 键名带 `_plan`：**规则自己也用 `_axis_sides`**，构建器往同一个键里写
        #: 计划期的表会把规则算出来的实际表顶掉（2026-10-04 踩过）。
        sides = getattr(context, "_axis_sides_plan", None)
        if sides is None:
            sides = axis_state(base, plan, _initial_cast_positions(context))
            context._axis_sides_plan = sides
        side = int(sides.get(str(shot.shot_id), live.established_side))
    else:
        side = int(live_side)
    #: 记下这一镜**实际**用的侧别：规则读它（`rule_checker._axis_sides`）。
    used = dict(getattr(context, "_axis_sides_used", None) or {})
    used[str(shot.shot_id)] = side
    context._axis_sides_used = used
    #: 同时记下摆位用的**那条线**（G2 v4 实测：只记侧别不记线，审核期拿
    #: 走位后的当前连线量相机，走位一转线，"机位在错侧"对整组镜头误报 460 次
    #: 并把修复回路推进"挪机位→出画/机后→回滚"的振荡）。"机位自己摆错"这条
    #: 判据的参照系必须与摆位同源，走位跨线交给 crossing/unbridged 机制。
    lines = dict(getattr(context, "_axis_lines_used", None) or {})
    lines[str(shot.shot_id)] = (tuple(live.start), tuple(live.end))
    context._axis_lines_used = lines
    return Axis(start=live.start, end=live.end, established_side=side,
                left_label=live.left_label, right_label=live.right_label)


def _initial_cast_positions(context) -> Dict[str, Tuple[float, float, float]]:
    """剧本起始站位（id 与显示名两套键）。`pair_spans` 与计划期近似表都读它。"""
    initial: Dict[str, Tuple[float, float, float]] = {}
    for member in (getattr(getattr(context, "spec", None), "cast", None) or []):
        location = tuple(member.initial_location)
        initial[str(member.id)] = location
        name = str(getattr(member, "name", "") or "")
        if name:
            initial[name] = location
    return initial


def _skip_character(cid: str, plan) -> bool:
    """角色级 skip（v1.7 J3）：仅当某角色**全部出场镜**都
    ``responsibility.skip_white_model=true`` → 构建循环跳过（不建主体）。

    白模角色是场景级共享对象，不能"该镜不建主体"（会拆掉其它镜的主体）：
    混合镜角色主体仍在。未声明镜（``responsibility is None``）零行为差。
    """
    shots_with = [s for s in plan.shots if cid in (s.characters or [])]
    return bool(shots_with) and all(
        s.responsibility is not None and s.responsibility.skip_white_model
        for s in shots_with)


def axis_for_shot(context, shot) -> Optional[Axis]:
    """**这一镜此刻**该用的轴线：线取两人此刻连线，侧取顺序状态机记下的侧别。

    这是主构建与工具层（`setup_camera`）**唯一的轴线入口**。两处各算一份必然
    漂移，而且漂得不是一点：工具层以前读 `context.axis.established_side`（全片
    一个常数），构建器读的是**逐镜**的 `_axis_sides_used`（换位之后会翻侧）——
    于是"修复"会把机位摆回观众没看见过的那一侧。

    状态机还没跑过（手工搭的场景、轴尚未确立）时返回 ``None``，由
    `place_shot_camera` 走"相对焦点朝向"的同一兜底路径。
    """
    plan = getattr(context, "plan", None)
    if plan is None or getattr(context, "axis", None) is None:
        return None
    cast_map = {member.id: member
                for member in (getattr(getattr(context, "spec", None), "cast", None)
                               or [])}
    #: 构建这一镜时**有没有**轴、用的是哪一侧，两张表里都记着；照着复现，
    #: 不重新猜（重新猜就会用"后来才确立的轴"把相机摆到观众没看见的一侧）。
    if str(shot.shot_id) in set(getattr(context, "_axis_absent_shots", None) or ()):
        return None
    used = getattr(context, "_axis_sides_used", None)
    if used is not None and str(shot.shot_id) in used:
        return _axis_for_placement(context, plan, cast_map, context.characters,
                                   shot, live_side=int(used[str(shot.shot_id)]))
    return _axis_for_placement(context, plan, cast_map, context.characters, shot,
                               live_side=None)


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
                      entries: Optional[Sequence[Any]] = None,
                      reuse: Optional[Any] = None):
    """**唯一的机位解算入口**：主构建与单镜再生共用。

    v1.2 里 :mod:`shot_regenerator` 自己又写了一遍解算，而且写死
    ``side="front"``、丢掉 ``lens``——两条路径必然漂移。v1.3 收敛到这里，
    并让 ``side`` 经 :func:`cinema.station.camera_direction` 解析
    （双人镜头相对两人连线，而不是相对焦点主体的朝向）。

    ``reuse`` 给一个已有的 ``CameraBundle`` 时，结果写到那台相机上而不新建对象
    （`reframe` 用）。
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
    #: v1.7：单主体镜头的**视线留白**——把对准点横移 1/6 幅宽，让主体落到
    #: 背向视线的那条三分线上（§10.4 的 `lead_room` ＋ `rule_of_thirds`）。
    #: 2026-10-04 第一次开它是**净负**（构图分中位 64.7 → 55.8、25 镜降），
    #: 但那时的机位锚点还是"剧本起始站位"——主体本来就在画框边缘，再横移就出画
    #: （`docs/evidence/20261004-leadroom-finding/`）。锚点（§六十三）与走位接力
    #: （§六十四）落地后重测：见 `docs/evidence/20261004-leadroom-retest/`。
    #: v1.5 §4.6（卡 P3-T4）：求解器的默认偏移（单主体 = §10.4 视线留白；
    #: 双人 = 0）现在只是**缺省值**——计划的 ``shot.composition`` 声明可以覆盖它
    #: （`center`/`symmetry` 显式居中、`left_third`/`right_third` 指定主体落点）。
    #: 空声明时 :func:`aim_offset_for_composition` 原样返回这个缺省值 ⇒
    #: **与接线前逐字节一致**（G3 的空声明对照就是这条）。
    default_aim_offset = 0.0
    if not frame.has_axis:
        default_aim_offset = aim_offset_for_lead_room(direction, frame.facing)
    declared_composition = dict(getattr(shot, "composition", None) or {})
    aim_offset = aim_offset_for_composition(
        declared_composition, direction, frame.facing,
        default=default_aim_offset)
    #: 竖直方向：单主体镜头把对准点抬高 `HEAD_ROOM_AIM_M`（见那个常量的实测依据）。
    aim_offset_y = HEAD_ROOM_AIM_M if not frame.has_axis else 0.0
    bundle, solution = place_camera_for_shot(
        shot.shot_id, frame.anchor, facing=frame.facing,
        shot_type=str(shot.shot_type), side=side,
        lens=resolved.get("lens"), room=(spec.room if spec else None),
        direction=direction, aim_offset_x=aim_offset,
        aim_offset_y=aim_offset_y, reuse=reuse)
    if declared_composition:
        rule = str(declared_composition.get("rule") or "") or "—"
        position = str(declared_composition.get("subject_position") or "") or "—"
        axis_notes.append(
            f"按构图声明（rule={rule}、subject_position={position}）把对准点"
            f"横向偏移 {aim_offset:+.3f} 幅宽")
    elif aim_offset:
        axis_notes.append(
            f"按 §10.4 的视线留白把对准点横向偏移 {aim_offset:+.3f} 幅宽"
            f"（主体落到背向视线的那条三分线上）")
    solution.warnings.extend(axis_notes)
    return bundle, solution, frame


def release_shot_camera(shot_id: str) -> None:
    """彻底放掉某镜的相机**对象＋数据＋对准 Empty**。

    只删相机对象会留下两样东西：孤立的相机**数据**与对准 **Empty**。它们都占着
    `BD_Cam_<shot_id>` / `BD_CamTarget_<shot_id>` 这两个名字，于是下一次
    `create_camera` 只能拿到 `…​.001`——而按名字找对准点的地方
    （`_shot_target_object`、主构建的运镜段）拿到的还是**旧的那一只**。
    实测（`work/_tool_delta_probe.py`）：同一镜重设一次机位就留下
    `BD_Cam_shot_001.001` 与 `BD_CamTarget_shot_001.001`。
    """
    target = bpy.data.objects.get(f"BD_CamTarget_{shot_id}")
    if target is not None:
        bpy.data.objects.remove(target, do_unlink=True)
    camera = bpy.data.objects.get(f"BD_Cam_{shot_id}")
    if camera is not None:
        data = camera.data
        bpy.data.objects.remove(camera, do_unlink=True)
        if data is not None and getattr(data, "users", 0) == 0:
            bpy.data.cameras.remove(data)


def apply_declared_movements(shot: ShotPlan, characters: Dict[str, Any],
                             start: int, end: int, *, camera: Any = None,
                             target: Any = None
                             ) -> Tuple[int, int, List[str]]:
    """把这一镜**声明的**运镜落到它自己的相机上（§3.6 声明式消费）。

    主构建与 `setup_camera` 共用。理由与 `axis_for_shot` 同源：`setup_camera`
    会**重建相机对象**，不重放运镜就等于把这个镜头的运动静默删掉——而构图门取
    首/中/尾的**最小值**，运动一没，这个门的结论就跟着变（实测 `shot_055` 的
    `dolly_out` 消失后 92.0 → 89.6）。

    返回 ``(落地的段数, 关键帧数, 告警)``。

    ``camera``/``target`` **必须由调用方给**：`build_scene` 直到收尾才
    `set_context(context)`，所以构建期间 `get_context()` 拿到的是**上一次**
    的场景（新检出上干脆是 None）——本函数第一版就踩了这个坑，于是整场
    运镜被静默跳过（实测 `work/_kf_probe.py`：64 镜全部 0 关键帧）。
    没给时才回退到全局上下文，那条路只留给"场景已经建好、正在跑工具"的场合。
    """
    context = get_context()
    if camera is None:
        camera = (context.cameras.get(shot.shot_id)
                  if context is not None else None)
    warnings: List[str] = []
    if camera is None:
        return 0, 0, [f"{shot.shot_id}: 没有相机，运镜声明已跳过"]
    declared = [dict(item) for item in
                (getattr(shot, "camera", None) or {}).get("movements", [])
                if isinstance(item, dict)]
    if not declared:
        return 0, 0, []
    if target is None:
        target = bpy.data.objects.get(f"BD_CamTarget_{shot.shot_id}")
    default_subject = (speaker_of(shot)
                       or (shot.characters[0] if shot.characters else ""))
    applied = 0
    keyframes = 0
    for raw in declared:
        try:
            move = movement_spec(raw, shot_start=start, shot_end=end,
                                 default_subject=default_subject)
            curve = movement_curve(raw)
        except ValueError as exc:
            warnings.append(f"{shot.shot_id}: 运镜声明无效（{exc}），已跳过")
            continue
        subject = characters.get(str(move["subject"]))
        if move["type"] in SUBJECT_TRACKING and subject is None:
            warnings.append(f"{shot.shot_id}: {move['type']} 找不到被摄主体"
                            f"（{move['subject'] or '未指定'}），已跳过")
            continue
        try:
            report = apply_camera_movement(
                camera, target, str(move["type"]), float(move["amount"]),
                int(move["start_frame"]), int(move["end_frame"]),
                subject=subject, seed=int(move["seed"]),
                curve=curve)
        except ValueError as exc:
            warnings.append(f"{shot.shot_id}: {exc}")
            continue
        applied += 1
        keyframes += int(report["keyframes"])
        log.info("%s: 运镜 %s（%s 帧）", shot.shot_id, move["type"],
                 f"{move['start_frame']}-{move['end_frame']}")
    return applied, keyframes, warnings


def action_requests(shot: ShotPlan, shot_start: int,
                     cast: Dict[str, CastMember],
                     warnings: List[str],
                     live_from: Optional[Dict[str, Tuple[float, float, float]]] = None,
                     extent_m: Optional[float] = None
                     ) -> List[ActionRequest]:
    """把计划里的动作转成全局帧号的动作请求。

    ``live_from`` 给 ``walk_to``/``run_to`` 提供**缺省起点**：角色在**这一镜
    开始时实际站在哪**（读它的世界坐标），而不是剧本开始时的站位。实测
    （2026-10-04，`work/_walk_once_probe.py`）：`from` 缺省时运动模型把
    `target_position` 当成**相对位移**（`base + target`），于是一串缺省 `from`
    的行走会**累加**——`long9` 重建里伊恩从起始站位一路累到 (13.0, −12.6)。
    给了实时起点之后，每一次行走都是"从他现在的位置走到计划写的位置"。
    """
    requests: List[ActionRequest] = []
    #: G8-C：结构化目标（look_at.target / 道具 toward）折算用的是**本镜首帧**
    #: 各角色的场景位置：剧本站位被 `live_from`（走位接力）覆盖。
    positions: Dict[str, Tuple[float, float, float]] = {}
    for character_id, member in cast.items():
        location = list(getattr(member, "initial_location", None) or [])
        while len(location) < 3:
            location.append(0.0)
        positions[str(character_id)] = (float(location[0]), float(location[1]),
                                        float(location[2]))
    positions.update({str(key): tuple(value)
                      for key, value in (live_from or {}).items()})
    #: 计划动作里的 target 常用剧本角色名（如“伊恩”），而 cast 的
    #: 主键可能是 char_###。两者都指向同一空间位置，给目标解析保留
    #: name 别名，避免单镜重建路径因 id/name 不一致拒绝 look_at。
    for member in cast.values():
        member_id = str(getattr(member, "id", "") or "")
        member_name = str(getattr(member, "name", "") or "")
        if member_name and member_id in positions:
            positions.setdefault(member_name, positions[member_id])
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
        #: G8-C：把结构化目标折算成引擎参数（look_at → yaw/pitch，
        #: 道具 toward → 方向量）。解析不出 = 确定性错误：如实告警并跳过，
        #: 绝不静默取默认角。函数内 import：`beat_compiler` 是纯的，且
        #: `build_scene` 用的是同一条函数内 import 纪律。
        from ..layer5_orchestrator.beat_compiler import resolve_action_targets

        params, target_problems = resolve_action_targets(
            action_type, character_id, params, positions,
            tuple(getattr(cast[character_id], "initial_facing", None)
                  or (0.0, 1.0, 0.0)))
        if target_problems:
            warnings.append(
                f"{shot.shot_id}: {target_problems[0]}"
                f"（角色 {character_id}），已跳过（不替 LLM 猜目标）")
            continue
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
            #: 越界**如实告警**（`config.scene.extent_m`；计划提示里是同一条硬约束）。
            #: 不夹取：夹取会把"整场被带出场地"这件事藏起来。
            if extent_m and out_of_bounds(params["target_position"], extent_m):
                warnings.append(
                    f"{shot.shot_id}: {action_type} 的目的地 "
                    f"{list(params['target_position'])[:2]} 超出场景范围 "
                    f"±{float(extent_m):g} 米（config.scene.extent_m）；"
                    "目的地是**绝对位置**，请改到范围内")
            default_from = (live_from or {}).get(character_id)
            params.setdefault("from", default_from
                              or cast[character_id].initial_location)
        requests.append(ActionRequest(action_type=action_type,
                                      start_frame=start, end_frame=end,
                                      params=params, character_id=character_id,
                                      action_id=f"{shot.shot_id}_{index}"))
    return requests


def _prepare_static_scene(plan: Plan, spec: Optional[SceneSpec],
                          brief, crowd,
                          *, clear_scene: bool = False):
    """方案 B（§3.6.3）：建场景与元素，返回后续两趟所需的全部局部状态。

    ``build_scene`` 与 ``prepare_scene`` 共用这一段：清对象/集合 → 环境/
    锚点/灯光 → 角色/标签 → ``SceneContext``。**不含**动作烘焙、机位、
    镜头标记、运镜、标签烘焙——那些是动态预演阶段的事。

    返回 ``(summary, context, characters, cast_map, label_entries,
    environment)``；``build_scene`` 拿它继续排片/烘焙/摆机位，
    ``prepare_scene`` 拿它落基线后结束。
    """
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

    # v1.5 §3.2/§4.3：场级环境声明（anchors）在计划里，只在这里消费一次；
    # 锚点坐标由 `solve_anchor_positions` 求，解析不出的如实进审计。
    environment = build_environment(
        ground_size=spec.ground_size, walls=spec.walls, props=spec.props,
        lighting=spec.lighting,
        anchors=list((getattr(plan, "environment", None) or {}).get("anchors")
                     or []),
        cast=list(spec.cast),
        light=dict((getattr(plan, "environment", None) or {}).get("light")
                   or {}),
        #: v1.6 C2（FR-A1）：阶段 S 理解出的闭集环境件真正进管线；
        #: 闭集外取值由 build_environment 报 E_ENV_001，不在这里过滤。
        environment_items=[dict(item) for item in
                           (getattr(brief, "environment", None) or [])
                           if isinstance(item, dict)])
    summary.warnings.extend(environment.unresolved_anchors)
    summary.warnings.extend(environment.light_notes)

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
        if _skip_character(str(member.id), plan):
            cast_map[member.id] = member
            continue                       # 全出场镜 skip：不建主体、不进 characters
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
    return (summary, context, characters, cast_map, label_entries,
            environment)


@main_thread_only("prepare_scene")
def prepare_scene(plan: Plan, spec: Optional[SceneSpec] = None,
                  clear_scene: bool = False, brief=None,
                  crowd=None) -> BuildSummary:
    """方案 B：只建场景与元素，不摆相机、不烘焙动作（§3.6.3）。

    ``clear_scene`` / ``brief`` / ``crowd`` 语义与 ``build_scene`` 相同；
    返回摘要里的 ``cameras=0``，逐镜相机由 ``rebuild_shot`` 落地。
    """
    spec = spec or SceneSpec.from_plan(plan, brief=brief, crowd=crowd)
    summary, context, _characters, _cast_map, _label_entries, _env = (
        _prepare_static_scene(plan, spec, brief, crowd, clear_scene=clear_scene))
    scene = bpy.context.scene
    scene.frame_set(1)
    set_context(context)
    from .scene_sync import note_build
    note_build()
    from .world_state import refresh_world_state
    refresh_world_state(get_context())
    summary.shots = len(plan.shots)
    summary.total_frames = scene.frame_end
    log.info("场景元素就位：%d 镜 / %d 角色 / %d 环境件（未摆机位）",
             summary.shots, summary.characters, len(_env.props))
    return summary


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
    (summary, context, characters, cast_map, label_entries, environment) = (
        _prepare_static_scene(plan, spec, brief, crowd,
                              clear_scene=clear_scene))
    scene = bpy.context.scene
    from ..settings import get_config
    app_config = get_config()
    label_config = app_config.character

    ranges = shot_ranges(plan)
    motion_requests: Dict[str, List[ActionRequest]] = {}
    movement_tasks: List[Tuple[str, int, int]] = []
    #: 第一趟只**排片**（帧区间、动作请求、运镜任务），不摆机位：机位必须等动作
    #: 烘焙完之后再按"这一镜首帧人在哪"来摆（v1.6，见 `live_subject_entries`）。
    planned: Dict[str, Dict[str, Any]] = {}
    #: 每一镜开始时各角色站在哪（把计划的行走终点接力起来）——`walk_to` 的缺省
    #: 起点用它，而不是剧本的起始站位（否则一串缺省 `from` 的行走会累加，见
    #: `cinema/schedule.travelled_positions` 的说明）。
    place_before_shot = travelled_positions(
        plan, {character_id: member.initial_location
               for character_id, member in cast_map.items()})
    #: v1.5 §4.1/§4.2（P3-T1 的生产消费者）：**拍点表 → actions**。
    #: 为什么接在这里而不是更早：编译 `beats[].target` 需要**已解算的锚点坐标**，
    #: 而锚点是在上面的 `build_environment` 里解的；`walk_to` 的缺省起点又要
    #: "这一镜开始时人在哪"（`place_before_shot`）。所以编译必须在**构建期**、
    #: 拿到这两样之后做一次，结果直接喂给既有的 `action_requests`——
    #: 下游 builder/auditor/R003 **零改动**。
    #: 用函数内 import：`beat_compiler` 是纯的（只依赖 contracts/motion/cinema），
    #: 但它住在 `layer5_orchestrator` 下，函数内 import 可保证不引入任何包级环。
    from ..layer5_orchestrator.beat_compiler import (  # noqa: PLC0415
        compile_beats, merge_with_actions)
    anchor_positions = {str(getattr(obj, "name", "")).removeprefix("BD_Anchor_"):
                        tuple(float(v) for v in obj.location)
                        for obj in environment.anchors}
    for shot in plan.shots:
        start, end = ranges[shot.shot_id]
        context.schedule[shot.shot_id] = (start, end)
        planned_warnings: List[str] = []
        live_from = place_before_shot.get(shot.shot_id)
        actions_source = shot
        #: 只有真的写了拍点才编译——**空 beats 路径逐字节零行为差**。
        if getattr(shot, "beats", None):
            compiled, beat_problems = compile_beats(
                shot, anchor_positions, cast_map,
                current_positions=live_from)
            planned_warnings.extend(beat_problems)
            actions_source = replace(
                shot, actions=merge_with_actions(compiled, shot.actions))
        requests = action_requests(
            actions_source, start, cast_map, planned_warnings,
            live_from=live_from,
            extent_m=float(getattr(app_config.scene, "extent_m", 0.0) or 0.0))
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
            #: 只登记"这一镜要放运镜"；具体怎么放由 `apply_declared_movements`
            #: 统一负责（与 `setup_camera` 共用），这里不再复制一份参数。
            movement_tasks.append((shot.shot_id, start, end))
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
    #:
    #: **顺序的状态机**（§七十三）：摆完一镜的机位，就量一次"这一镜的连线有没有
    #: 扫过这台机位"——扫过且两人同框，观众就是**看见**了换位，之后的镜头换到另一侧。
    #: 为什么要顺序（而不是像以前那样先算一张计划期的表）："换位看不看得见"的定义里
    #: 有机位，而机位正是这里摆出来的；先摆再量，**一次走完就自洽**，不需要迭代
    #: （会诊警告的固定点不收敛问题因此不存在）。
    live_side: Optional[int] = None
    spans: Dict[str, Any] = {}
    for shot in plan.shots:
        info = planned[shot.shot_id]
        start, end = int(info["start"]), int(info["end"])
        scene.frame_set(start)
        bpy.context.view_layer.update()

        # 阶段 B1 可以给这一镜一个"相对取景请求"（§16.1 的 CameraRequest）：
        # side 与 lens 由取景解算器消费；距离/高度仍按 §10.6/§10.5 推导。
        # v1.3：side 经 cinema.station 解析——双人镜头相对两人连线，
        # 而不是相对焦点主体的朝向（否则机位会落在轴线上）。
        #: 轴线**跟着走位走**（GLM 5.3 会诊 A3）：线取两人此刻的连线，侧别由
        #: `axis_state` 这份纯函数给出（继承，只在**看得见的换位**处翻转）。
        #: 规则侧另有一条独立内容（"规范首镜线 vs 当前派生线"的偏差），
        #: 所以两边共用状态不等于自证。
        placed_axis = _axis_for_placement(context, plan, cast_map, characters, shot,
                                          live_side=live_side)
        bundle, solution, frame = place_shot_camera(shot, cast_map, spec,
                                                    axis=placed_axis,
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
                #: 轴线刚确立 ⇒ 顺序状态机从**它自己**的基准侧起步。
                #: （实测教训：不初始化的话，第一次测到"扫过机位"之前会继续用计划期
                #: 近似表，而那张表在 `long9` 的第 27 镜多翻了一次——两次翻转互相抵消，
                #: 看着"没差别"，实际把 27–34 镜摆在了观众没看见过的另一侧。）
                if live_side is None:
                    live_side = int(context.axis.established_side)

        #: 摆完了 ⇒ 量"这一镜的连线扫没扫过这台机位"（判定后续镜头待在哪一侧）。
        #: 同一处把这**三个原生值**落下来（P14-313 轴族裁决）：有序 pair ＋ 叉积符号 ＋ 状态。
        axis_pair: List[str] = []
        axis_side_sign = 0
        axis_status_value = ""
        if context.axis is not None:
            axis_pair = [str(context.axis.left_label), str(context.axis.right_label)]
            camera_xy = (round(bundle.camera.matrix_world.translation.x, 4),
                         round(bundle.camera.matrix_world.translation.y, 4))
            axis_status_value = str(axis_status(context.axis, camera_xy))
            if not spans:
                spans = pair_spans(context.axis, plan,
                                   _initial_cast_positions(context))
            span = spans.get(str(shot.shot_id))
            if span is not None:
                camera_position = bundle.camera.matrix_world.translation
                before_side = camera_side_of(span[0], span[1], camera_position)
                after_side = camera_side_of(span[2], span[3], camera_position)
                #: 这一条就是"相对**有序 pair** 的叉积符号"——原样记，不做左右翻译。
                axis_side_sign = int(before_side)
                both_in_frame = len(
                    [cid for cid in (shot.characters or [])
                     if str(cid) in (context.axis.left_label,
                                     context.axis.right_label)]) >= 2
                if (both_in_frame and before_side != 0 and after_side != 0
                        and before_side != after_side):
                    current_side = (int(placed_axis.established_side)
                                    if placed_axis is not None
                                    else int(context.axis.established_side))
                    live_side = -current_side
                    shot_warnings.append(
                        f"{shot.shot_id}: 连线扫过机位 ⇒ 观众看得见这次换位，"
                        f"从下一镜起改到第 {live_side:+d} 侧")

        shot_warnings = list(solution.warnings) + list(info["warnings"])
        requests = info["requests"]

        # v1.5 §4.4：道具交互动词 → 道具对象的跟随关键帧（没被点名的道具不打）。
        # 放在动作烘焙之后：手部代理是 BodyPivot 的子级，烘焙也不会覆盖约束。
        shot_warnings.extend(apply_prop_interactions(
            shot, start, characters, environment.props))

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
            warnings=shot_warnings,
            axis_pair=axis_pair, axis_side_sign=axis_side_sign,
            axis_status=axis_status_value))
        summary.cameras += 1
        summary.warnings.extend(shot_warnings)

    for shot_id, start, end in movement_tasks:
        #: 落地逻辑与 `setup_camera` **共用一份**（`apply_declared_movements`）：
        #: 两处各写一遍，工具侧重设机位时就会把这镜的运动静默丢掉（见该函数抬头）。
        shot = next((item for item in plan.shots if item.shot_id == shot_id), None)
        if shot is None:
            continue
        applied, keyframes, warnings = apply_declared_movements(
            shot, characters, start, end,
            camera=context.cameras.get(shot_id),
            target=bpy.data.objects.get(f"BD_CamTarget_{shot_id}"))
        summary.movements += applied
        summary.keyframes += keyframes
        summary.warnings.extend(warnings)

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
            resolution=app_config.delivery.resolution,
            adaptive_sampling=bool(app_config.labels.adaptive_sampling),
            fullframe_verify=bool(app_config.labels.fullframe_verify),
            subjects={str(item.shot_id): list(item.characters or ())
                      for item in plan.shots})
        summary.label_report = label_report
        for item in label_report.get("unreadable", [])[:5]:
            summary.warnings.append(
                f"{item['character_id']} 在第 {item['frame']} 帧的标签低于"
                f"可读下限（{label_config.label_min_pixels:g}px）")
        # v1.6 A7（D-19）：全帧自检的余量进构建摘要告警，不静默。
        overlap_report = label_report.get("label_overlap_report") or {}
        overlap_frames = list(overlap_report.get("overlap_frames") or [])
        if overlap_frames:
            shown = ", ".join(str(frame) for frame in overlap_frames[:5])
            if len(overlap_frames) > 5:
                shown += " …"
            summary.warnings.append(
                f"标签全帧自检：{len(overlap_frames)} 帧交叠仍超 "
                f"{float(overlap_report.get('limit') or 0.05):g}"
                f"（最高 {float(overlap_report.get('max_overlap_ratio') or 0):.1%}，"
                f"帧 {shown}）")

    scene.frame_set(1)
    set_context(context)
    # §8.3：把这次插件写入记为基线，之后才分得清"哪些是用户改的"。
    from .scene_sync import note_build
    note_build()
    from .world_state import refresh_world_state
    refresh_world_state(get_context())
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
        self._coarse_cameras: Dict[str, Dict[str, Any]] = {}
        self._coarse_baseline_attached = False

    def attach_coarse_baseline(self, baseline: Dict[str, Any]) -> int:
        """Store the coarse gate's frozen, already-approved shot cameras."""
        if str(baseline.get("state") or "") != "frozen":
            raise ValueError("只能接入 state=frozen 的粗排基准")
        manifest = baseline.get("manifest")
        if not isinstance(manifest, dict):
            raise ValueError("粗排基准缺少 manifest")
        cameras: Dict[str, Dict[str, Any]] = {}
        for raw in manifest.get("cameras") or []:
            if not isinstance(raw, dict):
                raise ValueError("粗排 manifest.cameras 含非对象条目")
            if raw.get("resolved") is not True:
                continue
            shot_id = str(raw.get("shot_id") or "")
            if not shot_id:
                raise ValueError("粗排相机缺少 shot_id")
            if shot_id in cameras:
                raise ValueError(f"粗排相机 shot_id 重复：{shot_id}")
            cameras[shot_id] = dict(raw)
        self._coarse_cameras = cameras
        self._coarse_baseline_attached = True
        return len(cameras)

    def build(self, plan: Plan, brief=None) -> Dict[str, Any]:
        return build_scene(plan, self.spec, clear_scene=self.clear_scene,
                           brief=brief, crowd=self.crowd).to_dict()

    def prepare_scene(self, plan: Plan, brief=None, spec=None) -> Dict[str, Any]:
        """方案 B：只建场景与元素（§3.6.3），不摆相机/不烘焙动作。"""
        return prepare_scene(plan, spec or self.spec,
                             clear_scene=self.clear_scene,
                             brief=brief, crowd=self.crowd).to_dict()

    def rebuild_shot(self, shot_id: str, *, plan: Optional[Plan] = None,
                     brief=None,
                     preserve_camera_edits: bool = False) -> Dict[str, Any]:
        """方案 B：只重建/预演当前镜（增量，不推倒环境/角色/其他镜）。"""
        from .scene_sync import get_synchronizer
        from .shot_regenerator import ShotRegenError, regenerate_shot

        approved = None
        if self._coarse_baseline_attached:
            approved = self._coarse_cameras.get(str(shot_id))
            if approved is None:
                raise ShotRegenError(
                    f"{shot_id} 不在已冻结的粗排相机基准内；"
                    f"禁止静默重解详细机位")

        #: 与 UI 的"重生成此镜"同一条口径：先 ``sync_from_blender`` 回读
        #: 工具/用户改动（挪过的角色、改过的相机），再按计划重建当前镜——
        #: 否则修复回路里模型刚调好的机位/走位会被计划旧坐标覆盖
        #: （§8.3 的 DoD："手动修改被保留"）。
        return regenerate_shot(shot_id, plan=plan, spec=self.spec,
                               sync=get_synchronizer(),
                               preserve_camera_edits=preserve_camera_edits,
                               approved_camera=approved)
