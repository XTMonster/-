"""BlockDirector — 5.x 输出媒体类型（media_type）探针.

假设：Blender 5.x 把 scene.render.image_settings 拆成 IMAGE / VIDEO 两种媒体类型，
只有切到 VIDEO 时 file_format 才允许 FFMPEG。
"""

from __future__ import annotations

import json
import os
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
        REPORT[name] = {"error": f"{type(exc).__name__}: {exc}"}
        REPORT[name]["trace"] = traceback.format_exc(limit=2)


def p_has_media_type():
    s = bpy.context.scene.render.image_settings
    props = [p.identifier for p in s.bl_rna.properties]
    return {
        "has_media_type": "media_type" in props,
        "props_sample": props[:14],
    }


def p_media_type_values():
    s = bpy.context.scene.render.image_settings
    if "media_type" not in [p.identifier for p in s.bl_rna.properties]:
        return "NO_MEDIA_TYPE"
    item = s.bl_rna.properties["media_type"]
    return {
        "current": s.media_type,
        "items": [i.identifier for i in item.enum_items],
    }


def p_switch_to_video():
    s = bpy.context.scene.render.image_settings

    def fmt_enum():
        return [i.identifier for i in
                s.bl_rna.properties["file_format"].enum_items]

    before = fmt_enum()
    s.media_type = "VIDEO"
    after = fmt_enum()
    return {"image_enum": before, "video_enum": after,
            "now_media_type": s.media_type,
            "now_file_format": s.file_format}


def p_render_mp4_via_media_type():
    scene = bpy.context.scene
    scene.render.resolution_x = 160
    scene.render.resolution_y = 90
    scene.render.resolution_percentage = 100
    scene.frame_start, scene.frame_end = 1, 8
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.image_settings.media_type = "VIDEO"
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.ffmpeg.format = "MPEG4"
    scene.render.ffmpeg.codec = "H264"
    scene.render.ffmpeg.constant_rate_factor = "MEDIUM"
    scene.render.ffmpeg.audio_codec = "NONE"
    out = os.path.join(outdir(), "video_media_type.mp4")
    scene.render.filepath = out
    bpy.ops.render.render(animation=True)
    final = out if os.path.exists(out) else out + ".mp4"
    return {"ok": os.path.exists(final), "path": final,
            "size": os.path.getsize(final) if os.path.exists(final) else 0}


def p_still_after_video():
    """验证切回 IMAGE 是否仍能出 PNG（两种媒体类型互不干扰）。"""
    scene = bpy.context.scene
    scene.render.image_settings.media_type = "IMAGE"
    scene.render.image_settings.file_format = "PNG"
    out = os.path.join(outdir(), "still_after_video.png")
    scene.render.filepath = out
    scene.frame_set(1)
    bpy.ops.render.render(write_still=True)
    return {"ok": os.path.exists(out),
            "size": os.path.getsize(out) if os.path.exists(out) else 0}


def main():
    rec("has_media_type", p_has_media_type)
    rec("media_type_values", p_media_type_values)
    rec("switch_to_video", p_switch_to_video)
    rec("render_mp4", p_render_mp4_via_media_type)
    rec("still_after_video", p_still_after_video)

    path = os.path.join(outdir(), "report_media_type.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(REPORT, fh, ensure_ascii=False, indent=2, default=str)
    print("\n===== MEDIA TYPE PROBE BEGIN =====")
    print(json.dumps(REPORT, ensure_ascii=False, default=str))
    print("===== MEDIA TYPE PROBE END =====")


if __name__ == "__main__":
    main()
