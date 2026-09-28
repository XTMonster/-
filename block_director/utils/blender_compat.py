"""Blender 版本兼容封装（执行文档 v1.2 §21.7）。

这里只放**经过实测**的差异，不猜测。每一条都注明依据。
本模块依赖 bpy，只能在 Blender 内导入。
"""

from __future__ import annotations

from typing import Any, List, Optional, Sequence, Tuple

import bpy

from .logger import get_logger

log = get_logger("compat")


def blender_version() -> Tuple[int, ...]:
    return tuple(bpy.app.version)


def engine_identifier(logical: str) -> str:
    """逻辑引擎名 → 当前版本的实际标识。

    实测：4.2–4.x 的 EEVEE 是 ``BLENDER_EEVEE_NEXT``，而 5.x 又改回
    ``BLENDER_EEVEE``；直接写死任何一个都会在另一个版本上崩。
    """
    table = {
        "eevee": ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"),
        "workbench": ("BLENDER_WORKBENCH", "BLENDER_WORKBENCH"),
        "cycles": ("CYCLES", "CYCLES"),
    }
    modern, legacy = table.get(logical, (logical, logical))
    return modern if blender_version() >= (5, 0, 0) else legacy


def engine_is_available(logical: str) -> bool:
    """试着把引擎设进去，失败则回滚。用于避开未启用的引擎（如未装 Cycles）。"""
    scene = bpy.context.scene
    previous = scene.render.engine
    try:
        scene.render.engine = engine_identifier(logical)
        return True
    except Exception:  # noqa: BLE001
        return False
    finally:
        try:
            scene.render.engine = previous
        except Exception:  # noqa: BLE001
            pass


def supports_media_type() -> bool:
    """5.x 起输出设置拆成 IMAGE/VIDEO；视频输出必须先切 media_type。"""
    return hasattr(bpy.context.scene.render.image_settings, "media_type")


def configure_video_output(scene, filepath: str, codec: str = "H264",
                           crf: str = "MEDIUM") -> None:
    """按版本正确配置视频输出（§15.3 实测要求）。"""
    image_settings = scene.render.image_settings
    if supports_media_type():
        image_settings.media_type = "VIDEO"
    image_settings.file_format = "FFMPEG"
    ffmpeg = scene.render.ffmpeg
    ffmpeg.format = "MPEG4"
    ffmpeg.codec = codec
    ffmpeg.constant_rate_factor = crf
    ffmpeg.audio_codec = "NONE"
    scene.render.filepath = filepath


def action_fcurves(action: Optional[Any]) -> List[Any]:
    """取 Action 下所有 fcurve。

    实测：4.x 用 ``action.fcurves``；5.x 起该属性**已被移除**，
    改为 ``action.layers[*].strips[*].channelbags[*].fcurves``。
    """
    if action is None:
        return []
    curves = getattr(action, "fcurves", None)
    if curves is not None:
        return list(curves)
    collected: List[Any] = []
    for layer in getattr(action, "layers", []) or []:
        for strip in getattr(layer, "strips", []) or []:
            for channelbag in getattr(strip, "channelbags", []) or []:
                collected.extend(channelbag.fcurves)
    return collected


def set_keyframe_interpolation(action: Optional[Any],
                               interpolation: str = "BEZIER",
                               easing: str = "AUTO") -> int:
    """统一设置关键帧插值与缓动，返回修改的点数。"""
    changed = 0
    for curve in action_fcurves(action):
        for point in curve.keyframe_points:
            point.interpolation = interpolation
            try:
                point.easing = easing
            except (AttributeError, TypeError):
                pass
            changed += 1
    return changed


def orphan_purge() -> int:
    """回收无用户 datablock（§8.1）。"""
    return bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True,
                                  do_recursive=True)


def startup_report() -> dict:
    """启动时打印一次兼容性报告，便于远程排查（§21.7）。"""
    report = {
        "blender": bpy.app.version_string,
        "python": ".".join(str(v) for v in __import__("sys").version_info[:3]),
        "eevee": engine_identifier("eevee"),
        "workbench": engine_identifier("workbench"),
        "has_media_type": supports_media_type(),
        "has_action_fcurves": hasattr(bpy.types.Action, "fcurves"),
        "background": bpy.app.background,
    }
    log.info("兼容性报告: %s", report)
    return report
