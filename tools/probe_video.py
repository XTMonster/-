"""BlockDirector — 视频编码路径专项探针.

目的：确定在真实 Blender 上"把渲染结果变成 mp4"的可靠路径。
背景：外部 ffmpeg 不在 PATH；需确认 Blender 内置 FFmpeg 输出是否可用。
"""

from __future__ import annotations

import json
import os
import sys
import traceback

import bpy


REPORT: dict = {}


def outdir() -> str:
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_probe_out")
    os.makedirs(d, exist_ok=True)
    return d


def rec(name, fn):
    try:
        REPORT[name] = fn()
    except Exception as exc:  # noqa: BLE001
        REPORT[name] = {"error": f"{type(exc).__name__}: {exc}",
                        "trace": traceback.format_exc(limit=3)}


def _scene_prep():
    scene = bpy.context.scene
    scene.render.resolution_x = 160
    scene.render.resolution_y = 90
    scene.render.resolution_percentage = 100
    scene.frame_start = 1
    scene.frame_end = 6
    scene.render.engine = "BLENDER_EEVEE"
    return scene


def p_enum_instance():
    """实例级枚举：scene.render.image_settings.file_format。"""
    scene = bpy.context.scene
    items = scene.render.image_settings.bl_rna.properties["file_format"].enum_items
    return {
        "instance_enum": [i.identifier for i in items],
        "rna_type_enum": [
            i.identifier for i in
            bpy.types.ImageFormatSettings.bl_rna.properties["file_format"].enum_items
        ],
        "current": scene.render.image_settings.file_format,
        "is_movie_format": getattr(scene.render, "is_movie_format", "N/A"),
    }


def p_set_ffmpeg():
    scene = _scene_prep()
    scene.render.image_settings.file_format = "FFMPEG"
    return {"ok": True, "value": scene.render.image_settings.file_format,
            "is_movie_format": scene.render.is_movie_format}


def p_render_mp4():
    """真正的端到端：EEVEE 渲染动画 → 直接写 mp4。"""
    scene = _scene_prep()
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.ffmpeg.format = "MPEG4"
    scene.render.ffmpeg.codec = "H264"
    scene.render.ffmpeg.constant_rate_factor = "MEDIUM"
    scene.render.ffmpeg.audio_codec = "NONE"
    out = os.path.join(outdir(), "video_probe.mp4")
    scene.render.filepath = out
    bpy.ops.render.render(animation=True)
    final = out if os.path.exists(out) else out + ".mp4"
    return {"ok": os.path.exists(final), "path": final,
            "size": os.path.getsize(final) if os.path.exists(final) else 0}


def p_render_settings_keys():
    """RenderSettings 上与视频/输出相关的属性名（探查 5.x 是否有新 API）。"""
    keys = [p.identifier for p in bpy.types.RenderSettings.bl_rna.properties]
    interesting = [k for k in keys
                   if any(t in k.lower() for t in ("ff", "video", "movie", "format", "file"))]
    return {"interesting_keys": interesting, "total_props": len(keys)}


def p_ffmpeg_settings():
    scene = bpy.context.scene
    ff = scene.render.ffmpeg
    return {p.identifier: str(getattr(ff, p.identifier))
            for p in ff.bl_rna.properties
            if p.identifier not in ("rna_type",)}


def p_png_sequence_then_check():
    """备用路径：PNG 序列是否可写（外部编码器缺失时的降级产物）。"""
    scene = _scene_prep()
    scene.render.image_settings.file_format = "PNG"
    d = os.path.join(outdir(), "seq")
    os.makedirs(d, exist_ok=True)
    scene.render.filepath = os.path.join(d, "f_")
    bpy.ops.render.render(animation=True)
    files = sorted(os.listdir(d))
    return {"count": len(files), "sample": files[:4], "dir": d}


def p_imageio_ffmpeg():
    import importlib.util
    return {"has_imageio_ffmpeg": importlib.util.find_spec("imageio_ffmpeg") is not None}


def p_handlers_api():
    return {
        "frame_change_post": hasattr(bpy.app.handlers, "frame_change_post"),
        "depsgraph_update_post": hasattr(bpy.app.handlers, "depsgraph_update_post"),
        "load_post": hasattr(bpy.app.handlers, "load_post"),
        "counts": {
            "frame_change_post": len(bpy.app.handlers.frame_change_post),
            "depsgraph_update_post": len(bpy.app.handlers.depsgraph_update_post),
        },
    }


def p_collections_hide_render():
    scene = bpy.context.scene
    coll = bpy.data.collections.new("BlockDirector/Guides")
    scene.collection.children.link(coll)
    txt = bpy.data.curves.new("BD_g_txt", type="FONT")
    txt.body = "标签"
    obj = bpy.data.objects.new("BD_g_label", txt)
    coll.objects.link(obj)
    coll.hide_render = True
    return {
        "collection_hide_render": coll.hide_render,
        "object_hide_render_default": obj.hide_render,
        "has_view_layer_exclude": hasattr(bpy.types.ViewLayer, "exclude") or
                                  hasattr(bpy.context.view_layer, "exclude"),
    }


def main():
    rec("enum_instance", p_enum_instance)
    rec("set_ffmpeg", p_set_ffmpeg)
    rec("render_settings_keys", p_render_settings_keys)
    rec("ffmpeg_settings", p_ffmpeg_settings)
    rec("render_mp4", p_render_mp4)
    rec("png_sequence", p_png_sequence_then_check)
    rec("imageio_ffmpeg", p_imageio_ffmpeg)
    rec("handlers_api", p_handlers_api)
    rec("collections_hide_render", p_collections_hide_render)

    path = os.path.join(outdir(), "report_video.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(REPORT, fh, ensure_ascii=False, indent=2, default=str)
    print("\n===== VIDEO PROBE BEGIN =====")
    print(json.dumps(REPORT, ensure_ascii=False, default=str))
    print("===== VIDEO PROBE END =====")


if __name__ == "__main__":
    main()
