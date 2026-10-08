"""分段渲染与视频编码（执行文档 v1.2 §15.3）。

实测约束（架构审核）：
- ``bpy.ops.render.opengl`` 在 ``--background`` 下必然报错 → 批处理必须用
  Workbench / EEVEE；
- 5.x 必须先设 ``image_settings.media_type = "VIDEO"`` 才能选 FFMPEG；
- 外部 ffmpeg **不需要**，Blender 内置 FFmpeg 可直接出 mp4。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Sequence, Tuple

import bpy

from ..contracts.enums import Appearance, RenderBackend, resolution_for
from ..utils.blender_compat import (
    configure_video_output,
    engine_identifier,
    engine_is_available,
)
from ..utils.logger import get_logger
from ..utils.threading_guard import main_thread_only

log = get_logger("delivery.render")

BACKGROUND_BACKENDS = (RenderBackend.WORKBENCH, RenderBackend.EEVEE)


def _shading(scene):
    display = getattr(scene, "display", None)
    return getattr(display, "shading", None)


@main_thread_only("apply_delivery_settings")
def apply_delivery_settings(scene, config) -> List[str]:
    """按交付配置设置分辨率/帧率/引擎/外观，返回告警列表。"""
    warnings: List[str] = []

    width, height = resolution_for(config.preset)
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.fps = 24
    scene.render.film_transparent = False

    backend = config.render_backend
    if backend is RenderBackend.VIEWPORT and bpy.app.background:
        warnings.append("viewport(OpenGL) 在 --background 下不可用，已改用 workbench")
        backend = RenderBackend.WORKBENCH
    identifier = engine_identifier("workbench" if backend is RenderBackend.WORKBENCH
                                   else "eevee" if backend is RenderBackend.EEVEE
                                   else "cycles")
    try:
        scene.render.engine = identifier
    except TypeError:
        warnings.append(f"引擎 {identifier} 不可用，已回退到 workbench")
        scene.render.engine = engine_identifier("workbench")

    shading = _shading(scene)
    if shading is not None:
        shading.color_type = "MATERIAL"
        if config.appearance is Appearance.FLAT:
            shading.light = "FLAT"
        else:
            # clay 与 color_coded 都靠材质色区分，用 STUDY 让形体可读
            shading.light = "STUDIO"
        shading.background_type = "VIEWPORT"
        shading.background_color = (0.10, 0.11, 0.14)
        #: 卡 G1 / D-18：白模可读性——接触阴影 + 腔体（AO 式）暗角，让脚"踩"到
        #: 地面。Workbench 的 AO 等价物就是 ``show_cavity``；SCREEN = 屏幕空间
        #: （按深度算的接触暗角，最接近 SSAO）。实测（Blender 5.2 LTS）：
        #: 接触环/远处地面亮度比 0.99 → 0.87。
        shading.show_shadows = True
        shading.show_cavity = True
        shading.cavity_type = "SCREEN"

    if backend is RenderBackend.EEVEE:
        eevee = getattr(scene, "eevee", None)
        if eevee is not None:
            #: Blender 5.2 的 EEVEE 已经**没有** ``use_gtao`` / 每灯
            #: ``use_contact_shadow``（实测 RNA 移除）：AO 并入 fast GI 路径，
            #: 接触阴影由 ``use_shadows`` + 灯光自带 ``use_shadow`` 提供。两者
            #: 在 5.2 默认已开，这里显式钉住，防未来版本改默认。属性名已用
            #: Blender 5.2.0 LTS 实跑验证（不是猜的）。
            eevee.use_shadows = True
            eevee.use_fast_gi = True

    # depth 与 full_concat 的实际产出在 export_director 里编排（它们都依赖
    # 分段渲染的结果）。配置层面的前提条件在这里校验：
    if config.export_depth and backend is not RenderBackend.EEVEE:
        warnings.append("depth 导出需要 EEVEE 的 Z Pass，已跳过（当前后端 "
                        f"{backend}）")
    return warnings


def _resolve_video_path(base: str) -> str:
    """Blender 可能给文件名补上容器后缀，返回真实落盘路径。"""
    if os.path.exists(base):
        return base
    for suffix in (".mp4", ".mkv", ".avi"):
        if os.path.exists(base + suffix):
            return base + suffix
    return base


@main_thread_only("render_shot_video")
def render_shot_video(scene, start_frame: int, end_frame: int, base_path: str,
                      codec: str = "H264", crf: str = "MEDIUM") -> Tuple[str, int]:
    """渲染一个镜头的 mp4，返回 (落盘路径, 帧数)。"""
    scene.frame_start = int(start_frame)
    scene.frame_end = int(end_frame)
    configure_video_output(scene, base_path, codec=codec, crf=crf)
    bpy.ops.render.render(animation=True)
    path = _resolve_video_path(base_path)
    frames = int(end_frame) - int(start_frame) + 1
    return path, frames


@main_thread_only("render_first_frame")
def render_first_frame(scene, frame: int, path: str) -> bool:
    """渲染首帧 PNG（图生视频的输入图）。"""
    image_settings = scene.render.image_settings
    if hasattr(image_settings, "media_type"):
        image_settings.media_type = "IMAGE"
    image_settings.file_format = "PNG"
    scene.frame_set(int(frame))
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    return os.path.exists(path)


@main_thread_only("render_still")
def render_still(scene, frame: int, path: str) -> bool:
    return render_first_frame(scene, frame, path)
