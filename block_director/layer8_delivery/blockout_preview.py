"""Ticket 04：Blockout 低采样 16:9 预览渲染 + 数值/视觉自检（bpy 侧）。

对 Ticket 03 建好的体块场景，按 manifest 每镜渲染首/中/末三帧低采样 16:9
PNG（分辨率与画幅确定性），并采集数值证据（构图分/可见比例/画面占比/出入画/
设计 vs 实测偏差），经 ``cinema.blockout_report`` 折成版本化自检报告。
渲染帧同时作为执行 AI 视觉检查的输入——数据合法不等于视觉有效。

确定性：同一 manifest + 同一场景两次渲染设置逐位一致；报告两次构建逐位一致。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

from ..cinema.blockout_report import (
    ON_SCREEN_MIN,
    VISIBLE_RATIO_MIN,
    build_blockout_report,
    plan_shot_dicts,
)
from ..cinema.blockout_sequence import (
    blockout_isolation_primitive_ids,
    blockout_occluder_candidate_names,
)
from ..cinema.coarse_revision import resolve_prop_ref
from ..cinema.anchor import (
    DEFAULT_PROFILE as COARSE_PROFILE,
    coarse_local_bounds,
    facing_for_shot,
    hand_offset,
)
from ..cinema.framing import SHOT_FRAME
from ..cinema.composition import (
    SubjectBox,
    composition_passed,
    evaluate_composition,
)
from ..contracts.blockout import manifest_fingerprint
from ..utils.logger import get_logger
from ..utils.threading_guard import main_thread_only

log = get_logger("blockout-preview")

#: 预览分辨率：16:9 低采样（粗排只用低精度视觉自检，不做成片质量）。
PREVIEW_WIDTH = 1280
PREVIEW_HEIGHT = 720

#: 低采样帧数（EEVEE 抗锯齿采样；attr 存在才写，缺省由引擎默认）。
EEVEE_SAMPLES = 8

#: 遮挡射线采样点数（与 frustum_sampler 的 N=9 同口径）。
VISIBLE_POINTS = 9

#: 多步投递上限 / 命中距离容差（与 frustum_sampler / composition_guide 同源）。
MAX_RAY_STEPS = 8
RAY_TOLERANCE_M = 0.05

#: 体块朝机面采样的行（相对体块尺寸）。z 行避开脚底行 z=low.z 与地面共面；
#: 自由轴行收进面内 0.2/0.5/0.8，避免低机位斜射时采样点卡在棱上、
#: 首交点落在前表面而被自己“挡掉”（frustum_sampler 对真实角色取的是
#: 圆柱/头球表面凸点，不会出现棱点自遮挡）。
BODY_Z_FRACTIONS = (0.4, 0.7, 1.0)
FACE_FREE_FRACTIONS = (0.2, 0.5, 0.8)


def _subject_blocks(manifest: Mapping[str, Any]) -> Dict[str, str]:
    """manifest 主体体块 id -> 对象名（投影/遮挡判定用）。

    角色与道具都是合法拍对象（framing_target.kind=prop 的道具特写镜，
    ``shot_table[].prop_ids`` 已登记道具 id）——只收角色会把道具特写镜
    的可见性/空墙/面积判据全部带偏（实测 shot_002 银币特写被报空墙）。
    """
    blocks: Dict[str, str] = {}
    for primitive in manifest.get("primitives") or []:
        source = primitive.get("source") or {}
        if primitive.get("kind") in {"character", "prop"} \
                and source.get("id"):
            blocks[str(source["id"])] = f"BD_Blockout_{primitive['id']}"
    return blocks


def _character_staging_row(
    primitive: Mapping[str, Any],
    shot_id: str,
) -> Optional[Mapping[str, Any]]:
    return next(
        (
            row for row in (primitive.get("shot_positions") or [])
            if isinstance(row, Mapping)
            and str(row.get("shot_id") or "") == str(shot_id)
        ),
        None,
    )


def _apply_character_staging(
    manifest: Mapping[str, Any],
    shot_id: str,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Apply this shot's local character positions and return restore state.

    Character primitives are foot-anchored, so the object's origin is the
    requested ground position plus half the block height.  The caller owns the
    returned state and must restore it in ``finally``.
    """
    previous: Dict[str, Any] = {}
    audit: Dict[str, Any] = {}
    try:
        for primitive in manifest.get("primitives") or []:
            if not isinstance(primitive, Mapping) \
                    or primitive.get("kind") != "character":
                continue
            row = _character_staging_row(primitive, shot_id)
            if row is None:
                continue
            primitive_id = str(primitive.get("id") or "")
            obj = bpy.data.objects.get(f"BD_Blockout_{primitive_id}")
            if obj is None:
                continue
            position = row.get("position") or {}
            size = primitive.get("size") or {}
            dims_z = float(size.get("z") or 0.0)
            foot_z = float(position.get("z") or 0.0)
            origin = Vector((
                float(position.get("x") or 0.0),
                float(position.get("y") or 0.0),
                foot_z + (dims_z / 2.0
                          if primitive.get("z_anchor") == "foot" else 0.0),
            ))
            previous[obj.name] = tuple(obj.location)
            obj.location = origin
            source = primitive.get("source") or {}
            audit[str(source.get("id") or primitive_id)] = {
                "planned_position": copy.deepcopy(dict(position)),
                "actual_origin": [round(float(v), 6) for v in origin],
                "provenance": str(row.get("provenance") or ""),
                "reason": str(row.get("reason") or ""),
            }
    except Exception:
        _restore_character_staging(previous)
        raise
    if previous:
        bpy.context.view_layer.update()
    return previous, audit


def _restore_character_staging(previous: Mapping[str, Any]) -> None:
    for name, location in previous.items():
        obj = bpy.data.objects.get(str(name))
        if obj is not None:
            obj.location = location
    if previous:
        bpy.context.view_layer.update()


def _target_block_name(manifest: Mapping[str, Any], kind: str,
                       ref: str) -> Optional[str]:
    """拍对象（角色/道具）体块对象名；找不到返回 None（不猜）。

    角色按 ``source.id`` 精确匹配（角色名与计划引用同源，无别名问题）；
    道具先精确、再走与粗排处方同一口径的 ``resolve_prop_ref``（支持
    ``ref=银币`` 命中 ``prop_银币-金子`` 这类"一个道具两状态"的复合 id，
    多候选/无候选仍 None——判据与处方共用一个解析，修了才能判对）。
    """
    for primitive in manifest.get("primitives") or []:
        source = primitive.get("source") or {}
        if primitive.get("kind") == kind and str(source.get("id") or "") == str(ref):
            return f"BD_Blockout_{primitive['id']}"
    if kind != "prop":
        return None
    #: 道具：把 primitive 的 source.id 与 id（去 ``prop_`` 前缀）都作为候选
    #: id，交给 ``resolve_prop_ref`` 做确定性别名解析（与处方同一口径）。
    prop_ids: List[str] = []
    for primitive in manifest.get("primitives") or []:
        if primitive.get("kind") != "prop":
            continue
        source = primitive.get("source") or {}
        pid = str(source.get("id") or "")
        if pid:
            prop_ids.append(pid)
        raw_id = str(primitive.get("id") or "")
        if raw_id.startswith("prop_"):
            prop_ids.append(raw_id[len("prop_"):])
    resolved = resolve_prop_ref(str(ref or ""), prop_ids)
    if resolved is None:
        return None
    #: 反查命中体块的对象名（优先 source.id 精确命中，其次 id 去前缀命中）
    for primitive in manifest.get("primitives") or []:
        if primitive.get("kind") != "prop":
            continue
        source = primitive.get("source") or {}
        raw_id = str(primitive.get("id") or "")
        stripped = raw_id[len("prop_"):] if raw_id.startswith("prop_") else raw_id
        if str(source.get("id") or "") == resolved or stripped == resolved:
            return f"BD_Blockout_{primitive['id']}"
    return None


def _shot_isolation_objects(
    manifest: Mapping[str, Any],
    shot_table_row: Mapping[str, Any],
) -> List[bpy.types.Object]:
    """返回本镜外的角色/道具体块，供预演取景时临时隐藏。

    粗排验证的是本镜声明的 staging。其它镜头的角色/道具仍留在同一
    blockout 场景里会成为真实遮挡体：final7 的 shot_003 中，米迦尔（上一镜
    角色）挡住伊恩，导致 ``E_BLOCKOUT_EMPTY_WALL``/``E_FOREGROUND_OCCLUSION``
    重复出现，处方只改相机距离而永远消不掉。锚点、环境体块不在这里隐藏，
    因为它们属于场景连续性；只隔离不会出现在本镜的角色/道具。

    隔离集合由纯层 ``blockout_isolation_primitive_ids`` 决定（可单测）；
    这里只做 primitive id -> 对象名的 bpy 解析。
    """
    hidden: List[bpy.types.Object] = []
    for primitive_id in blockout_isolation_primitive_ids(
            manifest, shot_table_row):
        obj = bpy.data.objects.get(f"BD_Blockout_{primitive_id}")
        if obj is not None:
            hidden.append(obj)
    return hidden


def _block_object(node_name: Optional[str]) -> Optional[bpy.types.Object]:
    """按对象名取体块；``None``/空名是"目标体块未解析"的合法状态，返回 None。

    Blender 5.2 的 ``bpy.data.objects.get(None)`` 不返回 None 而是抛
    ``KeyError``——把未解析状态当异常会中断整个粗排门，而不是保留
    unresolved 证据交给报告层阻塞。
    """
    if not node_name:
        return None
    return bpy.data.objects.get(node_name)


def _project_box(scene, camera, block) -> Optional[SubjectBox]:
    """把体块 8 个角投影成 NDC 包围盒（与 frustum_sampler 同法）。"""
    bounds = block.bound_box
    if not bounds:
        return None
    xs: List[float] = []
    ys: List[float] = []
    for corner in bounds:
        world = block.matrix_world @ Vector(corner)
        projected = world_to_camera_view(scene, camera, world)
        if float(projected.z) < 0.0:
            #: 相机背后的角点投影会镜像 x/y（与 frustum_sampler 的
            #: behind_camera 同口径）：跳过，避免包围盒被镜像角点拉满。
            continue
        xs.append(float(projected.x))
        ys.append(float(projected.y))
    if not xs:
        return None
    box = SubjectBox(
        name=str(block.name), left=min(xs), right=max(xs),
        top=max(ys), bottom=min(ys))
    return box


def _project_bounds(low: Vector, high: Vector, name: str,
                    scene, camera) -> SubjectBox:
    """世界 AABB 8 角 -> NDC SubjectBox（composition_guide._project_bounds 同法）。"""
    xs: List[float] = []
    ys: List[float] = []
    for ix in (low.x, high.x):
        for iy in (low.y, high.y):
            for iz in (low.z, high.z):
                projected = world_to_camera_view(scene, camera,
                                                 Vector((ix, iy, iz)))
                xs.append(float(projected.x))
                ys.append(float(projected.y))
    return SubjectBox(name=name, left=min(xs), right=max(xs),
                      top=max(ys), bottom=min(ys))


def _clip_to_window(low: Vector, high: Vector,
                    window: Optional[Tuple[float, float]],
                    ) -> Tuple[Vector, Vector, bool]:
    """把世界 AABB 按景别高度窗口裁一刀（composition_guide 同语义）。

    细排 ``_screen_box`` 用 ``intended_window(shot_type)`` 把整身框裁成
    "这个景别该看到的那一段"；粗排 preview 必须用同一把尺子，否则特写镜的
    整身框被投影成"头顶被切、重心偏塌"的低分（实测 55–58）。返回
    ``(low, high, clipped_top)``：窗口外完全无交叠时退回原盒（不裁死）。
    """
    if window is None:
        return low, high, False
    win_low, win_high = window
    sliced_low = max(float(low.z), win_low)
    sliced_high = min(float(high.z), win_high)
    if sliced_high <= sliced_low:
        return low, high, False
    return (Vector((low.x, low.y, sliced_low)),
            Vector((high.x, high.y, sliced_high)),
            float(high.z) > win_high)


def _coarse_local_geometry(
    target_declared: Mapping[str, Any],
    subject_blocks: Mapping[str, str],
    reference_chars: Mapping[str, Mapping],
    scene,
    camera_obj,
    shot_id: str = "",
    target_block_name: Optional[str] = None,
) -> Optional[Tuple[Vector, Vector, str, float, bpy.types.Object]]:
    """构造粗排局部主体世界框与对象（hand/face/prop）。

    blockout 场景只有纯体块（无 parts/body_pivot），但剧本声明
    ``framing_target=character/part=hand|face`` 或 ``kind=prop`` 时，特写镜
    的构图尺子应当是**被摄局部**而不是整身——与细排/ruler 的
    ``_local_subject_box`` 同语义（裁决 D1=A：锚点＋预设偏移，来源 anchored）。
    几何推导走 ``cinema.anchor.coarse_local_bounds``——同一份冻结 profile、
    ``hand_offset`` 与手部测量窗，只是把"网格锚点"换成"体块 AABB + facing"；
    细排侧 ``composition_guide`` 也以同一份 ``anchor`` 为单一真源，两把尺子
    因此同源。

    * kind=prop：道具体块 AABB 直接作主锚（道具即被摄对象）；
    * part=face：头球立方（anchor.profile 冻结几何推导）；
    * part=hand：手部代理立方（``anchor.hand_offset``，相对角色体块中心）。
    返回 ``(low, high, label, screen_facing, block)``；缺体块/缺声明返回
    ``None``（退回旧整身评分，不脑补）。
    """
    kind = str(target_declared.get("kind") or "character")
    ref = str(target_declared.get("ref") or "")
    part = str(target_declared.get("part") or "none")
    #: 道具 ref 与场景 id 可能不是逐字一致（final12：ref=银币、
    #: id=银币-金子）。调用方先用 ``_target_block_name`` 做确定性别名
    #: 解析，再把命中对象名传进来；局部主锚必须与 framing_target 判据
    #: 使用同一体块，不能在这里退回整身评分。
    block_name = target_block_name or subject_blocks.get(ref)
    if not block_name:
        return None
    block = _block_object(block_name)
    if block is None:
        return None
    low, high = _world_bounds(block)
    if low is None:
        return None
    char = reference_chars.get(ref) or {}
    #: A camera may be solved for a turn declared only in this shot.  Reading
    #: the scene-wide ``facing`` here made the hand proxy land at the old
    #: heading while the camera targeted the new one (final16 shot_001).
    facing = list(facing_for_shot(char, shot_id))
    #: 屏幕空间朝向（lead_room 用）：与细排 ``composition_guide._screen_facing``
    #: 同语义——把角色世界朝向投影到相机屏幕空间，正对/背对镜头时判 0
    #: （无水平视线留白语义）。粗排体块没有 rotation，facing 来自参考 JSON
    #: （design 层默认 +Y 或剧本 gaze 推导）。
    screen_facing = _screen_facing_from_world(
        facing, camera_obj, scene)
    bounds = coarse_local_bounds(
        kind=kind, part=part, low=low, high=high,
        facing=facing, profile=COARSE_PROFILE)
    if bounds is None:
        return None
    label = f"{ref}:{part}" if part not in {"", "none"} else f"{ref}:prop"
    return Vector(bounds[0]), Vector(bounds[1]), label, screen_facing, block


def _coarse_local_primary(
    target_declared: Mapping[str, Any],
    subject_blocks: Mapping[str, str],
    reference_chars: Mapping[str, Mapping],
    scene,
    camera_obj,
    shot_id: str = "",
    target_block_name: Optional[str] = None,
) -> Optional[SubjectBox]:
    """把粗排局部主体世界框投成构图主锚。"""
    geometry = _coarse_local_geometry(
        target_declared, subject_blocks, reference_chars, scene, camera_obj,
        shot_id, target_block_name)
    if geometry is None:
        return None
    low_b, high_b, label, screen_facing, _block = geometry
    box = _project_bounds(low_b, high_b, label, scene, camera_obj)
    box.facing = screen_facing
    return box


def _screen_facing_from_world(facing: Sequence[float],
                              camera_obj, scene) -> float:
    """世界朝向 -> 屏幕水平朝向符号（+1 朝右，-1 朝左，0 无方向）。

    与细排 ``composition_guide._screen_facing`` 同口径：把世界朝向投影到
    相机的屏幕右侧向量；深度分量（正对/背对）超过水平分量 1.5 倍时判 0。
    粗排体块只有位置+facing（无 root 旋转矩阵），所以从参考 JSON 的 facing
    直接算，而不是从 Blender 对象回读。
    """
    fx, fy = float(facing[0]), float(facing[1])
    norm = (fx * fx + fy * fy) ** 0.5
    if norm < 1e-9:
        return 0.0
    fx, fy = fx / norm, fy / norm
    basis = camera_obj.matrix_world.to_3x3()
    screen_right = (basis @ Vector((1.0, 0.0, 0.0))).normalized()
    view_forward = (basis @ Vector((0.0, 0.0, -1.0))).normalized()
    horizontal = fx * screen_right.x + fy * screen_right.y
    depth = fx * view_forward.x + fy * view_forward.y
    if abs(depth) > abs(horizontal) * 1.5:
        return 0.0
    if abs(horizontal) < 1e-6:
        return 0.0
    return 1.0 if horizontal > 0 else -1.0


def _world_bounds(block) -> Optional[Tuple[Vector, Vector]]:
    """体块世界空间 AABB ``(low, high)``；空盒返回 ``None``。"""
    bounds = block.bound_box
    if not bounds:
        return None
    corners = [block.matrix_world @ Vector(corner) for corner in bounds]
    low = Vector((
        min(c[0] for c in corners),
        min(c[1] for c in corners),
        min(c[2] for c in corners)))
    high = Vector((
        max(c[0] for c in corners),
        max(c[1] for c in corners),
        max(c[2] for c in corners)))
    return low, high


def _row_fraction(index: int, is_z: bool) -> float:
    """自由轴采样行：z 轴用躯干/头部高度行，其余收进面内避开棱点。"""
    if not is_z:
        return FACE_FREE_FRACTIONS[index]
    return BODY_Z_FRACTIONS[index]


def _body_face_points(low: Vector, high: Vector,
                      camera_pos: Vector) -> List[Vector]:
    """体块朝机面 3×3（N=9）表面采样点（世界坐标）。

    与 ``frustum_sampler._face_grid_points`` 同选面逻辑：取
    ``(camera - face_center)·外法线`` 最大的轴对齐面；但 z 行不跨到
    脚底（``low.z`` 与地面共面会被地面 ray 吃掉），改用躯干/头部高度
    行（0.4/0.7/1.0 倍高），避免贴地误伤——与 frustum_sampler 对真实
    角色采“躯干+头”表面点的意图一致。
    """
    center = (low + high) * 0.5
    half = (high - low) * 0.5
    best: Optional[Tuple[float, int, int]] = None
    for axis in range(3):
        for sign in (1, -1):
            face_center = center.copy()
            face_center[axis] += sign * half[axis]
            normal = Vector((0.0, 0.0, 0.0))
            normal[axis] = float(sign)
            score = (camera_pos - face_center).dot(normal)
            if best is None or score > best[0]:
                best = (score, axis, sign)
    assert best is not None
    _score, axis, sign = best
    fixed = low[axis] if sign < 0 else high[axis]
    others = [index for index in range(3) if index != axis]
    points: List[Vector] = []
    for fu in range(3):
        for fv in range(3):
            point = [0.0, 0.0, 0.0]
            point[axis] = fixed
            point[others[0]] = (
                low[others[0]]
                + _row_fraction(fu, others[0] == 2)
                * (high[others[0]] - low[others[0]]))
            point[others[1]] = (
                low[others[1]]
                + _row_fraction(fv, others[1] == 2)
                * (high[others[1]] - low[others[1]]))
            points.append(Vector(point))
    return points


def _is_auxiliary(obj) -> bool:
    """射线首命中对象是否为“不参与遮挡判定”的辅助物。

    与 ``frustum_sampler`` 的 ``hide_render / _in_guides`` 同语义：地面、
    灯光、相机、目标 Empty（非 mesh 本就不会命中）以及 ``hide_render``
    的对象一律跳过，不当作前景遮挡。默认启动残留 Cube 已被
    ``build_blockout_scene`` 清掉，这里只作防御兜底。
    """
    if obj is None:
        return True
    if obj.hide_render:
        return True
    if obj.type != "MESH":
        return True
    name = str(obj.name or "")
    return name in {"BD_Blockout_Ground", "BD_ENV_Ground", "Cube"}


def _visible_fraction(scene, camera_pos: Vector, block,
                      depsgraph) -> float:
    """朝机面 3×3 采样点从相机到体块的遮挡判定（多步投递，命中自身才计可见）。"""
    bounds = _world_bounds(block)
    if bounds is None:
        return 0.0
    low, high = bounds
    points = _body_face_points(low, high, camera_pos)
    visible = 0
    for point in points:
        direction = point - camera_pos
        distance = direction.length
        if distance < 1e-6:
            continue
        unit = direction / distance
        travelled = 0.0
        hit_self = False
        for _step in range(MAX_RAY_STEPS):
            origin = camera_pos + unit * travelled
            remaining = distance - travelled + RAY_TOLERANCE_M
            hit, location, _normal, _index, obj, _matrix = scene.ray_cast(
                depsgraph, origin, unit, distance=max(remaining, 1e-4))
            if not hit or obj is None:
                break
            hit_distance = (location - camera_pos).length
            if obj.name == block.name:
                #: 命中主体：首交点必须落在采样点附近才计可见（与
                #: frustum_sampler 的 |hit - target| <= 0.05 同口径）。
                if abs(hit_distance - distance) <= RAY_TOLERANCE_M:
                    hit_self = True
                break
            if _is_auxiliary(obj):
                travelled = hit_distance + 1e-3
                if travelled >= distance + RAY_TOLERANCE_M:
                    break
                continue
            #: 被非辅助物体（其它体块/残留物）挡住：该采样点不可见。
            break
        if hit_self:
            visible += 1
    return float(visible) / float(VISIBLE_POINTS)


def _visible_fraction_bounds(
    scene,
    camera_pos: Vector,
    low: Vector,
    high: Vector,
    target_block,
    depsgraph,
) -> float:
    """局部主体世界框的真实射线可见比例（3×3 同口径）。

    角色手/脸在 blockout 场景里只有代理框，没有独立网格：射线对局部框
    “无命中”代表视线到达代理框；若先命中目标角色的整身块、且命中点明显
    在代理框之前，则目标自身身体仍可能遮挡局部，不算可见。其它非辅助
    网格先命中即遮挡。这样不会用整身块可见比冒充局部主体可见性。
    """
    points = _body_face_points(low, high, camera_pos)
    visible = 0
    for point in points:
        direction = point - camera_pos
        distance = direction.length
        if distance < 1e-6:
            continue
        unit = direction / distance
        travelled = 0.0
        point_visible = False
        for _step in range(MAX_RAY_STEPS):
            origin = camera_pos + unit * travelled
            remaining = distance - travelled + RAY_TOLERANCE_M
            hit, location, _normal, _index, obj, _matrix = scene.ray_cast(
                depsgraph, origin, unit, distance=max(remaining, 1e-4))
            if not hit or obj is None:
                #: 代理框本身不是网格；无遮挡即可见。
                point_visible = True
                break
            hit_distance = (location - camera_pos).length
            if obj.name == target_block.name:
                if abs(hit_distance - distance) <= RAY_TOLERANCE_M:
                    point_visible = True
                break
            if _is_auxiliary(obj):
                travelled = hit_distance + 1e-3
                if travelled >= distance + RAY_TOLERANCE_M:
                    point_visible = True
                    break
                continue
            break
        if point_visible:
            visible += 1
    return float(visible) / float(VISIBLE_POINTS)


def _foreground_occlusion_fraction(scene, camera_pos: Vector, block,
                                   subject_block_names, depsgraph,
                                   occluder_lookup=None) -> Tuple[float, List[str]]:
    """返回 (被非主体体块挡住的采样点比例, occluder 主体 id 列表)。

    ``_visible_fraction`` 只回答“射线最后是否命中主体自己”，无法区分
    “主体被场景体块挡住”和“采样点/角点数值不稳定”。这里保留同一组 9
    个采样点与同一条 ray_cast 口径，但把首命中对象显式分类：命中其它
    ``BD_Blockout_*`` 物体即计入前景遮挡，并记录“谁挡住了采样点”
    （occluder 主体，空间尺 ``OcclusionEvent.subject/occluder`` 归因的
    粗排侧对应物）；命中主体自身或无命中不计入。该值进入
    ``blockout_report`` 后是硬 gate，避免大型前景体块覆盖角色却仍因
    主体包围盒分数高而放行。

    ``occluder_lookup`` 把 ``BD_Blockout_<primitive_id>`` 对象名映射回
    角色/道具 source id（``manifest primitives`` 反查）；缺省时只计数不
    归因（旧行为零差异）。
    """
    bounds = _world_bounds(block)
    if bounds is None:
        return 0.0, []
    low, high = bounds
    #: 前景遮挡候选只保留"非主体的其他角色"：同镜剧情道具（手持/眼前的
    #: 被摄物）与主体同属一个语义单元，不是非主体前景遮挡（F11；final16
    #: 银币与偷盗者互相被记成 occluder，strafe 处方 50 轮死循环）。
    names = blockout_occluder_candidate_names(
        subject_block_names, str(block.name))
    points = _body_face_points(low, high, camera_pos)
    blocked = 0
    sampled = 0
    occluders: List[str] = []
    for point in points:
        direction = point - camera_pos
        distance = direction.length
        if distance < 1e-6:
            continue
        sampled += 1
        unit = direction / distance
        travelled = 0.0
        for _step in range(MAX_RAY_STEPS):
            origin = camera_pos + unit * travelled
            remaining = distance - travelled + RAY_TOLERANCE_M
            hit, location, _normal, _index, obj, _matrix = scene.ray_cast(
                depsgraph, origin, unit, distance=max(remaining, 1e-4))
            if not hit or obj is None:
                break
            hit_distance = (location - camera_pos).length
            #: 辅助物（含隔离隐藏的跨镜角色/道具，``hide_render`` 为 True）
            #: 必须最先跳过：``scene.ray_cast`` 会命中隐藏对象，若先判
            #: ``obj.name in names`` 会把隔离对象误计成前景遮挡，隔离失效。
            if _is_auxiliary(obj):
                travelled = hit_distance + 1e-3
                if travelled >= distance + RAY_TOLERANCE_M:
                    break
                continue
            if obj.name in names:
                blocked += 1
                if occluder_lookup is not None:
                    occluder_id = occluder_lookup.get(str(obj.name))
                    if occluder_id and occluder_id not in occluders:
                        occluders.append(occluder_id)
                break
            if obj.name == block.name:
                travelled = hit_distance + 1e-3
                if travelled >= distance + RAY_TOLERANCE_M:
                    break
                continue
            break
    return float(blocked) / float(sampled or 1), occluders


def _max_deviation(manifest: Mapping[str, Any],
                   camera_objects: Mapping[str, bpy.types.Object],
                   shot_id: str) -> float:
    """设计 vs 实测：本镜机位起点与场景实测位置的最大偏差（米）。

    只对当前 shot 的相机、在该镜自己的 start_frame 处比对——运镜会在镜内
    移动相机，起点是 manifest 基准；拿别的镜的 start 去 set 帧会把运镜终点
    误算成偏差（多镜时尤其明显）。
    """
    deviation: float = 0.0
    for camera in manifest.get("cameras") or []:
        camera_shot_id = str(camera.get("shot_id") or "")
        if camera_shot_id != shot_id:
            continue
        camera_obj = camera_objects.get(camera_shot_id)
        if camera_obj is None or camera.get("position") is None:
            continue
        expected = [float(v) for v in camera["position"]]
        bpy.context.scene.frame_set(int(camera.get("start_frame") or 1))
        bpy.context.view_layer.update()
        actual = list(camera_obj.location)
        deviation = max(deviation, sum((a - e) ** 2
                                       for a, e in zip(actual, expected)) ** 0.5)
    return round(deviation, 4)


def _apply_preview_settings(scene) -> None:
    """16:9 低采样确定性设置（不改用户成片配置）。"""
    scene.render.resolution_x = PREVIEW_WIDTH
    scene.render.resolution_y = PREVIEW_HEIGHT
    scene.render.resolution_percentage = 100
    if hasattr(scene, "eevee") and hasattr(scene.eevee, "taa_render_samples"):
        scene.eevee.taa_render_samples = EEVEE_SAMPLES


def _png_uniform(png_path: Path) -> bool:
    """判断渲染帧是否全帧同像素（S4：空画/空帧检测）。

    正常帧在第一个不同像素处就短路返回 False；只有真正全同的空帧才
    扫完整个像素数组。像素值按 Blender 的 float 逐通道比较。
    """
    image = bpy.data.images.load(str(png_path), check_existing=False)
    try:
        pixels = image.pixels
        if len(pixels) == 0:
            return False
        first = pixels[0]
        return all(pixels[i] == first for i in range(1, len(pixels)))
    finally:
        bpy.data.images.remove(image)


def _render_shot_preview(
    *,
    scene,
    camera_obj: bpy.types.Object,
    shot_id: str,
    frames: Sequence[Tuple[str, int]],
    shot_table_row: Mapping[str, Any],
    manifest: Mapping[str, Any],
    subject_blocks: Mapping[str, str],
    reference_chars: Mapping[str, Mapping],
    expected_by_shot: Mapping[str, Any],
    camera_objects: Mapping[str, bpy.types.Object],
    occluder_lookup: Mapping[str, str],
    preview_dir: Path,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """渲染单镜首/中/末帧并采集数值自检，返回 ``(per_shot_entry, frames)``。

    hide_render 隔离状态由调用方在进入前设置、退出后恢复；本函数只负责
    渲染与测量，不管理场景可见性状态，因此异常不会遗留隐藏对象。
    """
    subject_names = [str(name) for name in
                     ((shot_table_row.get("character_ids") or [])
                      + (shot_table_row.get("prop_ids") or []))]
    rendered_frames: List[Dict[str, Any]] = []
    comp_scores: List[float] = []
    visible_ratios: List[float] = []
    on_screen_ratios: List[float] = []
    subject_area_ratios: List[float] = []
    target_ratios: List[float] = []
    target_visible_ratios: List[float] = []
    off_screen = False
    blocks_found = 0
    boxes_total = 0
    #: “主体自身可见”不能发现前景环境体块挡住了主体：旧逻辑只对每个
    #: 角色分别做 ray_cast，且只把命中自身计为可见，未记录“命中的是谁”。
    #: 这里逐主体记录非主体遮挡射线比例，交给纯层报告变成硬伤。
    foreground_occluded_ratios: List[float] = []

    target_declared = None
    target_block: Optional[str] = None
    expected_shot = expected_by_shot.get(shot_id)
    if isinstance(expected_shot, Mapping) \
            and isinstance(expected_shot.get("framing_target"), Mapping):
        target_declared = dict(expected_shot["framing_target"])
        target_block = _target_block_name(
            manifest, str(target_declared.get("kind") or ""),
            str(target_declared.get("ref") or ""))
        #: 拍对象（主锚）体块若存在，补进主体测量集合：空墙/出画/遮挡
        #: 判据必须能测到拍对象本身，不能只测同框角色（场景级道具可能
        #: 没进本镜 prop_ids，但仍是被摄主体）。
        if target_block is not None and target_block not in subject_names:
            subject_names.append(target_block)
    #: 主锚优先：声明了拍对象且其体块存在时，occlusion/on_screen/面积/
    #: 前景遮挡判据以拍对象自身的读数为主（ECU 拍银币时同框角色占画幅
    #: 是取景，不是主体空墙/溢出）；未声明/体块缺失回退全员聚合（旧行为）。
    primary_block = (target_block
                     if target_declared is not None
                     and target_block is not None
                     and _block_object(target_block) is not None
                     else None)
    primary_visible: Optional[float] = None
    primary_on_screen: Optional[float] = None
    primary_area: Optional[float] = None
    primary_fg: Optional[float] = None
    local_geometry = (
        _coarse_local_geometry(
            target_declared, subject_blocks, reference_chars,
            scene, camera_obj, shot_id, target_block)
        if target_declared is not None else None)
    #: 构图评分主锚：声明了局部拍对象时用局部主体框（hand/face/prop），
    #: 与细排/ruler 的 ``_local_subject_box`` 同语义；缺声明退回整身框。
    #: 这是"两把尺子"断裂的修法——粗排 preview 之前拿整身框+无景别窗口
    #: 评特写，把合法取景压到 55–58，细排 gate（>80）永远过不了。
    local_primary = None
    if local_geometry is not None:
        low_b, high_b, label, screen_facing, _block = local_geometry
        local_primary = _project_bounds(
            low_b, high_b, label, scene, camera_obj)
        local_primary.facing = screen_facing
    shot_type = str(shot_table_row.get("shot_type")
                    or (expected_shot.get("shot_type") if expected_shot else None)
                    or "MS")
    shot_frame = SHOT_FRAME.get(str(shot_type).upper())
    expected_height = None
    window = None
    if shot_frame is not None:
        from ..cinema.framing import SUBJECT_HEIGHT
        visible = min(SUBJECT_HEIGHT, shot_frame.frame_height)
        expected_height = max(0.05, visible / shot_frame.frame_height)
        from ..cinema.framing import HEAD_TOP
        half = shot_frame.frame_height / 2.0
        window = (shot_frame.target_z - half, shot_frame.target_z + half)
    headroom_applies = bool(
        shot_frame is not None
        and shot_frame.frame_height <= COARSE_PROFILE.total_height)

    for phase, frame in frames:
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        depsgraph = bpy.context.evaluated_depsgraph_get()
        camera_pos = Vector(camera_obj.matrix_world.translation)
        png_path = preview_dir / f"{shot_id}_f{frame:04d}.png"
        scene.render.filepath = str(png_path)
        bpy.ops.render.render(write_still=True)
        uniform = (_png_uniform(png_path)
                   if png_path.exists() and png_path.stat().st_size > 0
                   else False)
        rendered_frames.append({
            "shot_id": shot_id, "frame": frame, "phase": phase,
            "png": str(png_path),
            "bytes": png_path.stat().st_size if png_path.exists() else 0,
            "uniform": uniform,
        })

        boxes = []
        occluded: Dict[str, bool] = {}
        fg_occluder_ids: List[str] = []
        target_visible: Optional[float] = None
        for name in subject_names:
            block_name = subject_blocks.get(name)
            if not block_name:
                continue
            block = _block_object(block_name)
            if block is None:
                continue
            is_primary = (primary_block is not None
                          and block_name == primary_block)
            blocks_found += 1
            box = _project_box(scene, camera_obj, block)
            #: Only clip a subject that actually projected in front of the
            #: camera.  ``_project_box`` deliberately returns None when every
            #: corner is behind the camera; re-projecting the AABB through the
            #: window path would mirror it back into frame and silently turn an
            #: empty-wall shot into a false positive (blockout-preview-smoke
            #: shot_003).
            if box is not None and window is not None:
                low_w, high_w = _world_bounds(block)
                if low_w is not None:
                    clipped_low, clipped_high, clipped_top = _clip_to_window(
                        low_w, high_w, window)
                    clipped_box = _project_bounds(
                        clipped_low, clipped_high,
                        f"{block.name}:window", scene, camera_obj)
                    clipped_box.clipped_top = clipped_top
                    #: 主体比景别画面还宽时，左右本就会出画（ECU 拍局部），
                    #: 标记后 framing 不再按"主体出画"扣分。
                    extent = high_w - low_w
                    clipped_box.clipped_sides = (
                        extent.x > shot_frame.frame_height * 16.0 / 9.0)
                    box = clipped_box
            visible = _visible_fraction(scene, camera_pos, block, depsgraph)
            occluded[block.name] = visible <= 0.5
            visible_ratios.append(visible)
            fg_ratio, occluder_ids = _foreground_occlusion_fraction(
                scene, camera_pos, block, subject_blocks.values(),
                depsgraph, occluder_lookup=occluder_lookup)
            foreground_occluded_ratios.append(fg_ratio)
            for occluder_id in occluder_ids:
                if occluder_id not in fg_occluder_ids:
                    fg_occluder_ids.append(occluder_id)
            if is_primary:
                primary_visible = visible
                primary_fg = fg_ratio
            if box is not None:
                boxes.append(box)
                boxes_total += 1
                area_ratio = max(0.0, min(1.0,
                    float(box.width) * float(box.height)))
                subject_area_ratios.append(area_ratio)
                if is_primary:
                    primary_area = area_ratio
                #: 出入画只在"主体几乎完全出画或不透明遮挡到近零"时置位；
                #: 贴边/部分出画由构图分项处理，不当作整镜出入画硬伤。
                if box.inside_ratio() <= ON_SCREEN_MIN or visible <= 0.0:
                    off_screen = True
                on_screen = float(box.inside_ratio()) * visible
                on_screen_ratios.append(on_screen)
                if is_primary:
                    primary_on_screen = on_screen

        if target_declared is not None:
            block = (_block_object(target_block)
                     if target_block is not None else None)
            if block is not None:
                if local_geometry is not None:
                    low_t, high_t, label_t, _facing_t, _block_t = local_geometry
                    target_box = _project_bounds(
                        low_t, high_t, label_t, scene, camera_obj)
                    target_visible = _visible_fraction_bounds(
                        scene, camera_pos, low_t, high_t, block, depsgraph)
                else:
                    target_box = _project_box(scene, camera_obj, block)
                    target_visible = _visible_fraction(
                        scene, camera_pos, block, depsgraph)
                if target_box is not None:
                    target_ratios.append(float(target_box.inside_ratio()))
                if target_visible is not None:
                    target_visible_ratios.append(float(target_visible))

        if boxes:
            #: 构图评分尺子与细排对齐：声明了局部拍对象时，把局部主体框
            #: 加进主体集合并作主锚（特写镜按手/脸/道具评，不拿整身当主锚）；
            #: 同时按景别窗口传 expected_height。未声明时退回旧行为
            #: （expected_height=None，framing 只按出画计分）。
            scoring_boxes = list(boxes)
            scoring_occluded = dict(occluded)
            primary = None
            if local_primary is not None:
                scoring_boxes.append(local_primary)
                scoring_occluded[local_primary.name] = (
                    target_visible is None
                    or target_visible < VISIBLE_RATIO_MIN)
                primary = local_primary.name
            report = evaluate_composition(
                scoring_boxes, occluded=scoring_occluded,
                expected_height=expected_height,
                headroom_applies=headroom_applies,
                primary=primary)
            comp_scores.append(float(report.score))
            #: 诊断可追溯：构图分项明细（headroom/lead_room/thirds/balance/
            #: occlusion/framing）随 per_shot 落盘，细排 gate 卡在阈值附近时
            #: 可以定位是哪个分项拖分，而不是只看总分。不参与任何 check。
            last_composition_items = {
                str(k): round(float(v.score), 4)
                for k, v in (report.items or {}).items()}
            last_composition_primary = primary
            last_composition_expected = expected_height
        else:
            last_composition_items = None
            last_composition_primary = None
            last_composition_expected = None

    #: 声明了主体、场景里也有体块，但整镜一个 box 都没投影出来
    #: （主体在相机背后/完全出画）：这是"主体不在画面内"而非"数据
    #: 缺失"——归零让纯层报 E_BLOCKOUT_EMPTY_WALL finding（as described
    #: in spec：主体投影近零 -> 相机对空墙）。主体体块对象缺失
    #: （blocks_found == 0）才保持 unresolved。
    if subject_names and blocks_found and not on_screen_ratios:
        on_screen_ratios.append(0.0)

    #: 主锚读数优先：拍对象特写镜用拍对象自身的数值进判据，避免同框
    #: 角色的占画幅/出画把合法取景误判成空墙或面积溢出。数值照记。
    visible_reading = (
        round(primary_visible, 4)
        if primary_visible is not None
        else (round(sum(visible_ratios) / len(visible_ratios), 4)
              if visible_ratios else None))
    on_screen_reading = (
        round(primary_on_screen, 4)
        if primary_on_screen is not None
        else (round(max(on_screen_ratios), 4)
              if on_screen_ratios else None))
    area_reading = (
        round(primary_area, 4)
        if primary_area is not None
        else (round(max(subject_area_ratios), 4)
              if subject_area_ratios else None))
    fg_reading = (
        round(primary_fg, 4)
        if primary_fg is not None
        else (round(sum(foreground_occluded_ratios)
                    / len(foreground_occluded_ratios), 4)
              if foreground_occluded_ratios else None))

    per_shot_entry = {
        "shot_id": shot_id,
        "empty": len(subject_names) == 0,
        "composition_score": (round(sum(comp_scores) / len(comp_scores), 2)
                              if comp_scores else None),
        "composition_items": last_composition_items,
        "composition_primary": last_composition_primary,
        "composition_expected_height": last_composition_expected,
        "visible_ratio": visible_reading,
        "foreground_occlusion_ratio": fg_reading,
        "foreground_occluders": list(fg_occluder_ids),
        "on_screen_ratio": on_screen_reading,
        "max_subject_area_ratio": area_reading,
        "off_screen": bool(off_screen),
        "design_diff": {"max_deviation_m":
                        _max_deviation(manifest, camera_objects, shot_id)},
        "frames": rendered_frames,
    }
    if target_declared is not None:
        part = str(target_declared.get("part") or "none")
        per_shot_entry["framing_target"] = {
            "kind": str(target_declared.get("kind") or ""),
            "ref": str(target_declared.get("ref") or ""),
            "part": part,
            "on_screen_ratio": (round(max(target_ratios), 4)
                                if target_ratios else None),
            "visible_ratio": (round(min(target_visible_ratios), 4)
                              if target_visible_ratios else None),
            "provenance": ("block_projection"
                           if part == "none"
                           else "coarse_block_approximation"),
            "note": ("粗排以目标体块投影 + 射线验证拍对象在画面内且可见"
                     if part == "none"
                     else "粗排以局部代理框投影 + 射线验证手/脸/道具可见性"),
        }
    return per_shot_entry, rendered_frames


@main_thread_only("render_blockout_preview")
def _render_blockout_preview_impl(
    manifest: Mapping[str, Any],
    out_dir: Path | str,
    expected: Any = None,
    reference_json: Mapping[str, Any] | None = None,
    *,
    shot_ids: Sequence[str] | None = None,
) -> Dict[str, Any]:
    """渲染每镜首/中/末帧 16:9 PNG 并产出数值自检报告。

    相机对象名沿用 Ticket 03：``BD_Blockout_cam_<shot_id>``；主体体块名
    ``BD_Blockout_char_<name>``。返回 report + previews + 证据路径。
    ``expected``（R10）：plan 语义层，供 ``framing_target`` check 取拍对象
    声明；缺省 None（旧调用方零行为差，不追加四类 check）。
    """
    #: 库函数防御：绝对化，避免 Blender 渲染把相对路径解析到引擎 CWD。
    out_dir = Path(out_dir).resolve()
    preview_dir = out_dir / "preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    selected_shot_ids = tuple(dict.fromkeys(
        str(shot_id) for shot_id in (shot_ids or ()) if str(shot_id)))
    selected = set(selected_shot_ids)
    scene = bpy.context.scene
    _apply_preview_settings(scene)
    subject_blocks = _subject_blocks(manifest)
    #: 前景遮挡归因查找表：``BD_Blockout_<primitive_id>`` 对象名 -> 角色/
    #: 道具 source id（空间尺 OcclusionEvent 归因的粗排侧对应物）。由
    #: manifest primitives 反查构建，保证与 ``_subject_blocks`` 同源。
    occluder_lookup: Dict[str, str] = {}
    for primitive in manifest.get("primitives") or []:
        source = primitive.get("source") or {}
        source_id = str(source.get("id") or "")
        if primitive.get("kind") in {"character", "prop"} and source_id:
            occluder_lookup[
                f"BD_Blockout_{primitive.get('id')}"] = source_id
    expected_shots = plan_shot_dicts(expected) if expected is not None else []
    expected_by_shot = {str(shot.get("shot_id") or ""): shot
                        for shot in expected_shots}

    camera_objects: Dict[str, bpy.types.Object] = {}
    for camera in manifest.get("cameras") or []:
        shot_id = str(camera.get("shot_id") or "")
        camera_id = str(camera.get("camera_id") or f"cam_{shot_id}")
        obj = bpy.data.objects.get(f"BD_Blockout_{camera_id}")
        if obj is not None:
            camera_objects[shot_id] = obj

    per_shot: List[Dict[str, Any]] = []
    previews: List[Dict[str, Any]] = []
    staging_audit: Dict[str, Any] = {}
    #: 角色 facing 字典（name -> {facing:[...]}），供局部主锚（hand/face）
    #: 几何推导使用。来源：manifest primitives 的 character source.id +
    #: 世界参考 JSON 的 characters[].facing；manifest 里没有 facing 时退回
    #: 细排同款默认朝向 +Y（anchor.coarse_local_bounds 的默认值）。
    reference_chars: Dict[str, Dict[str, Any]] = {}
    if isinstance(reference_json, Mapping):
        for char in reference_json.get("characters") or []:
            if not isinstance(char, Mapping):
                continue
            name = str(char.get("name") or "")
            if not name:
                continue
            #: Preserve shot-facing records as well as the scene-wide heading;
            #: the local hand/face geometry selects its heading by shot id.
            reference_chars[name] = dict(char)
    expected_shots_all = plan_shot_dicts(expected) if expected is not None else []
    for char in _reference_characters_from_expected(expected_shots_all):
        reference_chars.setdefault(char["name"], char)
    if not reference_chars:
        for primitive in manifest.get("primitives") or []:
            if primitive.get("kind") != "character":
                continue
            source = primitive.get("source") or {}
            cid = str(source.get("id") or "")
            if cid:
                reference_chars[cid] = {"name": cid, "facing": [0.0, 1.0, 0.0]}
    for camera in manifest.get("cameras") or []:
        shot_id = str(camera.get("shot_id") or "")
        if selected and shot_id not in selected:
            continue
        camera_obj = camera_objects.get(shot_id)
        if camera_obj is None or camera.get("position") is None:
            continue
        start = int(camera.get("start_frame") or 1)
        end = int(camera.get("end_frame") or start)
        frames = [
            ("first", start),
            ("middle", (start + end) // 2),
            ("last", end),
        ]
        scene.camera = camera_obj

        shot_table_row = next(
            (row for row in manifest.get("shot_table") or []
             if row.get("shot_id") == shot_id), {})
        #: 粗排是逐镜 staging 验证：其它镜头的角色/道具不能作为前景体块
        #: 参与本镜渲染与 ray_cast。保留并在本镜结束后恢复原 hide_render，
        #: 不污染后续镜头或调用方场景状态。
        isolated_objects = _shot_isolation_objects(manifest, shot_table_row)
        isolated_previous = {
            obj.name: bool(obj.hide_render) for obj in isolated_objects}
        for obj in isolated_objects:
            obj.hide_render = True
        staged_previous: Dict[str, Any] = {}
        try:
            staged_previous, shot_staging = _apply_character_staging(
                manifest, shot_id)
            try:
                per_shot_entry, rendered_frames = _render_shot_preview(
                    scene=scene, camera_obj=camera_obj, shot_id=shot_id,
                    frames=frames, shot_table_row=shot_table_row,
                    manifest=manifest, subject_blocks=subject_blocks,
                    reference_chars=reference_chars,
                    expected_by_shot=expected_by_shot,
                    occluder_lookup=occluder_lookup,
                    camera_objects=camera_objects, preview_dir=preview_dir)
            finally:
                _restore_character_staging(staged_previous)
            staging_audit[shot_id] = {
                "characters": shot_staging,
                "restored": True,
                "restore_verified": all(
                    bpy.data.objects.get(name) is not None
                    and all(
                        abs(float(actual) - float(expected)) <= 1e-6
                        for actual, expected in zip(
                            bpy.data.objects[name].location, location)
                    )
                    for name, location in staged_previous.items()
                ),
            }
        finally:
            if staged_previous:
                _restore_character_staging(staged_previous)
            for obj in isolated_objects:
                obj.hide_render = isolated_previous.get(obj.name, False)
        per_shot.append(per_shot_entry)
        previews.extend(rendered_frames)

    rendered_shot_ids = {
        str(camera.get("shot_id") or "")
        for camera in manifest.get("cameras") or []
        if (not selected or str(camera.get("shot_id") or "") in selected)
        and camera_objects.get(str(camera.get("shot_id") or "")) is not None
        and camera.get("position") is not None
    }
    missing_shot_ids = sorted(selected - rendered_shot_ids)
    if missing_shot_ids:
        raise ValueError(
            "requested preview shots are missing or unresolved: "
            + ", ".join(missing_shot_ids))
    report_expected = expected
    if selected and isinstance(expected, Mapping):
        report_expected = copy.deepcopy(dict(expected))
        report_expected["shots"] = [
            copy.deepcopy(dict(shot))
            for shot in expected.get("shots") or []
            if isinstance(shot, Mapping)
            and str(shot.get("shot_id") or "") in selected
        ]
    report = build_blockout_report(
        manifest=manifest,
        per_shot=per_shot,
        manifest_fingerprint=manifest_fingerprint(manifest),
        notes=["16:9 低采样预览；数值自检 + 渲染帧供执行 AI 视觉检查"],
        expected=report_expected)

    return {
        "report": report,
        "previews": previews,
        "shot_staging": staging_audit,
        "evidence_dir": str(out_dir),
        "settings": {
            "resolution": [PREVIEW_WIDTH, PREVIEW_HEIGHT],
            "aspect": round(PREVIEW_WIDTH / PREVIEW_HEIGHT, 4),
            "eevee_samples": EEVEE_SAMPLES,
        },
    }


@main_thread_only("render_blockout_preview")
def render_blockout_preview(
    manifest: Mapping[str, Any],
    out_dir: Path | str,
    expected: Any = None,
    reference_json: Mapping[str, Any] | None = None,
    *,
    shot_ids: Sequence[str] | None = None,
) -> Dict[str, Any]:
    """Render selected preview frames and restore caller scene state."""
    scene = bpy.context.scene
    previous_camera = scene.camera
    previous_frame = int(scene.frame_current)
    try:
        return _render_blockout_preview_impl(
            manifest,
            out_dir,
            expected=expected,
            reference_json=reference_json,
            shot_ids=shot_ids,
        )
    finally:
        scene.camera = previous_camera
        scene.frame_set(previous_frame)
        bpy.context.view_layer.update()


def _reference_characters_from_expected(
    expected_shots: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """从计划 shot 列表收集角色名 -> facing（先到先得，缺 facing 用 +Y）。"""
    collected: Dict[str, Dict[str, Any]] = {}
    for shot in expected_shots:
        if not isinstance(shot, Mapping):
            continue
        for character in shot.get("characters") or []:
            if not isinstance(character, str):
                continue
            if character not in collected:
                collected[character] = {"name": character,
                                        "facing": [0.0, 1.0, 0.0]}
    return list(collected.values())


@main_thread_only("refresh_blockout_composition")
def refresh_blockout_composition(
    baseline: Mapping[str, Any],
    out_dir: Path | str,
    expected: Any = None,
    reference_json: Mapping[str, Any] | None = None,
    runtime_world_state: Mapping[str, Any] | None = None,
    *,
    return_manifest: bool = False,
    shot_ids: Sequence[str] | None = None,
) -> Mapping[str, Any]:
    """在冻结空间上重测构图（不重建/不漂移），返回刷新后的 BlockoutReport。

    细排 gate 读的是冻结 baseline 里的旧 composition 数值（整身框时代
    55–58 分）。粗排 preview 的构图尺子修好后，必须用同一把尺子在**同一
    空间**重测一次：渲染 preview 帧（复用 manifest，相机/角色不动），只把
    per_shot 的 composition_score 换新，其余 check（occlusion/on_screen/
    area/design_vs_observed）原样保留——空间没有漂移，不需要重新判粗排
    硬伤。
    """
    baseline_manifest = baseline.get("manifest") or {}
    if not baseline_manifest:
        return baseline.get("report") or {}
    from block_director.layer3_engine.blockout_scene import (
        ensure_blockout_scene,
    )
    #: 没有实时场景时只负责把冻结基准物化一次；同一 manifest 的现有场景
    #: 必须原样复用。重建会删除 Agent 的相机关键帧、追加对象与编辑标记。
    ensure_blockout_scene(baseline_manifest, clear_scene=True)
    manifest = dict(baseline_manifest)
    reference_json = reference_json or baseline.get("reference")
    from block_director.layer3_engine.world_state import (
        collect_blockout_world_state,
    )

    live_world_state = collect_blockout_world_state(manifest)
    observed_world_state = (
        live_world_state
        if any(live_world_state.get(table)
               for table in ("characters", "cameras", "props", "anchors"))
        else runtime_world_state
    )
    if isinstance(observed_world_state, Mapping) \
            and observed_world_state.get("characters") is not None:
        #: 2026-10-21 真跑修复：agent 在细排阶段的 place_character/
        #: move_character/setup_camera/reframe 只写 Blender + runtime_world_state，
        #: 冻结 reference 还停在计划默认站位（伊恩实测 -1.6、参考 JSON -0.3，
        #: 构图 20 分）。重测构图前先把实测世界坐标合并进 reference——保证
        #: 细排 gate 用**同一把尺子量真实空间**，而不是量一个脱节的旧 JSON。
        from ..contracts.world_state import (
            merge_observed_world_into_reference,
        )
        merged = merge_observed_world_into_reference(
            dict(reference_json or {}), observed_world_state)
        if merged.get("characters"):
            reference_json = merged
    refreshed_reference = reference_json
    if isinstance(reference_json, Mapping) and reference_json.get("shots"):
        #: 相机是观测关系，不是冻结空间：旧冻结 manifest 的 target 落在脸高
        #: 带（整身对准），局部拍对象（hand/face）时手/银币出画。细排重测
        #: 构图前先重解相机意图（站位不动），再重建 manifest 让相机对准被摄
        #: 局部，最后在同一空间上重测构图。
        from block_director.cinema.spatial_design import (
            resolve_camera_intents,
        )
        refreshed_reference = resolve_camera_intents(reference_json)
        #: 重解器只产出"设计意图期望值"，不能覆盖实时场景里 Agent/粗排已经
        #: 落地的机位与对准点。否则审核表会拿计划默认机位评价一帧由另一台
        #: 相机渲染的画面，测量与交付再次分叉。
        if isinstance(observed_world_state, Mapping):
            refreshed_reference = merge_observed_world_into_reference(
                dict(refreshed_reference), observed_world_state)
        from block_director.cinema.blockout import build_blockout_manifest
        manifest = build_blockout_manifest(
            design=refreshed_reference, plan=None)
    preview = render_blockout_preview(
        manifest, out_dir, expected=expected,
        reference_json=refreshed_reference if isinstance(
            reference_json, Mapping) and reference_json.get("shots")
        else reference_json,
        shot_ids=shot_ids)
    #: 诊断可追溯：重解的相机 manifest 与重测 report 落盘，供细排 gate
    #: 卡壳时核对"相机是否对准被摄局部、构图分项差在哪"。
    from pathlib import Path as _Path
    diag_dir = _Path(out_dir)
    diag_dir.mkdir(parents=True, exist_ok=True)
    (diag_dir / "refreshed_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8")
    (diag_dir / "refreshed_report.json").write_text(
        json.dumps(dict(preview["report"]), ensure_ascii=False, indent=2),
        encoding="utf-8")
    new_report = dict(preview["report"])
    new_comp = {
        str(check.get("shot_id") or ""): check.get("actual")
        for check in new_report.get("checks") or []
        if str(check.get("check_id") or "") == "composition"
    }
    #: 只更新 composition check；其余 check/finding 保持冻结原值（同一空间）。
    report = dict(baseline.get("report") or {})
    checks = [dict(c) for c in report.get("checks") or []]
    for check in checks:
        if str(check.get("check_id") or "") != "composition":
            continue
        shot_id = str(check.get("shot_id") or "")
        if shot_id not in new_comp:
            continue
        check["actual"] = new_comp.get(shot_id)
        if new_comp.get(shot_id) is None:
            check["verdict"] = "unresolved"
        else:
            check["verdict"] = (
                "pass" if composition_passed(new_comp[shot_id]) else "fail")
    report["checks"] = checks
    if return_manifest:
        return {
            "report": report,
            "manifest": manifest,
            "reference": refreshed_reference,
            "observed_world_state": observed_world_state or {},
            "previews": copy.deepcopy(list(preview.get("previews") or [])),
            "shot_staging": copy.deepcopy(
                dict(preview.get("shot_staging") or {})),
            "shot_ids": list(shot_ids or ()),
        }
    return report


__all__ = ["render_blockout_preview", "PREVIEW_WIDTH", "PREVIEW_HEIGHT"]
