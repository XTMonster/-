"""视口叠加（执行文档 v1.2 §13.4）。

用 ``SpaceView3D.draw_handler_add`` 画：轴线（绿色虚线）、三分法网格、安全框、
角色移动路径（橙色）、相机视锥、违规元素红框。

**为什么用 GPU 叠加层而不是真实对象**：叠加层不进入渲染管线，天然不会污染
参考视频；对比 §9.4 的角色标签是真实对象，必须额外设 ``hide_render``。

几何全部来自 ``block_director/overlay/geometry.py``（纯计算、可单测），本模块
只负责把线段喂给 ``gpu``。``--background`` 下没有窗口，回调永远不会被调用，
因此注册/注销与绘图完全解耦——测试断言的就是"能挂上、能摘掉、几何算得对"。
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Sequence, Tuple

import bpy
from bpy_extras.view3d_utils import location_3d_to_region_2d
from mathutils import Vector

from ..overlay.geometry import (
    FLASH_PERIOD,
    ColoredPolyline,
    OverlayGeometry,
    build_overlay,
    colored_paths,
    flash_alpha,
    path_ticks,
)
from ..settings import get_config
from ..utils.logger import get_logger

log = get_logger("overlay")

RGBA = Tuple[float, float, float, float]

AXIS_COLOR: RGBA = (0.20, 0.90, 0.35, 1.0)
GRID_COLOR: RGBA = (1.0, 1.0, 1.0, 0.25)
SAFE_COLOR: RGBA = (1.0, 0.85, 0.20, 0.45)
PATH_COLOR: RGBA = (1.0, 0.55, 0.15, 0.90)
FRUSTUM_COLOR: RGBA = (0.65, 0.75, 1.0, 0.35)
VIOLATION_COLOR: RGBA = (1.0, 0.20, 0.20, 0.90)

_handle: Optional[object] = None
_flash_started = time.monotonic()
#: v1.7 G2：轨迹刻度/着色的缓存（帧变才重算；路径版本 = 曲线对象名列表）。
_PATH_CACHE: Dict[str, List[ColoredPolyline]] = {}

FLASH_TICK = 0.1          # 重绘节拍（秒）


def is_enabled() -> bool:
    """叠加层是否已挂上（面板与测试都读它）。"""
    return _handle is not None


def _path_points() -> List[List[Tuple[float, float, float]]]:
    """场景里的 ``BD_Path_*`` 曲线（§9.5 画出来的走位线）。"""
    paths: List[List[Tuple[float, float, float]]] = []
    for obj in bpy.data.objects:
        if obj.type != 'CURVE' or not obj.name.startswith("BD_Path_"):
            continue
        for spline in obj.data.splines:
            points = [tuple(obj.matrix_world @ point.co)
                      for point in spline.points]
            if len(points) >= 2:
                paths.append(points)
    return paths


def _path_roles() -> Dict[str, List[List[Tuple[float, float, float]]]]:
    """按角色分组走位线：曲线名 ``BD_Path_<role>_<idx>`` → 该角色点列。

    角色 id 可含下划线（``char_001``），曲线名末尾的 ``_<idx>`` 是序号，
    因此用 **倒序 split** 一次去掉序号段，剩下的前半整段就是角色 id。
    """
    grouped: Dict[str, List[List[Tuple[float, float, float]]]] = {}
    for obj in bpy.data.objects:
        if obj.type != 'CURVE' or not obj.name.startswith("BD_Path_"):
            continue
        stem = obj.name[len("BD_Path_"):]
        role, _, _idx = stem.rpartition("_")
        if not role or not _idx.isdigit():
            continue
        points = [tuple(obj.matrix_world @ point.co)
                  for spline in obj.data.splines
                  for point in spline.points]
        if len(points) >= 2:
            grouped.setdefault(role, []).append(points)
    return grouped


def _path_version() -> str:
    """路径版本：曲线对象名 + 点数（缓存键的一部分，对象增删/编辑即失效）。"""
    items = sorted(
        (obj.name, sum(len(s.points) for s in obj.data.splines))
        for obj in bpy.data.objects
        if obj.type == 'CURVE' and obj.name.startswith("BD_Path_"))
    return repr(items)


def _path_cache_key(frame: int) -> str:
    """轨迹刻度缓存键（帧 ＋ 路径版本；G2 帧变才重算）。"""
    return f"{int(frame)}|{_path_version()}"


def _frustums() -> List[Tuple[Sequence[float], Sequence[float], float, float]]:
    """当前各镜相机的视锥参数 ``(位置, 目标, 焦距, 传感器宽)``。"""
    from ..layer3_engine.scene_context import get_context

    scene_context = get_context()
    if scene_context is None:
        return []
    items = []
    for camera in scene_context.cameras.values():
        rotation = camera.matrix_world.to_quaternion()
        forward = rotation @ Vector((0.0, 0.0, -1.0))
        position = camera.matrix_world.translation
        items.append((tuple(position), tuple(position + forward * 3.0),
                      float(camera.data.lens), float(camera.data.sensor_width)))
    return items


def collect_geometry(context=None) -> OverlayGeometry:
    """按配置与当前场景组装叠加几何（不碰 GPU，可单独调用与断言）。"""
    from ..layer3_engine.scene_context import get_context

    ui = get_config().ui
    scene_context = get_context()
    scene = getattr(context, "scene", None)

    def flag(name: str, fallback: bool) -> bool:
        """场景开关优先（§13.4 的三个独立复选框），否则退到配置默认值。"""
        value = getattr(scene, name, None) if scene is not None else None
        return fallback if value is None else bool(value)

    axis = None
    if flag("bd_show_axis", getattr(ui, "show_axis", True)) \
            and scene_context is not None:
        line = scene_context.axis
        if line is not None:
            axis = [(line.start[0], line.start[1], 0.02),
                    (line.end[0], line.end[1], 0.02)]

    colored = _colored_paths_for(scene_context)
    return build_overlay(
        show_thirds=flag("bd_show_composition",
                         getattr(ui, "show_composition", True)),
        show_safe_area=flag("bd_show_safe_area",
                            getattr(ui, "show_safe_area", True)),
        axis=axis,
        paths=_path_points(),
        colored_paths_input=colored,
        frustums=_frustums())


def _colored_paths_for(scene_context) -> List[ColoredPolyline]:
    """按角色分组后喂 G1 ``colored_paths``；角色色从 cast 读，未知回落调色板。

    ``colored_paths`` 的契约是**每角色一条路径**（``Dict[str, List[WorldPoint]]``），
    而场景里一个角色可能有多条曲线（``BD_Path_<role>_001/_002``）——这里把
    每角色展开成多条单路径再逐条喂，保证类型契约不破。
    """
    roles = _path_roles()
    if not roles:
        return []
    colors: Dict[str, str] = {}
    if scene_context is not None:
        spec = getattr(scene_context, "spec", None)
        for member in (getattr(spec, "cast", []) if spec is not None else []):
            colors[str(member.id)] = str(member.color)
    single_paths: Dict[str, List[Tuple[float, float, float]]] = {}
    result: List[ColoredPolyline] = []
    for role_id, role_paths in roles.items():
        for path in role_paths:
            single_paths[role_id] = path
            result.extend(colored_paths(single_paths, colors))
    return result


def _collect_world_points(region, region_data,
                          geometry: OverlayGeometry
                          ) -> Dict[RGBA, List[Tuple[float, float]]]:
    """世界线 → 屏幕像素，按颜色分组。"""
    grouped: Dict[RGBA, List[Tuple[float, float]]] = {}

    def add(start, end, color):
        left = location_3d_to_region_2d(region, region_data, start)
        right = location_3d_to_region_2d(region, region_data, end)
        if left is None or right is None:
            return
        grouped.setdefault(color, []).extend([tuple(left), tuple(right)])

    for start, end in geometry.axis_lines:
        add(start, end, AXIS_COLOR)
    for path in geometry.paths:
        for index in range(1, len(path)):
            add(path[index - 1], path[index], PATH_COLOR)
    for frustum in geometry.frustums:
        for index in range(0, len(frustum) - 1, 2):
            add(frustum[index], frustum[index + 1], FRUSTUM_COLOR)
    return grouped


def _collect_screen_points(geometry: OverlayGeometry, width: int, height: int
                           ) -> Dict[RGBA, List[Tuple[float, float]]]:
    """屏幕线（归一化，左下原点）→ 像素，按颜色分组。"""
    grouped: Dict[RGBA, List[Tuple[float, float]]] = {}

    def add(start, end, color):
        grouped.setdefault(color, []).extend([
            (start[0] * width, start[1] * height),
            (end[0] * width, end[1] * height)])

    for start, end in geometry.thirds:
        add(start, end, GRID_COLOR)
    for rect in geometry.safe_areas:
        for index in range(len(rect)):
            add(rect[index], rect[(index + 1) % len(rect)], SAFE_COLOR)
    for box in geometry.violations:
        color = _flashing_violation_color()
        for index in range(len(box)):
            add(box[index], box[(index + 1) % len(box)], color)
    return grouped


def _flashing_violation_color() -> RGBA:
    """违规红框按 §13.4 闪烁：透明度随时间在 0.35–0.95 之间往返。"""
    alpha = flash_alpha(time.monotonic() - _flash_started, period=FLASH_PERIOD)
    return (VIOLATION_COLOR[0], VIOLATION_COLOR[1], VIOLATION_COLOR[2], alpha)


def _flash_tick():                            # pragma: no cover - 需 GUI
    """定时器：只要还有违规元素就请求重绘，让红框真的闪起来。"""
    if _handle is None:
        return None
    context = bpy.context
    area = getattr(context, "area", None)
    if area is not None:
        try:
            if collect_geometry(context).violations:
                area.tag_redraw()
        except Exception:                      # 绘制路径不该被异常打断
            return None
    return FLASH_TICK


def _draw():                                  # pragma: no cover - 需 GUI
    """draw_handler 回调：拿不到上下文就安静返回，绝不抛出打断绘制。"""
    context = bpy.context
    region = getattr(context, "region", None)
    region_data = getattr(context, "region_data", None)
    if region is None or region_data is None:
        return
    try:
        import gpu
        from gpu_extras.batch import batch_for_shader
    except Exception:
        return

    geometry = collect_geometry(context)
    if geometry.is_empty():
        return
    # v1.7 G2：轨迹刻度/高亮用缓存（帧变才重算；回调内只查命中才画）。
    frame = int(getattr(bpy.context.scene, "frame_current", 0))
    cache_key = _path_cache_key(frame)
    if cache_key not in _PATH_CACHE:
        _PATH_CACHE.clear()
        _PATH_CACHE[cache_key] = _colored_paths_for(get_context())
    ticks = [tick for polyline in _PATH_CACHE[cache_key]
             for tick in path_ticks(polyline.points,
                                    total_frames=max(frame, 1),
                                    interval_frames=12)]
    area = getattr(context, "area", None)
    width, height = (area.width, area.height) if area else (1, 1)
    grouped = _collect_world_points(region, region_data, geometry)
    for tick in ticks:
        grouped.setdefault(PATH_COLOR, []).append(
            tuple(location_3d_to_region_2d(region, region_data, tick)))
    for color, points in _collect_screen_points(geometry, width, height).items():
        grouped.setdefault(color, []).extend(points)

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    try:
        for color, points in grouped.items():
            if len(points) < 2:
                continue
            batch = batch_for_shader(shader, 'LINES', {"pos": points})
            shader.bind()
            shader.uniform_float("color", color)
            batch.draw(shader)
    finally:
        gpu.state.blend_set('NONE')


def register() -> None:
    """挂上绘制回调（重复调用安全）。"""
    global _handle
    if _handle is not None:
        return
    _handle = bpy.types.SpaceView3D.draw_handler_add(
        _draw, (), 'WINDOW', 'POST_PIXEL')
    if not bpy.app.timers.is_registered(_flash_tick):
        bpy.app.timers.register(_flash_tick, first_interval=FLASH_TICK)
    log.info("视口叠加已启用")


def unregister() -> None:
    global _handle
    if _handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handle, 'WINDOW')
        _handle = None
        if bpy.app.timers.is_registered(_flash_tick):
            bpy.app.timers.unregister(_flash_tick)
        log.info("视口叠加已关闭")
