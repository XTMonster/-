"""角色定妆卡（v1.6 E3 / FR-A5）。

每角色一张**固定机位**参考 PNG：相机在角色正前方 3 m、高 1.0 m、50 mm，
正方形 1024×1024、``sensor_fit = HORIZONTAL``（36 mm 横传感器）、水平对准，
全身（脚 0 → 头顶 1.70）＋ 标签锚点（2.00）全部入画，四边各留
≈3.7% 画面高（≈38 px @1024）。同一姿势、同一机位拍每一个角色（卡 E3 红线）。

画幅为什么是这一组（``docs/evidence/20261008-v16-intake/FOLLOWUP_FINDINGS.md``
的 square-frame 分支，本模块在 Blender 里用 ``world_to_camera_view`` 实测过）：

* 本库默认横传感器 36 mm、16:9 时竖传感器 20.25 mm ⇒ 50 mm 的竖视场角
  ``2·atan(20.25/100) ≈ 22.9°`` ⇒ 3 m 处画高仅 1.215 m，装不下 1.70 m 身体
  更装不下 2.00 m 标签（需求角跨度 ``atan(1/3)+atan(0.7/3) ≈ 31.57°``）。
* ``1024×1024 + sensor_fit HORIZONTAL + 36 mm`` 时竖视场角
  ``2·atan(36/100) ≈ 39.598°`` ⇒ 3 m 处画高 2.16 m；机位高 1.0 m 水平对准
  1.0 m 时覆盖 ``z ∈ [-0.08, 2.08]``——脚 0 / 头顶 1.70 / 标签锚点 2.00
  全部在画内，上下各留 0.08 m。

纯层部分（设计值、文件名清洗、机位数学）**不 import bpy**，供 ``tests/``
按文件路径直接加载（与 ``tests/test_tool_bindings_env.py`` 同一招）；一切
bpy 调用都在渲染函数内导入，入口照 §3.1 挂 ``@main_thread_only``。

快照/恢复纪律照抄 ``layer8_delivery/depth_pass.py``：渲染设置、活动相机、
当前帧、标签变换与关键帧、其它角色的 ``hide_render`` 全部在改前快照、
``finally`` 里恢复，任何一步异常都不留脏状态。
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from block_director.utils.threading_guard import main_thread_only

# --------------------------------------------------------------------------- #
# 机位设计值（卡 E3 钉死，不许改）：角色正前方 3 m、高 1.0 m、50 mm。
# --------------------------------------------------------------------------- #

#: 设计值：焦距（mm）。任务卡钉死 50 mm。
CARD_LENS_MM = 50.0
#: 设计值：机位到角色的水平距离（m）。任务卡钉死 3 m。
CARD_DISTANCE_M = 3.0
#: 设计值：机位高度（m，相对角色地面）。任务卡钉死 1.0 m。
CARD_HEIGHT_M = 1.0

# --------------------------------------------------------------------------- #
# 画幅设计值（FOLLOWUP_FINDINGS 的 square-frame 分支）。
# --------------------------------------------------------------------------- #

#: 设计值：横传感器尺寸（mm），Blender 相机默认 36 mm。**不改成别的大传感器**
#: （那等于偷偷缩短焦距），只改下方 sensor_fit / 分辨率来换取竖画幅。
CARD_SENSOR_WIDTH_MM = 36.0
#: 设计值：``sensor_fit = HORIZONTAL``。配合 1024×1024 让竖视场角与横视场角
#: 同为 39.598°（Blender 里 ``AUTO`` 对 1:1 画幅等效，这里显式钉死防版本漂移）。
CARD_SENSOR_FIT = "HORIZONTAL"
#: 设计值：正方形边长（px）。16:9 装不下全身＋标签，正方形是可行分支。
CARD_RESOLUTION = 1024
#: 设计值：水平对准——对准点高度 = 机位高度（无俯仰），覆盖区间关于
#: 身体＋标签的竖直中点（1.0 m）对称，上下边距相等。
CARD_AIM_HEIGHT_M = 1.0

#: 卡片落盘目录（相对导出根目录）。
CARD_DIRNAME = Path("reference") / "characters"
CARD_EXTENSION = ".png"

#: 卡片帧放在排程之外（帧号 = min(frame_start, 1) - 100）：给标签烘焙的
#: 临时关键帧不与既有排程帧（≥1）重叠，恢复时只删这一帧的点即可逐位还原。
CARD_FRAME_OFFSET = 100

#: 临时相机与烘焙排程键（渲染后即删除/恢复）。
CARD_CAMERA_NAME = "BD_CardCamera"
CARD_SHOT_ID = "reference_card"

# --------------------------------------------------------------------------- #
# 由设计值推导的画幅几何（不是第二份设计值，是单一真源的推导）。
# --------------------------------------------------------------------------- #

#: 竖视场角（rad）：``2·atan(36/(2·50)) ≈ 0.6911 rad ≈ 39.598°``。
CARD_VERTICAL_FOV_RAD = 2.0 * math.atan(
    CARD_SENSOR_WIDTH_MM / (2.0 * CARD_LENS_MM))

#: 3 m 处的画面高度（m）：``2·3·tan(vfov/2) = 2·3·0.36 = 2.16``。
CARD_FRAME_HEIGHT_M = (
    2.0 * CARD_DISTANCE_M * math.tan(CARD_VERTICAL_FOV_RAD / 2.0))


def card_camera_pose(position: Sequence[float],
                     facing: Sequence[float] = (0.0, 1.0, 0.0)
                     ) -> Tuple[Tuple[float, float, float],
                                Tuple[float, float, float]]:
    """由角色位置与朝向求 ``(机位, 对准点)``。纯函数，可单测。

    机位 = 角色位置 + 朝向（XY 归一）× 3 m、抬 1.0 m；对准点 = 角色位置
    抬 1.0 m（水平对准）。朝向退化（零向量）时回落到 ``(0, 1, 0)``。
    """
    x, y, z = (float(value) for value in position[:3])
    fx, fy = float(facing[0]), float(facing[1])
    length = math.hypot(fx, fy)
    if length < 1e-9:
        fx, fy = 0.0, 1.0
    else:
        fx, fy = fx / length, fy / length
    return ((x + fx * CARD_DISTANCE_M, y + fy * CARD_DISTANCE_M,
             z + CARD_HEIGHT_M),
            (x, y, z + CARD_AIM_HEIGHT_M))


def card_ndc_y(z: float, aim_height: float = CARD_AIM_HEIGHT_M) -> float:
    """水平对准时，高度 ``z`` 的点在卡片画面里的 NDC y（0..1，自下而上）。

    与 Blender 的 ``world_to_camera_view`` 实测逐位一致（探针对拍）：
    ``card_ndc_y(0) ≈ 0.037037``、``card_ndc_y(1.70) ≈ 0.824074``、
    ``card_ndc_y(2.00) ≈ 0.962963``。
    """
    bottom = float(aim_height) - CARD_FRAME_HEIGHT_M / 2.0
    return (float(z) - bottom) / CARD_FRAME_HEIGHT_M


#: Windows 保留设备名（大小写不敏感）：这些名字在文件系统里被拒或指到设备。
_WINDOWS_RESERVED = frozenset({
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{digit}" for digit in range(1, 10)),
    *(f"LPT{digit}" for digit in range(1, 10)),
})

#: 文件名长度上限：留给 ``reference/characters/`` 前缀与后续后缀余量。
_MAX_NAME_CHARS = 120


def sanitise_filename(text: str) -> str:
    """把显示名洗成确定性的安全文件名（不含扩展名）。

    * 保留字母数字（含 CJK）与 ``_``/``-``，其余字符替换为 ``_``；
    * 连续下划线折叠、首尾下划线与尾点去除；
    * Windows 保留设备名前置 ``_`` 中性化；
    * 空结果回落到 ``character``（调用方会先尝试用元素 id）。

    同一输入永远同一输出；碰撞交给 :func:`assign_card_names` 处理。
    """
    text = str(text or "").strip()
    cleaned = "".join(
        ch if ch.isalnum() or ch in "_-" else "_" for ch in text)
    cleaned = re.sub(r"_+", "_", cleaned)
    cleaned = cleaned.strip("_").rstrip(".")
    if not cleaned:
        return "character"
    if cleaned.upper() in _WINDOWS_RESERVED:
        cleaned = "_" + cleaned
    if len(cleaned) > _MAX_NAME_CHARS:
        cleaned = cleaned[:_MAX_NAME_CHARS].rstrip("_")
        if not cleaned:
            cleaned = "character"
    return cleaned


def assign_card_names(elements: Sequence[Any]) -> Dict[str, str]:
    """元素 → 卡片文件名（不含扩展名）。确定性、防碰撞。

    * 基础名 = ``sanitise_filename(label)``；label 为空时回落到
      ``sanitise_filename(id)``；
    * 处理顺序按 ``(基础名, id 清洗形)`` 排序——与调用方传入顺序无关，
      同名不同 id 的分配结果固定；
    * 碰撞（**大小写不敏感**，Windows/macOS 文件系统语义）时追加
      ``_<id 清洗形>``，仍碰撞再追数字，保证输出两两不同。
    """
    def sort_key(element: Any) -> Tuple[str, str]:
        element_id = str(getattr(element, "id", "") or "").strip()
        label = str(getattr(element, "label", "") or "").strip()
        base = sanitise_filename(label) if label else sanitise_filename(element_id)
        return base, sanitise_filename(element_id)

    used: Dict[str, bool] = {}
    names: Dict[str, str] = {}
    for element in sorted(elements, key=sort_key):
        element_id = str(getattr(element, "id", "") or "").strip()
        label = str(getattr(element, "label", "") or "").strip()
        base = (sanitise_filename(label) if label
                else sanitise_filename(element_id))
        candidate = base
        if candidate.lower() in used:
            suffix = sanitise_filename(element_id)
            candidate = f"{base}_{suffix}" if suffix else f"{base}_2"
            counter = 2
            while candidate.lower() in used:
                candidate = f"{base}_{counter}"
                counter += 1
        used[candidate.lower()] = True
        names[element_id] = candidate
    return names


# --------------------------------------------------------------------------- #
# bpy 侧（函数内 import，保证本模块可被纯 pytest 按路径加载）。
# --------------------------------------------------------------------------- #


def _hide_other_elements(scene, character, characters: Dict[str, Any]
                         ) -> List[Tuple[Any, bool, bool]]:
    """隐藏本角色之外的身份元素（其它角色、其它标签、群众），返回恢复表。

    定妆卡是"每个角色的身份参考"，画面里不能混进另一个人；环境件与道具是
    中性场景上下文，保留。``hide_render`` 与 ``hide_viewport`` **两个都关**
    ——后者管 ``bpy`` 的 ``scene.ray_cast``：Blender 5.2 实测只关
    ``hide_render`` 时其它角色仍会挡在标签烘焙的遮挡射线
    （``label_baking._blocked``）上，把卡片标签误判成被挡住、推到画外。
    两个开关改前记值、恢复时逐对象写回。
    """
    import bpy

    changed: List[Tuple[Any, bool, bool]] = []

    def hide(obj) -> None:
        if obj is None:
            return
        changed.append((obj, obj.hide_render, obj.hide_viewport))
        obj.hide_render = True
        obj.hide_viewport = True

    for other_id, other in (characters or {}).items():
        if other is character:
            continue
        for obj in getattr(other, "all_objects", lambda: [])():
            hide(obj)
        for suffix in ("Fill", "Stroke"):
            hide(bpy.data.objects.get(f"BD_Label_{other_id}{suffix}"))

    from block_director.layer3_engine.scene_context import get_context
    context = get_context()
    for obj in list(getattr(context, "crowd", None) or []):
        hide(obj)
    return changed


def _snapshot_labels(character) -> List[Tuple[Any, Dict[str, Any]]]:
    """快照本角色渲染标签（fill/stroke）的变换与动画数据存在性。"""
    import bpy

    snapshots: List[Tuple[Any, Dict[str, Any]]] = []
    for suffix in ("Fill", "Stroke"):
        obj = bpy.data.objects.get(f"BD_Label_{character.id}_{suffix}")
        if obj is None:
            continue
        animation = getattr(obj, "animation_data", None)
        snapshots.append((obj, {
            "location": tuple(obj.location),
            "rotation": tuple(obj.rotation_euler),
            "scale": tuple(obj.scale),
            "had_animation_data": animation is not None,
            "had_action": getattr(animation, "action", None) is not None,
        }))
    return snapshots


def _restore_labels(scene, snapshots, card_frame: int) -> None:
    """删掉卡片帧上我们加的关键帧，再写回烘焙前的变换。"""
    from block_director.utils.blender_compat import action_fcurves

    for obj, snapshot in snapshots:
        animation = getattr(obj, "animation_data", None)
        action = getattr(animation, "action", None) if animation else None
        if action is not None:
            for fcurve in action_fcurves(action):
                if fcurve.data_path not in ("location", "rotation_euler",
                                            "scale"):
                    continue
                for point in list(fcurve.keyframe_points):
                    if int(round(float(point.co[0]))) == int(card_frame):
                        fcurve.keyframe_points.remove(point, fast=True)
        obj.location = snapshot["location"]
        obj.rotation_euler = snapshot["rotation"]
        obj.scale = snapshot["scale"]
        if not snapshot["had_animation_data"]:
            obj.animation_data_clear()
        elif not snapshot["had_action"] and animation is not None \
                and animation.action is not None \
                and not action_fcurves(animation.action):
            obj.animation_data_clear()


def _render_one_card(scene, character, element, name: str,
                     characters: Dict[str, Any], card_dir: Path) -> str:
    """渲染一张定妆卡并完整恢复场景。"""
    import bpy
    from mathutils import Vector

    from block_director.layer3_engine.character_system.character_factory \
        import get_facing
    from block_director.layer3_engine.label_baking import (
        bake_labels,
        collect_label_entries,
    )
    from block_director.utils.logger import get_logger
    from .renderer import render_first_frame

    log = get_logger("delivery.reference")
    target_path = card_dir / f"{name}{CARD_EXTENSION}"

    settings = scene.render.image_settings
    previous = {
        "camera": scene.camera,
        "frame_current": scene.frame_current,
        "resolution_x": scene.render.resolution_x,
        "resolution_y": scene.render.resolution_y,
        "resolution_percentage": scene.render.resolution_percentage,
        "filepath": scene.render.filepath,
        "file_format": settings.file_format,
        "color_mode": settings.color_mode,
        "color_depth": settings.color_depth,
        "media_type": getattr(settings, "media_type", None),
    }
    #: 时间线剪切标记会把 ``scene.camera`` 绑到分镜相机：Blender 5.2 实测
    #: ``scene.frame_set`` 与渲染操作都会**按标记重新派生** ``scene.camera``，
    #: 把刚赋上的卡片相机覆盖回分镜相机（渲染出来的是分镜画面，人物/标签
    #: 全错位）。渲染前先解绑全部标记相机，恢复时逐条写回。
    markers = [(marker, marker.camera)
               for marker in scene.timeline_markers]
    for marker, _camera in markers:
        marker.camera = None

    card_frame = min(int(scene.frame_start), 1) - CARD_FRAME_OFFSET
    scene.frame_set(card_frame)
    bpy.context.view_layer.update()

    root = getattr(character, "root", None)
    if root is None:
        raise RuntimeError(f"{element.id} 没有 root 对象，无法摆定妆卡机位")
    position = root.matrix_world.translation.copy()
    facing = get_facing(character)
    location, look_at = card_camera_pose(position, facing)

    hidden = _hide_other_elements(scene, character, characters)
    label_snapshots = _snapshot_labels(character)

    camera_obj = None
    camera_data = None
    try:
        camera_data = bpy.data.cameras.new(CARD_CAMERA_NAME)
        camera_data.lens = CARD_LENS_MM
        camera_data.sensor_width = CARD_SENSOR_WIDTH_MM
        camera_data.sensor_fit = CARD_SENSOR_FIT
        camera_obj = bpy.data.objects.new(CARD_CAMERA_NAME, camera_data)
        scene.collection.objects.link(camera_obj)
        camera_obj.location = tuple(location)
        direction = Vector(look_at) - Vector(location)
        camera_obj.rotation_euler = direction.to_track_quat(
            "-Z", "Y").to_euler()
        scene.camera = camera_obj
        bpy.context.view_layer.update()

        #: 分辨率必须在标签烘焙**之前**切到正方形：``bake_labels`` 的锚点
        #: 投影用 ``world_to_camera_view`` 读的是 ``scene.render`` 的当前分辨率
        #: （不是传入的 ``resolution`` 参数）——16:9 下锚点被投到画外 1.32，
        #: 出画回推会按 0.25 上限把标签压进头球里，渲染出来标签被头挡掉。
        scene.render.resolution_x = CARD_RESOLUTION
        scene.render.resolution_y = CARD_RESOLUTION
        scene.render.resolution_percentage = 100
        if hasattr(settings, "media_type"):
            settings.media_type = "IMAGE"
        settings.file_format = "PNG"
        settings.color_mode = "RGB"
        settings.color_depth = "8"

        #: 标签照生产管线烘焙到卡片相机：公告板、屏幕恒定字号、出画回推
        #: （FRAME_MARGIN）——不是另写一套近似摆放。
        entries = collect_label_entries([character])
        if entries:
            report = bake_labels(
                scene, entries,
                {CARD_SHOT_ID: (card_frame, card_frame)},
                {CARD_SHOT_ID: camera_obj},
                resolution=(CARD_RESOLUTION, CARD_RESOLUTION))
            unreadable = list(report.get("unreadable") or [])
            if unreadable:
                log.warning("%s: 定妆卡标签不可读（%s）",
                            element.id, unreadable)
        else:
            log.warning("%s: 场景里没有渲染标签，定妆卡不带标签", element.id)

        if not render_first_frame(scene, card_frame, str(target_path)):
            raise RuntimeError(f"定妆卡渲染未产出文件：{target_path}")
    finally:
        _restore_labels(scene, label_snapshots, card_frame)
        for obj, was_hidden_render, was_hidden_viewport in reversed(hidden):
            obj.hide_render = was_hidden_render
            obj.hide_viewport = was_hidden_viewport
        if scene.camera is camera_obj or previous["camera"] is not None:
            scene.camera = previous["camera"]
        scene.render.resolution_x = previous["resolution_x"]
        scene.render.resolution_y = previous["resolution_y"]
        scene.render.resolution_percentage = previous["resolution_percentage"]
        scene.render.filepath = previous["filepath"]
        settings = scene.render.image_settings
        settings.file_format = previous["file_format"]
        settings.color_mode = previous["color_mode"]
        settings.color_depth = previous["color_depth"]
        if previous["media_type"] is not None:
            settings.media_type = previous["media_type"]
        scene.frame_set(previous["frame_current"])
        if camera_obj is not None:
            bpy.data.objects.remove(camera_obj, do_unlink=True)
        if camera_data is not None and camera_data.name in bpy.data.cameras:
            bpy.data.cameras.remove(camera_data, do_unlink=True)
        for marker, camera in markers:
            marker.camera = camera
    return str(target_path)


@main_thread_only("render_reference_cards")
def render_reference_cards(scene, registry, out_dir: str) -> List[str]:
    """为登记表里每个角色元素渲染一张定妆卡，返回写出的绝对路径列表。

    * 机位：每个角色正前方 3 m、高 1.0 m、50 mm（同一姿势同一机位）；
    * 画幅：1024×1024、sensor_fit HORIZONTAL、36 mm；
    * 白模预设：沿用交付层已配置的引擎与外观，只改分辨率和图像设置；
    * 标签开：用生产管线（``bake_labels``）烘焙到卡片相机；
    * 落盘：``<out_dir>/reference/characters/<name>.png``，
      ``name`` = 登记表 label 的确定性清洗形（碰撞安全）；
    * 每张卡渲染后恢复渲染设置、活动相机、当前帧、标签变换/关键帧与其它
      对象的 ``hide_render``。

    登记表里有角色、场景里缺对象时直接报错（不静默跳过）；渲染未产出文件
    同样报错。
    """
    from block_director.layer3_engine.scene_context import get_context
    from block_director.utils.logger import get_logger

    log = get_logger("delivery.reference")
    context = get_context()
    characters = getattr(context, "characters", {}) \
        if context is not None else {}
    elements = [element for element in getattr(registry, "elements", [])
                if str(getattr(element, "kind", "")) == "character"]
    missing = [str(element.id) for element in elements
               if str(element.id) not in characters]
    if missing:
        raise RuntimeError(
            "角色定妆卡缺少场景对象（登记表里有、场景里没有）："
            + "、".join(missing))
    if not elements:
        log.info("登记表里没有角色元素，跳过定妆卡")
        return []

    names = assign_card_names(elements)
    card_dir = Path(out_dir).resolve() / CARD_DIRNAME
    card_dir.mkdir(parents=True, exist_ok=True)

    written: List[str] = []
    for element in elements:
        character = characters[str(element.id)]
        name = names[str(element.id)]
        path = _render_one_card(scene, character, element, name,
                                characters, card_dir)
        written.append(path)
        log.info("角色定妆卡已写入：%s → %s", element.id, path)
    return written


__all__ = [
    "CARD_LENS_MM", "CARD_DISTANCE_M", "CARD_HEIGHT_M",
    "CARD_SENSOR_WIDTH_MM", "CARD_SENSOR_FIT", "CARD_RESOLUTION",
    "CARD_AIM_HEIGHT_M", "CARD_DIRNAME", "CARD_EXTENSION",
    "CARD_FRAME_OFFSET", "CARD_CAMERA_NAME", "CARD_SHOT_ID",
    "CARD_VERTICAL_FOV_RAD", "CARD_FRAME_HEIGHT_M",
    "card_camera_pose", "card_ndc_y", "sanitise_filename",
    "assign_card_names", "render_reference_cards",
]
