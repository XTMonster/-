"""BlockDirector — Blender 运行时能力探针.

用途：在真实 Blender 上确认实现所依赖的 API 是否存在/可用，输出结构化报告。
运行：blender --background --factory-startup --python tools/probe_blender.py

实现要点：所有探针先注册、待模块加载完毕后再统一执行（避免前向引用）。
报告同时写入 <script_dir>/_probe_out/report.json，便于外部读取。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import traceback

import bpy


_PROBES: list = []
REPORT: dict = {}


def probe(name):
    """注册探针，延迟到 main() 执行。"""
    def deco(fn):
        _PROBES.append((name, fn))
        return fn
    return deco


def outdir() -> str:
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_probe_out")
    os.makedirs(d, exist_ok=True)
    return d


# --------------------------------------------------------------------------- #
# 基础环境
# --------------------------------------------------------------------------- #
@probe("env")
def _env():
    return {
        "python": sys.version.split()[0],
        "blender": bpy.app.version_string,
        "blender_tuple": list(bpy.app.version),
        "background": bpy.app.background,
        "config_dir": bpy.utils.user_resource("CONFIG"),
        "scripts_dir": bpy.utils.user_resource("SCRIPTS"),
        "python_exe": sys.executable,
        "temp_dir": tempfile.gettempdir(),
    }


@probe("render_engines")
def _engines():
    """逐个尝试设置渲染引擎，确认当前版本下哪些引擎真实可用。"""
    result = {}
    scene = bpy.context.scene
    original = scene.render.engine
    for ident in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT",
                  "BLENDER_WORKBENCH", "CYCLES"):
        try:
            scene.render.engine = ident
            result[ident] = "ok"
        except Exception as exc:  # noqa: BLE001
            result[ident] = f"{type(exc).__name__}: {exc}"
    scene.render.engine = original
    return result


@probe("video_encoding")
def _video_encoding():
    """Blender 自带 FFmpeg 是否可直接输出 mp4（决定是否需要外部 ffmpeg）。"""
    scene = bpy.context.scene
    ff = scene.render.ffmpeg
    return {
        "file_formats": [
            i.identifier for i in
            bpy.types.ImageFormatSettings.bl_rna.properties["file_format"].enum_items
        ],
        "ffmpeg_formats": [
            i.identifier for i in
            bpy.types.FFmpegSettings.bl_rna.properties["format"].enum_items
        ],
        "codecs": [i.identifier for i in ff.bl_rna.properties["codec"].enum_items],
        "external_ffmpeg_on_path": shutil.which("ffmpeg"),
    }


# --------------------------------------------------------------------------- #
# 关键 API
# --------------------------------------------------------------------------- #
@probe("api_surface")
def _api():
    from bpy_extras.object_utils import world_to_camera_view

    def has(path):
        obj = bpy
        try:
            for part in path.split("."):
                obj = getattr(obj, part)
            return True
        except AttributeError:
            return False

    return {
        "world_to_camera_view": callable(world_to_camera_view),
        "data_orphans_purge": has("data.orphans_purge"),
        "data_fonts_load": has("data.fonts.load"),
        "scene_ray_cast": has("context.scene.ray_cast"),
        "timeline_markers": has("context.scene.timeline_markers"),
        "marker_has_camera": "camera" in bpy.types.TimelineMarker.bl_rna.properties,
        "ops_render_opengl": has("ops.render.opengl"),
        "ops_render_render": has("ops.render.render"),
        "ops_extensions": has("ops.extensions"),
        "ops_preferences_addon_install": has("ops.preferences.addon_install"),
        "scene_use_nodes": "use_nodes" in bpy.types.Scene.bl_rna.properties,
        "view_layer_update": has("context.view_layer.update"),
    }


@probe("docstrings")
def _docs():
    return {
        "orphans_purge": bpy.data.orphans_purge.__doc__,
        "ray_cast": bpy.context.scene.ray_cast.__doc__,
    }


# --------------------------------------------------------------------------- #
# 投影区间（决定 §17.4）
# --------------------------------------------------------------------------- #
@probe("projection_range")
def _projection():
    from mathutils import Vector
    from bpy_extras.object_utils import world_to_camera_view

    scene = bpy.context.scene
    bpy.ops.object.camera_add(location=(0.0, -5.0, 0.0))
    cam = bpy.context.object
    cam.rotation_euler = (1.5707963, 0.0, 0.0)
    scene.camera = cam
    scene.render.resolution_x, scene.render.resolution_y = 1280, 720
    bpy.context.view_layer.update()

    samples = {}
    for label, point in {
        "center": (0.0, 0.0, 0.0),
        "left_edge": (-2.2, 0.0, 0.0),
        "right_edge": (2.2, 0.0, 0.0),
        "above_center": (0.0, 0.0, 1.0),
    }.items():
        co = world_to_camera_view(scene, cam, Vector(point))
        samples[label] = [round(co.x, 4), round(co.y, 4), round(co.z, 4)]
    return {"samples": samples, "sensor_width": cam.data.sensor_width,
            "lens": cam.data.lens, "resolution": [1280, 720]}


# --------------------------------------------------------------------------- #
# 中文字体
# --------------------------------------------------------------------------- #
@probe("cjk_font")
def _font():
    candidates = [
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
        r"C:\Windows\Fonts\Deng.ttf",
    ]
    found = [p for p in candidates if os.path.exists(p)]
    loaded = None
    if found:
        loaded = bpy.data.fonts.load(found[0]).name
    txt = bpy.data.curves.new("BD_probe_text", type="FONT")
    txt.body = "小明：你好"
    if loaded:
        txt.font = bpy.data.fonts[loaded]
    obj = bpy.data.objects.new("BD_probe_label", txt)
    bpy.context.scene.collection.objects.link(obj)
    obj.hide_render = True
    return {"candidates_present": found, "loaded_font": loaded,
            "text_body_ok": txt.body}


# --------------------------------------------------------------------------- #
# 真实渲染能力：headless 能否出图、能否直接出 mp4
# --------------------------------------------------------------------------- #
def _setup_scene(frame_end=4):
    scene = bpy.context.scene
    scene.render.resolution_x = 160
    scene.render.resolution_y = 90
    scene.render.resolution_percentage = 100
    scene.frame_start = 1
    scene.frame_end = frame_end


@probe("render_still_eevee")
def _render_eevee():
    scene = bpy.context.scene
    _setup_scene()
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.image_settings.file_format = "PNG"
    out = os.path.join(outdir(), "still_eevee.png")
    scene.render.filepath = out
    bpy.ops.render.render(write_still=True)
    return {"ok": os.path.exists(out),
            "size": os.path.getsize(out) if os.path.exists(out) else 0}


@probe("render_still_workbench")
def _render_wb():
    scene = bpy.context.scene
    _setup_scene()
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.image_settings.file_format = "PNG"
    out = os.path.join(outdir(), "still_workbench.png")
    scene.render.filepath = out
    bpy.ops.render.render(write_still=True)
    return {"ok": os.path.exists(out),
            "size": os.path.getsize(out) if os.path.exists(out) else 0}


@probe("render_animation_to_mp4")
def _render_mp4():
    """关键路径：不依赖外部 ffmpeg，直接用 Blender 输出 mp4。"""
    scene = bpy.context.scene
    _setup_scene(frame_end=6)
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.ffmpeg.format = "MPEG4"
    scene.render.ffmpeg.codec = "H264"
    scene.render.ffmpeg.constant_rate_factor = "MEDIUM"
    out = os.path.join(outdir(), "anim_test.mp4")
    scene.render.filepath = out
    bpy.ops.render.render(animation=True)
    final = out if os.path.exists(out) else out + ".mp4"
    exists = os.path.exists(final)
    return {"ok": exists, "path": final,
            "size": os.path.getsize(final) if exists else 0}


@probe("render_opengl_animation")
def _render_gl():
    """视口 OpenGL 渲染在 background 下是否能工作。"""
    scene = bpy.context.scene
    _setup_scene()
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = os.path.join(outdir(), "gl_frame_")
    try:
        bpy.ops.render.opengl(animation=True, view_context=False)
        produced = sorted(f for f in os.listdir(outdir()) if f.startswith("gl_frame"))
        return {"ok": bool(produced), "files": produced[:6]}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


# --------------------------------------------------------------------------- #
# 插件侧依赖可行性
# --------------------------------------------------------------------------- #
@probe("python_env")
def _python_env():
    import importlib.util

    out = {}
    for mod in ("numpy", "pip", "ensurepip", "ssl", "ctypes", "requests"):
        out[f"has_{mod}"] = importlib.util.find_spec(mod) is not None
    try:
        import numpy
        out["numpy_version"] = numpy.__version__
    except Exception as exc:  # noqa: BLE001
        out["numpy_version"] = f"ERR {exc}"
    for mod in ("openai", "httpx", "pydantic", "rank_bm25", "faiss", "pdfplumber"):
        out[f"has_{mod}"] = importlib.util.find_spec(mod) is not None
    return out


@probe("pip_in_blender_python")
def _pip_target():
    import subprocess

    try:
        res = subprocess.run([sys.executable, "-m", "pip", "--version"],
                             capture_output=True, text=True, timeout=60)
        return {"exe": sys.executable, "rc": res.returncode,
                "stdout": res.stdout.strip(), "stderr": res.stderr.strip()[:300]}
    except Exception as exc:  # noqa: BLE001
        return {"exe": sys.executable, "error": f"{type(exc).__name__}: {exc}"}


@probe("extension_system")
def _extensions():
    out = {}
    try:
        import addon_utils
        mods = list(addon_utils.modules(refresh=False))
        out["addon_utils_count"] = len(mods)
        out["addon_utils_sample"] = [
            getattr(m, "__name__", str(m)) for m in mods[:8]
        ]
    except Exception as exc:  # noqa: BLE001
        out["addon_utils"] = f"{type(exc).__name__}: {exc}"
    try:
        repos = list(bpy.context.preferences.extensions.repos)
        out["repos"] = [
            {"name": r.name, "enabled": r.enabled,
             "directory": getattr(r, "directory", None)}
            for r in repos
        ]
    except Exception as exc:  # noqa: BLE001
        out["repos"] = f"{type(exc).__name__}: {exc}"
    out["has_addon_install"] = hasattr(bpy.ops.preferences, "addon_install")
    out["has_extensions_ops"] = hasattr(bpy.ops, "extensions")
    return out


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main():
    for name, fn in _PROBES:
        try:
            REPORT[name] = fn()
        except Exception as exc:  # noqa: BLE001
            REPORT[name] = {
                "error": f"{type(exc).__name__}: {exc}",
                "trace": traceback.format_exc(limit=3),
            }

    path = os.path.join(outdir(), "report.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(REPORT, fh, ensure_ascii=False, indent=2, default=str)

    print("\n===== PROBE BEGIN =====")
    print(json.dumps(REPORT, ensure_ascii=False, default=str))
    print("===== PROBE END =====")
    print("REPORT_PATH", path)


if __name__ == "__main__":
    main()
