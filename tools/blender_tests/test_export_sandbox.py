"""v1.7 I1（FR-E2）：导出沙箱 headless 探针（TDD §13.1 / 卡 I1）。

断言：

* ``export_sandbox`` 进入时把 ``scene.camera`` 设为传入相机、``render.fps``
  设为传入帧率，模拟导出期间的写点；退出后 SANDBOX_KEYS **十一项**（render
  的 10 项属性路径＋``("camera",)``）逐项还原为进入前的值。``media_type``
  在清单里排在 ``file_format`` 之前——Blender 5.x 必须先还 media_type 才能
  还 file_format（视频 pass 会把设置留在 VIDEO/FFMPEG，图片枚举在 VIDEO 下
  不可写）。
* 沙箱内抛异常时 ``finally`` 同样逐项还原，且**异常不吞**
  （原异常继续向外抛，测试捕获后仍能读到还原结果）；
* 对缺 ffmpeg 等属性的替身对象（SimpleNamespace）不抛异常——缺失项记名
  跳过、还原同样跳过。

运行：:

  blender --background --factory-startup --python tools/blender_tests/test_export_sandbox.py

输出：一行 ``BD_TEST_RESULT {json}``（不含 NaN/Inf 字面量）；退出码 0 = 全通过。
"""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402

from block_director.layer8_delivery.export_sandbox import (  # noqa: E402
    SANDBOX_KEYS,
    export_sandbox,
)
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

RESULTS: dict = {}


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                         "trace": traceback.format_exc(limit=4)}


def _read_path(node, path):
    cur = node
    for part in path:
        cur = getattr(cur, part)
    return cur


def _write_path(node, path, value):
    cur = node
    for part in path[:-1]:
        cur = getattr(cur, part)
    setattr(cur, path[-1], value)


def _snapshot(scene):
    """按 SANDBOX_KEYS 逐项读生存值；缺项记 None。"""
    snap = {}
    for path in SANDBOX_KEYS:
        try:
            snap[path] = _read_path(scene, path)
        except AttributeError:
            snap[path] = None
    return snap


def _render_shapes_ok(scene, before):
    """九项 render 属性路径全部还原（与 before 逐项相等）。"""
    mismatches = []
    render_paths = [p for p in SANDBOX_KEYS if p != ("camera",)]
    for path in render_paths:
        try:
            got = _read_path(scene, path)
        except AttributeError:
            got = None
        if before.get(path) is None:
            #: 进入前就不存在的项跳过（如无 ffmpeg 的构建）
            continue
        if got != before[path]:
            mismatches.append((path, before[path], got))
    return mismatches


def t_restores_nine_items():
    scene = bpy.context.scene
    before = _snapshot(scene)
    #: 进入前必须真的存在这 9 条 render 路径（Blender 5.2 出厂场景）
    missing = [p for p in SANDBOX_KEYS if before.get(p) is None]
    if missing:
        return {"ok": False, "missing": [list(p) for p in missing]}

    #: 造一个非空相机对象；进入沙箱后 scene.camera 应指向它
    cam_data = bpy.data.cameras.new("sandbox_camera")
    cam_obj = bpy.data.objects.new("sandbox_camera", cam_data)
    scene.collection.objects.link(cam_obj)
    try:
        inside = {"camera": None, "fps": None}
        with export_sandbox(scene, camera=cam_obj, fps=30):
            inside["camera"] = scene.camera
            inside["fps"] = scene.render.fps
            #: 沙箱内故意污染全部 10 项 render 路径＋camera，验证退出时还原。
            #: 污染按真实 pass 的合法写序：图片项（色深/模式）先于切 VIDEO，
            #: media_type 与 file_format 再按视频 pass 写序（先 VIDEO 后
            #: FFMPEG）——Blender 5.x 下 VIDEO 只接受 8/10 色深与 FFMPEG
            #: 枚举，颠倒写序本身就会抛 enum TypeError；退出后必须逐项还原，
            #: 且还原顺序颠倒（先 file_format 后 media_type）同样会抛错。
            _write_path(scene, ("render", "filepath"), "//mutated.mp4")
            #: Blender 5.x：ffmpeg.format 是容器枚举（非编码名）
            _write_path(scene, ("render", "ffmpeg", "format"), "QUICKTIME")
            _write_path(scene, ("render", "ffmpeg", "codec"), "H264")
            _write_path(scene, ("render", "ffmpeg", "constant_rate_factor"),
                        "LOW")
            _write_path(scene, ("render", "resolution_percentage"), 50)
            _write_path(scene, ("render", "fps"), 12)
            _write_path(scene, ("render", "image_settings", "color_depth"),
                        "16")
            _write_path(scene, ("render", "image_settings", "color_mode"),
                        "RGBA")
            _write_path(scene, ("render", "image_settings", "media_type"),
                        "VIDEO")
            _write_path(scene, ("render", "image_settings", "file_format"),
                        "FFMPEG")
            scene.camera = cam_obj

        after = _snapshot(scene)
        mismatches = _render_shapes_ok(scene, before)
        camera_ok = after[("camera",)] == before[("camera",)]
        return {
            "ok": (inside["camera"] == cam_obj and inside["fps"] == 30
                   and not mismatches and camera_ok),
            "inside_camera_locked": inside["camera"] == cam_obj,
            "inside_fps": inside["fps"],
            "render_mismatches": [[list(p), str(b), str(g)]
                                  for p, b, g in mismatches],
            "camera_restored": camera_ok,
        }
    finally:
        bpy.data.objects.remove(cam_obj, do_unlink=True)
        bpy.data.cameras.remove(cam_data)


def t_restores_on_exception():
    scene = bpy.context.scene
    before = _snapshot(scene)
    cam_data = bpy.data.cameras.new("sandbox_camera_exc")
    cam_obj = bpy.data.objects.new("sandbox_camera_exc", cam_data)
    scene.collection.objects.link(cam_obj)
    raised = False
    restored = False
    try:
        try:
            with export_sandbox(scene, camera=cam_obj, fps=24):
                _write_path(scene, ("render", "fps"), 7)
                scene.camera = cam_obj
                raise RuntimeError("boom")
        except RuntimeError:
            raised = True
        finally:
            after = _snapshot(scene)
            restored = (after == before)
        return {"ok": raised and restored,
                "raised": raised,
                "restored": restored}
    finally:
        bpy.data.objects.remove(cam_obj, do_unlink=True)
        bpy.data.cameras.remove(cam_data)


def _stub_scene():
    """无 ffmpeg 的替身对象：只有 camera 与 render.fps 可写。"""
    render = SimpleNamespace(fps=24)
    image_settings = SimpleNamespace(file_format="PNG", color_depth="8",
                                     color_mode="RGB")
    render.image_settings = image_settings
    scene = SimpleNamespace(render=render, camera=None)
    return scene


def t_missing_attr_skipped():
    scene = _stub_scene()
    try:
        with export_sandbox(scene, camera="cam-stub", fps=30):
            scene.render.fps = 5
            scene.camera = "cam-stub"
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"ok": scene.render.fps == 24 and scene.camera is None,
            "fps_after": scene.render.fps,
            "camera_after": scene.camera}


def main() -> int:
    capture_main_thread()
    check("restores_nine_items", t_restores_nine_items)
    check("restores_on_exception", t_restores_on_exception)
    check("missing_attr_skipped", t_missing_attr_skipped)

    passed = [name for name, value in RESULTS.items() if value.get("ok")]
    failed = [name for name, value in RESULTS.items() if not value.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS},
        ensure_ascii=False, allow_nan=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
